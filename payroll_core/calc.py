# -*- coding: utf-8 -*-
"""Правила розрахунку листка в порядку номерів.

Порядок і формули збігаються з правилами на стенді один в один. Категорія накопичується
в міру виконання правил, тому правило бачить підсумки тих, що вже порахувалися: так
ПДФО бачить нарахування, а аліменти - податки.

Категорії:
    BASIC оклад · ALW доплати · AVG середній заробіток · GROSS усього нараховано
    MAT декретні (без ПДФО і ВЗ, з ЄСВ) · NOTAX виплати без податків і внесків
    NOESV оподатковувані виплати без ЄСВ · DED утримання · NET до виплати
    COMP за рахунок підприємства
"""
from . import average, indexation
from .dsl import evaluate
from .model import Line, Result

INPUT_CODES = ("BONUS", "GPH", "COMP_DAYS", "DAILY", "FOP_PAY", "INDEX", "AID", "GIFT",
               "SEVERANCE", "COMP_TOOL", "ALIM_PCT", "UNION_PCT", "EXEC_AMT", "EXEC_PCT",
               "DAMAGE_AMT", "ADVANCE")
LEAVE_FIELDS = ("vac_days", "sick_emp_days", "sick_pfu_days", "sick_care_days", "mat_days",
                "mat_cover_days", "study_days", "child_vac_days", "child3_days", "unpaid_days",
                "trip_days", "trip_work_days")

PSP_MULT = {"none": 0.0, "base": 1.0, "child": None, "child150": None, "s150": 1.5, "s200": 2.0}


def _r2(value):
    return round(value, 2)


def values(slip, params):
    """Числа, на які спираються правила. Аналог `payroll.ua` на стенді."""
    employee = slip.employee
    on_date = slip.date_to()
    p = params.all(on_date)
    children = max(employee.psp_children, 1)
    psp_mult = {"none": 0.0, "base": 1.0, "child": float(children),
                "child150": 1.5 * children, "s150": 1.5, "s200": 2.0}[employee.psp or "none"]
    thr_mult = float(children) if employee.psp in ("child", "child150") else 1.0
    holidays = p.get("holidays_per_year", 0.0)
    kind = employee.contract_kind or "employment"
    ua = {
        "min_wage": p["min_wage"], "living_wage": p["living_wage"],
        "pdfo_rate": p["pdfo_rate"], "vz_rate": p["vz_rate"],
        "esv_rate": p["esv_rate_disabled"] if employee.disabled else p["esv_rate"],
        "esv_max_base": p["min_wage"] * p["esv_max_multiplier"],
        "esv_min_applies": bool(employee.main_job) and kind == "employment",
        "psp_amount": p["psp_base"] * psp_mult,
        "psp_threshold": p["psp_threshold"] * thr_mult,
        "month_workdays": slip.worked.month_workdays,
        "contract_kind": kind,
        "fte": float(employee.fte or 1.0),
        "reserve_rate": p.get("reserve_rate", 0.0),
        "aid_charity_limit": p.get("aid_charity_limit", 0.0),
        "gift_limit_share": p.get("gift_limit_share", 0.0),
        "aid_used_year": slip.aid_used_year,
        "time_ratio": slip.worked.time_ratio,
        "avg100_day": average.per_calendar_day(slip, holidays),
        "avg1266_day": average.per_calendar_day(slip, holidays),
        "avg100_work_day": average.per_work_day(slip, holidays),
        "sick_percent": average.sick_percent(employee),
        "index_amount": indexation.amount(slip, p["living_wage"]),
    }
    ua["min_sal_target"] = _min_sal_target(slip, ua)
    return ua


def _worked_share(slip, ua):
    """Частка відпрацьованого часу за рядками відпрацьованих днів."""
    worked = slip.worked.worked()
    total = ua["month_workdays"] or slip.worked.work_days or 1.0
    return max(min(worked, total), 0.0) / (total or 1.0)


