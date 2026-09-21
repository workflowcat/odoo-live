"""Доставка як носій видаткової накладної і ТТН.

Доставка знає кількості, але не гроші. Ціну і податок беремо з рядка замовлення,
що стоїть за рухом (його дає sale_stock); якщо замовлення немає, друкуються самі
кількості без сум - це чесніше, ніж підставляти прайс і вигадувати ПДВ.
"""
from odoo import fields, models


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "ua.docs.source"]

    x_ua_proxy_number = fields.Char(
        "Довіреність №",
        help="Номер довіреності, за якою представник одержувача забирає товар.")
    x_ua_proxy_date = fields.Date("Дата довіреності")
    x_ua_proxy_person = fields.Char("Видана на (ПІБ)")

    # ------------------------------------------------------------------
    # Що дає носій
    # ------------------------------------------------------------------
    def _ua_docs_date(self):
        self.ensure_one()
        moment = self.date_done or self.scheduled_date
        return moment.date() if moment else False

    def _ua_docs_basis(self):
        self.ensure_one()
        return self.origin or ""

    def _ua_docs_proxy(self):
        self.ensure_one()
        return {
            "number": self.x_ua_proxy_number or "",
            "date": self.x_ua_proxy_date or False,
            "person": self.x_ua_proxy_person or "",
        }

    def _ua_docs_currency(self):
        self.ensure_one()
        return self.company_id.currency_id

    def _ua_docs_moves(self):
        self.ensure_one()
        return self.move_ids.filtered(lambda move: move.product_id and move.state != "cancel")

    def _ua_docs_sale_line(self, move):
        """Рядок замовлення за рухом, якщо sale_stock у базі є."""
        return getattr(move, "sale_line_id", False) or False

    def _ua_docs_taxes(self):
        self.ensure_one()
        taxes = self.env["account.tax"]
        for move in self._ua_docs_moves():
            line = self._ua_docs_sale_line(move)
            if line:
                taxes |= line.tax_ids
        return taxes

    def _ua_docs_lines(self):
        self.ensure_one()
        rows = []
        for move in self._ua_docs_moves():
            line = self._ua_docs_sale_line(move)
            quantity = move.quantity or move.product_uom_qty
            price = line.price_unit if line else 0.0
            subtotal = price * quantity
            total = subtotal
            if line and line.tax_ids:
                taxed = line.tax_ids.compute_all(
                    price, currency=self._ua_docs_currency(), quantity=quantity,
                    product=move.product_id, partner=self.partner_id)
                subtotal = taxed["total_excluded"]
                total = taxed["total_included"]
            rows.append({
                "index": len(rows) + 1,
                "name": move.product_id.display_name,
                "code": move.product_id.default_code or "",
                "uktzed": getattr(move.product_id, "x_uktzed", "") or "",
                "quantity": quantity,
                "uom": move.product_uom.name or "",
                "weight": move.product_id.weight * quantity,
                "price": price,
                "subtotal": subtotal,
                "total": total,
                "tax": total - subtotal,
            })
        return rows

    def _ua_docs_money(self):
        """Сум у доставці немає - збираємо їх із позицій."""
        self.ensure_one()
        rows = self._ua_docs_lines()
        untaxed = sum(row["subtotal"] for row in rows)
        total = sum(row["total"] for row in rows)
        return {"untaxed": untaxed, "tax": total - untaxed, "total": total}

    def _ua_docs_weight(self):
        self.ensure_one()
        return sum(row["weight"] for row in self._ua_docs_lines())
