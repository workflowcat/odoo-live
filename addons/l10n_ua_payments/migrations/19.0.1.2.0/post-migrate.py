# -*- coding: utf-8 -*-
"""Пронумерувати вже затверджені/оплачені відомості на перерахування, що лишилися без номера.

Поле number з'явилося разом із нумерацією ua.payment.batch; документи, затверджені
раніше, проставляємо в хронологічному порядку тим самим ланцюжком, яким action_confirm
нумерує нові.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    docs = env["ua.payment.batch"].search([
        ("state", "in", ("confirmed", "paid")), ("number", "=", False),
    ], order="year, month, id")
    Sequence = env["ir.sequence"].sudo()
    for doc in docs:
        sequence_date = doc.pay_date or doc.create_date.date()
        doc.number = Sequence.next_by_code("ua.payment.batch", sequence_date=sequence_date)
        if not doc.number_date:
            doc.number_date = sequence_date
