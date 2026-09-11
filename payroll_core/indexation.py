# -*- coding: utf-8 -*-
"""Індексація зарплати за Постановою 1078.

Наростаючий коефіцієнт рахується за місяці після базового. Базовий місяць - місяць
останнього підвищення окладу або той, який поставив бухгалтер. Місяць без внесеного
індексу вважається за 100 % і суму не змінює.
"""
from datetime import date


def amount(slip, living_wage):
    """Сума індексації за листок. Нуль, якщо індексація вимкнена або коефіцієнт не зріс."""
    employee = slip.employee
    if employee.index_off or not employee.index_base:
        return 0.0
    by_month = {(row.year, row.month): row.value for row in slip.cpi}
    cumulative = 1.0
    year, month = employee.index_base.year, employee.index_base.month
    while True:
        month += 1
        if month > 12:
            year, month = year + 1, 1
        if (year, month) > (slip.year, slip.month):
            break
        cumulative *= by_month.get((year, month), 100.0) / 100.0
    percent = (cumulative - 1.0) * 100.0
    if percent <= 0:
        return 0.0
    return round(living_wage * percent / 100.0, 2)
