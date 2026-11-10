# -*- coding: utf-8 -*-
"""Сценарій із golden/scenarios.json -> листок для незалежної перевірки.

Тут немає жодного очікуваного числа. Є тільки переклад опису сценарію (період, оклад,
дати прийняття і звільнення, відрізки відсутностей) у величини, з яких закон велить
рахувати: норма робочих днів місяця, відпрацьовані дні, календарні дні кожної
відсутності, історія заробітку за розрахунковий період.

Усе, чого сценарій не описує, або чого пакет не вміє, піднімає `Unsupported`. Краще
чесне «не порахував» у звіті, ніж число, підігнане під Odoo.
"""
import json
import re
from datetime import date

from . import calendar_ua as cal
from .model import CpiMonth, EarningsMonth, Employee, Leaves, Slip, WorkedTime

KNOWN_SETUP = {"start", "end", "history", "leaves", "years", "rehire", "index_base", "diia_city"}
KNOWN_EMPLOYEE = {"ua_main_job", "ua_fte", "ua_psp", "ua_esv_category", "ua_contract_kind"}
KNOWN_LEAVES = {"VAC", "SICK", "SICK_CARE", "MAT", "STUDY", "TRIP", "CHILD_VAC", "MIL"}
KNOWN_PSP = {"none", "base", "child", "child150", "s150", "s200"}
KNOWN_KINDS = {"employment", "gph", "gig", "fop"}

# ч. 2 ст. 22 ЗУ 1105-XIV: перші п'ять днів хвороби оплачує роботодавець,
# з шостого - Пенсійний фонд.
SICK_EMPLOYER_DAYS = 5

HISTORY_MONTHS = 12   # п. 2 Порядку 100 і п. 3 Порядку 1266: розрахунковий період

UA_MONTHS = {"січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
             "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11,
             "грудня": 12}


class Unsupported(Exception):
    """Сценарій не виражається наявними правилами еталона."""


def _date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


def _rehire_start(scenario, month_start, month_finish):
    """Дата повторного прийняття.

    `setup.rehire = true` сама по собі дат не несе: у сценарії 11 вони живуть у назві
    («Повторне прийняття 17 серпня після звільнення 31 травня»). Дістаємо дату з назви,
    щоб не зашивати число в код. Не вийшло - сценарій не рахуємо."""
    match = re.search(r"прийнятт\w*\s+(\d{1,2})\s+([а-яіїєґ]+)", scenario.get("title", ""))
    if not match:
        raise Unsupported("setup.rehire без дати прийняття: у сценарії її ніде взяти")
    month = UA_MONTHS.get(match.group(2))
    if not month:
        raise Unsupported("не розпізнав місяць «%s» у назві сценарію" % match.group(2))
    day = date(month_start.year, month, int(match.group(1)))
    if not (month_start <= day <= month_finish):
        raise Unsupported("дата повторного прийняття поза періодом листка")
    return day


def _employee(scenario):
    raw = scenario.get("employee") or {}
    unknown = set(raw) - KNOWN_EMPLOYEE
    if unknown:
        raise Unsupported("невідомі поля працівника: %s" % ", ".join(sorted(unknown)))
    kind = raw.get("ua_contract_kind") or "employment"
    if kind not in KNOWN_KINDS:
        raise Unsupported("невідомий вид договору: %s" % kind)
    psp = raw.get("ua_psp") or "none"
    if psp not in KNOWN_PSP:
        raise Unsupported("невідома ПСП: %s" % psp)
    category = raw.get("ua_esv_category") or "general"
    if category not in ("general", "disabled"):
        raise Unsupported("невідома категорія ЄСВ: %s" % category)
    setup = scenario.get("setup") or {}
    return Employee(
        main_job=bool(raw.get("ua_main_job", True)),
        contract_kind=kind,
        disabled=(category == "disabled"),
        psp=psp,
        fte=float(raw.get("ua_fte") or 1.0),
        insurance_years=float(setup.get("years") or 0.0),
        index_base=_date(setup.get("index_base")),
    )


def _history(scenario, year, month):
    """Заробіток за 12 повних календарних місяців перед місяцем події.

    Постанова КМУ 100 (відпускні, відрядження) і Постанова КМУ 1266 (лікарняні, декрет)
    беруть той самий розрахунковий період. `setup.history` - місячний заробіток; сценарії
    описують рівний заробіток усі місяці."""
    gross = scenario.get("setup", {}).get("history")
    if not gross:
        return []
    rows = []
    for back in range(HISTORY_MONTHS, 0, -1):
        total = (year * 12 + month - 1) - back
        row_year, row_month = divmod(total, 12)
        row_month += 1
        rows.append(EarningsMonth(
            month=date(row_year, row_month, 1),
            gross=float(gross),
            work_days=cal.workdays_in_month(row_year, row_month),
        ))
    return rows


