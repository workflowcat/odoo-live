"""Чарівник OCA «запит -> замовлення»: доносимо запит, підрозділ, рахунок і ціну.

Сам чарівник не змінюємо - лише доповнюємо значення нового замовлення.
"""
from odoo import api, models


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

    @api.model
    def _prepare_purchase_order_line(self, po, item):
        """Ціна рядка: чарівник OCA ставить нуль і на цьому зупиняється.

        В OCA рядок народжується з `price_unit = 0.0` у розрахунку на каталог
        постачальника (`product.supplierinfo`). Каталог веде не кожне
        підприємство, а нативне обчислення ціни після цього вже не спрацьовує:
        воно чіпляється за зміну кількості, а чарівник записує ту саму
        кількість, тобто не змінює нічого. Замовлення і рахунок виходять
        нульові.

        Тому: каталог у цього постачальника є - прибираємо нуль і даємо
        порахувати Odoo; каталогу немає - беремо останню ціну, за якою цей
        товар уже купували в цього постачальника (підтверджене замовлення,
        далі проведений рахунок); немає й історії - знову прибираємо нуль, і
        Odoo візьме облікову ціну товару, як робить у звичайному замовленні.
        OCA не чіпаємо.
        """
        vals = super()._prepare_purchase_order_line(po, item)
        if vals.get("price_unit"):
            return vals
        product = item.product_id
        partner = po.partner_id
        if self.env["purchase.order.line"]._ua_has_supplierinfo(product, partner):
            vals.pop("price_unit", None)
            return vals
        price = self.env["purchase.order.line"]._ua_price_from_history(
            product, partner, po.company_id, po.currency_id)
        if price:
            vals["price_unit"] = price
        else:
            vals.pop("price_unit", None)
        return vals
