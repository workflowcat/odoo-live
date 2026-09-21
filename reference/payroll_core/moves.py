# -*- coding: utf-8 -*-
"""Проводки з рядків листка за Інструкцією про застосування Плану рахунків № 291.

Рахунки:
    92   адміністративні витрати - нарахування за рахунок підприємства
    661  розрахунки за заробітною платою
    6411 розрахунки з бюджетом: ПДФО
    6415 розрахунки з бюджетом: військовий збір
    651  розрахунки із загальнообов'язкового державного соціального страхування (ЄСВ)
    471  забезпечення виплат відпусток
    378  розрахунки з державними цільовими фондами - те, що відшкодовує ПФУ

Рахунок витрат 92 - припущення: куди відносити оплату праці (23, 91, 92, 93), залежить
від того, де працює людина, а не від закону. Сценарії описують адміністративний
персонал. Решта проводок з Інструкції 291 і не має вибору.
"""
from .calc import _r2

# те, що врешті відшкодовує Пенсійний фонд: нараховується, але підприємству не коштує
PFU_CODES = ("SICK_PFU", "SICK_CARE_PAY", "MAT")
COST_ACCOUNT = "92"


def build(result):
    """Список проводок: [{"side": "Дт"|"Кт", "account": str, "amount": float}]."""
    line = result.dict()
    cat = result.categories

    def amount(code):
        return line.get(code, 0.0)

    pfu = _r2(sum(amount(code) for code in PFU_CODES))
    pdfo = _r2(-amount("PDFO"))
    vz = _r2(-amount("VZ"))
    esv = _r2(amount("ESV"))
    reserve = _r2(amount("RESERVE") + amount("RESERVE_ESV"))
    # нараховано на користь працівника: усе, що лягає на рахунок 661
    payroll = _r2(cat["GROSS"] + cat["MAT"] + cat["NOTAX"] + cat["NOESV"])
    # витрати підприємства: те саме мінус частка ПФУ, плюс ЄСВ і резерв відпусток
    cost = _r2(payroll - pfu + esv + reserve)

    moves = [{"side": "Дт", "account": COST_ACCOUNT, "amount": cost}]
    if pfu:
        moves.append({"side": "Дт", "account": "378", "amount": pfu})
    moves.append({"side": "Кт", "account": "661", "amount": payroll})
    if pdfo or vz:
        moves.append({"side": "Дт", "account": "661", "amount": _r2(pdfo + vz)})
    if pdfo:
        moves.append({"side": "Кт", "account": "6411", "amount": pdfo})
    if vz:
        moves.append({"side": "Кт", "account": "6415", "amount": vz})
    if esv:
        moves.append({"side": "Кт", "account": "651", "amount": esv})
    if reserve:
        moves.append({"side": "Кт", "account": "471", "amount": reserve})
    return moves


def balanced(moves):
    """Дебет і кредит сходяться."""
    debit = _r2(sum(m["amount"] for m in moves if m["side"] == "Дт"))
    credit = _r2(sum(m["amount"] for m in moves if m["side"] == "Кт"))
    return abs(debit - credit) < 0.005, debit, credit
