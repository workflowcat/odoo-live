"""Зв'язок нативного landed cost з митною декларацією і контрагент «митниця» в проводці."""
from odoo import fields, models


class StockLandedCost(models.Model):
    _inherit = "stock.landed.cost"

    ua_customs_declaration_id = fields.Many2one(
        "ua.customs.declaration", "Митна декларація", readonly=True, copy=False,
        index="btree_not_null")


class StockValuationAdjustmentLines(models.Model):
    _inherit = "stock.valuation.adjustment.lines"

    def _prepare_account_move_line_values(self):
        values = super()._prepare_account_move_line_values()
        declaration = self.cost_id.ua_customs_declaration_id
        if declaration.customs_partner_id:
            values["partner_id"] = declaration.customs_partner_id.id
        return values
