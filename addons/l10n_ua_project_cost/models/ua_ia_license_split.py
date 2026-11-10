"""Розподіл амортизації нематеріального активу на продані ліцензії.

Програма - один актив, а продається вона ліцензіями (товарами). Щоб бачити собівартість кожної
ліцензії, амортизацію активу за місяць ділять між ліцензіями за кількістю, проданою в місяці.
Кількість береться з проведених рахунків покупцям мінус повернення: товари-ліцензії перелічено в
картці активу, аналітика - з рядка рахунку. Проведення: Кт рахунок витрат на амортизацію з
профілю активу (з аналітикою активу), Дт рахунок призначення (типово той самий, або 903/901) за
кожним рядком з його аналітикою. Сума частин дорівнює амортизації: копійки - в останній рядок.
"""
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .ua_payroll_allocation import MONTHS, _analytic, _first_day


class AccountAsset(models.Model):
    _inherit = "account.asset"

    ua_license_product_ids = fields.Many2many(
        "product.product", "ua_asset_license_product_rel", "asset_id", "product_id", "Ліцензії",
        help="Товари, якими продається цей актив. За їхньою кількістю в рахунках покупцям "
             "амортизація ділиться в документі «Розподіл амортизації НМА на ліцензії».")


class UaIaLicenseSplit(models.Model):
    _name = "ua.ia.license.split"
    _inherit = ["mail.thread"]
    _description = "Розподіл амортизації НМА на ліцензії"
    _order = "month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    asset_id = fields.Many2one("account.asset", "Актив", required=True, tracking=True,
                               domain="[('profile_id.ua_tax_group', '=like', 'nma_%')]")
    company_id = fields.Many2one(related="asset_id.company_id", store=True)
    currency_id = fields.Many2one(related="asset_id.company_id.currency_id")
    month = fields.Date("Місяць", required=True, tracking=True,
                        default=lambda s: fields.Date.context_today(s).replace(day=1))
    source_account_id = fields.Many2one(related="asset_id.profile_id.account_expense_depreciation_id",
                                        string="Рахунок амортизації")
    target_account_id = fields.Many2one(
        "account.account", "Рахунок призначення", tracking=True,
        help="Куди перенести амортизацію за ліцензіями. Порожньо - той самий рахунок витрат, лише з "
             "аналітикою ліцензій; для собівартості реалізації - 903 або 901.")
    amount = fields.Monetary("Амортизація за місяць", currency_field="currency_id", compute="_compute_amount")
    quantity_total = fields.Float("Усього ліцензій", compute="_compute_totals")
    line_ids = fields.One2many("ua.ia.license.split.line", "split_id", "Ліцензії", copy=True)
    state = fields.Selection([("draft", "Чернетка"), ("posted", "Проведено"), ("cancel", "Скасовано")], "Стан",
                             default="draft", required=True, readonly=True, copy=False, tracking=True)
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)

    _asset_month_uniq = models.Constraint(
        "unique(asset_id, month)", "Розподіл амортизації цього активу за місяць уже є.")

    @api.depends("asset_id.name", "month")
    def _compute_name(self):
        for doc in self:
            when = "%s %s" % (MONTHS[doc.month.month - 1], doc.month.year) if doc.month else ""
            doc.name = "Амортизація на ліцензії: %s, %s" % (doc.asset_id.name or "", when)

    def _period(self):
        self.ensure_one()
        start = self.month
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        return start, fields.Date.subtract(end, days=1)

    def _depreciation_lines(self):
        self.ensure_one()
        start, end = self._period()
        return self.asset_id.depreciation_line_ids.filtered(
            lambda l: l.type == "depreciate" and l.move_check and start <= l.line_date <= end)

    @api.depends("asset_id", "month")
    def _compute_amount(self):
        for doc in self:
            doc.amount = sum(doc._depreciation_lines().mapped("amount")) if doc.asset_id and doc.month else 0.0

    @api.depends("line_ids.quantity")
    def _compute_totals(self):
        for doc in self:
            doc.quantity_total = sum(doc.line_ids.mapped("quantity"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("month"):
                vals["month"] = _first_day(vals["month"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("month"):
            vals["month"] = _first_day(vals["month"])
        return super().write(vals)

    # ---- з продажів ------------------------------------------------------------------
    def action_fill_from_sales(self):
        """Кількість ліцензій з проведених рахунків покупцям за місяць, мінус повернення."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Рядки змінюються лише в чернетці."))
        products = self.asset_id.ua_license_product_ids
        if not products:
            raise UserError(_("У картці активу не вказано товари-ліцензії."))
        start, end = self._period()
        lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
            ("move_id.move_type", "in", ("out_invoice", "out_refund")), ("display_type", "=", "product"),
            ("product_id", "in", products.ids), ("date", ">=", start), ("date", "<=", end)])
        quantities = {}
        for line in lines:
            sign = -1.0 if line.move_id.move_type == "out_refund" else 1.0
            keys = list((line.analytic_distribution or {}).keys())
            analytic = int(keys[0]) if len(keys) == 1 and "," not in keys[0] else False
            key = (line.product_id.id, analytic)
            quantities[key] = quantities.get(key, 0.0) + sign * line.quantity
        rows = [(0, 0, {"product_id": product, "analytic_account_id": analytic, "quantity": qty})
                for (product, analytic), qty in quantities.items() if qty > 0]
        if not rows:
            raise UserError(_("За місяць ліцензій не продано."))
        self.line_ids.unlink()
        self.write({"line_ids": rows})
        return True

    # ---- проведення ------------------------------------------------------------------
    def _parts(self):
        """[(рядок, сума)]: амортизація за кількістю, копійки округлення - в останній рядок."""
        self.ensure_one()
        currency = self.currency_id
        lines = self.line_ids.filtered(lambda l: l.quantity > 0)
        total = sum(lines.mapped("quantity"))
        parts, done = [], 0.0
        for index, line in enumerate(lines):
            if index == len(lines) - 1:
                part = currency.round(self.amount - done)
            else:
                part = currency.round(self.amount * line.quantity / total)
                done += part
            parts.append((line, part))
        return parts

    def action_post(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Провести можна лише чернетку."))
            if doc.currency_id.compare_amounts(doc.amount, 0.0) <= 0:
                raise UserError(_("За %s у активу немає проведеної амортизації.") % doc.name)
            if not doc.line_ids.filtered(lambda l: l.quantity > 0):
                raise UserError(_("Немає жодної ліцензії з кількістю."))
            source = doc.source_account_id
            if not source:
                raise UserError(_("У профілі активу немає рахунку витрат на амортизацію."))
            target = doc.target_account_id or source
            vals = []
            for line, part in doc._parts():
                if doc.currency_id.is_zero(part):
                    continue
                label = "%s · %s" % (doc.asset_id.name, line.product_id.display_name)
                vals.append((0, 0, {"name": label, "account_id": target.id, "debit": part, "credit": 0.0,
                                    "analytic_distribution": _analytic(line.analytic_account_id)}))
            vals.append((0, 0, {"name": doc.name, "account_id": source.id, "debit": 0.0, "credit": doc.amount,
                                "analytic_distribution": doc.asset_id.analytic_distribution or False}))
            move = self.env["account.move"].with_company(doc.company_id).create({
                "journal_id": doc.asset_id.profile_id.journal_id.id, "date": doc._period()[1],
                "move_type": "entry", "ref": doc.name, "line_ids": vals})
            move.action_post()
            doc.write({"state": "posted", "move_id": move.id})
        return True

    def action_cancel(self):
        for doc in self.filtered(lambda d: d.state == "posted" and d.move_id):
            move = doc.move_id
            move._reverse_moves([{"date": move.date, "ref": _("Скасування: %s") % move.ref}], cancel=True)
        self.write({"state": "cancel"})
        return True

    def action_draft(self):
        self.filtered(lambda d: d.state == "cancel").write({"state": "draft", "move_id": False})
        return True


class UaIaLicenseSplitLine(models.Model):
    _name = "ua.ia.license.split.line"
    _description = "Рядок розподілу амортизації на ліцензії"
    _order = "id"

    split_id = fields.Many2one("ua.ia.license.split", "Розподіл", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="split_id.company_id", store=True)
    product_id = fields.Many2one("product.product", "Ліцензія", required=True)
    analytic_account_id = fields.Many2one("account.analytic.account", "Аналітика", check_company=True)
    quantity = fields.Float("Кількість")
    share = fields.Float("Частка, %", compute="_compute_share", digits=(5, 2))
    amount = fields.Monetary("Сума", currency_field="currency_id", compute="_compute_share")
    currency_id = fields.Many2one(related="split_id.currency_id")

    @api.depends("quantity", "split_id.line_ids.quantity", "split_id.amount")
    def _compute_share(self):
        for split in self.split_id:
            parts = dict((line.id, part) for line, part in split._parts()) if split.line_ids else {}
            total = sum(split.line_ids.filtered(lambda l: l.quantity > 0).mapped("quantity"))
            for line in split.line_ids & self:
                line.share = 100.0 * line.quantity / total if total and line.quantity > 0 else 0.0
                line.amount = parts.get(line.id, 0.0)
        for line in self.filtered(lambda l: not l.split_id):
            line.share = line.amount = 0.0

    @api.constrains("quantity")
    def _check_quantity(self):
        if self.filtered(lambda line: line.quantity < 0):
            raise ValidationError(_("Кількість не буває від'ємною."))
