"""Акт невідповідності при поверненні товару від покупця.

Кредит-нота зменшує дохід і борг покупця на те, що в документі. Акт показує, що прийнято
насправді: кількість за документом (кредит-нота, а без неї - прийомка) проти кількості
фактично (прийомка повернення), розбіжність у кількості й сумі за ціною документа без ПДВ,
вид невідповідності і рішення щодо товару. Акт нічого не проводить: за ним бухгалтер
виправляє кредит-ноту або виставляє претензію.
"""
from collections import OrderedDict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

ISSUES = [
    ("none", "Відповідає"),
    ("shortage", "Нестача"),
    ("surplus", "Надлишок"),
    ("damage", "Пошкодження"),
    ("incomplete", "Некомплект"),
    ("wrong", "Пересорт"),
    ("quality", "Якість"),
]
DECISIONS = [
    ("stock", "На склад"),
    ("repair", "У ремонт"),
    ("scrap", "Списати"),
    ("back", "Повернути покупцю"),
]


class UaReturnAct(models.Model):
    _name = "ua.return.act"
    _inherit = ["mail.thread"]
    _description = "Акт невідповідності при поверненні"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="/")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one("res.partner", "Покупець", required=True, tracking=True, check_company=True)
    picking_id = fields.Many2one("stock.picking", "Прийомка повернення", tracking=True, check_company=True,
                                 domain="[('picking_type_code', '=', 'incoming')]")
    refund_id = fields.Many2one("account.move", "Кредит-нота", tracking=True, check_company=True,
                                domain="[('move_type', '=', 'out_refund')]")
    reason = fields.Text("Підстава повернення")
    conclusion = fields.Text("Висновок комісії")
    state = fields.Selection([("draft", "Чернетка"), ("done", "Підписано"), ("cancel", "Скасовано")], "Стан",
                             default="draft", required=True, readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many("ua.return.act.line", "act_id", "Товари", copy=True)
    amount_doc = fields.Monetary("За документом", compute="_compute_amounts", store=True)
    amount_received = fields.Monetary("Прийнято", compute="_compute_amounts", store=True)
    amount_diff = fields.Monetary("Розбіжність", compute="_compute_amounts", store=True,
                                  help="Прийнято мінус за документом, без ПДВ. Мінус - прийняли менше, ніж у документі.")

    @api.depends("line_ids.amount_doc", "line_ids.amount_received")
    def _compute_amounts(self):
        for act in self:
            act.amount_doc = sum(act.line_ids.mapped("amount_doc"))
            act.amount_received = sum(act.line_ids.mapped("amount_received"))
            act.amount_diff = act.amount_received - act.amount_doc

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.return.act") or "/"
        return super().create(vals_list)

    @api.onchange("refund_id", "picking_id")
    def _onchange_source(self):
        self.partner_id = self.partner_id or self.refund_id.partner_id.commercial_partner_id \
            or self.picking_id.partner_id.commercial_partner_id

    # ------------------------------------------------------------------
    # Заповнення
    # ------------------------------------------------------------------
    def _ua_refund_rows(self):
        """{товар: [кількість в одиниці товару, сума без ПДВ у валюті компанії]} з кредит-ноти."""
        rows = OrderedDict()
        for line in self.refund_id.invoice_line_ids.filtered(lambda l: l.display_type == "product" and l.product_id):
            product = line.product_id
            qty = line.product_uom_id._compute_quantity(line.quantity, product.uom_id) if line.product_uom_id \
                else line.quantity
            row = rows.setdefault(product, [0.0, 0.0])
            row[0] += qty
            row[1] += abs(line.balance)
        return rows

    def _ua_picking_rows(self):
        """{товар: [за документом, фактично, серійні номери]} з прийомки, в одиниці товару."""
        rows = OrderedDict()
        for move in self.picking_id.move_ids.filtered(lambda m: m.state != "cancel"):
            product = move.product_id
            row = rows.setdefault(product, [0.0, 0.0, []])
            row[0] += move.product_uom._compute_quantity(move.product_uom_qty, product.uom_id)
            row[1] += move.product_uom._compute_quantity(move.quantity, product.uom_id)
            row[2] += [name for name in move.move_line_ids.lot_id.mapped("name") if name not in row[2]]
        return rows

    def action_fill(self):
        """Рядки з кредит-ноти і прийомки; рядки, вписані рукою, лишаються.

        У рядках з документів кількість і ціна беруться заново, а вид невідповідності (крім нестачі
        й надлишку, їх видно з кількості), опис і рішення, поставлені рукою, переходять у нові рядки.
        """
        for act in self:
            if act.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            if not act.refund_id and not act.picking_id:
                raise UserError(_("Вкажіть кредит-ноту або прийомку повернення."))
            refund = act._ua_refund_rows()
            picking = act._ua_picking_rows()
            old_auto = act.line_ids.filtered("auto")
            kept = {line.product_id: (line.issue, line.description, line.decision) for line in old_auto}
            old_auto.unlink()
            values = []
            for product in list(refund) + [p for p in picking if p not in refund]:
                ref_qty, ref_amount = refund.get(product, (0.0, 0.0))
                doc_qty, got_qty, lots = picking.get(product, (0.0, 0.0, []))
                qty_doc = ref_qty if act.refund_id else doc_qty
                qty_received = got_qty if act.picking_id else qty_doc
                price = ref_amount / ref_qty if ref_qty else 0.0
                issue = "shortage" if qty_received < qty_doc else "surplus" if qty_received > qty_doc else "none"
                old_issue, description, decision = kept.get(product, (None, False, False))
                if old_issue not in (None, "none", "shortage", "surplus"):
                    issue = old_issue
                values.append({
                    "act_id": act.id, "auto": True, "product_id": product.id, "qty_doc": qty_doc,
                    "qty_received": qty_received, "price_unit": act.currency_id.round(price),
                    "lot_names": ", ".join(lots), "issue": issue, "description": description,
                    "decision": decision,
                })
            self.env["ua.return.act.line"].create(values)
            if not act.line_ids:
                raise UserError(_("У кредит-ноті і прийомці немає товарів."))
        return True

    # ------------------------------------------------------------------
    # Стани і друк
    # ------------------------------------------------------------------
    def action_done(self):
        for act in self:
            if act.state != "draft":
                raise UserError(_("Підписати можна лише чернетку."))
            if not act.line_ids:
                raise UserError(_("Немає рядків. Натисніть «Заповнити»."))
            if all(line.issue == "none" for line in act.line_ids):
                raise UserError(_("Невідповідностей немає: усі рядки «Відповідає». Акт не потрібен."))
        self.write({"state": "done"})
        for act in self:
            for source in (act.refund_id, act.picking_id):
                if not source:
                    continue
                source.message_post(body=_("Акт невідповідності %(act)s: розбіжність %(amount)s.",
                                           act=act.name, amount=act.amount_diff))
        return True

    def action_cancel(self):
        self.filtered(lambda a: a.state != "cancel").write({"state": "cancel"})
        return True

    def action_draft(self):
        self.filtered(lambda a: a.state == "cancel").write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_return_act.action_report_ua_return_act").report_action(self)

    @api.model
    def _ua_open_for(self, source):
        """Акт для кредит-ноти або прийомки: наявний чи новий, заповнений."""
        field = "refund_id" if source._name == "account.move" else "picking_id"
        act = self.search([(field, "=", source.id), ("state", "!=", "cancel")], limit=1)
        if not act:
            act = self.create({field: source.id, "company_id": source.company_id.id,
                               "partner_id": source.partner_id.commercial_partner_id.id})
            act.action_fill()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": act.id,
                "view_mode": "form", "target": "current"}


