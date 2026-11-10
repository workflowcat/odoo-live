"""Частка додаткових витрат на продану кількість - на собівартість реалізації."""
from odoo import fields, models


class StockLandedCost(models.Model):
    _inherit = "stock.landed.cost"

    ua_sold_to_cogs = fields.Boolean(
        "Продане - на собівартість", default=True,
        help="Частка витрат на товар, якого вже немає на складі, іде на рахунок витрат товару "
             "(собівартість реалізації) тією самою проводкою. Вимкнено - лишається на рахунку послуги.")

    def _ua_sold_handled_elsewhere(self):
        """Митна декларація розносить цю частку сама (l10n_ua_customs)."""
        return "ua_customs_declaration_id" in self._fields and bool(self.ua_customs_declaration_id)


class StockValuationAdjustmentLines(models.Model):
    _inherit = "stock.valuation.adjustment.lines"

    def _create_accounting_entries(self, remaining_qty):
        lines = super()._create_accounting_entries(remaining_qty) or []
        cost = self.cost_id
        if not cost.ua_sold_to_cogs or cost._ua_sold_handled_elsewhere() or not self.quantity:
            return lines
        sold = self.quantity - max(remaining_qty or 0.0, 0.0)
        if self.product_id.uom_id.compare(sold, 0.0) <= 0:
            return lines
        amount = cost.currency_id.round(self.additional_landed_cost * min(sold, self.quantity) / self.quantity)
        if cost.currency_id.is_zero(amount):
            return lines
        cogs = self.product_id.product_tmpl_id.get_product_accounts().get("expense")
        credit = self.cost_line_id.account_id or self.cost_line_id.product_id._get_product_accounts()["expense"]
        if not cogs or not credit or cogs == credit:
            return lines
        base = dict(self._prepare_account_move_line_values(), name=self.env._("%s (продана частка)", self.name))
        debit_line = dict(base, account_id=cogs.id, debit=max(amount, 0.0), credit=max(-amount, 0.0))
        credit_line = dict(base, account_id=credit.id, debit=max(-amount, 0.0), credit=max(amount, 0.0))
        return lines + [[0, 0, debit_line], [0, 0, credit_line]]
