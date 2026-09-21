# -*- coding: utf-8 -*-
"""Виробничий календар України.

Норма робочих днів місяця - це п'ятиденний робочий тиждень зі ст. 50 і ст. 52 КЗпП:
понеділок - п'ятниця, субота і неділя вихідні.

Святкові і неробочі дні зі ст. 73 КЗпП тут НЕ віднімаються. Стаття 6 Закону 2136-IX
«Про організацію трудових відносин в умовах воєнного стану» зупиняє дію ст. 73 КЗпП
на період воєнного стану: святкових і неробочих днів у цей період немає, робота в
такі дні оплачується як звичайна. Те саме каже параметр `holidays_per_year = 0` у
`data/params-ua.json`. Коли воєнний стан скінчиться, сюди додається таблиця свят, а
параметр перестає бути нулем - і те, й те зміниться одночасно.
"""
import calendar
from datetime import date, timedelta


def is_workday(day):
    """Робочий день за п'ятиденкою (ст. 50, 52 КЗпП)."""
    return day.weekday() < 5


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def workdays_in_month(year, month):
    """Норма робочих днів місяця."""
    return sum(1 for day in days_of_month(year, month) if is_workday(day))


def days_of_month(year, month):
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, last + 1)]


def workdays_between(start, end):
    """Робочі дні у відрізку включно з обома кінцями."""
    if end < start:
        return 0
    return sum(1 for day in each_day(start, end) if is_workday(day))


def calendar_days_between(start, end):
    """Календарні дні у відрізку включно з обома кінцями."""
    return max((end - start).days + 1, 0)


def each_day(start, end):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def overlap(a_start, a_end, b_start, b_end):
    """Перетин двох відрізків або None."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return (start, end) if start <= end else None
