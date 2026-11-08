# -*- coding: utf-8 -*-
"""Примітки до річної фінансової звітності (форма № 5, наказ Мінфіну № 302).

Розділи I і II - рух нематеріальних активів і основних засобів за групами рахунків (12, 10 і 11).
Кожен рядок проводки на рахунку групи за період потрапляє рівно в одну графу:
- кореспондент 41, 746 чи 975 - переоцінка (графа 6);
- кореспондент - рахунок іншої групи того самого розділу - інші зміни (графа 12);
- інакше дебет - надійшло (графа 5), кредит - вибуло (графа 8).
Знос (131, 132, 135 для II, 133 для I) так само: переоцінка - графа 7, кореспондент 972 чи 742 -
втрати від зменшення корисності (графа 11), дебет з рахунком групи - вибуло (графа 9), кредит -
нараховано (графа 10), решта - інші зміни (графа 13). Групу для рядка зносу дає актив на рядку
проводки (його профіль, рахунок активу), інакше кореспондентний рахунок групи, інакше рядок інших
активів (180, 250, 105, 070) і зауваження. Тож графи 14 і 15 завжди дорівнюють сальдо рахунків.

Розділи III, V, VI, VII, VIII, X, XII, XIII - сальдо й обороти рахунків, за потреби з кореспондентом.
Розділ IX - додатне сальдо кожного контрагента на рахунку, розкладене на найновіші дебетові обороти
(строк від дати обороту до кінця періоду: до 12, 12-18, 18-36 місяців).

Розділи IV, XI, XIV, XV модуль поки не заповнює. Коди рядків - форма № 5 у редакції наказу
№ 302 зі змінами; перевіряйте чинну редакцію перед поданням.
"""
from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

COLS = ["c%d" % n for n in range(3, 20)]
REVALUATION = ("41", "746", "975")
IMPAIRMENT = ("972", "742")

SECTIONS = [
    ("intangible", "I. Нематеріальні активи"),
    ("fixed", "II. Основні засоби"),
    ("capex", "III. Капітальні інвестиції"),
    ("income", "V. Доходи і витрати"),
    ("cash", "VI. Грошові кошти"),
    ("provision", "VII. Забезпечення і резерви"),
    ("inventory", "VIII. Запаси"),
    ("receivable", "IX. Дебіторська заборгованість"),
    ("shortage", "X. Нестачі і втрати від псування цінностей"),
    ("tax", "XII. Податок на прибуток"),
    ("amortization", "XIII. Використання амортизаційних відрахувань"),
]

_ASSET_HEAD = [
    ("c3", "Залишок на початок року: первісна (переоцінена) вартість"),
    ("c4", "Залишок на початок року: %s"),
    ("c5", "Надійшло за рік"),
    ("c6", "Переоцінка (дооцінка +, уцінка -): первісної (переоціненої) вартості"),
    ("c7", "Переоцінка: %s"),
    ("c8", "Вибуло за рік: первісна (переоцінена) вартість"),
    ("c9", "Вибуло за рік: %s"),
    ("c10", "Нараховано амортизації за рік"),
    ("c11", "Втрати від зменшення корисності за рік"),
    ("c12", "Інші зміни за рік: первісної (переоціненої) вартості"),
    ("c13", "Інші зміни за рік: %s"),
    ("c14", "Залишок на кінець року: первісна (переоцінена) вартість"),
    ("c15", "Залишок на кінець року: %s"),
]
HEADS = {
    "intangible": [(c, t % "накопичена амортизація" if "%s" in t else t) for c, t in _ASSET_HEAD],
    "fixed": [(c, t % "знос" if "%s" in t else t) for c, t in _ASSET_HEAD] + [
        ("c16", "У тому числі одержані за фінансовою орендою: первісна (переоцінена) вартість"),
        ("c17", "Одержані за фінансовою орендою: знос"),
        ("c18", "Передані в оперативну оренду: первісна (переоцінена) вартість"),
        ("c19", "Передані в оперативну оренду: знос"),
    ],
    "capex": [("c3", "За рік"), ("c4", "На кінець року")],
    "income": [("c3", "Доходи"), ("c4", "Витрати")],
    "cash": [("c3", "На кінець року")],
    "provision": [
        ("c3", "Залишок на початок року"), ("c4", "Збільшення за рік: нараховано (створено)"),
        ("c5", "Збільшення за рік: додаткові відрахування"), ("c6", "Використано у звітному році"),
        ("c7", "Сторновано невикористану суму у звітному році"),
        ("c8", "Сума очікуваного відшкодування витрат іншою стороною"), ("c9", "Залишок на кінець року"),
    ],
    "inventory": [
        ("c3", "Балансова вартість на кінець року"),
        ("c4", "Переоцінка за рік: збільшення чистої вартості реалізації"), ("c5", "Переоцінка за рік: уцінка"),
    ],
    "receivable": [
        ("c3", "Всього на кінець року"), ("c4", "У т. ч. за строками непогашення: до 12 місяців"),
        ("c5", "Від 12 до 18 місяців"), ("c6", "Від 18 до 36 місяців"),
    ],
    "shortage": [("c3", "Сума")],
    "tax": [("c3", "Сума")],
    "amortization": [("c3", "Сума")],
}

