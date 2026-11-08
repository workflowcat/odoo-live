"""Річна декларація з податку на прибуток підприємств і її XML для ДПС.

Один документ на компанію і рік, з рядками, як у самій декларації (J0100129, наказ
Мінфіну № 897 у редакції наказу № 101 від 2023 року) і в додатку РІ (J0111829):

    01        дохід від будь-якої діяльності (Ф2: 2000 + 2120 + 2200 + 2220 + 2240)
    02        фінансовий результат до оподаткування (Ф2 ряд. 2290)
    РІ 2.1.1  бухгалтерська амортизація року (збільшує)
    РІ 2.2.1  податкова амортизація за ст. 138 ПКУ (зменшує)
    РІ 3.2.4  від'ємне значення об'єкта минулих років (зменшує, пп. 140.4.4 ПКУ)
    03        різниці, усього
    04        об'єкт оподаткування (02 + 03; від'ємний переходить на наступний рік)
    06        податок (додатний 04 × ставка)
    17        податок за звітний період (= 06)
    18        податок за попередній звітний період року (лише квартальні платники)
    19        податок до нарахування за останній квартал або рік (17 - 18)

Суми в гривнях без копійок, як у формі: рядки документа і рядки XML - ті самі числа.

Фінрезультат не рахується вдруге. Його бере звіт mis_builder за шаблоном Ф2 з
l10n_ua_finrep - той самий, що його друкує бухгалтер. Ф2 має рядок 2290 зі знаком
(збиток - від'ємне число), тож і тут прибуток і збиток - одне поле зі знаком.

Амортизація (ст. 138 ПКУ): у РІ йде вся бухгалтерська амортизація року і вся податкова.
Податкова - за мінімально допустимим строком групи з профілю активу
(l10n_ua_assets.account.asset.profile.ua_min_months, п. 138.3.3 ПКУ); актив без
мінімального строку дає податкову амортизацію, рівну бухгалтерській. Залежність м'яка:
якщо модуля основних засобів у базі немає, амортизація нульова і документ про це каже.

Від'ємне значення минулих років (пп. 140.4.4 ПКУ): непогашений залишок переходить з
попередньої підтвердженої декларації. Великий платник зменшує результат лише на частку
залишку (50 %), а якщо залишок не більший за 10 % додатного об'єкта - на весь залишок.
Частки - датовані параметри ua.profit.param; хто є великим платником - позначка в
документі. Обидва правила звіряйте з чинною редакцією ПКУ.

XML: основна форма і додаток РІ (якщо є різниці), пов'язані через LINKED_DOCS і перевірені
схемами з теки schemas. Схеми чинні для періодів, що закінчуються з 2025-10-01.
Не формуються: уточнююча декларація, рядки 05, 06.1-16 (пільги, КІК, страховики, лотереї,
дивіденди), авансові внески 20-28, додатки АМ, ЦП, ТЦ, БД.
"""

import base64
import re
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

from odoo.addons.l10n_ua_finrep_dps.models import dps_xml

KEY_RATE = "profit_tax_rate"
KEY_LOW_INCOME = "profit_low_income_limit"
KEY_LOSS_SHARE = "profit_loss_share_large"
KEY_LOSS_FULL = "profit_loss_full_if_large"

# Рядки Ф2, що складають рядок 01 декларації (дохід від будь-якої діяльності).
INCOME_ROWS = ("2000", "2120", "2200", "2220", "2240")

FORM_MAIN = "J0100129"
FORM_RI = "J0111829"
# Перший день, з якого закінчуються звітні періоди для цих версій схем (перевіряйте чинні).
FORM_FROM = date(2025, 10, 1)

STATES = [("draft", "Чернетка"), ("confirmed", "Підтверджено")]
BASE_PERIODS = [("year", "Рік (H02)"), ("quarter", "Квартал (H01)")]
DOC_KINDS = [("HZ", "Звітна"), ("HZN", "Звітна нова")]


def _uah(value):
    """Гривні без копійок, половина - вгору від нуля, як у формі."""
    return float_round(value or 0.0, precision_digits=0)


def _digits(value):
    return re.sub(r"\D", "", value or "")


