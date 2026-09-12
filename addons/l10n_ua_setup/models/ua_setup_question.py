# -*- coding: utf-8 -*-
"""Каталог питань анкети.

Текст питань узятий з анкети бухгалтера і не змінюється: заповнену анкету звіряють
з оригіналом. Питання з позначкою «обов'язкове» треба закрити до першого реального
розрахунку.
"""
from odoo import fields, models

KINDS = [("choice", "Один варіант"), ("multi", "Кілька варіантів"),
         ("text", "Текст"), ("number", "Число"), ("date", "Дата")]


class UaSetupQuestion(models.Model):
    _name = "ua.setup.question"
    _description = "Питання анкети"
    _order = "sequence, id"

    code = fields.Char("Код", required=True, index=True)
    sequence = fields.Integer("Порядок", default=10)
    section = fields.Char("Розділ", required=True)
    name = fields.Char("Питання", required=True)
    kind = fields.Selection(KINDS, "Вид відповіді", default="text", required=True)
    required = fields.Boolean("Обов'язкове для старту",
                              help="У анкеті позначене знаком уваги. Без відповіді реальний розрахунок не починаємо.")
    options = fields.Char("Варіанти", help="Варіанти з анкети, розділені знаком |")
    hint = fields.Char("Підказка")
    target = fields.Char("Що налаштовує", help="Поле або параметр системи, на який впливає відповідь")

    _code_uniq = models.Constraint("unique(code)", "Питання з таким кодом уже є.")