# Розділи I і II: код рядка, назва, початки кодів рахунку групи, винятки.
INTANGIBLE_ROWS = [
    ("010", "Права користування природними ресурсами", ("121",), ()),
    ("020", "Права користування майном", ("122",), ()),
    ("030", "Права на комерційні позначення", ("123",), ()),
    ("040", "Права на об'єкти промислової власності", ("124",), ()),
    ("050", "Авторське право та суміжні з ним права", ("125",), ()),
    ("070", "Інші нематеріальні активи", ("126", "127", "128", "129"), ()),
]
FIXED_ROWS = [
    ("100", "Земельні ділянки", ("101",), ()),
    ("105", "Інвестиційна нерухомість", ("100",), ()),
    ("110", "Капітальні витрати на поліпшення земель", ("102",), ()),
    ("120", "Будинки, споруди та передавальні пристрої", ("103",), ()),
    ("130", "Машини та обладнання", ("104",), ()),
    ("140", "Транспортні засоби", ("105",), ()),
    ("150", "Інструменти, прилади, інвентар (меблі)", ("106",), ()),
    ("160", "Тварини", ("107",), ()),
    ("170", "Багаторічні насадження", ("108",), ()),
    ("180", "Інші основні засоби", ("109",), ("1092",)),
    ("190", "Бібліотечні фонди", ("111",), ()),
    ("200", "Малоцінні необоротні матеріальні активи", ("112",), ()),
    ("210", "Тимчасові (нетитульні) споруди", ("113",), ()),
    ("220", "Природні ресурси", ("114",), ()),
    ("230", "Інвентарна тара", ("115",), ()),
    ("240", "Предмети прокату", ("116",), ()),
    ("250", "Інші необоротні матеріальні активи", ("117",), ()),
]
ASSET_TABLES = {
    "intangible": {"rows": INTANGIBLE_ROWS, "total": ("080", "Разом"), "depr": ("133",),
                   "fallback": {"133": "070"}},
    "fixed": {"rows": FIXED_ROWS, "total": ("260", "Разом"), "depr": ("131", "132", "135"),
              "fallback": {"131": "180", "132": "250", "135": "105"}},
}


def _t(kind, prefixes, sign=1, exclude=(), counters=None, without=()):
    """Доданок клітинки: end/start - сальдо (дебет мінус кредит) на кінець / до початку періоду,
    debit/credit - оборот за період; counters - лише рядки з таким кореспондентом, without - без них."""
    return {"kind": kind, "prefixes": tuple(prefixes), "sign": sign, "exclude": tuple(exclude),
            "counters": tuple(counters) if counters else None, "without": tuple(without)}


def _end(p, sign=1, exclude=()):
    return _t("end", p, sign, exclude)


def _start(p, sign=1, exclude=()):
    return _t("start", p, sign, exclude)


def _dt(p, sign=1, **kw):
    return _t("debit", p, sign, **kw)


def _ct(p, sign=1, **kw):
    return _t("credit", p, sign, **kw)


def _capex(code, name, prefixes, exclude=()):
    return (code, name, "item", {"c3": [_dt(prefixes, exclude=exclude, without=("15",))],
                                 "c4": [_end(prefixes, exclude=exclude)]})


def _provision(code, name, prefixes):
    if not prefixes:
        return (code, name, "item", {})
    back = ("71", "74")  # невикористане забезпечення - в інші доходи
    return (code, name, "item", {
        "c3": [_start(prefixes, -1)], "c4": [_ct(prefixes)],
        "c6": [_dt(prefixes, without=back)], "c7": [_dt(prefixes, counters=back)],
        "c9": [_end(prefixes, -1)]})


def _stock(code, name, prefixes, exclude=()):
    return (code, name, "item", {"c3": [_end(prefixes, exclude=exclude)],
                                 "c4": [_dt(prefixes, exclude=exclude, counters=("719",))],
                                 "c5": [_ct(prefixes, exclude=exclude, counters=("946",))]})


