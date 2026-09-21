"""Замовлення на продаж як носій рахунку на оплату.

Замовлення підмішує `ua.docs.source` і дає чотири речі: позиції, податки, дату
і підставу. Суми, сторони, ПДВ і пропис рахує домішок, бланк - той самий, що в
рахунку клієнта.
"""
from odoo import fields, models


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "ua.docs.source"]

    x_ua_contract_number = fields.Char(
        "Договір №",
        help="Номер договору, за яким виставляється рахунок. Друкується в підставі.")
    x_ua_contract_date = fields.Date("Дата договору")

    def _ua_docs_date(self):
        self.ensure_one()
        return self.date_order.date() if self.date_order else False

    def _ua_docs_due(self):
        self.ensure_one()
        return self.validity_date

    def _ua_docs_basis(self):
        """Підстава: власний договір, інакше посилання клієнта."""
        self.ensure_one()
        if self.x_ua_contract_number:
            text = "Договір № %s" % self.x_ua_contract_number
            if self.x_ua_contract_date:
                text += " від %s" % self.x_ua_contract_date.strftime("%d.%m.%Y")
            return text
        return self.client_order_ref or ""

    def _ua_docs_product_lines(self):
        self.ensure_one()
        return self.order_line.filtered(lambda line: not line.display_type)

    def _ua_docs_taxes(self):
        self.ensure_one()
        return self._ua_docs_product_lines().tax_ids

    def _ua_docs_lines(self):
        self.ensure_one()
        rows = []
        for line in self._ua_docs_product_lines():
            product = line.product_id
            rows.append({
                "index": len(rows) + 1,
                "name": line.name or (product.display_name if product else ""),
                "code": (product.default_code or "") if product else "",
                "uktzed": (getattr(product, "x_uktzed", "") or "") if product else "",
                "quantity": line.product_uom_qty,
                "uom": line.product_uom_id.name or "",
                "price": line.price_unit,
                "subtotal": line.price_subtotal,
                "total": line.price_total,
                "tax": line.price_total - line.price_subtotal,
            })
        return rows
