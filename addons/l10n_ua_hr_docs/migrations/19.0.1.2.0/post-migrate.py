# -*- coding: utf-8 -*-
"""Перезаписати англійські назви рядків відпрацьованого часу.

Рушій OCA зберігає назву рядка перекладом у момент створення листка. Листки,
створені до встановлення українського перекладу, лишилися з текстом
«Normal Working Days paid at 100%». Назва тепер приходить зі свого переліку,
а старі рядки виправляємо тут.
"""
from odoo import SUPERUSER_ID, api

NAMES = {"WORK100": "Відпрацьовані дні"}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for code, name in NAMES.items():
        lines = env["hr.payslip.worked_days"].search([("code", "=", code), ("name", "!=", name)])
        if lines:
            lines.write({"name": name})
