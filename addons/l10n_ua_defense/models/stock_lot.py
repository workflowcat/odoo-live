"""Паспорт виробу на серійному номері.

Серійний номер готового виробу знає замовлення на виробництво, що його випустило, а
через нього - серійні номери складових (камери, контролера, радіомодуля) і контракт.
Затверджений акт приймання ставить себе на номер. Паспорт друкує все це одним аркушем.
"""
from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    ua_passport_number = fields.Char("Номер паспорта")
    ua_contract_id = fields.Many2one(
        "ua.contract", "Контракт", index="btree_not_null",
        help="Ставиться актом приймання або береться із замовлення на виробництво.")
    ua_acceptance_id = fields.Many2one("ua.defense.acceptance", "Акт приймання", readonly=True, copy=False)
    ua_production_id = fields.Many2one(
        "mrp.production", "Замовлення на виробництво", compute="_compute_ua_production")
    ua_component_lot_ids = fields.Many2many(
        "stock.lot", string="Серійні номери складових", compute="_compute_ua_production")

    @api.depends("name")
    def _compute_ua_production(self):
        Production = self.env["mrp.production"]
        for lot in self:
            production = Production.search(
                [("lot_producing_ids", "in", lot.ids), ("state", "=", "done")], limit=1) \
                if isinstance(lot.id, int) else Production
            lot.ua_production_id = production
            lot.ua_component_lot_ids = production.move_raw_ids.move_line_ids.lot_id

    def _ua_contract(self):
        self.ensure_one()
        return self.ua_contract_id or self.ua_production_id.ua_contract_id

    def action_print_passport(self):
        return self.env.ref("l10n_ua_defense.action_report_ua_product_passport").report_action(self)