CLOSING = ("79",)
PL_INCOME = ("71", "72", "73", "74")
PL_EXPENSE = ("94", "95", "96", "97")


def _pl(code, name, income=(), expense=(), income_ex=(), expense_ex=(), kind="item"):
    """Розділ V: доходи - кредит мінус дебет рахунків класу 7, витрати - дебет мінус кредит класу 9,
    без закриття на 79."""
    spec = {}
    if income:
        spec["c3"] = [_ct(income, exclude=income_ex, without=CLOSING),
                      _dt(income, -1, exclude=income_ex, without=CLOSING)]
    if expense:
        spec["c4"] = [_dt(expense, exclude=expense_ex, without=CLOSING),
                      _ct(expense, -1, exclude=expense_ex, without=CLOSING)]
    return (code, name, kind, spec)


DEPRECIATION = ("131", "132", "133", "134", "135")
# Прості розділи: (код, назва, вид, {графа: [доданки]}) або (код, назва, "total", [коди рядків]).
TABLES = {
    "capex": [
        _capex("280", "Капітальне будівництво", ("151",)),
        _capex("290", "Придбання (виготовлення) основних засобів", ("152",)),
        _capex("300", "Придбання (виготовлення) інших необоротних матеріальних активів", ("153",)),
        _capex("310", "Придбання (створення) нематеріальних активів", ("154",)),
        _capex("320", "Придбання (вирощування) довгострокових біологічних активів", ("155",)),
        _capex("330", "Інші", ("15",), ("151", "152", "153", "154", "155")),
        ("340", "Разом", "total", ["280", "290", "300", "310", "320", "330"]),
    ],
    "income": [
        _pl("440", "Операційна оренда активів", ("713",)),
        _pl("450", "Операційна курсова різниця", ("714",), ("945",)),
        _pl("460", "Реалізація інших оборотних активів", ("712",), ("943",)),
        _pl("470", "Штрафи, пені, неустойки", ("715",), ("948",)),
        _pl("480", "Утримання об'єктів житлово-комунального і соціально-культурного призначення"),
        _pl("490", "Інші операційні доходи і витрати", ("71",), ("94",),
            ("712", "713", "714", "715"), ("943", "945", "948")),
        _pl("491", "у тому числі: відрахування до резерву сумнівних боргів", (), ("944",), kind="sub"),
        _pl("492", "непродуктивні витрати і втрати", (), ("947",), kind="sub"),
        _pl("500", "Участь в капіталі: асоційовані підприємства", ("721",), ("961",)),
        _pl("510", "Участь в капіталі: дочірні підприємства", ("723",), ("963",)),
        _pl("520", "Участь в капіталі: спільна діяльність", ("722",), ("962",)),
        _pl("530", "Дивіденди", ("731",)),
        _pl("540", "Проценти", (), ("951",)),
        _pl("550", "Фінансова оренда активів"),
        _pl("560", "Інші фінансові доходи і витрати", ("732", "733"), ("952",)),
        _pl("570", "Реалізація фінансових інвестицій", ("741",), ("971",)),
        _pl("580", "Доходи від об'єднання підприємств"),
        _pl("590", "Результат оцінки корисності", ("742",), ("972",)),
        _pl("600", "Неопераційна курсова різниця", ("744",), ("974",)),
        _pl("610", "Безоплатно одержані активи", ("745",)),
        _pl("620", "Списання необоротних активів", (), ("976",)),
        _pl("630", "Інші доходи і витрати", ("740", "743", "746"), ("970", "973", "975", "977")),
    ],
    "cash": [
        ("640", "Каса", "item", {"c3": [_end(("30",))]}),
        ("650", "Поточний рахунок у банку", "item", {"c3": [_end(("311", "312"))]}),
        ("660", "Інші рахунки в банку (акредитиви, чекові книжки)", "item",
         {"c3": [_end(("313", "314", "315", "316", "331", "332", "335"))]}),
        ("670", "Грошові кошти в дорозі", "item", {"c3": [_end(("333", "334"))]}),
        ("680", "Еквіваленти грошових коштів", "item", {"c3": [_end(("351",))]}),
        ("690", "Разом", "total", ["640", "650", "660", "670", "680"]),
    ],
    "provision": [
        _provision("710", "Забезпечення на виплату відпусток працівникам", ("471",)),
        _provision("720", "Забезпечення наступних витрат на додаткове пенсійне забезпечення", ("472",)),
        _provision("730", "Забезпечення наступних витрат на виконання гарантійних зобов'язань", ("473",)),
        _provision("740", "Забезпечення наступних витрат на реструктуризацію", ()),
        _provision("750", "Забезпечення наступних витрат на виконання зобов'язань щодо обтяжливих контрактів", ()),
        _provision("760", "Забезпечення інших витрат і платежів (474-478)",
                   ("474", "475", "476", "477", "478")),
        _provision("775", "Резерв сумнівних боргів", ("38",)),
        ("780", "Разом", "total", ["710", "720", "730", "740", "750", "760", "775"]),
    ],
    "inventory": [
        _stock("800", "Сировина і матеріали", ("200", "201", "206", "209")),
        _stock("810", "Купівельні напівфабрикати та комплектуючі вироби", ("202",)),
        _stock("820", "Паливо", ("203",)),
        _stock("830", "Тара і тарні матеріали", ("204",)),
        _stock("840", "Будівельні матеріали", ("205",)),
        _stock("850", "Запасні частини", ("207",)),
        _stock("860", "Матеріали сільськогосподарського призначення", ("208",)),
        _stock("870", "Поточні біологічні активи", ("21",)),
        _stock("880", "Малоцінні та швидкозношувані предмети", ("22",)),
        _stock("890", "Незавершене виробництво", ("23", "24", "25")),
        _stock("900", "Готова продукція", ("26", "27")),
        _stock("910", "Товари", ("28",), ("286",)),
        ("920", "Разом", "total", ["800", "810", "820", "830", "840", "850", "860", "870", "880", "890",
                                   "900", "910"]),
    ],
    "shortage": [
        ("960", "Виявлено (списано) за рік нестач і втрат", "item", {"c3": [_dt(("947",))]}),
        ("970", "Визнано заборгованістю винних осіб у звітному році", "item", {"c3": [_dt(("375",))]}),
        ("980", "Сума нестач і втрат, остаточне рішення щодо винуватців за якими на кінець року не "
                "прийнято (позабалансовий рахунок 072)", "item", {}),
    ],
    "tax": [
        ("1210", "Поточний податок на прибуток", "item", {"c3": [_dt(("98",), counters=("641",))]}),
        ("1220", "Відстрочені податкові активи: на початок звітного року", "item", {"c3": [_start(("17",))]}),
        ("1225", "Відстрочені податкові активи: на кінець звітного року", "item", {"c3": [_end(("17",))]}),
        ("1230", "Відстрочені податкові зобов'язання: на початок звітного року", "item",
         {"c3": [_start(("54",), -1)]}),
        ("1235", "Відстрочені податкові зобов'язання: на кінець звітного року", "item",
         {"c3": [_end(("54",), -1)]}),
        ("1241", "Включено до звіту про фінансові результати: поточний податок на прибуток", "sub",
         {"c3": [_dt(("98",), counters=("641",)), _ct(("98",), -1, counters=("641",))]}),
        ("1242", "Зменшення (збільшення) відстрочених податкових активів", "sub",
         {"c3": [_ct(("17",), counters=("98",)), _dt(("17",), -1, counters=("98",))]}),
        ("1243", "Збільшення (зменшення) відстрочених податкових зобов'язань", "sub",
         {"c3": [_ct(("54",), counters=("98",)), _dt(("54",), -1, counters=("98",))]}),
        ("1240", "Включено до звіту про фінансові результати - усього", "total", ["1241", "1242", "1243"]),
        ("1251", "Відображено у складі власного капіталу: поточний податок на прибуток", "sub",
         {"c3": [_ct(("641",), counters=("4",)), _dt(("641",), -1, counters=("4",))]}),
        ("1252", "Зменшення (збільшення) відстрочених податкових активів", "sub",
         {"c3": [_ct(("17",), counters=("4",)), _dt(("17",), -1, counters=("4",))]}),
        ("1253", "Збільшення (зменшення) відстрочених податкових зобов'язань", "sub",
         {"c3": [_ct(("54",), counters=("4",)), _dt(("54",), -1, counters=("4",))]}),
        ("1250", "Відображено у складі власного капіталу - усього", "total", ["1251", "1252", "1253"]),
    ],
    "amortization": [
        ("1300", "Нараховано за звітний рік", "item",
         {"c3": [_ct(DEPRECIATION, without=("10", "11", "12", "16") + REVALUATION + IMPAIRMENT)]}),
    ],
}
# Рядки, що в друкованій формі йдуть перед своїм підсумком, а розраховуються після.
ORDER = {"tax": ["1210", "1220", "1225", "1230", "1235", "1240", "1241", "1242", "1243", "1250", "1251",
                 "1252", "1253"]}
