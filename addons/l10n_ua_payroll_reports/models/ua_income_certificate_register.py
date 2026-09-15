# -*- coding: utf-8 -*-
"""Реєстр виданих довідок про доходи: номер і дата видачі кожної довідки.

Сам майстер довідки - тимчасова модель (ua.income.certificate.wizard), тому номер
береться з послідовності «ua.income.certificate» і записується сюди, щоб історію
видачі можна було переглянути пізніше.
"""
from odoo import fields, models


class UaIncomeCertificateRegister(models.Model):
    _name = "ua.income.certificate.register"
    _description = "Реєстр довідок про доходи"
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True)
    date = fields.Date("Дата видачі", required=True, default=fields.Date.context_today)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    date_from = fields.Date("Період з")
    date_to = fields.Date("Період по")
    purpose = fields.Char("Для подання")
