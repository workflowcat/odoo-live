"""Митна декларація на імпорт (ІМ-40) і що з нею робить облік.

Порядок розрахунку на рядок (Митний кодекс, ст. 49-58 - митна вартість; ПКУ, ст. 190 - база ПДВ):

    митна вартість = фактурна вартість * курс НБУ на дату декларації (поле можна виправити:
                     сюди ж додається доставка до кордону, якщо вона не у фактурі)
    мито           = митна вартість * ставка мита
    база ПДВ       = митна вартість + мито + акциз
    ПДВ            = база ПДВ * ставка ПДВ (20 %, 0 % при звільненні з підставою)

Митні збори за оформлення не входять у базу ПДВ, але входять у первісну вартість запасів
(П(С)БО 9, п. 9) і розносяться на рядки пропорційно митній вартості.

Проведення:
    Дт 20x (рахунок оцінки товару) / Кт 3771 - мито, акциз і збори, через нативний landed cost
        на отримані за декларацією надходження; середня собівартість товару зростає;
    Дт 6412 / Кт 3771 - митний ПДВ у податковий кредит (позначка ua_customs_entry, її бачить
        зведення ПДВ за період).
Оплата митниці з банку закриває 3771.

Брокер і доставка від кордону приходять окремими рахунками постачальників: їх у собівартість
розносить нативна кнопка landed cost на рахунку, тут вони не враховуються, щоб не задвоїти.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class UaCustomsDeclaration(models.Model):
    _name = "ua.customs.declaration"
    _description = "Митна декларація на імпорт"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(
        "Номер декларації", required=True, tracking=True, copy=False,
        help="Номер з митної декларації, напр. UA100010/2026/012345.")
    date = fields.Date(
        "Дата декларації", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, default=lambda self: self.env.company)
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", "Постачальник", tracking=True,
        help="Іноземний постачальник товару за контрактом.")
    customs_partner_id = fields.Many2one(
        "res.partner", "Митниця", required=True, tracking=True,
        help="Контрагент у проводках по 3771: з ним розраховуються за митні платежі.")
    currency_id = fields.Many2one(
        "res.currency", "Валюта контракту", required=True,
        default=lambda self: self.env.company.currency_id)
    rate = fields.Float(
        "Курс НБУ", digits=(12, 6), compute="_compute_rate", store=True, readonly=False,
        help="Гривень за одиницю валюти на дату декларації. Береться з курсів системи, "
             "можна виправити за декларацією.")
    picking_ids = fields.Many2many(
        "stock.picking", string="Надходження",
        domain="[('picking_type_code', '=', 'incoming'), ('state', '=', 'done'), "
               "('company_id', '=', company_id)]",
        help="Отримані надходження з товарами цієї декларації: на них розносяться мито і збори.")
    line_ids = fields.One2many(
        "ua.customs.declaration.line", "declaration_id", "Товари", copy=True)
    fee_amount = fields.Monetary(
        "Митні збори", currency_field="company_currency_id",
        help="Збори за митне оформлення за декларацією. Входять у собівартість, не в базу ПДВ.")
    state = fields.Selection(
        [("draft", "Чернетка"), ("posted", "Проведено"), ("cancel", "Скасовано")],
        "Стан", default="draft", required=True, tracking=True, copy=False)
    landed_cost_id = fields.Many2one(
        "stock.landed.cost", "Розподіл на собівартість", readonly=True, copy=False)
    vat_move_id = fields.Many2one(
        "account.move", "Проводка митного ПДВ", readonly=True, copy=False)
    rest_move_id = fields.Many2one(
        "account.move", "Мито на списаний товар", readonly=True, copy=False,
        help="Частина мита і зборів на товар, якого на дату проведення вже не було на складі.")
    note = fields.Text("Примітка")

    customs_value_total = fields.Monetary(
        "Митна вартість", currency_field="company_currency_id",
        compute="_compute_totals", store=True)
    duty_total = fields.Monetary(
        "Мито", currency_field="company_currency_id", compute="_compute_totals", store=True)
    excise_total = fields.Monetary(
        "Акциз", currency_field="company_currency_id", compute="_compute_totals", store=True)
    vat_total = fields.Monetary(
        "ПДВ", currency_field="company_currency_id", compute="_compute_totals", store=True)
    landed_total = fields.Monetary(
        "У собівартість", currency_field="company_currency_id", compute="_compute_totals",
        store=True, help="Мито, акциз і митні збори.")
    payable_total = fields.Monetary(
        "До сплати митниці", currency_field="company_currency_id",
        compute="_compute_totals", store=True)

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)", "Декларація з таким номером уже є в цій компанії.")

    @api.depends("currency_id", "date", "company_id")
    def _compute_rate(self):
        for declaration in self:
            company = declaration.company_id or self.env.company
            if not declaration.currency_id or declaration.currency_id == company.currency_id:
                declaration.rate = 1.0
            else:
                declaration.rate = declaration.currency_id._convert(
                    1.0, company.currency_id, company,
                    declaration.date or fields.Date.context_today(declaration), round=False)

    @api.depends("line_ids.customs_value", "line_ids.duty", "line_ids.excise",
                 "line_ids.vat", "fee_amount")
    def _compute_totals(self):
        for declaration in self:
            lines = declaration.line_ids
            declaration.customs_value_total = sum(lines.mapped("customs_value"))
            declaration.duty_total = sum(lines.mapped("duty"))
            declaration.excise_total = sum(lines.mapped("excise"))
            declaration.vat_total = sum(lines.mapped("vat"))
            declaration.landed_total = (declaration.duty_total + declaration.excise_total
                                        + declaration.fee_amount)
            declaration.payable_total = declaration.landed_total + declaration.vat_total

    @api.constrains("fee_amount")
    def _check_fee(self):
        for declaration in self:
            if declaration.fee_amount < 0:
                raise ValidationError(_("Митні збори не можуть бути від'ємними."))

    # ------------------------------------------------------------------ дії
    def _ua_check_draft(self):
        for declaration in self:
            if declaration.state != "draft":
                raise UserError(_("Декларація %(name)s уже проведена або скасована.",
                                  name=declaration.name))

    def action_fill_from_pickings(self):
        """Рядки з отриманих надходжень: кількість, фактурна вартість із замовлення."""
        self._ua_check_draft()
        for declaration in self:
            if not declaration.picking_ids:
                raise UserError(_("Спершу виберіть отримані надходження за цією декларацією."))
            grouped = defaultdict(lambda: {"quantity": 0.0, "invoice_value": 0.0})
            for move in declaration.picking_ids.move_ids.filtered(
                    lambda m: m.state == "done" and m.quantity):
                product = move.product_id
                quantity = move.product_uom._compute_quantity(move.quantity, product.uom_id)
                po_line = move.purchase_line_id
                if po_line:
                    price = po_line.product_uom_id._compute_price(
                        po_line.price_unit, product.uom_id) if po_line.product_uom_id else \
                        po_line.price_unit
                    if po_line.currency_id != declaration.currency_id:
                        price = po_line.currency_id._convert(
                            price, declaration.currency_id, declaration.company_id,
                            declaration.date, round=False)
                else:
                    price = 0.0
                grouped[product]["quantity"] += quantity
                grouped[product]["invoice_value"] += quantity * price
            commands = [(5, 0, 0)]
            for product, values in grouped.items():
                commands.append((0, 0, {
                    "product_id": product.id,
                    "quantity": values["quantity"],
                    "invoice_value": declaration.currency_id.round(values["invoice_value"]),
                }))
            declaration.line_ids = commands
        return True

    def action_compute(self):
        """Перераховує митну вартість, мито, базу і суму ПДВ, розносить збори."""
        self._ua_check_draft()
        for declaration in self:
            declaration.line_ids._ua_compute()
            declaration._ua_spread_fee()
        return True

    def _ua_spread_fee(self):
        """Збори на рядки пропорційно митній вартості; копійка залишку - на останній рядок."""
        self.ensure_one()
        currency = self.company_currency_id
        total = sum(self.line_ids.mapped("customs_value"))
        spread = 0.0
        lines = self.line_ids.sorted("id")
        for index, line in enumerate(lines):
            if index == len(lines) - 1:
                share = currency.round(self.fee_amount - spread)
            else:
                share = currency.round(self.fee_amount * line.customs_value / total) if total else 0.0
            spread += share
            line.fee_share = share

    def action_post(self):
        self._ua_check_draft()
        for declaration in self:
            declaration = declaration.with_company(declaration.company_id)
            if not declaration.line_ids:
                raise UserError(_("У декларації немає товарів."))
            declaration.action_compute()
            if declaration.landed_total and not declaration.picking_ids:
                raise UserError(_("Мито і збори розносяться на отримані надходження: виберіть їх."))
            declaration._ua_check_vat_not_taken()
            account = declaration.company_id._ua_vat_account("customs")
            journal = declaration.company_id._ua_vat_journal()
            if not account or not journal:
                raise UserError(_("Не знайдено рахунок 3771 або журнал інших операцій: "
                                  "перевірте план рахунків компанії."))
            values = {"state": "posted"}
            if declaration.landed_total:
                values["landed_cost_id"] = declaration._ua_post_landed_cost(account, journal).id
            if declaration.vat_total:
                values["vat_move_id"] = declaration._ua_post_vat(account, journal).id
            declaration.write(values)
        return True

    def _ua_check_vat_not_taken(self):
        """ПДВ за цією МД уже взяли в кредит кнопкою на рахунку постачальника - не задвоюємо."""
        self.ensure_one()
        bill = self.env["account.move"].search([
            ("company_id", "=", self.company_id.id),
            ("ua_customs_decl_number", "=", self.name),
            ("ua_customs_move_id", "!=", False),
        ], limit=1)
        if bill and self.vat_total:
            raise UserError(_(
                "ПДВ за МД %(name)s уже взято в кредит з рахунку %(bill)s. Приберіть ПДВ із "
                "декларації (ставка 0 %% з приміткою) або скасуйте ту проводку.",
                name=self.name, bill=bill.display_name))

    def _ua_post_landed_cost(self, account, journal):
        """Нативний landed cost з точним розподілом: кожен товар отримує своє мито і акциз."""
        self.ensure_one()
        product = self.env.ref("l10n_ua_customs.product_customs_costs")
        cost = self.env["stock.landed.cost"].sudo().create({
            "date": self.date,
            "company_id": self.company_id.id,
            "picking_ids": [(6, 0, self.picking_ids.ids)],
            "account_journal_id": journal.id,
            "ua_customs_declaration_id": self.id,
            "description": _("Митна декларація %s", self.name),
            "cost_lines": [(0, 0, {
                "name": _("Мито, акциз і збори за МД %s", self.name),
                "product_id": product.id,
                "price_unit": self.landed_total,
                "split_method": "by_current_cost_price",
                "account_id": account.id,
            })],
        })
        cost.compute_landed_cost()
        currency = self.company_currency_id
        by_product = defaultdict(float)
        for line in self.line_ids:
            by_product[line.product_id] += line.duty + line.excise + line.fee_share
        adjustments = cost.valuation_adjustment_lines
        adjustments.write({"additional_landed_cost": 0.0})
        for product_variant, amount in by_product.items():
            if currency.is_zero(amount):
                continue
            targets = adjustments.filtered(lambda a: a.product_id == product_variant)
            if not targets:
                raise UserError(_(
                    "Товару %(product)s немає серед отриманих надходжень декларації, або його "
                    "собівартість не середня чи FIFO: мито нема на що рознести.",
                    product=product_variant.display_name))
            quantity = sum(targets.mapped("quantity"))
            spread = 0.0
            for index, target in enumerate(targets):
                if index == len(targets) - 1:
                    share = currency.round(amount - spread)
                else:
                    share = currency.round(amount * target.quantity / quantity) if quantity else 0.0
                spread += share
                target.additional_landed_cost = share
        # Нативний landed cost проводить лише частку, що лишилась на складі, і лише при
        # безперервній оцінці. Решта (товар уже списаний, або оцінка періодична) - у витрати,
        # щоб 3771 отримав повну суму платежів.
        rest = defaultdict(float)
        for adjustment in adjustments.filtered("additional_landed_cost"):
            posted = 0.0
            move = adjustment.move_id
            if move and move.product_id.valuation == "real_time" and adjustment.quantity:
                posted = adjustment.additional_landed_cost * (move.remaining_qty / adjustment.quantity)
            if not currency.is_zero(adjustment.additional_landed_cost - posted):
                accounts = adjustment.product_id.product_tmpl_id.get_product_accounts()
                rest[accounts.get("expense")] += adjustment.additional_landed_cost - posted
        cost.button_validate()
        if rest:
            self._ua_post_rest(rest, account, journal, cost)
        return cost

    def _ua_post_rest(self, rest, account, journal, cost):
        """Мито на товар, якого вже немає на складі: Дт рахунок витрат товару / Кт 3771."""
        currency = self.company_currency_id
        lines = []
        total = 0.0
        for expense, amount in rest.items():
            amount = currency.round(amount)
            if not expense:
                raise UserError(_("Частина товару декларації вже списана, а в категорії товару "
                                  "не вказано рахунок витрат: мито нема куди віднести."))
            total += amount
            lines.append((0, 0, {"account_id": expense.id, "partner_id": self.customs_partner_id.id,
                                 "name": _("Мито і збори за МД %s на списаний товар", self.name),
                                 "debit": amount if amount > 0 else 0.0,
                                 "credit": -amount if amount < 0 else 0.0}))
        if currency.is_zero(total):
            return
        lines.append((0, 0, {"account_id": account.id, "partner_id": self.customs_partner_id.id,
                             "name": _("Мито і збори за МД %s", self.name),
                             "debit": -total if total < 0 else 0.0,
                             "credit": total if total > 0 else 0.0}))
        entry = self.env["account.move"].sudo().create({
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "ref": _("%(cost)s: частина без складу", cost=cost.name),
            "line_ids": lines,
        })
        entry.action_post()
        self.rest_move_id = entry

    def action_view_landed_cost(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "stock.landed.cost",
                "res_id": self.landed_cost_id.id, "view_mode": "form"}

    def action_view_vat_move(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "account.move",
                "res_id": self.vat_move_id.id, "view_mode": "form"}

    def _ua_post_vat(self, account, journal):
        self.ensure_one()
        vat_account = self.company_id._ua_vat_account("vat")
        if not vat_account:
            raise UserError(_("Не знайдено рахунок 6412 для митного ПДВ."))
        entry = self.env["account.move"].sudo().create({
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "ref": _("Митний ПДВ за МД %s", self.name),
            "ua_customs_entry": True,
            "line_ids": [
                (0, 0, {"account_id": vat_account.id, "partner_id": self.customs_partner_id.id,
                        "name": _("Податковий кредит: ПДВ за МД %s", self.name),
                        "debit": self.vat_total, "credit": 0.0}),
                (0, 0, {"account_id": account.id, "partner_id": self.customs_partner_id.id,
                        "name": _("ПДВ до сплати митниці за МД %s", self.name),
                        "debit": 0.0, "credit": self.vat_total}),
            ],
        })
        entry.action_post()
        return entry

    def action_cancel(self):
        self._ua_check_draft()
        self.write({"state": "cancel"})
        return True

    def action_reset_draft(self):
        for declaration in self:
            if declaration.state != "cancel":
                raise UserError(_("Проведену декларацію не повертають у чернетку: мито вже в "
                                  "собівартості. Для виправлення оформіть коригування."))
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_customs.action_report_ua_customs_declaration").report_action(self)

    def unlink(self):
        if any(declaration.state == "posted" for declaration in self):
            raise UserError(_("Проведену декларацію видалити не можна."))
        return super().unlink()


class UaCustomsDeclarationLine(models.Model):
    _name = "ua.customs.declaration.line"
    _description = "Товар митної декларації"
    _order = "declaration_id, sequence, id"

    declaration_id = fields.Many2one(
        "ua.customs.declaration", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="declaration_id.company_id", store=True)
    company_currency_id = fields.Many2one(related="declaration_id.company_currency_id")
    currency_id = fields.Many2one(related="declaration_id.currency_id")
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", "Товар", required=True)
    uktzed = fields.Char(
        "Код УКТ ЗЕД", compute="_compute_from_product", store=True, readonly=False)
    quantity = fields.Float("Кількість", digits="Product Unit of Measure", default=1.0)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    invoice_value = fields.Monetary(
        "Фактурна вартість", currency_field="currency_id",
        help="Вартість за інвойсом у валюті контракту.")
    customs_value = fields.Monetary(
        "Митна вартість, грн", currency_field="company_currency_id",
        help="Фактурна вартість за курсом; заповнюється перерахунком, можна виправити.")
    duty_rate = fields.Float(
        "Мито, %", digits=(5, 2), compute="_compute_from_product", store=True, readonly=False)
    duty = fields.Monetary("Мито", currency_field="company_currency_id")
    excise = fields.Monetary("Акциз", currency_field="company_currency_id")
    vat_rate = fields.Float(
        "ПДВ, %", digits=(5, 2), compute="_compute_from_product", store=True, readonly=False)
    vat_exempt_basis = fields.Char(
        "Підстава звільнення від ПДВ", compute="_compute_from_product", store=True, readonly=False,
        help="Пункт закону, за яким ввезення звільнене від ПДВ. Обов'язкова при ставці 0 %.")
    vat_base = fields.Monetary("База ПДВ", currency_field="company_currency_id")
    vat = fields.Monetary("ПДВ", currency_field="company_currency_id")
    fee_share = fields.Monetary("Частка зборів", currency_field="company_currency_id")
    landed_cost = fields.Monetary(
        "У собівартість", currency_field="company_currency_id", compute="_compute_landed")

    @api.depends("product_id")
    def _compute_from_product(self):
        for line in self:
            template = line.product_id.product_tmpl_id
            line.uktzed = template.ua_uktzed or line.uktzed
            line.duty_rate = template.ua_customs_duty_rate
            relief = template.ua_vat_relief_effective_id
            line.vat_rate = 0.0 if relief else 20.0
            line.vat_exempt_basis = (relief.basis or relief.display_name) if relief else False

    @api.depends("duty", "excise", "fee_share")
    def _compute_landed(self):
        for line in self:
            line.landed_cost = line.duty + line.excise + line.fee_share

    @api.constrains("duty_rate", "vat_rate", "quantity")
    def _check_rates(self):
        for line in self:
            if line.duty_rate < 0 or line.vat_rate < 0 or line.quantity < 0:
                raise ValidationError(_("Ставки і кількість не можуть бути від'ємними."))

    def _ua_compute(self):
        for line in self:
            currency = line.company_currency_id
            rate = line.declaration_id.rate or 1.0
            if line.invoice_value:
                line.customs_value = currency.round(line.invoice_value * rate)
            line.duty = currency.round(line.customs_value * line.duty_rate / 100.0)
            line.vat_base = line.customs_value + line.duty + line.excise
            line.vat = currency.round(line.vat_base * line.vat_rate / 100.0)
            if not line.vat_rate and line.vat_base and not line.vat_exempt_basis:
                raise UserError(_("Рядок %(product)s: ПДВ 0 %% без підстави звільнення. "
                                  "Вкажіть пункт закону або ставку 20 %%.",
                                  product=line.product_id.display_name))

