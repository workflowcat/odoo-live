# -*- coding: utf-8 -*-
"""Середня зарплата: Постанова 100 (відпускні) і Постанова 1266 (лікарняні, декрет).

Розрахунковий період - 12 повних календарних місяців перед місяцем події. Якщо історії
немає, база береться від окладу: оклад × 12 і 365 днів (п. 4 Постанови 100).
"""
import calendar
from datetime import date

SICK_PERCENT_BY_YEARS = ((8, 100.0), (5, 70.0), (3, 60.0), (0, 50.0))


def add_months(day, count):
    year, month = divmod(day.month - 1 + count, 12)
    return date(day.year + year, month + 1, 1)


def window(year, month):
    """12 повних місяців перед місяцем листка: [початок, кінець)."""
    first = date(year, month, 1)
    return add_months(first, -12), first


def base(slip, holidays_per_year=0.0):
    """Сума заробітку і календарні дні розрахункового періоду."""
    start, end = window(slip.year, slip.month)
    rows = [row for row in slip.history if start <= row.month < end]
    if not rows:
        return slip.wage * 12.0, 365.0
    total = sum(row.gross for row in rows)
    days = sum(row.calendar_days or calendar.monthrange(row.month.year, row.month.month)[1] for row in rows)
    days -= sum(row.excluded_days for row in rows)
    days -= holidays_per_year * len(rows) / 12.0
    return total, max(days, 1.0)


def per_calendar_day(slip, holidays_per_year=0.0):
    """Середня за календарний день."""
    total, days = base(slip, holidays_per_year)
    return total / days if days else 0.0


def per_work_day(slip, holidays_per_year=0.0):
    """Середня за робочий день: календарні дні вікна × 5/7 (ст. 121 КЗпП, відрядження)."""
    total, days = base(slip, holidays_per_year)
    work_days = round(days * 5.0 / 7.0, 2) if days else 0.0
    return (total / work_days) if work_days else 0.0


def sick_percent(employee):
    """Відсоток лікарняних за страховим стажем (ст. 24 ЗУ 1105)."""
    if employee.sick_percent:
        return employee.sick_percent
    for years, percent in SICK_PERCENT_BY_YEARS:
        if employee.insurance_years >= years:
            return percent
    return 50.0
