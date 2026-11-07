"""Акт приймання продукції представником замовника.

Акт фіксує, які вироби (і які серійні номери) замовник прийняв або повернув на
доопрацювання. Затверджений акт закриває графік поставки контракту і ставить себе на
серійні номери: паспорт виробу друкує номер і дату акта.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UaDefenseAcceptance(models.Model):
    _name = "ua.defense.acceptance"
    _description = "Акт приймання продукції за оборонним контрактом"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    contract_id = fields.Many2one(
        "ua.contract", "Контракт", required=True, index=True, check_company=True,
        domain="[('ua_defense', '=', True)]")
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    partner_id = fields.Many2one(related="contract_id.partner_id", string="Замовник")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    representative = fields.Char(
        "Представник замовника", help="Посада, звання (за потреби) і прізвище того, хто приймав.")
    picking_id = fields.Many2one(
        "stock.picking", "Відвантаження", check_company=True,
        help="Накладна, якою вироби передано замовнику.")
    state = fields.Selection(
        [("draft", "Чернетка"), ("done", "Затверджено"), ("cancel", "Скасовано")],
        "Стан", default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.defense.acceptance.line", "acceptance_id", "Вироби", copy=True)
    note = fields.Text("Зауваження")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "l10n_ua_defense.acceptance", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    def action_fill_from_picking(self):
        """Рядки з відвантаження: виріб, кількість і серійні номери."""
        for act in self:
            if not act.picking_id:
                raise UserError(_("Оберіть відвантаження."))
            rows = []
            for move in act.picking_id.move_ids.filtered(lambda m: m.state != "cancel"):
                lots = move.move_line_ids.lot_id
                rows.append((0, 0, {
                    "product_id": move.product_id.id,
                    "quantity": move.quantity or move.product_uom_qty,
                    "lot_ids": [(6, 0, lots.ids)],
                }))
            act.line_ids = [(5, 0, 0)] + rows
        return True

    def action_done(self):
        for act in self:
            if not act.line_ids:
                raise UserError(_("В акті немає жодного виробу."))
            for line in act.line_ids:
                if line.lot_ids and line.product_id.tracking == "serial" and len(line.lot_ids) != line.quantity:
                    raise UserError(_(
                        "%(product)s: серійних номерів %(lots)s, а кількість %(qty)s.",
                        product=line.product_id.display_name, lots=len(line.lot_ids), qty=line.quantity))
            act.line_ids.filtered(lambda line: line.result == "accepted").lot_ids.write({
                "ua_acceptance_id": act.id,
                "ua_contract_id": act.contract_id.id,
            })
        self.write({"state": "done"})

    def action_cancel(self):
        for act in self:
            act.line_ids.lot_ids.filtered(lambda lot: lot.ua_acceptance_id == act).write(
                {"ua_acceptance_id": False})
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.action_cancel()
        self.write({"state": "draft"})

    def action_print(self):
        return self.env.ref("l10n_ua_defense.action_report_ua_defense_acceptance").report_action(self)


class UaDefenseAcceptanceLine(models.Model):
    _name = "ua.defense.acceptance.line"
    _description = "Рядок акта приймання"
    _order = "acceptance_id, id"

    acceptance_id = fields.Many2one(
        "ua.defense.acceptance", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", "Виріб", required=True)
    quantity = fields.Float("Пред'явлено", required=True, default=1.0, digits="Product Unit of Measure")
    result = fields.Selection(
        [("accepted", "Прийнято"), ("rework", "На доопрацювання")], "Результат",
        required=True, default="accepted")
    qty_accepted = fields.Float(
        "Прийнято", compute="_compute_qty_accepted", store=True, digits="Product Unit of Measure")
    lot_ids = fields.Many2many(
        "stock.lot", string="Серійні номери",
        domain="[('product_id', '=', product_id)]")
    note = fields.Char("Зауваження")

    @api.depends("quantity", "result")
    def _compute_qty_accepted(self):
        for line in self:
            line.qty_accepted = line.quantity if line.result == "accepted" else 0.0
