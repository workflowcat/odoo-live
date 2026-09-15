# -*- coding: utf-8 -*-
"""Пронумерувати наказом уже затверджені штатні розписи, що лишилися без номера.

Поля order_number/order_date з'явилися разом із нумерацією ua.staff.list; затверджені
раніше документи проставляємо в хронологічному порядку тим самим ланцюжком, яким
action_confirm нумерує нові.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    docs = env["ua.staff.list"].search([
        ("state", "=", "confirmed"), ("order_number", "=", False),
    ], order="date, id")
    Sequence = env["ir.sequence"].sudo()
    for doc in docs:
        doc.order_number = Sequence.next_by_code("ua.staff.list", sequence_date=doc.date)
        if not doc.order_date:
            doc.order_date = doc.date