def _leaves(scenario, month_start, month_finish, hired, fired):
    """Відсутності: календарні дні в місяці листка і робочі дні, які через них втрачено."""
    leaves = Leaves()
    absence = {}
    for row in scenario.get("setup", {}).get("leaves") or []:
        code, start, finish = row[0], _date(row[1]), _date(row[2])
        if code not in KNOWN_LEAVES:
            raise Unsupported("невідомий вид відсутності: %s" % code)
        window = cal.overlap(start, finish, max(month_start, hired), min(month_finish, fired))
        if not window:
            continue
        in_month, in_month_end = window
        days = cal.calendar_days_between(in_month, in_month_end)
        absence[code] = absence.get(code, 0) + cal.workdays_between(in_month, in_month_end)
        if code == "VAC":
            leaves.vac_days += days
        elif code == "STUDY":
            leaves.study_days += days
        elif code == "CHILD_VAC":
            leaves.child_vac_days += days
        elif code == "SICK":
            # перші 5 днів листка - за рахунок підприємства, решта - ПФУ
            emp_last = min(start.toordinal() + SICK_EMPLOYER_DAYS - 1, in_month_end.toordinal())
            emp_days = max(emp_last - in_month.toordinal() + 1, 0)
            leaves.sick_emp_days += emp_days
            leaves.sick_pfu_days += days - emp_days
        elif code == "SICK_CARE":
            # ч. 1 ст. 22 ЗУ 1105: догляд за хворим оплачує ПФУ з першого дня
            leaves.sick_care_days += days
        elif code == "MAT":
            # допомога нараховується за весь листок одразу, тому беремо його цілком
            leaves.mat_days += cal.calendar_days_between(start, finish)
            leaves.mat_cover_days += days
            leaves.mat_start = start if leaves.mat_start is None else min(leaves.mat_start, start)
            leaves.mat_end = finish if leaves.mat_end is None else max(leaves.mat_end, finish)
        elif code == "MIL":
            leaves.mil_days += days
        elif code == "TRIP":
            leaves.trip_days += days
            leaves.trip_work_days += cal.workdays_between(in_month, in_month_end)
    return leaves, absence


def _diia_city(setup):
    """Стан резидента Дія Сіті в місяці листка: "" (не резидент), compliant, noncompliant."""
    value = setup.get("diia_city") or ""
    if value not in ("", "compliant", "noncompliant"):
        raise Unsupported("невідомий стан Дія Сіті: %s" % value)
    return value


def build(scenario, cpi=()):
    """Зібрати листок зі сценарію. Піднімає Unsupported, якщо сценарій не виражається."""
    setup = scenario.get("setup") or {}
    unknown = set(setup) - KNOWN_SETUP
    if unknown:
        raise Unsupported("невідомі поля setup: %s" % ", ".join(sorted(unknown)))

    period_from, period_to = [_date(value) for value in scenario["period"]]
    year, month = period_from.year, period_from.month
    month_start = date(year, month, 1)
    month_finish = cal.month_end(year, month)
    if period_from != month_start or period_to != month_finish:
        raise Unsupported("період листка не дорівнює календарному місяцю")

    hired = _date(setup.get("start")) or month_start
    if setup.get("rehire"):
        hired = _rehire_start(scenario, month_start, month_finish)
    fired = _date(setup.get("end")) or month_finish

    employee = _employee(scenario)
    leaves, absence = _leaves(scenario, month_start, month_finish, hired, fired)

    worked = WorkedTime(
        # робочі дні періоду роботи в місяці: від них віднімаються дні відсутностей
        work_days=cal.workdays_between(max(hired, month_start), min(fired, month_finish)),
        month_workdays=cal.workdays_in_month(year, month),
        absence_work_days=absence,
    )
    slip = Slip(
        year=year, month=month, wage=float(scenario.get("wage") or 0.0),
        employee=employee, worked=worked, leaves=leaves,
        inputs=dict(scenario.get("inputs") or {}),
        history=_history(scenario, year, month),
        cpi=list(cpi) if employee.index_base else [],
        diia_city=_diia_city(setup),
    )
    return slip


def load_scenarios(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def load_cpi(path):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    return [CpiMonth(row["year"], row["month"], float(row["value"])) for row in data["months"]]
