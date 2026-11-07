"""Договір на оплаті.

Оплата з рахунку бере договір рахунку; оплата, введена вручну, - основний договір
контрагента. Договір переходить у проводку оплати, тож аванс і погашення видно за
договором.
"""
from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Договір", compute="_compute_ua_contract_id", store=True,
        readonly=False, check_company=True,
        domain="[('partner_id', '=', ua_commercial_partner_id), ('state', '!=', 'closed')]")
    ua_commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id")

    @api.depends("partner_id", "partner_type", "company_id")
    def _compute_ua_contract_id(self):
        Contract = self.env["ua.contract"]
        for payment in self:
            partner = payment.partner_id.commercial_partner_id
            if payment.ua_contract_id and partner and payment.ua_contract_id._ua_fits(partner):
                continue
            kind = {"customer": "sale", "supplier": "purchase"}.get(payment.partner_type)
            payment.ua_contract_id = Contract._ua_default_for(partner, payment.company_id, kind) if kind else False

    def _generate_move_vals(self, write_off_line_vals=None, force_balance=None, line_ids=None):
        vals = super()._generate_move_vals(write_off_line_vals, force_balance, line_ids)
        vals["ua_contract_id"] = self.ua_contract_id.id
        return vals

    def write(self, vals):
        result = super().write(vals)
        if "ua_contract_id" in vals:
            for payment in self.filtered("move_id"):
                if payment.move_id.ua_contract_id != payment.ua_contract_id:
                    payment.move_id.ua_contract_id = payment.ua_contract_id
        return result


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Договір", compute="_compute_ua_contract_id", store=True, readonly=False,
        help="Порожньо, якщо рахунки з різних договорів: тоді кожна оплата бере договір свого рахунку.")

    @api.depends("line_ids")
    def _compute_ua_contract_id(self):
        for wizard in self:
            contracts = wizard.line_ids.move_id.ua_contract_id
            wizard.ua_contract_id = contracts if len(contracts) == 1 else False

    def _ua_contract_for(self, lines):
        contracts = lines.move_id.ua_contract_id
        if len(contracts) == 1:
            return contracts
        return self.ua_contract_id

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals["ua_contract_id"] = (self.ua_contract_id or self._ua_contract_for(batch_result["lines"])).id
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        vals = super()._create_payment_vals_from_batch(batch_result)
        vals["ua_contract_id"] = self._ua_contract_for(batch_result["lines"]).id
        return vals