def _min_sal_target(slip, ua):
    """Мінімальна зарплата за ст. 3-1 пропорційно ставці і відпрацьованому часу."""
    if ua["contract_kind"] != "employment":
        return 0.0
    share = ua["time_ratio"]
    if share is None or share < 0:
        share = _worked_share(slip, ua)
    share = max(min(share, 1.0), 0.0)
    return _r2(ua["min_wage"] * ua["fte"] * share)


class _Ctx:
    """Стан розрахунку: сам листок, числа, категорії і вже пораховані суми."""

    def __init__(self, slip, ua):
        self.slip = slip
        self.ua = ua
        self.cat = {k: 0.0 for k in ("BASIC", "ALW", "AVG", "GROSS", "MAT", "NOTAX",
                                     "NOESV", "DED", "NET", "COMP")}
        self.lines = []

    def input(self, code):
        return float(self.slip.inputs.get(code) or 0.0)

    def add(self, code, name, category, amount):
        self.lines.append(Line(code, name, category, amount))
        self.cat[category] = _r2(self.cat[category] + amount)


# ---------------------------------------------------------------- правила
def _basic(c):
    ua, slip = c.ua, c.slip
    if ua["time_ratio"] is not None and ua["time_ratio"] >= 0:
        return _r2(slip.wage * ua["fte"] * ua["time_ratio"])
    days = slip.worked.worked()
    total = ua["month_workdays"] or slip.worked.work_days or 1.0
    return _r2(slip.wage * ua["fte"] * max(min(days, total), 0.0) / total)


def _aid_free(c):
    limit = c.ua["aid_charity_limit"] - c.ua["aid_used_year"]
    return _r2(max(min(c.input("AID"), limit), 0.0))


def _gift_limit(c):
    return c.ua["min_wage"] * c.ua["gift_limit_share"] / 100.0


def _esv(c):
    ua = c.ua
    base = c.cat["GROSS"] + c.cat["MAT"]
    full_month = bool(ua["month_workdays"]) and c.slip.worked.work_days >= ua["month_workdays"]
    if ua["esv_min_applies"] and full_month and base < ua["min_wage"] and not c.slip.leaves.mat_cover_days:
        base = ua["min_wage"]
    base = min(base, ua["esv_max_base"])
    return _r2(base * ua["esv_rate"] / 100.0)


def _exec_doc(c):
    rest = c.cat["GROSS"] + c.cat["NOESV"] + c.cat["DED"]
    if c.input("EXEC_AMT"):
        return -_r2(min(c.input("EXEC_AMT"), max(rest, 0.0)))
    return -_r2(max(rest, 0.0) * c.input("EXEC_PCT") / 100.0)


