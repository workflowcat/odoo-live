"""Річна декларація з податку на прибуток підприємств.

Один документ на компанію і рік, з рядками, як у самій декларації:

    01    дохід від будь-якої діяльності (Ф2: 2000 + 2120 + 2240)
    02    фінансовий результат до оподаткування (Ф2 ряд. 2290)
    03.1  амортизаційна різниця (ст. 138 ПКУ)
    03.2  збиток минулих років (пп. 140.4.4 ПКУ)
    03    різниці, усього
    04    об'єкт оподаткування (02 + 03, не менше нуля)
    06    податок на прибуток (04 × ставка)
    16    авансові внески, сплачені у звітному році
    19    податок до сплати (06 - 16, не менше нуля)

Фінрезультат не рахується вдруге. Його бере звіт mis_builder за шаблоном
Ф2 з l10n_ua_finrep - той самий, що його друкує бухгалтер: один сорс
правди. Форма Ф2 має рядок 2290 зі знаком (збиток - від'ємне число),
окремого рядка 2295 у шаблоні немає, тож і тут прибуток і збиток - одне
поле зі знаком.

Амортизаційна різниця (ст. 138.1 і 138.2 ПКУ): бухгалтерська амортизація
року збільшує фінрезультат, податкова зменшує. Податкову рахуємо за
мінімально допустимим строком групи з профілю активу
(l10n_ua_assets.account.asset.profile.ua_min_months, п. 138.3.3 ПКУ).
Залежність м'яка: якщо модуля основних засобів у базі немає, різниця
нульова і документ про це каже словами.

XML для подання модуль не робить. Чинну схему ДПС ми не звіряли, а
чернетка формату, яку не можна подати, користі не дає.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

KEY_RATE = "profit_tax_rate"
KEY_LOW_INCOME = "profit_low_income_limit"

STATES = [("draft", "Чернетка"), ("confirmed", "Підтверджено")]


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

    income_total = fields.Monetary("01 Дохід від будь-якої діяльності", readonly=True)
    finres = fields.Monetary(
        "02 Фінансовий результат до оподаткування", readonly=True,
        help="Ф2 ряд. 2290 за звітний рік. Збиток - від'ємне число.")
    diff_amortisation = fields.Monetary(
        "03.1 Амортизаційна різниця", readonly=True,
        help="Бухгалтерська амортизація року мінус податкова за мінімальним "
             "строком групи (ст. 138 ПКУ). Додатна різниця збільшує об'єкт.")
    diff_loss = fields.Monetary(
        "03.2 Збиток минулих років", readonly=True,
        help="Непогашений збиток попередніх років зменшує об'єкт "
             "(пп. 140.4.4 ПКУ). Число від'ємне.")
    diff_total = fields.Monetary("03 Різниці, усього", readonly=True)
    tax_base = fields.Monetary("04 Об'єкт оподаткування", readonly=True)
    rate = fields.Float("Ставка, %", digits=(16, 2), readonly=True)
    tax_amount = fields.Monetary("06 Податок на прибуток", readonly=True)
    advance_paid = fields.Monetary(
        "16 Авансові внески",
        help="Сплачені у звітному році авансові внески з податку на прибуток. "
             "Вводить бухгалтер: у плані рахунків окремого рахунку авансів немає.")
    tax_to_pay = fields.Monetary(
        "19 Податок до сплати", compute="_compute_tax_to_pay", store=True)
    low_income = fields.Boolean(
        "Малодохідник", readonly=True,
        help="Дохід не перевищує поріг пп. 134.1.1 ПКУ: різниці можна не "
             "застосовувати, крім збитків минулих років.")
    low_income_limit = fields.Monetary("Поріг малодохідника", readonly=True)
    note = fields.Text("Примітки розрахунку", readonly=True)
    line_ids = fields.One2many(
        "ua.profit.declaration.line", "declaration_id", "Рядки декларації",
        readonly=True)

    _company_year_uniq = models.Constraint(
        "unique(company_id, year)", "Декларація за цей рік для компанії вже існує."
    )

    @api.depends("company_id", "year")
    def _compute_name(self):
        for record in self:
            record.name = "Декларація з прибутку %s - %s" % (
                record.year or "", record.company_id.name or "")

    @api.depends("tax_amount", "advance_paid")
    def _compute_tax_to_pay(self):
        for record in self:
            record.tax_to_pay = max(record.tax_amount - record.advance_paid, 0.0)

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

    def _amortisation_difference(self):
        """(різниця, примітка). Бухгалтерська амортизація мінус податкова.

        М'яка залежність: модель активів дає l10n_ua_assets поверх OCA
        account_asset_management. Немає модуля - немає різниці.
        """
        self.ensure_one()
        if "account.asset" not in self.env:
            return 0.0, ("Модуль основних засобів не встановлено: амортизаційна "
                         "різниця прийнята нульовою.")
        date_from, date_to = self._year_bounds()
        assets = self.env["account.asset"].sudo().search([
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("open", "close", "removed")),
        ])
        difference, without_minimum = 0.0, 0
        for asset in assets:
            lines = asset.depreciation_line_ids.filtered(
                lambda line: (line.type == "depreciate"
                              and line.line_date
                              and date_from <= line.line_date <= date_to
                              and line.move_check))
            if not lines:
                continue
            book = sum(lines.mapped("amount"))
            minimum = getattr(asset.profile_id, "ua_min_months", 0) or 0
            if not minimum:
                without_minimum += 1
                continue  # мінімального строку за ПКУ немає - різниці теж
            tax = round(asset.depreciation_base / minimum * len(lines), 2)
            difference += round(book - tax, 2)
        note = ("Амортизаційна різниця порахована за %d активами; податкова "
                "амортизація - за мінімальним строком групи (ст. 138 ПКУ)."
                % len(assets))
        if without_minimum:
            note += (" Активів без мінімального строку групи: %d - за ними "
                     "різниці немає." % without_minimum)
        return round(difference, 2), note

    def _carried_loss(self):
        """Непогашений збиток минулих років (пп. 140.4.4 ПКУ), число від'ємне."""
        self.ensure_one()
        previous = self.search([
            ("company_id", "=", self.company_id.id),
            ("year", "<", self.year),
            ("state", "=", "confirmed"),
        ], order="year desc", limit=1)
        if not previous:
            return 0.0
        # Об'єкт попереднього року рахувався з нуля відсічений; збиток лежить
        # у полі «фінрезультат плюс різниці» до відсікання.
        previous_object = previous.finres + previous.diff_total
        return round(min(previous_object, 0.0), 2)

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
        income = round(f2.get("2000", 0.0) + f2.get("2120", 0.0)
                       + f2.get("2240", 0.0), 2)
        finres = round(f2.get("2290", 0.0), 2)
        amortisation, note = self._amortisation_difference()
        loss = self._carried_loss()
        differences = round(amortisation + loss, 2)
        base = round(max(finres + differences, 0.0), 2)
        tax = round(base * rate / 100.0, 2)
        self.write({
            "income_total": income,
            "finres": finres,
            "diff_amortisation": amortisation,
            "diff_loss": loss,
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
            ("03.1", "Різниця: амортизація (ст. 138 ПКУ)", self.diff_amortisation),
            ("03.2", "Різниця: збиток минулих років (пп. 140.4.4 ПКУ)", self.diff_loss),
            ("03", "Різниці, усього", self.diff_total),
            ("04", "Об'єкт оподаткування", self.tax_base),
            ("06", "Податок на прибуток (%.2f %%)" % self.rate, self.tax_amount),
            ("16", "Авансові внески, сплачені у звітному році", self.advance_paid),
            ("19", "Податок до сплати", self.tax_to_pay),
        ]
        self.env["ua.profit.declaration.line"].create([{
            "declaration_id": self.id,
            "sequence": (number + 1) * 10,
            "code": code,
            "name": label,
            "amount": amount,
        } for number, (code, label, amount) in enumerate(rows)])

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
