# -*- coding: utf-8 -*-
"""Місткість полиці в місцях і скільки з них зайнято.

Два поля, обидва тонкі. «Місць» комірник ставить руками - це фізична властивість
полиці, порахувати її нізвідки. «Зайнято місць» рахується з нативних залишків:
кількість × габарит товару (`product.template.ua_size`, S/M/L = 1/4/16 місць).

Чому сума кількостей, а не кількість різних товарів: полиця переповнюється від
штук, а не від назв. Двадцять однакових рам займають двадцять місць, а не одне.
Габарит потрібен рівно для того, щоб рама важила більше за гвинт.

Заповнення рахується по локації РАЗОМ З ДОЧІРНІМИ (`child_of`). Для полиці, в якої
дітей немає, це та сама полиця; для зони чи складу виходить сума по всіх полицях
усередині, і карта складу читається на будь-якому рівні.

Поле не зберігається: залишки міняються щохвилини, а збережене число застаріло б
до першого ж відвантаження. Переповнення (зайнято > місць) не блокується нічим -
це показник для карти складу, а не обмеження розкладання. Обмеження вміє нативна
категорія зберігання, і вона лишається на своєму місці.
"""
import math

from odoo import api, fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    ua_capacity = fields.Integer(
        string="Місць",
        help="Скільки місць має полиця. Нуль - місткість не задано, переповнення "
             "не рахується.",
    )
    ua_capacity_used = fields.Integer(
        string="Зайнято місць",
        compute="_compute_ua_capacity_used",
        help="Сума «кількість × габарит товару» по залишках цієї локації та її "
             "дочірніх. Товар без габариту займає одне місце.",
    )

    @api.depends("quant_ids.quantity", "quant_ids.product_id", "child_ids")
    def _compute_ua_capacity_used(self):
        for location in self:
            if not isinstance(location.id, int):
                location.ua_capacity_used = 0
                continue
            quants = self.env["stock.quant"].search([
                ("location_id", "child_of", location.id),
                ("quantity", ">", 0),
            ])
            slots = sum(
                quant.quantity * quant.product_id.product_tmpl_id._ua_slots()
                for quant in quants
            )
            location.ua_capacity_used = int(math.ceil(round(slots, 6)))
