# -*- coding: utf-8 -*-
"""Знімок старих залишків відпусток перед переходом на hr.leave.allocation.

Читаємо чистим SQL за старими формулами, а не через ORM: на цьому кроці нова версія моделей
ще не завантажена, а стара вже не гарантована. Результат лягає в таблицю
ua_leave_migration_snapshot, яку звіряє і прибирає end-migrate.py.

Старі формули, які тут відтворено:
  VAC          = початковий залишок + норма x календарні дні роботи з дати впровадження / 365
                 - календарні дні проведених відпусток VAC - виплачені COMP_DAYS
  VAC_UBD      = 14 (УБД або інвалідність внаслідок війни) - використано в поточному році
  SOC_CHILD    = ua_soc_child_allocated - використано за всі роки
  VAC_SPECIAL  = min(ua_special_leave_days, 7) - використано в поточному році
"""
import logging
from datetime import date

_logger = logging.getLogger(__name__)

TABLE = "ua_leave_migration_snapshot"


def _column_exists(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
               (table, column))
    return bool(cr.fetchone())


def _leaves(cr, code, employee_ids):
    """[(employee_id, початок, кінець)] проведених відпусток цього виду."""
    cr.execute("""
        SELECT l.employee_id, l.request_date_from, l.request_date_to
          FROM hr_leave l
          JOIN hr_leave_type lt ON lt.id = l.holiday_status_id
          JOIN hr_work_entry_type wet ON wet.id = lt.work_entry_type_id
         WHERE wet.code = %s AND l.state = 'validate' AND l.employee_id IN %s
               AND l.request_date_from IS NOT NULL AND l.request_date_to IS NOT NULL""",
               (code, tuple(employee_ids)))
    return cr.fetchall()


def _days_in_year(leaves, year):
    """{employee_id: календарні дні} з обрізанням по календарному році."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    out = {}
    for employee_id, start, end in leaves:
        lo, hi = max(start, first), min(end, last)
        if hi >= lo:
            out[employee_id] = out.get(employee_id, 0.0) + (hi - lo).days + 1
    return out


def _days_total(leaves):
    out = {}
    for employee_id, start, end in leaves:
        out[employee_id] = out.get(employee_id, 0.0) + (end - start).days + 1
    return out


def migrate(cr, version):
    if not version:
        return
    today = date.today()

    cr.execute("SELECT id, name, company_id, ua_contract_kind, COALESCE(ua_vacation_days_year, 24), "
               "COALESCE(ua_vacation_opening_balance, 0), ua_vacation_opening_date, "
               "COALESCE(ua_soc_child_allocated, 0), COALESCE(ua_special_leave_days, 0), "
               "COALESCE(ua_war_disability, false) FROM hr_employee")
    rows = cr.fetchall()

    cr.execute("DROP TABLE IF EXISTS %s" % TABLE)
    cr.execute("""
        CREATE TABLE %s (
            employee_id integer NOT NULL,
            employee_name varchar,
            code varchar NOT NULL,
            old_balance double precision NOT NULL,
            PRIMARY KEY (employee_id, code))""" % TABLE)
    if not rows:
        _logger.info("Перехід на нарахування відпусток: працівників немає, знімок порожній.")
        return

    employee_ids = [row[0] for row in rows]

    veterans = set()
    if _column_exists(cr, "hr_employee", "ua_veteran"):
        cr.execute("SELECT id FROM hr_employee WHERE ua_veteran IS TRUE")
        veterans = {row[0] for row in cr.fetchall()}

    cr.execute("SELECT id, ua_vacation_opening_date FROM res_company")
    company_opening = dict(cr.fetchall())

    cr.execute("SELECT employee_id, contract_date_start, contract_date_end FROM hr_version "
               "WHERE employee_id IN %s AND contract_date_start IS NOT NULL", (tuple(employee_ids),))
    spans = {}
    for employee_id, start, end in cr.fetchall():
        spans.setdefault(employee_id, set()).add((start, end))

    cr.execute("""
        SELECT s.employee_id, s.date_to, i.amount
          FROM hr_payslip_input i
          JOIN hr_payslip s ON s.id = i.payslip_id
         WHERE i.code = 'COMP_DAYS' AND s.state = 'done' AND s.employee_id IN %s""",
               (tuple(employee_ids),))
    comp_rows = cr.fetchall()

    vac_leaves = _leaves(cr, "VAC", employee_ids)
    soc_used = _days_total(_leaves(cr, "SOC_CHILD", employee_ids))
    ubd_used = _days_in_year(_leaves(cr, "VAC_UBD", employee_ids), today.year)
    special_used = _days_in_year(_leaves(cr, "VAC_SPECIAL", employee_ids), today.year)

    values = []
    for (emp_id, name, company_id, _kind, days_year, opening_balance, opening_date,
         soc_allocated, special_days, war_disability) in rows:
        opening = opening_date or company_opening.get(company_id)

        worked = 0
        for start, end in sorted(spans.get(emp_id, set())):
            span_start = max(start, opening) if opening else start
            span_end = min(end or today, today)
            if span_end >= span_start:
                worked += (span_end - span_start).days + 1
        accrued = round(float(days_year or 24) * worked / 365.0, 1)

        used = 0.0
        for leave_emp, lstart, lend in vac_leaves:
            if leave_emp == emp_id and (not opening or lstart >= opening):
                used += (lend - lstart).days + 1
        for comp_emp, date_to, amount in comp_rows:
            if comp_emp == emp_id and (not opening or (date_to and date_to >= opening)):
                used += float(amount or 0)

        values.append((emp_id, name, "VAC",
                       round(float(opening_balance if opening else 0.0) + accrued - used, 1)))
        values.append((emp_id, name, "VAC_UBD",
                       round((14 if (emp_id in veterans or war_disability) else 0) - ubd_used.get(emp_id, 0.0), 1)))
        values.append((emp_id, name, "SOC_CHILD",
                       round(float(soc_allocated) - soc_used.get(emp_id, 0.0), 1)))
        values.append((emp_id, name, "VAC_SPECIAL",
                       round(max(0, min(special_days, 7)) - special_used.get(emp_id, 0.0), 1)))

    cr.executemany("INSERT INTO %s (employee_id, employee_name, code, old_balance) "
                   "VALUES (%%s, %%s, %%s, %%s)" % TABLE, values)
    _logger.info("Перехід на нарахування відпусток: знято %d залишків по %d працівниках.",
                 len(values), len(rows))
