"""Зв'язки складу, виробництва і рахунків із замовленням на переробку."""
from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    ua_tolling_partner_id = fields.Many2one(
        "res.partner", "Давалець", index="btree_not_null", readonly=True,
        help="Місце зберігання сировини цього замовника. Вона належить йому і не оцінюється.")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ua_tolling_id = fields.Many2one("ua.tolling.order", "Переробка давальницької сировини",
                                    index="btree_not_null", readonly=True, copy=False)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ua_tolling_id = fields.Many2one("ua.tolling.order", "Переробка давальницької сировини",
                                    index="btree_not_null", readonly=True, copy=False)


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_tolling_id = fields.Many2one("ua.tolling.order", "Переробка давальницької сировини",
                                    index="btree_not_null", readonly=True, copy=False)
