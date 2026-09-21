"""МФО банку - не окреме поле, а шість цифр з IBAN.

Український IBAN складається з «UA», двох контрольних цифр, шестизначного коду
банку (це і є МФО) і дев'ятнадцяти цифр рахунку. Заводити МФО руками означало б
тримати два джерела однієї правди, тому поле обчислюване і не зберігається.
"""
from odoo import api, fields, models

from .tools import mfo_from_iban


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"

    x_ua_mfo = fields.Char(
        "МФО", compute="_compute_x_ua_mfo",
        help="Код банку з IBAN (позиції 5-10). Порожнє, якщо номер не є українським IBAN.")

    @api.depends("acc_number")
    def _compute_x_ua_mfo(self):
        for bank in self:
            bank.x_ua_mfo = mfo_from_iban(bank.acc_number)
