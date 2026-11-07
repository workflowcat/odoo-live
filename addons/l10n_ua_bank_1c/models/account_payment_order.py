"""Доручення на оплату зі способом «Клієнт-банк (файл 1С)» дає файл платіжок 1С."""
from odoo import models

from .account_payment_method import METHOD_CODE


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def generate_payment_file(self):
        self.ensure_one()
        if self.payment_method_id.code != METHOD_CODE:
            return super().generate_payment_file()
        content, _filename = self.payment_ids._ua_bank1c_file()
        return content, "%s.txt" % (self.name or "1c_to_bank").replace("/", "-")
