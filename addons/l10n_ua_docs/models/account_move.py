"""Українська первинка з нативного рахунку.

Номер документа - нативний номер рахунку, суми і ПДВ - нативні `amount_*`,
позиції - нативні рядки. Свого номера, свого реєстру і своєї копії сум тут
немає: рахунок і є документ, ми лише кладемо його на український бланк.
"""
from odoo import _, models
from odoo.exceptions import UserError

# Типи, з яких друкується українська первинка продавця.
UA_DOC_TYPES = ("out_invoice", "out_refund")


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "ua.docs.source"]

    def _ua_docs_date(self):
        self.ensure_one()
        return self.invoice_date or self.date

    def _ua_docs_basis(self):
        """Підстава: договір із поля «Посилання», інакше джерело документа."""
        self.ensure_one()
        return self.ref or self.invoice_origin or ""

    def _ua_docs_due(self):
        self.ensure_one()
        return self.invoice_date_due

    def _ua_docs_bank(self):
        """Рахунок для оплати з самого документа, інакше перший рахунок компанії."""
        self.ensure_one()
        return self.partner_bank_id or super()._ua_docs_bank()

    def _ua_docs_product_lines(self):
        self.ensure_one()
        return self.invoice_line_ids.filtered(lambda line: line.display_type == "product")

    def _ua_docs_taxes(self):
        self.ensure_one()
        return self._ua_docs_product_lines().tax_ids

    def _ua_docs_lines(self):
        """Позиції документа з наскрізною нумерацією."""
        self.ensure_one()
        rows = []
        for line in self._ua_docs_product_lines():
            product = line.product_id
            rows.append({
                "index": len(rows) + 1,
                "name": line.name or (product.display_name if product else ""),
                "code": (product.default_code or "") if product else "",
                "uktzed": (getattr(product, "ua_uktzed", "") or "") if product else "",
                "quantity": line.quantity,
                "uom": line.product_uom_id.name or "",
                "price": line.price_unit,
                "subtotal": line.price_subtotal,
                "total": line.price_total,
                "tax": line.price_total - line.price_subtotal,
            })
        return rows

    def _ua_docs_has_goods(self):
        """Чи є в рахунку товар - видаткову накладну складають лише на товар."""
        self.ensure_one()
        return any(
            line.product_id and line.product_id.type == "consu"
            for line in self._ua_docs_product_lines()
        )

    def _ua_docs_check(self):
        """Первинку продавця друкують лише з рахунку клієнта."""
        for move in self:
            if move.move_type not in UA_DOC_TYPES:
                raise UserError(_(
                    "Українську первинку друкують з рахунку клієнта. "
                    "Документ «%s» має інший тип.", move.display_name))
        return True
