# -*- coding: utf-8 -*-
"""Стаття руху коштів на платежі, проводці (і рядку виписки) та рядку проводки.

Стаття необов'язкова: без неї звіт бере правило за кореспондентним рахунком. Вибирають її там,
де рахунок не каже всього, наприклад оплата постачальнику (63) за верстат - це придбання
необоротних активів (3260), а не оплата товарів (3100).
"""
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_cashflow_item_id = fields.Many2one(
        "ua.cashflow.item", string="Стаття руху коштів", copy=False, index="btree_not_null",
        help="Для форми № 3: усі рухи грошей у цій проводці підуть у цю статтю, якщо на рядку "
             "проводки не вибрано іншої.")


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    ua_cashflow_item_id = fields.Many2one(
        "ua.cashflow.item", string="Стаття руху коштів", copy=False, index="btree_not_null")


class AccountPayment(models.Model):
    _inherit = "account.payment"

    ua_cashflow_item_id = fields.Many2one(
        "ua.cashflow.item", string="Стаття руху коштів", copy=False,
        help="Для форми № 3. Порожньо - стаття за кореспондентним рахунком.")
