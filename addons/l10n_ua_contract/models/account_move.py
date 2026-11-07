"""Договір на рахунку і на рядках проводки.

Рахунок бере основний (або єдиний чинний) договір контрагента сам; бухгалтер може
обрати інший. Рядок проводки бере договір документа, але в ручній операції договір
ставиться на кожен рядок окремо: так переносять аванс з одного договору на інший.
"""
from odoo import api, fields, models

from .tools import contract_kind_of_move


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Договір", compute="_compute_ua_contract_id", store=True,
        readonly=False, index="btree_not_null", check_company=True, tracking=True,
        domain="[('partner_id', '=', commercial_partner_id), ('state', '!=', 'closed')]",
        help="Розрахунки за цим документом ідуть у розрізі договору.")

    @api.depends("partner_id", "move_type", "company_id")
    def _compute_ua_contract_id(self):
        Contract = self.env["ua.contract"]
        for move in self:
            partner = move.partner_id.commercial_partner_id
            if move.ua_contract_id and partner and move.ua_contract_id._ua_fits(partner):
                continue
            kind = contract_kind_of_move(move.move_type)
            move.ua_contract_id = Contract._ua_default_for(partner, move.company_id, kind) if kind else False

    def _ua_docs_basis(self):
        """Підстава в первинці: договір, якщо він є на документі."""
        self.ensure_one()
        if self.ua_contract_id:
            return self.ua_contract_id._ua_print_name()
        return super()._ua_docs_basis()

    def _post(self, soft=True):
        invoices = self.filtered(lambda m: m.is_invoice(include_receipts=True) and m.ua_contract_id)
        for contract in invoices.ua_contract_id:
            moves = invoices.filtered(lambda m, c=contract: m.ua_contract_id == c)
            contract._ua_check_posting(moves)
            distribution = contract._ua_analytic_distribution()
            if distribution:
                moves.invoice_line_ids.filtered(
                    lambda line: line.display_type == "product" and not line.analytic_distribution
                ).analytic_distribution = distribution
        return super()._post(soft)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Договір", compute="_compute_ua_contract_id", store=True,
        readonly=False, index="btree_not_null",
        help="Договір, за яким ведуться розрахунки цього рядка.")

    @api.depends("move_id.ua_contract_id")
    def _compute_ua_contract_id(self):
        for line in self:
            line.ua_contract_id = line.move_id.ua_contract_id
