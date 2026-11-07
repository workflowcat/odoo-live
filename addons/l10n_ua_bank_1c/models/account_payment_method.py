"""Спосіб оплати «Клієнт-банк 1С»: доручення з ним дає файл 1CClientBankExchange."""
from odoo import api, models

METHOD_CODE = "ua_1c_exchange"


class AccountPaymentMethod(models.Model):
    _inherit = "account.payment.method"

    @api.model
    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res[METHOD_CODE] = {"mode": "multi", "domain": [("type", "=", "bank")]}
        return res