# (номер, код, назва, категорія, умова, сума)
RULES = [
    (1, "BASIC", "Оклад", "BASIC", None, _basic),
    (10, "BONUS", "Премія", "ALW", lambda c: bool(c.input("BONUS")), lambda c: _r2(c.input("BONUS"))),
    (12, "GPH", "Винагорода за ЦПХ", "ALW", lambda c: bool(c.input("GPH")), lambda c: _r2(c.input("GPH"))),
    (20, "VAC", "Відпускні", "AVG", lambda c: c.slip.leaves.vac_days > 0,
     lambda c: _r2(c.slip.leaves.vac_days * c.ua["avg100_day"])),
    (22, "SICK_EMP", "Лікарняні за рахунок підприємства, перші 5 днів", "AVG",
     lambda c: c.slip.leaves.sick_emp_days > 0,
     lambda c: _r2(c.slip.leaves.sick_emp_days * c.ua["avg1266_day"] * c.ua["sick_percent"] / 100.0)),
    (23, "SICK_PFU", "Лікарняні за рахунок ПФУ, з 6-го дня", "AVG",
     lambda c: c.slip.leaves.sick_pfu_days > 0,
     lambda c: _r2(c.slip.leaves.sick_pfu_days * c.ua["avg1266_day"] * c.ua["sick_percent"] / 100.0)),
    (24, "COMP_VAC", "Компенсація за невикористану відпустку", "AVG",
     lambda c: bool(c.input("COMP_DAYS")), lambda c: _r2(c.input("COMP_DAYS") * c.ua["avg100_day"])),
    (25, "MAT", "Допомога по вагітності та пологах", "MAT", lambda c: c.slip.leaves.mat_days > 0,
     lambda c: _r2(c.slip.leaves.mat_days * c.ua["avg1266_day"])),
    (26, "STUDY_PAY", "Оплата навчальної відпустки", "AVG", lambda c: c.slip.leaves.study_days > 0,
     lambda c: _r2(c.slip.leaves.study_days * c.ua["avg100_day"])),
    (27, "CHILD_VAC_PAY", "Оплата додаткової відпустки на дітей", "AVG",
     lambda c: c.slip.leaves.child_vac_days > 0,
     lambda c: _r2(c.slip.leaves.child_vac_days * c.ua["avg100_day"])),
    (28, "TRIP_PAY", "Середній заробіток за час відрядження", "AVG",
     lambda c: c.slip.leaves.trip_work_days > 0,
     lambda c: _r2(c.slip.leaves.trip_work_days * max(
         c.ua["avg100_work_day"],
         (c.slip.wage * c.ua["fte"] / c.ua["month_workdays"]) if c.ua["month_workdays"] else 0.0))),
    (29, "SICK_CARE_PAY", "Допомога по догляду за хворим", "AVG",
     lambda c: c.slip.leaves.sick_care_days > 0,
     lambda c: _r2(c.slip.leaves.sick_care_days * c.ua["avg1266_day"] * c.ua["sick_percent"] / 100.0)),
    (30, "DAILY", "Добові за відрядження", "NOTAX", lambda c: bool(c.input("DAILY")),
     lambda c: _r2(c.input("DAILY"))),
    (32, "FOP", "Оплата ФОП", "ALW", lambda c: bool(c.input("FOP_PAY")), lambda c: _r2(c.input("FOP_PAY"))),
    (33, "INDEX", "Індексація", "ALW", lambda c: bool(c.input("INDEX") or c.ua["index_amount"]),
     lambda c: _r2(c.input("INDEX") or c.ua["index_amount"])),
    (40, "MINSAL", "Доплата до мінімальної зарплати", "ALW",
     lambda c: c.ua["min_sal_target"] > 0 and (c.cat["BASIC"] + c.cat["ALW"]) < c.ua["min_sal_target"] - 0.005,
     lambda c: _r2(c.ua["min_sal_target"] - (c.cat["BASIC"] + c.cat["ALW"]))),
    (50, "AID_FREE", "Матеріальна допомога в межах норми", "NOTAX", lambda c: bool(c.input("AID")), _aid_free),
    (51, "AID_TAX", "Матеріальна допомога понад норму", "NOESV", lambda c: bool(c.input("AID")),
     lambda c: _r2(c.input("AID") - _aid_free(c))),
    (52, "GIFT_FREE", "Подарунок у межах норми", "NOTAX", lambda c: bool(c.input("GIFT")),
     lambda c: _r2(min(c.input("GIFT"), _gift_limit(c)))),
    (53, "GIFT_TAX", "Подарунок понад норму", "NOESV", lambda c: bool(c.input("GIFT")),
     lambda c: _r2(max(c.input("GIFT") - _gift_limit(c), 0.0))),
    (54, "SEVERANCE", "Вихідна допомога", "NOESV", lambda c: bool(c.input("SEVERANCE")),
     lambda c: _r2(c.input("SEVERANCE"))),
    (55, "COMP_TOOL", "Компенсація за використання власного майна", "NOESV",
     lambda c: bool(c.input("COMP_TOOL")), lambda c: _r2(c.input("COMP_TOOL"))),
    (100, "GROSS", "Усього нараховано", "GROSS", None,
     lambda c: _r2(c.cat["BASIC"] + c.cat["ALW"] + c.cat["AVG"])),
    (110, "PDFO", "ПДФО", "DED", lambda c: c.ua["contract_kind"] != "fop",
     lambda c: -_r2(max(c.cat["GROSS"] + c.cat["NOESV"] - (
         c.ua["psp_amount"] if (c.ua["psp_amount"] and c.cat["GROSS"] <= c.ua["psp_threshold"]) else 0.0
     ), 0.0) * c.ua["pdfo_rate"] / 100.0)),
    (120, "VZ", "Військовий збір", "DED", lambda c: c.ua["contract_kind"] != "fop",
     lambda c: -_r2((c.cat["GROSS"] + c.cat["NOESV"]) * c.ua["vz_rate"] / 100.0)),
    (150, "ALIM", "Аліменти", "DED", lambda c: bool(c.input("ALIM_PCT")),
     lambda c: -_r2((c.cat["GROSS"] + c.cat["NOESV"] + c.cat["DED"]) * c.input("ALIM_PCT") / 100.0)),
    (155, "UNION", "Профспілковий внесок", "DED", lambda c: bool(c.input("UNION_PCT")),
     lambda c: -_r2(c.cat["GROSS"] * c.input("UNION_PCT") / 100.0)),
    (160, "EXEC_DOC", "Утримання за виконавчим документом", "DED",
     lambda c: bool(c.input("EXEC_AMT") or c.input("EXEC_PCT")), _exec_doc),
    (165, "DAMAGE", "Відшкодування шкоди", "DED", lambda c: bool(c.input("DAMAGE_AMT")),
     lambda c: -_r2(min(c.input("DAMAGE_AMT"),
                        max(c.cat["GROSS"] + c.cat["NOESV"] + c.cat["DED"], 0.0)))),
    (180, "ADV_PAID", "Виплачено авансом", "DED", lambda c: bool(c.input("ADVANCE")),
     lambda c: -_r2(c.input("ADVANCE"))),
    (200, "NET", "До виплати", "NET", None,
     lambda c: _r2(c.cat["GROSS"] + c.cat["MAT"] + c.cat["NOTAX"] + c.cat["NOESV"] + c.cat["DED"])),
    (300, "ESV", "ЄСВ за рахунок підприємства", "COMP", lambda c: c.ua["contract_kind"] != "fop", _esv),
    (310, "RESERVE", "Резерв відпусток", "COMP",
     lambda c: c.ua["contract_kind"] == "employment" and c.ua["reserve_rate"] > 0,
     lambda c: _r2((c.cat["BASIC"] + c.cat["ALW"]) * c.ua["reserve_rate"] / 100.0)),
    (311, "RESERVE_ESV", "ЄСВ на резерв відпусток", "COMP",
     lambda c: c.ua["contract_kind"] == "employment" and c.ua["reserve_rate"] > 0,
     lambda c: _r2((c.cat["BASIC"] + c.cat["ALW"]) * c.ua["reserve_rate"] / 100.0 * c.ua["esv_rate"] / 100.0)),
]


def compute(slip, params):
    """Порахувати листок. Повертає рядки і підсумки категорій."""
    ctx = _Ctx(slip, values(slip, params))
    for _seq, code, name, category, condition, amount in RULES:
        if condition and not condition(ctx):
            continue
        ctx.add(code, name, category, amount(ctx))
    return Result(ctx.lines, dict(ctx.cat))


# ---------------------------------------------------------------- правила як дані
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


def compute_rules(slip, params, ruleset):
    """Порахувати листок за набором правил-даних. Результат той самий, що й у compute()."""
    ua = values(slip, params)
    ctx = _Ctx(slip, ua)
    names = context(slip, ua, ctx.cat)
    for item in ruleset.derived:
        names[item["name"]] = evaluate(item["value"], names)
    for rule in ruleset.rules:
        if rule.get("when") and not evaluate(rule["when"], names):
            continue
        amount = evaluate(rule["amount"], names)
        ctx.add(rule["code"], rule["name"], rule["category"], amount)
        names.update(ctx.cat)
    return Result(ctx.lines, dict(ctx.cat))
