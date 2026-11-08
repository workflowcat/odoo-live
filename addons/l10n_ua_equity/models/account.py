# -*- coding: utf-8 -*-
"""Рядок форми № 4 на проводці і рядку проводки.

Позначка потрібна там, де рахунок не каже всього: виправлення помилки минулих років (4010) чи
зміна облікової політики (4005) проводяться тими самими рахунками, що й звичайні рухи.
"""
from odoo import fields, models

from .equity import ROW_SELECTION


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_equity_row = fields.Selection(
        ROW_SELECTION, string="Рядок звіту про власний капітал", copy=False,
        help="Для форми № 4: усі рухи на рахунках капіталу в цій проводці підуть у цей рядок, якщо на "
             "рядку проводки не вибрано іншого. Порожньо - рядок за правилом.")


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    ua_equity_row = fields.Selection(ROW_SELECTION, string="Рядок форми № 4", copy=False)
