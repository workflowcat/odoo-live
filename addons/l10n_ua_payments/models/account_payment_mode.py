# -*- coding: utf-8 -*-
"""Спосіб оплати (account.payment.mode) як місце, де живе формат файлу для банку.

OCA тримає формат вивантаження на способі оплати: `generate_payment_file` дивиться, який
спосіб стоїть на дорученні, і віддає той файл, який цей банк приймає (так зроблено в
`account_banking_pain_base` для SEPA). Нам із того шару потрібен лише сам файл, тому тут
одне поле - `ua_file_format`, і один формат - CSV у windows-1251, який приймають Приват
і Моно.
"""
from odoo import fields, models

FILE_FORMATS = [("csv1251", "CSV для банку (windows-1251)")]


class AccountPaymentMode(models.Model):
    _inherit = "account.payment.mode"

    ua_file_format = fields.Selection(
        FILE_FORMATS, "Формат файлу для банку",
        help="Який файл формує кнопка «Файл для банку» на дорученні з цим способом оплати.")
