"""Замовлення на виробництво за контрактом.

Замовлення, випущене для контракту, несе посилання на нього: фактична калькуляція
збирає саме такі замовлення, а паспорт виробу знаходить контракт через замовлення,
що випустило серійний номер.
"""
from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ua_contract_id = fields.Many2one(
        "ua.contract", "Контракт", index="btree_not_null", check_company=True,
        domain="[('ua_defense', '=', True), ('state', '=', 'active')]",
        help="Оборонний контракт, для якого випускається виріб. Витрати замовлення "
             "йдуть у фактичну калькуляцію цього контракту.")
