from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    bp_intake_id = fields.Many2one("bp.purchase.intake", "Вхідний рахунок", readonly=True, copy=False, index="btree_not_null")
    bp_supplier_unverified = fields.Boolean(compute="_compute_bp_supplier_unverified")

    @api.depends("partner_id.commercial_partner_id.bp_supplier_status", "move_type")
    def _compute_bp_supplier_unverified(self):
        for m in self:
            m.bp_supplier_unverified = bool(m.is_purchase_document(include_receipts=True)
                                            and m.partner_id.commercial_partner_id.bp_supplier_status == "unverified")

    def action_post(self):
        blocked = self.filtered("bp_supplier_unverified")
        if blocked:
            names = ", ".join(blocked.mapped("partner_id.commercial_partner_id.name"))
            raise UserError(f"Постачальник не перевірений: {names}. Провести рахунок можна після позначки "
                            "«Перевірено» в картці постачальника.")
        return super().action_post()
