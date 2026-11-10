# -*- coding: utf-8 -*-
"""Індексація за Порядком 1078.

1. Наростаючий індекс рахується з місяця, наступного за базовим, і округлюється до 0,1 %.
2. Право виникає, коли індекс перевищує поріг (типово 103 %).
3. Індекс місяця листка не застосовується: його ще не оприлюднено.
4. Сума = прожитковий мінімум × приріст, у пропорції ставки і відпрацьованого часу.
5. Після виплати базовим стає місяць виплати, і цикл починається наново.
"""

THRESHOLD_DEFAULT = 103.0


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def base_month(slip):
    """Базовий місяць: пізніший з поставленого і місяця останньої виплати."""
    employee = slip.employee
    base = employee.index_base
    paid = employee.index_paid_month
    if paid and (not base or paid > base):
        return paid
    return base


def months(slip, base):
    """Місяці індексів: від наступного за базовим до місяця перед місяцем листка."""
    out = []
    year, month = _next_month(base.year, base.month)
    last = (slip.year - 1, 12) if slip.month == 1 else (slip.year, slip.month - 1)
    while (year, month) <= last and len(out) < 240:
        out.append((year, month))
        year, month = _next_month(year, month)
    return out


def cumulative(slip, base, month_end):
    """Наростаючий індекс у відсотках і перелік місяців без індексу."""
    by_month = {(row.year, row.month): row for row in slip.cpi}
    value, missing = 1.0, []
    for key in months(slip, base):
        row = by_month.get(key)
        if row and (not row.published_on or row.published_on <= month_end):
            value *= row.value / 100.0
        else:
            missing.append(key)
    return round(value * 100.0, 1), missing


def amount(slip, living_wage, threshold=THRESHOLD_DEFAULT, share=1.0):
    """Сума індексації за листок."""
    from .calc import _r2
    employee = slip.employee
    if employee.index_off or employee.contract_kind != "employment":   # індексують лише трудовий договір
        return 0.0
    base = base_month(slip)
    if not base:
        return 0.0
    percent, _missing = cumulative(slip, base, slip.date_to())
    if percent <= threshold:
        return 0.0
    return _r2(living_wage * (percent - 100.0) / 100.0 * share)