RECEIVABLE_ROWS = [
    ("940", "Дебіторська заборгованість за товари, роботи, послуги", ("36",), ()),
    ("950", "Інша поточна дебіторська заборгованість",
     ("34", "372", "373", "374", "375", "376", "377", "378", "379"), ()),
]


def _match(code, prefixes, exclude=()):
    return bool(code) and code.startswith(prefixes) and not (exclude and code.startswith(exclude))


class UaNotesStatement(models.Model):
    _name = "ua.notes.statement"
    _description = "Примітки до річної фінансової звітності (форма № 5)"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date(
        "З", required=True, tracking=True,
        default=lambda self: (fields.Date.context_today(self) - relativedelta(years=1)).replace(month=1, day=1))
    date_to = fields.Date(
        "По", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1) - timedelta(days=1))
    state = fields.Selection(
        [("draft", "Чернетка"), ("done", "Затверджено")], default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.notes.statement.line", "statement_id", string="Рядки")
    intangible_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                     domain=[("section", "=", "intangible")], string="I")
    fixed_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                domain=[("section", "=", "fixed")], string="II")
    capex_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                domain=[("section", "=", "capex")], string="III")
    income_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                 domain=[("section", "=", "income")], string="V")
    cash_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                               domain=[("section", "=", "cash")], string="VI")
    provision_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                    domain=[("section", "=", "provision")], string="VII")
    inventory_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                    domain=[("section", "=", "inventory")], string="VIII")
    receivable_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                     domain=[("section", "=", "receivable")], string="IX")
    other_ids = fields.One2many("ua.notes.statement.line", "statement_id",
                                domain=[("section", "in", ("shortage", "tax", "amortization"))],
                                string="X, XII, XIII")
    check_text = fields.Text("Зауваження", readonly=True)
    computed_at = fields.Datetime("Розраховано", readonly=True)

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for st in self:
            if st.date_from and st.date_to:
                st.name = "Ф5 %s - %s" % (st.date_from.strftime("%d.%m.%Y"), st.date_to.strftime("%d.%m.%Y"))
            else:
                st.name = "Ф5"

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for st in self:
            if st.date_from and st.date_to and st.date_from > st.date_to:
                raise ValidationError(_("Початок періоду пізніше за кінець."))

    # ------------------------------------------------------------------ дані з обліку
    def _ua_base(self):
        return [("parent_state", "=", "posted"), ("company_id", "=", self.company_id.id)]

    def _ua_period(self):
        return self._ua_base() + [("date", ">=", self.date_from), ("date", "<=", self.date_to)]

    def _ua_load(self):
        """Коди рахунків і суми за рахунками: сальдо до початку, на кінець, обороти періоду."""
        Account = self.env["account.account"].with_company(self.company_id)
        codes = {a.id: a.code or "" for a in Account.search([("company_ids", "in", self.company_id.id)])}
        AML = self.env["account.move.line"]
        start, end, debit, credit = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
        for account, balance in AML._read_group(
                self._ua_base() + [("date", "<", self.date_from)], groupby=["account_id"],
                aggregates=["balance:sum"]):
            start[account.id] = balance or 0.0
        for account, balance, deb, cred in AML._read_group(
                self._ua_period(), groupby=["account_id"],
                aggregates=["balance:sum", "debit:sum", "credit:sum"]):
            debit[account.id], credit[account.id] = deb or 0.0, cred or 0.0
            end[account.id] = start[account.id] + (balance or 0.0)
        for account_id, value in start.items():
            end.setdefault(account_id, value)
        return {"codes": codes, "start": start, "end": end, "debit": debit, "credit": credit, "lines": {}}

    def _ua_accounts(self, data, prefixes, exclude=()):
        return [aid for aid, code in data["codes"].items() if _match(code, prefixes, exclude)]

    def _ua_counters(self, line):
        """Коди рахунків на протилежному боці тієї самої проводки."""
        currency = self.company_id.currency_id
        debit = line.balance > 0
        return [other.account_id.code or "" for other in line.move_id.line_ids
                if other != line and not currency.is_zero(other.balance) and (other.balance > 0) != debit]

    def _ua_term(self, data, term):
        accounts = self._ua_accounts(data, term["prefixes"], term["exclude"])
        kind = term["kind"]
        if kind in ("start", "end"):
            return term["sign"] * sum(data[kind].get(aid, 0.0) for aid in accounts)
        if term["counters"] is None and not term["without"]:
            return term["sign"] * sum(data[kind].get(aid, 0.0) for aid in accounts)
        key = (term["prefixes"], term["exclude"])
        if key not in data["lines"]:
            data["lines"][key] = self.env["account.move.line"].search(
                self._ua_period() + [("account_id", "in", accounts)])
        total = 0.0
        for line in data["lines"][key]:
            amount = line.debit if kind == "debit" else line.credit
            if not amount:
                continue
            counters = self._ua_counters(line)
            if term["counters"] is not None and not any(c.startswith(term["counters"]) for c in counters):
                continue
            if term["without"] and any(c.startswith(term["without"]) for c in counters):
                continue
            total += amount
        return term["sign"] * total

    # ------------------------------------------------------------------ розділи
    def _ua_table_rows(self, section, data):
        values, rows = {}, []
        for code, name, kind, spec in TABLES[section]:
            if kind == "total":
                amounts = {c: sum(values[part][c] for part in spec) for c in COLS}
            else:
                amounts = dict.fromkeys(COLS, 0.0)
                for column, terms in spec.items():
                    amounts[column] = sum(self._ua_term(data, term) for term in terms)
            values[code] = amounts
            rows.append((code, name, kind, amounts))
        order = ORDER.get(section)
        if order:
            rows.sort(key=lambda row: order.index(row[0]))
        return rows

    def _ua_asset_rows(self, section, data):
        """Розділи I і II: рух за групами, графи 3-15."""
        table = ASSET_TABLES[section]
        groups = table["rows"]
        codes = data["codes"]
        AML = self.env["account.move.line"]
        has_asset = "asset_id" in AML._fields
        notes = []

        def group_of(code):
            for row_code, _name, prefixes, exclude in groups:
                if _match(code, prefixes, exclude):
                    return row_code
            return None

        cells = {row[0]: dict.fromkeys(COLS, 0.0) for row in groups}
        cost_ids = {aid: group_of(code) for aid, code in codes.items() if group_of(code)}
        depr_ids = [aid for aid, code in codes.items() if _match(code, table["depr"])]
        for aid, grp in cost_ids.items():
            cells[grp]["c3"] += data["start"].get(aid, 0.0)
        unassigned = [0]

        def depr_group(line, counters):
            if has_asset and line.asset_id:
                grp = group_of(line.asset_id.profile_id.account_asset_id.code or "")
                if grp:
                    return grp
            for counter in counters:
                grp = group_of(counter)
                if grp:
                    return grp
            if has_asset and line.asset_profile_id:
                grp = group_of(line.asset_profile_id.account_asset_id.code or "")
                if grp:
                    return grp
            unassigned[0] += 1
            code = codes.get(line.account_id.id, "")
            for prefix, grp in table["fallback"].items():
                if code.startswith(prefix):
                    return grp
            return groups[-1][0]

        # Знос на початок: усі рядки до початку періоду, за активом або поштучно.
        before = self._ua_base() + [("date", "<", self.date_from), ("account_id", "in", depr_ids)]
        if has_asset and depr_ids:
            for asset, balance in AML._read_group(
                    before + [("asset_id", "!=", False)], groupby=["asset_id"], aggregates=["balance:sum"]):
                grp = group_of(asset.profile_id.account_asset_id.code or "")
                if grp:
                    cells[grp]["c4"] -= balance or 0.0
                else:
                    for line in AML.search(before + [("asset_id", "=", asset.id)]):
                        cells[depr_group(line, self._ua_counters(line))]["c4"] -= line.balance
            before = before + [("asset_id", "=", False)]
        if depr_ids:
            for line in AML.search(before):
                cells[depr_group(line, self._ua_counters(line))]["c4"] -= line.balance
        unassigned_before = unassigned[0]

        currency = self.company_id.currency_id
        for line in AML.search(self._ua_period() + [("account_id", "in", list(cost_ids))]):
            if currency.is_zero(line.balance):
                continue
            counters = self._ua_counters(line)
            cell = cells[cost_ids[line.account_id.id]]
            if any(c.startswith(REVALUATION) for c in counters):
                cell["c6"] += line.balance
            elif counters and all(group_of(c) for c in counters):
                cell["c12"] += line.balance
            elif line.balance > 0:
                cell["c5"] += line.balance
            else:
                cell["c8"] -= line.balance
        for line in AML.search(self._ua_period() + [("account_id", "in", depr_ids)]) if depr_ids else []:
            if currency.is_zero(line.balance):
                continue
            counters = self._ua_counters(line)
            cell = cells[depr_group(line, counters)]
            amount = -line.balance
            if any(c.startswith(REVALUATION) for c in counters):
                cell["c7"] += amount
            elif any(c.startswith(IMPAIRMENT) for c in counters):
                cell["c11"] += amount
            elif amount < 0 and any(group_of(c) for c in counters):
                cell["c9"] -= amount
            elif amount > 0:
                cell["c10"] += amount
            else:
                cell["c13"] += amount
        if unassigned[0]:
            notes.append(_("%(section)s: %(count)s рядків зносу (амортизації) без активу і без рахунку групи "
                           "(%(before)s з них - до початку періоду) - у рядку інших активів. Вкажіть актив на "
                           "рядку проводки.") % {"section": dict(SECTIONS)[section], "count": unassigned[0],
                                                 "before": unassigned_before})
        rows = []
        for code, name, _prefixes, _exclude in groups:
            cell = cells[code]
            cell["c14"] = cell["c3"] + cell["c5"] + cell["c6"] - cell["c8"] + cell["c12"]
            cell["c15"] = cell["c4"] + cell["c7"] - cell["c9"] + cell["c10"] + cell["c11"] + cell["c13"]
            rows.append((code, name, "item", cell))
        total_code, total_name = table["total"]
        total = {c: sum(cells[row[0]][c] for row in groups) for c in COLS}
        rows.append((total_code, total_name, "total", total))
        book_cost = sum(data["end"].get(aid, 0.0) for aid in cost_ids)
        book_depr = -sum(data["end"].get(aid, 0.0) for aid in depr_ids)
        if currency.compare_amounts(total["c14"], book_cost) or currency.compare_amounts(total["c15"], book_depr):
            notes.append(_("%(section)s: залишок на кінець (%(cost).2f; %(depr).2f) не дорівнює сальдо рахунків "
                           "(%(book_cost).2f; %(book_depr).2f).") % {
                "section": dict(SECTIONS)[section], "cost": total["c14"], "depr": total["c15"],
                "book_cost": book_cost, "book_depr": book_depr})
        return rows, notes

    def _ua_receivable_rows(self, data):
        """Розділ IX: додатне сальдо контрагента, розкладене на найновіші дебетові обороти."""
        AML = self.env["account.move.line"]
        end = self.date_to
        bounds = [end - relativedelta(months=12), end - relativedelta(months=18), end - relativedelta(months=36)]
        rows = []
        for code, name, prefixes, exclude in RECEIVABLE_ROWS:
            accounts = self._ua_accounts(data, prefixes, exclude)
            cell = dict.fromkeys(COLS, 0.0)
            domain = self._ua_base() + [("date", "<=", end), ("account_id", "in", accounts)]
            for account, partner, balance in AML._read_group(
                    domain, groupby=["account_id", "partner_id"], aggregates=["balance:sum"]):
                left = balance or 0.0
                if left <= 0:
                    continue
                cell["c3"] += left
                debits = AML.search(domain + [("account_id", "=", account.id), ("partner_id", "=", partner.id),
                                              ("debit", ">", 0)], order="date desc, id desc")
                for line in debits:
                    part = min(left, line.debit)
                    if line.date > bounds[0]:
                        cell["c4"] += part
                    elif line.date > bounds[1]:
                        cell["c5"] += part
                    elif line.date > bounds[2]:
                        cell["c6"] += part
                    left -= part
                    if left <= 0:
                        break
            rows.append((code, name, "item", cell))
        written_off = self._ua_term(data, _ct(("36", "37"), counters=("38", "944")))
        rows.append(("951", "Списано у звітному році безнадійної дебіторської заборгованості", "sub",
                     dict(dict.fromkeys(COLS, 0.0), c3=written_off)))
        return rows

    def action_compute(self):
        for st in self:
            if st.state == "done":
                raise UserError(_("Затверджені примітки не перераховують: поверніть їх у чернетку."))
            st.line_ids.unlink()
            data = st._ua_load()
            values, notes = [], []
            for section, _title in SECTIONS:
                if section in ASSET_TABLES:
                    rows, section_notes = st._ua_asset_rows(section, data)
                    notes += section_notes
                elif section == "receivable":
                    rows = st._ua_receivable_rows(data)
                else:
                    rows = st._ua_table_rows(section, data)
                for seq, (code, name, kind, amounts) in enumerate(rows, 1):
                    values.append(dict({c: amounts.get(c, 0.0) for c in COLS}, statement_id=st.id, section=section,
                                       sequence=seq * 10, code=code, name=name, row_kind=kind))
            self.env["ua.notes.statement.line"].create(values)
            st.invalidate_recordset()
            lines = {(l.section, l.code): l for l in st.line_ids}
            charged = lines[("intangible", "080")].c10 + lines[("fixed", "260")].c10
            if st.currency_id.compare_amounts(lines[("amortization", "1300")].c3, charged):
                notes.append(_("Рядок 1300 (%(row).2f) не дорівнює амортизації розділів I і II (%(sum).2f): "
                               "різниця - знос біологічних активів (134) або нарахування поза групами.")
                             % {"row": lines[("amortization", "1300")].c3, "sum": charged})
            pl = [l for l in st.line_ids if l.section == "income" and l.row_kind == "item"]
            for column, prefixes, label in (("c3", PL_INCOME, _("доходів (71-74)")),
                                            ("c4", PL_EXPENSE, _("витрат (94-97)"))):
                sign = 1 if column == "c3" else -1
                book = sign * (st._ua_term(data, _ct(prefixes, without=CLOSING))
                               - st._ua_term(data, _dt(prefixes, without=CLOSING)))
                shown = sum(l[column] for l in pl)
                if st.currency_id.compare_amounts(shown, book):
                    notes.append(_("Розділ V: рядки %(label)s дають %(shown).2f, а обороти рахунків - %(book).2f; "
                                   "різниця на рахунках, яких немає в жодному рядку.")
                                 % {"label": label, "shown": shown, "book": book})
            st.write({"check_text": "\n".join(notes) or False, "computed_at": fields.Datetime.now()})
        return True

    def action_done(self):
        for st in self:
            if not st.line_ids:
                raise UserError(_("Спершу розрахуйте примітки."))
            st.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_notes.action_report_ua_notes").report_action(self)

    # ------------------------------------------------------------------ друк
    def ua_sections(self):
        """Для друку: (назва розділу, [(графа, заголовок)], [(назва, код, вид, [суми])])."""
        self.ensure_one()
        result = []
        for section, title in SECTIONS:
            head = HEADS[section]
            lines = self.line_ids.filtered(lambda l: l.section == section).sorted("sequence")
            result.append((title, head, [(l.name, l.code, l.row_kind, [l[c] for c, _label in head])
                                         for l in lines]))
        return result

    def ua_money(self, value):
        """Сума для форми: від'ємна в дужках, нуль - прочерк."""
        self.ensure_one()
        if self.currency_id.is_zero(value or 0.0):
            return "-"
        text = "{:,.2f}".format(abs(value)).replace(",", " ")
        return "(%s)" % text if value < 0 else text