class UaProfitDeclaration(models.Model):
    _name = "ua.profit.declaration"
    _description = "Декларація з податку на прибуток"
    _order = "year desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", "Компанія", required=True,
        default=lambda self: self.env.company,
        help="Платник податку на прибуток на загальній системі. ФОП-єдинники "
             "звітують декларацією платника ЄП - див. l10n_ua_fop.")
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True)
    year = fields.Integer(
        "Звітний рік", required=True,
        default=lambda self: fields.Date.context_today(self).year - 1)
    state = fields.Selection(
        STATES, "Стан", default="draft", required=True, copy=False, tracking=True)

    # --- як платник звітує ---------------------------------------------------
    base_period = fields.Selection(
        BASE_PERIODS, "Податковий період", default="year", required=True,
        help="Рік - для малодохідника (дохід до порогу пп. 134.1.1 ПКУ). Інші платники "
             "звітують щокварталу наростаючим підсумком, і річна декларація має рядок 18.")
    doc_kind = fields.Selection(DOC_KINDS, "Вид декларації", default="HZ", required=True)
    new_number = fields.Integer(
        "Номер звітної нової", default=1,
        help="Для звітної нової: котра вона за цей період (C_DOC_TYPE у файлі).")
    no_adjustments = fields.Boolean(
        "Без коригувань на різниці",
        help="Пп. 134.1.1 ПКУ: малодохідник може не застосовувати різниці, крім від'ємного "
             "значення минулих років. У декларації - позначка HJ2.")
    large_payer = fields.Boolean(
        "Великий платник податків",
        help="Для великого платника (пп. 14.1.24 ПКУ) від'ємне значення минулих років "
             "зменшує результат лише частково (пп. 140.4.4 ПКУ). Перевірте статус за "
             "чинною редакцією ПКУ і реєстром ДПС.")
    prior_tax = fields.Monetary(
        "18 Податок за попередній звітний період року",
        help="Лише для квартального платника: рядок 17 декларації за 9 місяців.")

    # --- числа декларації ----------------------------------------------------
    income_total = fields.Monetary("01 Дохід від будь-якої діяльності", readonly=True)
    finres = fields.Monetary(
        "02 Фінансовий результат до оподаткування", readonly=True,
        help="Ф2 ряд. 2290 за звітний рік. Збиток - від'ємне число.")
    amort_book = fields.Monetary(
        "РІ 2.1.1 Бухгалтерська амортизація", readonly=True,
        help="Амортизація основних засобів і нематеріальних активів у бухобліку за рік.")
    amort_tax = fields.Monetary(
        "РІ 2.2.1 Податкова амортизація", readonly=True,
        help="Амортизація за ст. 138 ПКУ: за мінімальним строком групи активу.")
    diff_amortisation = fields.Monetary(
        "Амортизаційна різниця", readonly=True,
        help="РІ 2.1.1 мінус РІ 2.2.1. Додатна різниця збільшує об'єкт.")
    diff_loss = fields.Monetary(
        "РІ 3.2.4 Від'ємне значення минулих років", readonly=True,
        help="Частина непогашеного від'ємного значення об'єкта минулих років, що зменшує "
             "об'єкт цього року (пп. 140.4.4 ПКУ). Число від'ємне.")
    loss_left = fields.Monetary(
        "Від'ємне значення на наступний рік", readonly=True,
        help="Непогашений залишок від'ємного значення після цього року. Наступна декларація "
             "бере його звідси.")
    diff_total = fields.Monetary("03 Різниці, усього", readonly=True)
    tax_base = fields.Monetary(
        "04 Об'єкт оподаткування", readonly=True,
        help="02 + 03. Від'ємне значення не оподатковують, воно переходить на наступний рік.")
    rate = fields.Float("Ставка, %", digits=(16, 2), readonly=True)
    tax_amount = fields.Monetary("06 Податок на прибуток", readonly=True)
    tax_due = fields.Monetary(
        "19 Податок до нарахування", compute="_compute_tax_due", store=True,
        help="17 - 18: для річного платника дорівнює податку року, для квартального - "
             "податку за IV квартал.")
    advance_paid = fields.Monetary(
        "Уже сплачено за рік",
        help="Сплачене у звітному році в рахунок податку на прибуток. У декларацію не йде: "
             "лише щоб бачити залишок до сплати.")
    tax_to_pay = fields.Monetary(
        "Залишок до сплати", compute="_compute_tax_to_pay", store=True,
        help="06 мінус уже сплачене, не менше нуля.")
    low_income = fields.Boolean(
        "Малодохідник", readonly=True,
        help="Дохід не перевищує поріг пп. 134.1.1 ПКУ: різниці можна не "
             "застосовувати, крім збитків минулих років.")
    low_income_limit = fields.Monetary("Поріг малодохідника", readonly=True)
    note = fields.Text("Примітки розрахунку", readonly=True)
    line_ids = fields.One2many(
        "ua.profit.declaration.line", "declaration_id", "Рядки декларації",
        readonly=True)

    # --- реквізити для XML ---------------------------------------------------
    tin = fields.Char("Код ЄДРПОУ", default=lambda self: _digits(self.env.company.company_registry))
    sti_code = fields.Char(
        "Код ДПІ", size=4, default=lambda self: self._ua_company_value("ua_dps_sti", "ua_sti_code"),
        help="Чотири цифри: перші дві - область (C_REG), дві наступні - район (C_RAJ).")
    sti_name = fields.Char(
        "Назва ДПІ", default=lambda self: self._ua_company_value("ua_sti_name"),
        help="Найменування контролюючого органу, як у шапці декларації.")
    kved = fields.Char("Основний КВЕД", default=lambda self: self._ua_company_value("ua_kved"))
    address = fields.Char("Адреса", default=lambda self: self._ua_company_address())
    phone = fields.Char("Телефон", default=lambda self: self.env.company.phone)
    email = fields.Char("Ел. пошта", default=lambda self: self.env.company.email)
    director = fields.Char("Керівник", default=lambda self: self._ua_company_value("ua_director_name"))
    director_rnokpp = fields.Char(
        "РНОКПП керівника", size=10, default=lambda self: self._ua_company_value("ua_director_rnokpp"))
    accountant = fields.Char("Головний бухгалтер",
                             default=lambda self: self._ua_company_value("ua_accountant_name"))
    accountant_rnokpp = fields.Char("РНОКПП бухгалтера", size=10)
    xml_file = fields.Binary("Декларація XML", attachment=True, readonly=True, copy=False)
    xml_name = fields.Char("Ім'я файлу декларації", readonly=True, copy=False)
    ri_xml_file = fields.Binary("Додаток РІ XML", attachment=True, readonly=True, copy=False)
    ri_xml_name = fields.Char("Ім'я файлу додатка РІ", readonly=True, copy=False)

    _company_year_uniq = models.Constraint(
        "unique(company_id, year)", "Декларація за цей рік для компанії вже існує."
    )

    @api.depends("company_id", "year")
    def _compute_name(self):
        for record in self:
            record.name = "Декларація з прибутку %s - %s" % (
                record.year or "", record.company_id.name or "")

    @api.depends("tax_amount", "prior_tax", "base_period")
    def _compute_tax_due(self):
        for record in self:
            prior = record.prior_tax if record.base_period == "quarter" else 0.0
            record.tax_due = record.tax_amount - prior

    @api.depends("tax_amount", "advance_paid")
    def _compute_tax_to_pay(self):
        for record in self:
            record.tax_to_pay = max(record.tax_amount - record.advance_paid, 0.0)

    @api.model
    def _ua_company_value(self, *names):
        """Реквізит компанії з поля іншого модуля, якщо такий модуль стоїть (звітність з ЄСВ, ПДВ)."""
        company = self.env.company
        for name in names:
            if name in company._fields and company[name]:
                return company[name]
        return False

    @api.model
    def _ua_company_address(self):
        company = self.env.company
        return ", ".join(filter(None, [company.zip, company.state_id.name, company.city, company.street,
                                       company.street2])) or False

    # --- період -------------------------------------------------------------

    def _year_bounds(self):
        self.ensure_one()
        if not self.year:
            raise UserError("У декларації не вказано звітний рік.")
        return (fields.Date.to_date("%d-01-01" % self.year),
                fields.Date.to_date("%d-12-31" % self.year))

    # --- фінрезультат: один сорс правди з фінзвітами -------------------------

    def _f2_values(self):
        """Рядки Ф2 за звітний рік з тимчасового звіту mis_builder."""
        self.ensure_one()
        date_from, date_to = self._year_bounds()
        instance = self.env["mis.report.instance"].create({
            "name": "Ф2 для декларації з прибутку %s" % self.year,
            "report_id": self.env.ref("l10n_ua_finrep.report_f2").id,
            "target_move": "posted",
            "company_id": self.company_id.id,
            "temporary": True,
            "period_ids": [(0, 0, {
                "name": "За звітний рік",
                "mode": "fix",
                "manual_date_from": date_from,
                "manual_date_to": date_to,
                "sequence": 1,
            })],
        })
        values = instance.with_company(self.company_id)._ua_finrep_values()
        instance.unlink()
        return values

    # --- різниці -------------------------------------------------------------

    def _amortisation_parts(self):
        """(бухгалтерська, податкова, примітка) амортизація року.

        М'яка залежність: модель активів дає l10n_ua_assets поверх OCA
        account_asset_management. Немає модуля - немає амортизації.
        """
        self.ensure_one()
        if "account.asset" not in self.env:
            return 0.0, 0.0, ("Модуль основних засобів не встановлено: амортизаційна "
                              "різниця прийнята нульовою.")
        date_from, date_to = self._year_bounds()
        assets = self.env["account.asset"].sudo().search([
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("open", "close", "removed")),
        ])
        book_total, tax_total, without_minimum = 0.0, 0.0, 0
        for asset in assets:
            lines = asset.depreciation_line_ids.filtered(
                lambda line: (line.type == "depreciate"
                              and line.line_date
                              and date_from <= line.line_date <= date_to
                              and line.move_check))
            if not lines:
                continue
            book = round(sum(lines.mapped("amount")), 2)
            minimum = getattr(asset.profile_id, "ua_min_months", 0) or 0
            if minimum:
                tax = round(asset.depreciation_base / minimum * len(lines), 2)
            else:
                without_minimum += 1
                tax = book  # мінімального строку за ПКУ немає - різниці теж
            book_total += book
            tax_total += tax
        note = ("Амортизаційна різниця порахована за %d активами; податкова "
                "амортизація - за мінімальним строком групи (ст. 138 ПКУ)."
                % len(assets))
        if without_minimum:
            note += (" Активів без мінімального строку групи: %d - за ними "
                     "податкова амортизація дорівнює бухгалтерській." % without_minimum)
        return _uah(book_total), _uah(tax_total), note

    def _amortisation_difference(self):
        """(різниця, примітка): бухгалтерська амортизація мінус податкова."""
        book, tax, note = self._amortisation_parts()
        return book - tax, note

    def _previous(self):
        self.ensure_one()
        return self.search([
            ("company_id", "=", self.company_id.id),
            ("year", "<", self.year),
            ("state", "=", "confirmed"),
        ], order="year desc", limit=1)

    def _carried_loss(self):
        """Непогашене від'ємне значення минулих років на початок року, число додатне."""
        self.ensure_one()
        previous = self._previous()
        if not previous:
            return 0.0
        if previous.loss_left:
            return previous.loss_left
        # Декларація, порахована до появи поля loss_left: залишок - від'ємний об'єкт.
        return max(-(previous.finres + previous.diff_total), 0.0)

    def _loss_used(self, carried, base_before, date_to):
        """Скільки від'ємного значення минулих років іде в РІ 3.2.4 (пп. 140.4.4 ПКУ)."""
        self.ensure_one()
        if not carried or not self.large_payer:
            return carried
        Param = self.env["ua.profit.param"]
        share = Param.get(KEY_LOSS_SHARE, date_to, self.company_id)
        full_if = Param.get(KEY_LOSS_FULL, date_to, self.company_id)
        if base_before > 0 and carried <= base_before * full_if / 100.0:
            return carried
        return _uah(carried * share / 100.0)

    # --- розрахунок ----------------------------------------------------------

    def action_compute(self):
        """Заповнити числа і рядки декларації. Дозволено лише в чернетці."""
        for record in self:
            if record.state != "draft":
                raise UserError(
                    "Декларацію %s підтверджено - поверніть її в чернетку, щоб "
                    "перерахувати." % record.name)
            record._compute_declaration()
        return True

    def _compute_declaration(self):
        self.ensure_one()
        _date_from, date_to = self._year_bounds()
        Param = self.env["ua.profit.param"]
        rate = Param.get(KEY_RATE, date_to, self.company_id)
        limit = Param.get(KEY_LOW_INCOME, date_to, self.company_id)
        f2 = self._f2_values()
        income = _uah(sum(f2.get(code, 0.0) for code in INCOME_ROWS))
        finres = _uah(f2.get("2290", 0.0))
        if self.no_adjustments:
            if income > limit:
                raise UserError(
                    "Не застосовувати різниці може лише платник з доходом до %.0f грн "
                    "(пп. 134.1.1 ПКУ), а дохід року %.0f грн." % (limit, income))
            book, tax_amort = 0.0, 0.0
            note = ("Різниці не застосовуються (пп. 134.1.1 ПКУ), крім від'ємного значення "
                    "минулих років.")
        else:
            book, tax_amort, note = self._amortisation_parts()
        amortisation = book - tax_amort
        carried = self._carried_loss()
        base_before = finres + amortisation
        used = self._loss_used(carried, base_before, date_to)
        loss_left = carried - min(used, max(base_before, 0.0)) + max(-base_before, 0.0)
        if carried and used < carried:
            note += (" Від'ємне значення минулих років %.0f грн враховано частково: %.0f грн "
                     "(великий платник, пп. 140.4.4 ПКУ)." % (carried, used))
        differences = amortisation - used
        base = finres + differences
        tax = _uah(max(base, 0.0) * rate / 100.0)
        self.write({
            "income_total": income,
            "finres": finres,
            "amort_book": book,
            "amort_tax": tax_amort,
            "diff_amortisation": amortisation,
            "diff_loss": -used,
            "loss_left": loss_left,
            "diff_total": differences,
            "tax_base": base,
            "rate": rate,
            "tax_amount": tax,
            "low_income": income <= limit,
            "low_income_limit": limit,
            "note": note,
        })
        self._rebuild_lines()
        return True

    def _rebuild_lines(self):
        """Рядки декларації з уже порахованих полів - без другої арифметики."""
        self.ensure_one()
        self.line_ids.unlink()
        rows = [
            ("01", "Дохід від будь-якої діяльності", self.income_total),
            ("02", "Фінансовий результат до оподаткування", self.finres),
            ("РІ 2.1.1", "Бухгалтерська амортизація (збільшує)", self.amort_book),
            ("РІ 2.2.1", "Податкова амортизація, ст. 138 ПКУ (зменшує)", -self.amort_tax),
            ("РІ 3.2.4", "Від'ємне значення минулих років, пп. 140.4.4 ПКУ (зменшує)",
             self.diff_loss),
            ("03", "Різниці, усього", self.diff_total),
            ("04", "Об'єкт оподаткування", self.tax_base),
            ("06", "Податок на прибуток (%.2f %%)" % self.rate, self.tax_amount),
            ("17", "Податок за звітний період", self.tax_amount),
        ]
        if self.base_period == "quarter":
            rows.append(("18", "Податок за попередній звітний період року", self.prior_tax))
        rows.append(("19", "Податок до нарахування", self.tax_due))
        self.env["ua.profit.declaration.line"].create([{
            "declaration_id": self.id,
            "sequence": (number + 1) * 10,
            "code": code,
            "name": label,
            "amount": amount,
        } for number, (code, label, amount) in enumerate(rows)])

    # --- XML -----------------------------------------------------------------

    def _ua_head_problems(self):
        self.ensure_one()
        problems = []
        if not re.fullmatch(r"\d{8}", _digits(self.tin)):
            problems.append("код ЄДРПОУ - 8 цифр")
        if not re.fullmatch(r"\d{4}", _digits(self.sti_code)):
            problems.append("код ДПІ - 4 цифри")
        if not (self.sti_name or "").strip():
            problems.append("назва ДПІ")
        if not re.fullmatch(r"\d{2}\.\d{1,2}(\.\d)?", (self.kved or "").strip()):
            problems.append("КВЕД у вигляді 00.00")
        if not (self.address or "").strip():
            problems.append("адреса")
        if not (self.director or "").strip():
            problems.append("керівник")
        if not re.fullmatch(r"\d{10}", _digits(self.director_rnokpp)):
            problems.append("РНОКПП керівника - 10 цифр")
        if not self.line_ids:
            problems.append("рядки (кнопка «Розрахувати»)")
        return problems

    def _ua_has_ri(self):
        self.ensure_one()
        return any(_uah(value) for value in (self.amort_book, self.amort_tax, self.diff_loss))

    def _ua_xml(self):
        """[(ім'я файлу, байти)]: декларація і, якщо є різниці, додаток РІ; перевірені схемами."""
        self.ensure_one()
        _date_from, date_to = self._year_bounds()
        if date_to < FORM_FROM:
            raise UserError(
                "Схеми %s і %s - для звітних періодів, що закінчуються з %s. Для %s діяла "
                "інша версія форми." % (FORM_MAIN, FORM_RI, FORM_FROM.isoformat(), self.year))
        problems = self._ua_head_problems()
        if problems:
            raise UserError("Для XML заповніть: %s." % "; ".join(problems))
        sti, tin = _digits(self.sti_code), _digits(self.tin)
        state, doc_type = (2, max(self.new_number, 1)) if self.doc_kind == "HZN" else (1, 0)
        period_type, month = 5, 12  # рік; квартальний платник за рік подає теж річну
        fill_date = fields.Date.context_today(self)
        common = {self.doc_kind: True, "HTIN": tin, "HZY": str(self.year), "HY": True}
        with_ri = self._ua_has_ri()
        name_main = dps_xml.file_name(FORM_MAIN, sti, tin, period_type, month, self.year,
                                      state=state, doc_type=doc_type)
        name_ri = dps_xml.file_name(FORM_RI, sti, tin, period_type, month, self.year,
                                    state=state, doc_type=doc_type)
        phone = re.sub(r"[^0-9 ()\-+.,;]", "", self.phone or "")
        zip_code = (self.company_id.zip or "").strip()
        main = dict(common, **{
            "H01" if self.base_period == "quarter" else "H02": True,
            "HNAME": self.company_id.name,
            "HKVED": self.kved.strip(),
            "HLOC": self.address.strip(),
            "HZIP": zip_code if re.fullmatch(r"\d{5}", zip_code) else False,
            "HTEL": phone if len(phone) >= 4 else False,
            "HEMAIL": self.email if re.fullmatch(r"[^@\s]+@[^@\s]+", self.email or "") else False,
            "HSTI": self.sti_name.strip(),
            "R001G3": self.income_total,
            "R002G3": self.finres,
            "R003G3": self.diff_total if with_ri else 0.0,
            "R004G3": self.tax_base,
            "R006G1": self.rate,
            "R006G3": self.tax_amount,
            "R017G3": self.tax_amount,
            "R018G3": self.prior_tax if self.base_period == "quarter" else 0.0,
            "R019G3": self.tax_due,
            "HD6": with_ri,
            "HJ2": self.no_adjustments,
            "HBOS": self.director.strip(),
            "HKBOS": _digits(self.director_rnokpp),
            "HBUH": (self.accountant or "").strip(),
            "HKBUH": _digits(self.accountant_rnokpp) if self.accountant else False,
            "HFILL": fill_date.strftime("%d%m%Y"),
        })
        files = []
        try:
            files.append(dps_xml.build(
                dps_xml.schema_path(__file__, FORM_MAIN), FORM_MAIN, sti, tin, period_type, month,
                self.year, fill_date, main, linked=[(FORM_RI, name_ri, 1)] if with_ri else (),
                state=state, doc_type=doc_type))
            if with_ri:
                ri = dict(common, **{
                    "R0211G3": self.amort_book,
                    "R0221G3": self.amort_tax,
                    "R0324G3": -self.diff_loss,
                    "R001G3": self.amort_book,
                    "R002G3": self.amort_tax - self.diff_loss,
                    "R003G3": self.diff_total,
                    "HBOS": self.director.strip(),
                    "HBUH": (self.accountant or "").strip(),
                })
                files.append(dps_xml.build(
                    dps_xml.schema_path(__file__, FORM_RI), FORM_RI, sti, tin, period_type, month,
                    self.year, fill_date, ri, linked=[(FORM_MAIN, name_main, 2)],
                    state=state, doc_type=doc_type))
        except ValueError as error:
            raise UserError("XML не відповідає схемі ДПС:\n%s" % error) from error
        return files

    def action_xml(self):
        """Зберегти XML декларації і додатка РІ в документі."""
        for record in self:
            files = record._ua_xml()
            (name, data), ri = files[0], files[1] if len(files) > 1 else (False, False)
            record.write({
                "xml_file": base64.b64encode(data), "xml_name": name,
                "ri_xml_file": ri[1] and base64.b64encode(ri[1]), "ri_xml_name": ri[0],
            })
        return True

    # --- стани ---------------------------------------------------------------

    def action_confirm(self):
        for record in self:
            if not record.line_ids:
                record._compute_declaration()
            record.state = "confirmed"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True


class UaProfitDeclarationLine(models.Model):
    _name = "ua.profit.declaration.line"
    _description = "Рядок декларації з податку на прибуток"
    _order = "sequence, id"

    declaration_id = fields.Many2one(
        "ua.profit.declaration", "Декларація", required=True,
        ondelete="cascade", index=True)
    company_id = fields.Many2one(
        "res.company", related="declaration_id.company_id", store=True)
    currency_id = fields.Many2one(
        "res.currency", related="declaration_id.currency_id", readonly=True)
    sequence = fields.Integer("Порядок", default=10)
    code = fields.Char("Рядок", required=True)
    name = fields.Char("Показник", required=True)
    amount = fields.Monetary("Сума")
