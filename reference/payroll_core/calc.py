# -*- coding: utf-8 -*-
"""Рушій розрахунку листка. Правила лежать у `data/rules-ua.json`, не тут.

У пакеті є рівно один набір правил - JSON. Раніше поряд жив python-список RULES із тими
самими формулами; його видалено, щоб не було двох джерел істини. Тут залишилися лише
речі, які виразом не запишеш: числа листка (`values`), помісячний ЄСВ (`esv_monthly`),
помісячний розподіл декретної допомоги (`_mat_shares`) і грошове округлення.

Категорії:
    BASIC оклад · ALW доплати · AVG середній заробіток · GROSS усього нараховано
    MAT декретні (без ПДФО і ВЗ, з ЄСВ) · NOTAX виплати без податків і внесків
    NOESV оподатковувані виплати без ЄСВ · DED утримання · NET до виплати
    COMP за рахунок підприємства
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from . import average, indexation
from .dsl import evaluate
from .model import Line, Result

EXTRA_FUNCS = ("esv_monthly", "pdfo_amount")   # названі алгоритми, дозволені у виразах правил
INPUT_CODES = ("BONUS", "PIECE", "GPH", "GIG", "GIG_BONUS", "COMP_DAYS", "DAILY", "FOP_PAY", "INDEX", "AID", "GIFT",
               "SEVERANCE", "COMP_TOOL", "ALIM_PCT", "UNION_PCT", "EXEC_AMT", "EXEC_PCT",
               "DAMAGE_AMT", "ADVANCE")
LEAVE_FIELDS = ("vac_days", "sick_emp_days", "sick_pfu_days", "sick_care_days", "mat_days",
                "mat_cover_days", "study_days", "child_vac_days", "child3_days", "unpaid_days",
                "trip_days", "trip_work_days", "mil_days")


def _r2(value, digits=2):
    """Округлення грошей: пів копійки вгору. round() Python округлює до парного."""
    if value is None:
        return 0.0
    quant = Decimal(1).scaleb(-int(digits))
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def values(slip, params):
    """Числа, на які спираються правила: ставки, межі, середні, індексація."""
    employee = slip.employee
    on_date = slip.date_to()
    p = params.all(on_date)
    children = max(employee.psp_children, 1)
    psp_mult = {"none": 0.0, "base": 1.0, "child": float(children),
                "child150": 1.5 * children, "s150": 1.5, "s200": 2.0}[employee.psp or "none"]
    thr_mult = float(children) if employee.psp in ("child", "child150") else 1.0
    holidays = p.get("holidays_per_year", 0.0)
    kind = employee.contract_kind or "employment"
    # Дія Сіті: пільгові ставки для трудового договору і гіг-контракту, коли резидент
    # відповідає вимогам у місяці; ЦПХ і ФОП пільг не мають
    dc_applies = slip.diia_city == "compliant" and kind in ("employment", "gig")
    ua = {
        "min_wage": p["min_wage"], "living_wage": p["living_wage"],
        "pdfo_rate": p["pdfo_rate"], "vz_rate": p["vz_rate"],
        # ч. 13 ст. 8 ЗУ про ЄСВ: 8,41 % для працівників з інвалідністю
        "esv_rate": p["esv_rate_disabled"] if employee.disabled else p["esv_rate"],
        # п. 4 ч. 1 ст. 1 ЗУ про ЄСВ: максимальна база - 20 мінімальних зарплат
        "esv_max_base": p["min_wage"] * p["esv_max_multiplier"],
        # ч. 5 ст. 8 ЗУ про ЄСВ: мінімальний внесок лише за основним місцем роботи
        "esv_min_applies": bool(employee.main_job) and kind == "employment",
        "dc_applies": dc_applies,
        "dc_pdfo_rate": p.get("dc_pdfo_rate", p["pdfo_rate"]),
        "psp_amount": p["psp_base"] * psp_mult,            # пп. 169.1 ПКУ
        "psp_threshold": p["psp_threshold"] * thr_mult,    # пп. 169.4.1 ПКУ
        "month_workdays": slip.worked.month_workdays,
        "contract_kind": kind,
        "fte": float(employee.fte or 1.0),
        "reserve_rate": p.get("reserve_rate", 0.0),
        "aid_charity_limit": p.get("aid_charity_limit", 0.0),   # пп. 170.7.3 ПКУ
        "gift_limit_share": p.get("gift_limit_share", 0.0),     # пп. 165.1.39 ПКУ
        "aid_used_year": slip.aid_used_year,
        "time_ratio": slip.worked.time_ratio,
        "avg100_day": average.per_calendar_day(slip, holidays),    # Постанова КМУ 100
        "avg1266_day": average.per_calendar_day(slip, holidays),   # Постанова КМУ 1266
        "avg_trip_day": average.per_trip_day(slip),
        "sick_percent": average.sick_percent(employee),            # ст. 24 ЗУ 1105
        "index_amount": indexation.amount(                         # Порядок КМУ 1078
            slip, p["living_wage"], p.get("index_threshold", indexation.THRESHOLD_DEFAULT),
            _index_share(slip, employee)),
    }
    ua["mat_shares"] = _mat_shares(slip, ua)
    return ua


def _index_share(slip, employee):
    """Пропорція індексації: ставка і відпрацьований час, як для окладу (п. 4 Порядку 1078)."""
    norm = slip.worked.month_workdays or slip.worked.work_days or 1.0
    time_share = max(min(slip.worked.worked() / norm, 1.0), 0.0) if norm else 1.0
    return float(employee.fte or 1.0) * time_share


def _mat_shares(slip, ua):
    """Частки декретної допомоги за місяцями листка непрацездатності.

    ч. 2 ст. 24 ЗУ про ЄСВ: якщо база за місяць менша за мінімальну зарплату, внесок
    рахується з мінімальної. Допомога по вагітності та пологах нараховується одразу за
    весь листок, тому її треба рознести на місяці, яких вона стосується, і перевіряти
    мінімум за кожен місяць окремо."""
    import calendar as _calendar
    from datetime import timedelta
    leaves = slip.leaves
    if not leaves.mat_days or not leaves.mat_start or not leaves.mat_end:
        return []
    total = _r2(leaves.mat_days * ua["avg1266_day"])
    days_total = (leaves.mat_end - leaves.mat_start).days + 1
    shares, current = [], leaves.mat_start
    while current <= leaves.mat_end:
        month_end = date(current.year, current.month,
                         _calendar.monthrange(current.year, current.month)[1])
        segment_end = min(month_end, leaves.mat_end)
        days = (segment_end - current).days + 1
        shares.append(_r2(total * days / days_total))
        current = segment_end + timedelta(days=1)
    return shares


def pdfo_amount(ua, gross, noesv):
    """ПДФО листка (п. 167.1 ПКУ) як додатне число.

    База - нараховане плюс оподатковувані виплати без ЄСВ, мінус податкова соціальна пільга,
    якщо нараховане не більше за поріг (пп. 169.1.1, 169.4.1 ПКУ). У резидента Дія Сіті, що
    відповідає вимогам, ставка 5 % береться лише з винагороди і зарплати (GROSS); подарунки
    і допомога понад межу (NOESV) - за загальною ставкою."""
    psp = ua["psp_amount"] if (ua["psp_amount"] and gross <= ua["psp_threshold"]) else 0.0
    taxable = max(gross + noesv - psp, 0.0)
    if not ua.get("dc_applies"):
        return _r2(taxable * ua["pdfo_rate"] / 100.0)
    preferential = min(max(gross - psp, 0.0), taxable)
    return _r2(preferential * ua["dc_pdfo_rate"] / 100.0 + (taxable - preferential) * ua["pdfo_rate"] / 100.0)


def esv_monthly(slip, ua, gross, mat_total=0.0):
    """ЄСВ за листок (ЗУ про ЄСВ, ст. 7, 8).

    Без декрету - один місяць: база = нараховане, не більше максимальної бази, і не
    менше мінімальної зарплати, якщо місяць відпрацьовано повністю за основним місцем.
    З декретом - по місяцях листка непрацездатності, мінімум за кожен місяць окремо.
    Резидент Дія Сіті, що відповідає вимогам, платить мінімальний страховий внесок раз на
    місяць, незалежно від суми і відпрацьованих днів."""
    if ua.get("dc_applies"):
        return _r2(ua["min_wage"] * ua["esv_rate"] / 100.0) if (gross + mat_total) > 0 else 0.0
    shares = ua.get("mat_shares") or []
    if shares:
        total = 0.0
        for index, share in enumerate(shares):
            base = share + (gross if index == 0 else 0.0)
            if ua["esv_min_applies"] and base < ua["min_wage"]:
                base = ua["min_wage"]
            total += min(base, ua["esv_max_base"]) * ua["esv_rate"] / 100.0
        return _r2(total)
    base = gross + mat_total
    full_month = bool(ua["month_workdays"]) and slip.worked.work_days >= ua["month_workdays"]
    if ua["esv_min_applies"] and full_month and 0 < base < ua["min_wage"]:   # без нарахувань ЄСВ немає
        base = ua["min_wage"]
    return _r2(min(base, ua["esv_max_base"]) * ua["esv_rate"] / 100.0)


class _Ctx:
    """Стан розрахунку: листок, числа, підсумки категорій і вже додані рядки."""

    def __init__(self, slip, ua):
        self.slip = slip
        self.ua = ua
        self.cat = {k: 0.0 for k in ("BASIC", "ALW", "AVG", "GROSS", "MAT", "NOTAX",
                                     "NOESV", "DED", "NET", "COMP")}
        self.lines = []

    def add(self, code, name, category, amount):
        self.lines.append(Line(code, name, category, amount))
        self.cat[category] = _r2(self.cat[category] + amount)


def context(slip, ua, categories):
    """Плоский контекст для виразів: числа листка, параметри і підсумки категорій."""
    ctx = dict(ua)
    ctx.update(categories)
    ctx.update({
        "wage": slip.wage,
        "fte": ua["fte"],
        "kind": ua["contract_kind"],
        "work_days": slip.worked.work_days,
        "norm": ua["month_workdays"] or slip.worked.work_days or 1.0,
        "worked": slip.worked.worked(),
        "full_month": bool(ua["month_workdays"]) and slip.worked.work_days >= ua["month_workdays"],
    })
    for field in LEAVE_FIELDS:
        ctx[field] = getattr(slip.leaves, field)
    for code in INPUT_CODES:
        ctx["in_" + code] = float(slip.inputs.get(code) or 0.0)
    return ctx


def compute(slip, params, ruleset):
    """Порахувати листок за набором правил-даних. Єдиний шлях розрахунку в пакеті."""
    ua = values(slip, params)
    ctx = _Ctx(slip, ua)
    names = context(slip, ua, ctx.cat)
    names["esv_monthly"] = lambda gross, mat=0.0: esv_monthly(slip, ua, gross, mat)
    names["pdfo_amount"] = lambda gross, noesv=0.0: pdfo_amount(ua, gross, noesv)
    for item in ruleset.derived:
        names[item["name"]] = evaluate(item["value"], names, EXTRA_FUNCS)
    for rule in ruleset.rules:
        if rule.get("when") and not evaluate(rule["when"], names, EXTRA_FUNCS):
            continue
        amount = evaluate(rule["amount"], names, EXTRA_FUNCS)
        ctx.add(rule["code"], rule["name"], rule["category"], amount)
        names.update(ctx.cat)
    return Result(ctx.lines, dict(ctx.cat))
