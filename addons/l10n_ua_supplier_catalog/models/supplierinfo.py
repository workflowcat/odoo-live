"""Ціни постачальників: ціна за одиницю обліку, найкращий постачальник, порівняння.

Odoo обирає постачальника за ціною без огляду на одиницю: 120 грн за кілограм болтів
виглядає дорожче за 3,10 грн за штуку. Тут ціна приводиться до одиниці обліку товару
(з урахуванням знижки), і порівнюються вже ці числа. Валюта не перераховується:
порівнюються ціни в одній валюті.
"""
from odoo import api, fields, models


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    ua_price_base = fields.Float("Ціна за одиницю обліку", compute="_compute_ua_price_base",
                                 store=True, digits="Product Price",
                                 help="Ціна зі знижкою, перерахована в одиницю обліку товару.")
    ua_stock = fields.Float("Залишок у постачальника", help="З останнього прайсу.")
    ua_import_id = fields.Many2one("ua.supplier.price.import", "З прайсу", ondelete="set null",
                                   readonly=True)
    ua_component_class_id = fields.Many2one(related="product_tmpl_id.ua_component_class_id",
                                            store=True, string="Вид комплектуючих")

    @api.depends("price", "discount", "product_uom_id", "product_tmpl_id.uom_id")
    def _compute_ua_price_base(self):
        for rec in self:
            price = rec.price * (1.0 - (rec.discount or 0.0) / 100.0)
            base = rec.product_tmpl_id.uom_id
            uom = rec.product_uom_id
            if uom and base and uom != base:
                per = uom._compute_quantity(1.0, base, round=False, raise_if_failure=False)
                price = price / per if per else price
            rec.ua_price_base = price


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_best_price = fields.Float("Найкраща ціна", compute="_compute_ua_best",
                                 digits="Product Price",
                                 help="Найменша чинна ціна постачальника за одиницю обліку.")
    ua_best_partner_id = fields.Many2one("res.partner", "Найдешевший постачальник",
                                         compute="_compute_ua_best")
    ua_supplier_count = fields.Integer("Постачальників", compute="_compute_ua_best")

    def _ua_valid_sellers(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        company = self.env.company
        return self.seller_ids.filtered(
            lambda s: (not s.date_end or s.date_end >= today)
            and (not s.date_start or s.date_start <= today)
            and (not s.company_id or s.company_id == company) and s.ua_price_base > 0)

    @api.depends_context("company")
    def _compute_ua_best(self):
        for tmpl in self:
            sellers = tmpl._ua_valid_sellers()
            best = min(sellers, key=lambda s: (s.ua_price_base, s.delay)) if sellers else None
            tmpl.ua_best_price = best.ua_price_base if best else 0.0
            tmpl.ua_best_partner_id = best.partner_id if best else False
            tmpl.ua_supplier_count = len(sellers.mapped("partner_id"))

    def action_ua_compare_suppliers(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Порівняння постачальників",
            "res_model": "product.supplierinfo",
            "view_mode": "list",
            "views": [(self.env.ref(
                "l10n_ua_supplier_catalog.product_supplierinfo_compare_list").id, "list")],
            "domain": [("product_tmpl_id", "in", self.ids)],
            "context": {"group_by": ["product_tmpl_id"]},
        }

    def action_ua_find_suppliers(self):
        self.ensure_one()
        return self.env["ua.supplier.find"]._ua_open(
            query=self.ua_component_name or self.name,
            dk021=self.ua_dk021_id if "ua_dk021_id" in self._fields else False,
            cls=self.ua_component_class_id)


class UaComponentClass(models.Model):
    _inherit = "ua.component.class"

    def action_ua_suppliers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Постачальники: %s" % self.name,
            "res_model": "product.supplierinfo",
            "view_mode": "list",
            "views": [(self.env.ref(
                "l10n_ua_supplier_catalog.product_supplierinfo_compare_list").id, "list")],
            "domain": [("ua_component_class_id", "child_of", self.id)],
            "context": {"group_by": ["partner_id"]},
        }

    def action_ua_find_suppliers(self):
        self.ensure_one()
        return self.env["ua.supplier.find"]._ua_open(
            query=self.name, dk021=self._ua_inherited("dk021_id"), cls=self)
