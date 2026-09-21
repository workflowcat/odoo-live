# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_vat_status = fields.Selection(
        selection=[
            ("payer", "Платник ПДВ"),
            ("non_payer", "Неплатник ПДВ"),
            ("single_tax", "ФОП / єдиний податок"),
        ],
        string="Статус ПДВ",
        default="non_payer",
        help="Податковий статус контрагента. Платнику ПДВ за першою подією "
             "(оплата чи відвантаження - що раніше) складається податкова "
             "накладна, яку треба зареєструвати в ЄРПН.",
    )
