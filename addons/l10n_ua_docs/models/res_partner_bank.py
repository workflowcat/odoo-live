"""МФО банку - не окреме поле, а шість цифр з IBAN.

Український IBAN складається з «UA», двох контрольних цифр, шестизначного коду
банку (це і є МФО) і дев'ятнадцяти цифр рахунку. Заводити МФО руками означало б
тримати два джерела однієї правди, тому поле обчислюване і не зберігається.

Коли номер не є українським IBAN (закордонний рахунок, чернетка), беремо МФО з довідника
банків - `res.bank.ua_mfo`, означений у res_bank.py. Це те саме поле і той самий зміст,
іншого джерела МФО в модулі немає.
"""
from odoo import api, fields, models

from .res_bank import MFO_HELP, MFO_LABEL
from .tools import mfo_from_iban


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"

    ua_mfo = fields.Char(
        MFO_LABEL, compute="_compute_x_ua_mfo",
        help="Код банку з IBAN (позиції 5-10); якщо номер не є українським IBAN - "
             "МФО з довідника банків. " + MFO_HELP)

    @api.depends("acc_number", "bank_id.ua_mfo")
    def _compute_x_ua_mfo(self):
        for bank in self:
            bank.ua_mfo = mfo_from_iban(bank.acc_number) or bank.bank_id.ua_mfo or ""
