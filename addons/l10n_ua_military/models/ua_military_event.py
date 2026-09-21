# -*- coding: utf-8 -*-
"""Подія військового обліку працівника: взяття на облік, зміна даних, звірка тощо."""
from odoo import fields, models

KIND = [
    ("register", "Взято на облік"),
    ("update", "Зміна даних"),
    ("notice", "Повідомлення ТЦК"),
    ("reserve", "Бронювання"),
    ("deregister", "Зняття з обліку"),
    ("check", "Звірка"),
]


class UaMilitaryEvent(models.Model):
    _name = "ua.military.event"
    _description = "Подія військового обліку"
    _order = "date desc, id desc"

    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, ondelete="cascade")
    date = fields.Date("Дата", required=True, default=lambda s: fields.Date.context_today(s))
    kind = fields.Selection(KIND, string="Вид події", required=True)
    note = fields.Char("Примітка")
    user_id = fields.Many2one("res.users", "Відповідальний", default=lambda s: s.env.user)