class UaNotesStatementLine(models.Model):
    _name = "ua.notes.statement.line"
    _description = "Рядок форми № 5"
    _order = "section, sequence, id"

    statement_id = fields.Many2one("ua.notes.statement", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="statement_id.company_id", store=True)
    currency_id = fields.Many2one(related="statement_id.currency_id")
    section = fields.Selection(SECTIONS, string="Розділ", required=True)
    sequence = fields.Integer()
    code = fields.Char("Код рядка")
    name = fields.Char("Показник", required=True)
    row_kind = fields.Selection(
        [("item", "Рядок"), ("sub", "У тому числі"), ("total", "Підсумок")], string="Вид",
        required=True, default="item")
    c3 = fields.Monetary("Гр. 3", currency_field="currency_id")
    c4 = fields.Monetary("Гр. 4", currency_field="currency_id")
    c5 = fields.Monetary("Гр. 5", currency_field="currency_id")
    c6 = fields.Monetary("Гр. 6", currency_field="currency_id")
    c7 = fields.Monetary("Гр. 7", currency_field="currency_id")
    c8 = fields.Monetary("Гр. 8", currency_field="currency_id")
    c9 = fields.Monetary("Гр. 9", currency_field="currency_id")
    c10 = fields.Monetary("Гр. 10", currency_field="currency_id")
    c11 = fields.Monetary("Гр. 11", currency_field="currency_id")
    c12 = fields.Monetary("Гр. 12", currency_field="currency_id")
    c13 = fields.Monetary("Гр. 13", currency_field="currency_id")
    c14 = fields.Monetary("Гр. 14", currency_field="currency_id")
    c15 = fields.Monetary("Гр. 15", currency_field="currency_id")
    c16 = fields.Monetary("Гр. 16", currency_field="currency_id")
    c17 = fields.Monetary("Гр. 17", currency_field="currency_id")
    c18 = fields.Monetary("Гр. 18", currency_field="currency_id")
    c19 = fields.Monetary("Гр. 19", currency_field="currency_id")
