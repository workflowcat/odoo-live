"""Чарівник OCA «запит -> замовлення»: доносимо запит, підрозділ і рахунок витрат.

Сам чарівник не змінюємо - лише доповнюємо значення нового замовлення.
"""
from odoo import models


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    def _prepare_purchase_order(self, picking_type, company, origin):
        vals = super()._prepare_purchase_order(picking_type, company, origin)
        requests = self.item_ids.line_id.request_id
        if len(requests) == 1:
            vals["ua_request_id"] = requests.id
            vals["ua_department_id"] = requests.ua_department_id.id
            vals["ua_expense_account_id"] = requests.ua_expense_account_id.id
        return vals
