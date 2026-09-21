# -*- coding: utf-8 -*-
"""Перехід залишків відпусток на рідні hr.leave.allocation.

Чому end, а не post: право на УБД (ua_veteran) і склад сім'ї (ua_child_ids, ua_single_parent)
живуть у l10n_ua_hr_card, який залежить від цього модуля і завантажується ПІСЛЯ нього. На
кроці post цих полів ще немає, генератор порахував би нуль там, де має бути 14. Крок end
виконується після завантаження всіх модулів, тому картка вже повна.

Що робить:
  1. вмикає на чотирьох видах відпусток requires_allocation, підставу нарахування і облік
     у календарних днях. Через SQL: leave_types.xml має noupdate="1", тому оновлення модуля
     ці поля не переписує, а рідний constrains не дає вмикати requires_allocation, коли за
     видом уже є відпустки;
  2. проганяє генератор на всіх працівниках;
  3. звіряє новий залишок зі знімком pre-migrate: розбіжність, видиму в картці (більшу за
     0,05 дня), записує в журнал як WARNING і закриває нарахуванням «Коригування при
     переході», після чого перевіряє результат ще раз.

Свідома розбіжність без коригування одна: ЦПХ і ФОП. Стара формула давала їм залишок
відпустки, хоча відпустка належить лише працівникам за трудовим договором (ст. 2 ЗУ
«Про відпустки»). Таким залишок обнуляється, і рядок у журналі це називає.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

TABLE = "ua_leave_migration_snapshot"
CODES = ("VAC", "VAC_UBD", "SOC_CHILD", "VAC_SPECIAL")
# код виду роботи -> підстава нарахування (див. models/hr_leave_type.py)
BASIS = {"VAC": "work_year", "VAC_UBD": "year", "SOC_CHILD": "year_carry", "VAC_SPECIAL": "year"}
TOLERANCE = 0.05          # поля показують один знак після коми; менше - це шум заокруглення
TRANSITION_LABEL = "Коригування при переході"


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT to_regclass(%s)", (TABLE,))
    if not cr.fetchone()[0]:
        _logger.warning("Знімок %s відсутній - перехід залишків пропущено.", TABLE)
        return

    Type = env["hr.leave.type"].sudo()
    types = {}
    for code in CODES:
        leave_type = Type.with_context(active_test=False).search(
            [("work_entry_type_id.code", "=", code)], limit=1)
        if leave_type:
            types[code] = leave_type

    for code, leave_type in types.items():
        cr.execute("UPDATE hr_leave_type SET requires_allocation = true, ua_alloc_basis = %s, "
                   "ua_calendar_days = true WHERE id = %s", (BASIS[code], leave_type.id))
    env.invalidate_all()
    missing = [code for code in CODES if code not in types]
    if missing:
        _logger.warning("Перехід відпусток: видів %s немає в базі, нарахування за ними не буде.", missing)

    # стару річну задачу вимикаємо: замість неї модуль привіз щоденну (ir_cron_ua_leave_days).
    # Напряму SQL, бо майже всі поля ir.cron делеговані на ir.actions.server і запис через
    # ORM під час оновлення модуля падає; active - власна колонка ir_cron.
    old_cron = env.ref("l10n_ua_average.ir_cron_ua_leave_allocations", raise_if_not_found=False)
    if old_cron:
        cr.execute("UPDATE ir_cron SET active = false WHERE id = %s", (old_cron.id,))
        env.invalidate_all()
        _logger.info("Перехід відпусток: стару річну задачу нарахування вимкнено.")

    # дні вже оформлених відпусток порахувати заново: у базі лежать робочі дні за графіком
    # (14 к.д. записані як 10), а нарахування списуються календарними
    if types:
        leaves = env["hr.leave"].sudo().with_context(active_test=False).search(
            [("holiday_status_id", "in", [t.id for t in types.values()])])
        if leaves:
            env.add_to_compute(env["hr.leave"]._fields["number_of_days"], leaves)
            leaves.flush_recordset()
            _logger.info("Перехід відпусток: перераховано дні %d заявок у календарні.", len(leaves))

    employees = env["hr.employee"].sudo().with_context(active_test=False).search([])
    employees._ua_ensure_leave_allocations()

    cr.execute("SELECT employee_id, employee_name, code, old_balance FROM %s" % TABLE)
    snapshot = {(row[0], row[2]): (row[1], row[3]) for row in cr.fetchall()}

    balance_field = {"VAC": "ua_vacation_balance", "VAC_UBD": "ua_vac_ubd_balance",
                     "SOC_CHILD": "ua_soc_child_balance", "VAC_SPECIAL": "ua_special_balance"}
    fixed = mismatched = skipped = 0
    adjusted = []
    employees.invalidate_recordset()
    for employee in employees:
        for code in CODES:
            key = (employee.id, code)
            if key not in snapshot:
                continue
            name, old = snapshot[key]
            new = employee[balance_field[code]] or 0.0
            delta = round(old - new, 2)
            if abs(delta) < TOLERANCE:
                continue
            mismatched += 1
            if employee.ua_contract_kind != "employment":
                skipped += 1
                _logger.warning(
                    "Перехід відпусток: %s (%s, %s) - залишок %.1f обнулено свідомо: "
                    "не трудовий договір, відпустка не належить (ст. 2 ЗУ «Про відпустки»).",
                    name or employee.name, employee.ua_contract_kind, code, old)
                continue
            leave_type = types.get(code)
            if not leave_type:
                _logger.warning("Перехід відпусток: немає виду %s, коригування %s не записано.", code, delta)
                continue
            _logger.warning(
                "Перехід відпусток: %s, %s - було %.1f, стало %.1f, різниця %.1f; "
                "записано нарахування «%s».", name or employee.name, code, old, new, delta, TRANSITION_LABEL)
            employee._ua_write_transition_adjustment(leave_type, delta)
            adjusted.append((employee, code, name, old))
            fixed += 1

    # контрольний прохід: коригування мало довести залишок до старого значення
    employees.invalidate_recordset()
    unresolved = 0
    for employee, code, name, old in adjusted:
        new = employee[balance_field[code]] or 0.0
        if abs(old - new) >= TOLERANCE:
            unresolved += 1
            _logger.warning("Перехід відпусток: %s, %s - після коригування залишок %.1f, "
                            "а мав бути %.1f. Перевірити руками.", name or employee.name, code, new, old)

    cr.execute("DROP TABLE IF EXISTS %s" % TABLE)
    _logger.info("Перехід відпусток завершено: працівників %d, розбіжностей %d, коригувань %d, "
                 "свідомо обнулено %d, незакритих %d.",
                 len(employees), mismatched, fixed, skipped, unresolved)
