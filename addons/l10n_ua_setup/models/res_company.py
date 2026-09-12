# -*- coding: utf-8 -*-
"""Рішення компанії, які приходять з анкети.

Це не довідкові поля: кожне з них щось вмикає або вимикає далі. Тому анкета пише їх
сюди тільки з підтверджених відповідей, а не з пропозицій.
"""
from odoo import fields, models

TAX_SYSTEMS = [
    ("ep3_5", "ЄП 3 група, 5 % (без ПДВ)"),
    ("ep3_3", "ЄП 3 група, 3 % + ПДВ"),
    ("general", "Загальна система, 18 % на прибуток"),
    ("undecided", "Ще не обрано"),
]


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_tax_system = fields.Selection(TAX_SYSTEMS, "Система оподаткування")
    ua_vat_payer = fields.Boolean("Платник ПДВ")
    ua_settlement_currency = fields.Char("Валюта розрахунків з клієнтами")
    ua_engagement_forms = fields.Char("Форми залучення людей")
    ua_has_disabled = fields.Boolean("Є працівники з інвалідністю (ЄСВ 8,41 %)")
    ua_below_min_wage = fields.Boolean("Є оклади нижче мінімальної зарплати")
    ua_index_default_off = fields.Boolean("Індексацію не ведемо",
                                          help="Типове значення для нових працівників.")
    ua_payroll_bank_mode = fields.Selection([("one", "Один банк для всіх"),
                                             ("many", "Кілька банків")],
                                            "Зарплатний проєкт")
    ua_booking_planned = fields.Boolean("Бронюємо або плануємо бронювати")
    ua_military_officer = fields.Char("Відповідальний за військовий облік")
    ua_opening_balances = fields.Boolean("Будуть вхідні залишки")
