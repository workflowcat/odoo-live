"""Договір на замовленнях на продаж і на купівлю.

Замовлення бере основний договір контрагента, передає його в рахунок і, якщо за
договором окремий облік, ставить аналітику договору на рядки без аналітики при
підтвердженні.
"""
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Договір", compute="_compute_ua_contract_id", store=True,
        readonly=False, check_company=True, index="btree_not_null",
        domain="[('partner_id', '=', ua_commercial_partner_id), ('kind', '=', 'sale'), ('state', '!=', 'closed')]")
    ua_commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id")

    @api.depends("partner_id", "company_id")
    def _compute_ua_contract_id(self):
        Contract = self.env["ua.contract"]
        for order in self:
            partner = order.partner_id.commercial_partner_id
            if order.ua_contract_id and partner and order.ua_contract_id._ua_fits(partner):
                continue
            order.ua_contract_id = Contract._ua_default_for(partner, order.company_id, "sale")

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals["ua_contract_id"] = self.ua_contract_id.id
        return vals

    def _ua_docs_basis(self):
        self.ensure_one()
        if self.ua_contract_id:
            return self.ua_contract_id._ua_print_name()
        return super()._ua_docs_basis()

    def action_confirm(self):
        for order in self.filtered("ua_contract_id"):
            distribution = order.ua_contract_id._ua_analytic_distribution()
            if distribution:
                order.order_line.filtered(
                    lambda line: not line.display_type and not line.analytic_distribution
                ).analytic_distribution = distribution
        return super().action_confirm()


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Договір", compute="_compute_ua_contract_id", store=True,
        readonly=False, check_company=True, index="btree_not_null",
        domain="[('partner_id', '=', ua_commercial_partner_id), ('kind', '=', 'purchase'), ('state', '!=', 'closed')]")
    ua_commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id")
    ua_sale_contract_id = fields.Many2one(
        "ua.contract", "Для договору з покупцем", check_company=True, index="btree_not_null",
        domain="[('kind', '=', 'sale'), ('separate_accounting', '=', True)]",
        help="Закупівля для виконання договору з покупцем з окремим обліком: рядки отримають "
             "аналітику того договору, і витрати ляжуть на нього.")

    @api.depends("partner_id", "company_id")
    def _compute_ua_contract_id(self):
        Contract = self.env["ua.contract"]
        for order in self:
            partner = order.partner_id.commercial_partner_id
            if order.ua_contract_id and partner and order.ua_contract_id._ua_fits(partner):
                continue
            order.ua_contract_id = Contract._ua_default_for(partner, order.company_id, "purchase")

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals["ua_contract_id"] = self.ua_contract_id.id
        return vals

    def button_confirm(self):
        for order in self:
            source = order.ua_sale_contract_id or order.ua_contract_id
            distribution = source._ua_analytic_distribution() if source else False
            if distribution:
                order.order_line.filtered(
                    lambda line: not line.display_type and not line.analytic_distribution
                ).analytic_distribution = distribution
        return super().button_confirm()
