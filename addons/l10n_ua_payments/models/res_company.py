# -*- coding: utf-8 -*-
"""Рахунки бюджету для сплати податків і внеску.

Рахунки відкриває Казначейство, вони різні для кожної області і змінюються щороку.
Тому це поле компанії, а не константа в коді. Бухгалтер бере їх з сайта ДПС.
"""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_iban_pdfo = fields.Char("Рахунок бюджету: ПДФО")
    ua_iban_vz = fields.Char("Рахунок бюджету: військовий збір")
    ua_iban_esv = fields.Char("Рахунок бюджету: ЄСВ")
