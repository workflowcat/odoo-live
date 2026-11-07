"""Код ДК 021 на товарі і на рядку закупівлі."""
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_dk021_id = fields.Many2one(
        "ua.dk021", "Код ДК 021", index="btree_not_null",
        help="Код Єдиного закупівельного словника: потрібен для Prozorro, річного плану "
             "закупівель і звіту про договори.")


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    ua_dk021_id = fields.Many2one(
        "ua.dk021", "Код ДК 021", compute="_compute_ua_dk021", store=True,
        readonly=False, index="btree_not_null")

    @api.depends("product_id")
    def _compute_ua_dk021(self):
        for line in self:
            line.ua_dk021_id = line.product_id.product_tmpl_id.ua_dk021_id or line.ua_dk021_id
