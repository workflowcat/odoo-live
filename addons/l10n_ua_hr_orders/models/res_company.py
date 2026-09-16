# -*- coding: utf-8 -*-
"""Умови оплати за замовчуванням: аванс і остаточний розрахунок. Компанія задає загальні дні і
відсоток авансу; наказ про прийняття і трудовий договір успадковують їх зі справи прийняття,
можна змінити для конкретного працівника до проведення наказу.

Власні поля модуля (а не ua_advance_day/ua_advance_percent/ua_salary_day з
l10n_ua_payroll_rules/models/hr_version_pay.py - той файл ще не завершений і не в депендах цього
модуля; змішувати з незавершеною роботою іншого агента в паралель небезпечно)."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_pay_advance_percent = fields.Float("Аванс, % окладу", default=50.0)
    ua_pay_advance_day = fields.Integer("Аванс до числа", default=20, help="16-22 число місяця")
    ua_pay_final_day = fields.Integer("Остаточний розрахунок до числа", default=5, help="1-7 число наступного місяця")