class UaReturnActLine(models.Model):
    _name = "ua.return.act.line"
    _description = "Рядок акта невідповідності"
    _order = "act_id, sequence, id"

    act_id = fields.Many2one("ua.return.act", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    auto = fields.Boolean("З документів", readonly=True,
                          help="Рядок з кредит-ноти або прийомки: «Заповнити» перебудовує його.")
    company_id = fields.Many2one(related="act_id.company_id", store=True)
    currency_id = fields.Many2one(related="act_id.currency_id")
    product_id = fields.Many2one("product.product", "Товар", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    qty_doc = fields.Float("За документом", digits="Product Unit")
    qty_received = fields.Float("Фактично", digits="Product Unit")
    qty_diff = fields.Float("Розбіжність", digits="Product Unit", compute="_compute_diff", store=True)
    price_unit = fields.Monetary("Ціна без ПДВ", help="З кредит-ноти: сума рядка без ПДВ / кількість.")
    amount_doc = fields.Monetary("Сума за документом", compute="_compute_diff", store=True)
    amount_received = fields.Monetary("Сума фактично", compute="_compute_diff", store=True)
    amount_diff = fields.Monetary("Сума розбіжності", compute="_compute_diff", store=True)
    issue = fields.Selection(ISSUES, "Невідповідність", required=True, default="none")
    lot_names = fields.Char("Серійні номери")
    description = fields.Char("Опис")
    decision = fields.Selection(DECISIONS, "Рішення")

    @api.depends("qty_doc", "qty_received", "price_unit")
    def _compute_diff(self):
        for line in self:
            currency = line.currency_id or self.env.company.currency_id
            line.qty_diff = line.qty_received - line.qty_doc
            line.amount_doc = currency.round(line.qty_doc * line.price_unit)
            line.amount_received = currency.round(line.qty_received * line.price_unit)
            line.amount_diff = line.amount_received - line.amount_doc

    def issue_label(self):
        """Назва невідповідності для друку."""
        self.ensure_one()
        return dict(ISSUES).get(self.issue, "")

    def decision_label(self):
        """Назва рішення для друку."""
        self.ensure_one()
        return dict(DECISIONS).get(self.decision, "")

    def write(self, vals):
        if any(line.act_id.state != "draft" for line in self):
            raise UserError(_("Рядки змінюють лише в чернетці акта."))
        return super().write(vals)


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_return_act_ids = fields.One2many("ua.return.act", "refund_id", "Акти невідповідності")
    ua_return_act_count = fields.Integer(compute="_compute_ua_return_act_count")

    @api.depends("ua_return_act_ids")
    def _compute_ua_return_act_count(self):
        for move in self:
            move.ua_return_act_count = len(move.ua_return_act_ids)

    def action_ua_return_act(self):
        self.ensure_one()
        if self.move_type != "out_refund":
            raise UserError(_("Акт невідповідності складають до кредит-ноти покупцю."))
        return self.env["ua.return.act"]._ua_open_for(self)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ua_return_act_ids = fields.One2many("ua.return.act", "picking_id", "Акти невідповідності")
    ua_return_act_count = fields.Integer(compute="_compute_ua_return_act_count")

    @api.depends("ua_return_act_ids")
    def _compute_ua_return_act_count(self):
        for picking in self:
            picking.ua_return_act_count = len(picking.ua_return_act_ids)

    def action_ua_return_act(self):
        self.ensure_one()
        if self.picking_type_code != "incoming" or not self.partner_id:
            raise UserError(_("Акт невідповідності складають до прийомки повернення від покупця."))
        return self.env["ua.return.act"]._ua_open_for(self)
