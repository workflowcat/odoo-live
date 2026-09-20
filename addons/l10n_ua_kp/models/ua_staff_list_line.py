# -*- coding: utf-8 -*-
"""Рядок штатного розпису отримує посилання на довідник кодів.

Поле kp_code лишається як було (вільний текст): на нього спирається звіт і наявні
дані. Нове поле kp_id - зв'язок із довідником; коли його заповнюють, код у текстовому
полі проставляється сам. Так нічого не ламається, а нові рядки стають перевірними."""
from odoo import api, fields, models


class UaStaffListLine(models.Model):
    _inherit = "ua.staff.list.line"

    kp_id = fields.Many2one("ua.kp.code", string="Код професії", ondelete="restrict")
    # Офіційна назва професії стоїть тут, а не в довіднику кодів: під одним кодом
    # їх буває дев'яносто, і яка з них ця посада - знає лише сама посада.
    kp_official_name = fields.Char("Офіційна назва професії",
                                   help="Назва дослівно з класифікатора; друкується в розписі і наказі")

    @api.onchange("kp_id")
    def _onchange_kp_id(self):
        for line in self:
            if line.kp_id:
                line.kp_code = line.kp_id.code
