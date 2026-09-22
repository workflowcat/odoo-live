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

Читання залишків - ОДНЕ на весь набір локацій. Карта складу малює сотні полиць
одним `search_read`, і пошук квантів на кожну локацію окремо дав би стільки ж
запитів у базу. Тому всі підлеглі локації беруться однією вибіркою, кванти -
одним `_read_group` по (локація, товар), а сума піднімається деревом через
`parent_path`, який стоїть у нативної `stock.location` саме для цього.
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
        saved = self.filtered(lambda location: isinstance(location.id, int))
        for location in self - saved:
            location.ua_capacity_used = 0
        if not saved:
            return

        # Піддерево всіх запитаних локацій однією вибіркою: далі кванти читаються
        # по цьому переліку, а не по кожній локації окремо.
        subtree = self.env["stock.location"].search([("id", "child_of", saved.ids)])

        # Один запит по квантах на весь набір. Групування по товару потрібне,
        # бо габарит - властивість товару, а не кванта.
        groups = self.env["stock.quant"]._read_group(
            [("location_id", "in", subtree.ids), ("quantity", ">", 0)],
            groupby=["location_id", "product_id"],
            aggregates=["quantity:sum"],
        )
        rows = [(location.id, product.id, quantity)
                for location, product, quantity in groups]
        # Товари одним набором: інакше кожен `product_tmpl_id` тягнув би свій запит.
        products = self.env["product.product"].browse({row[1] for row in rows})
        slots_per_unit = {
            product.id: product.product_tmpl_id._ua_slots() for product in products}

        own_slots = {}
        for location_id, product_id, quantity in rows:
            own_slots[location_id] = (
                own_slots.get(location_id, 0.0) + quantity * slots_per_unit[product_id])

        # Підйом деревом: `parent_path` - це «1/7/12/», тобто id всіх предків
        # разом із самою локацією. Полиця віддає своє число кожному предкові,
        # який нас цікавить, за один прохід і без жодного запиту.
        totals = dict.fromkeys(saved.ids, 0.0)
        for location in subtree:
            slots = own_slots.get(location.id)
            if not slots:
                continue
            for part in (location.parent_path or "").split("/"):
                if part and int(part) in totals:
                    totals[int(part)] += slots

        for location in saved:
            location.ua_capacity_used = int(
                math.ceil(round(totals[location.id], 6)))
