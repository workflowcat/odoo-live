# -*- coding: utf-8 -*-
"""Протокол перевірки якості.

Контроль якості в Odoo Community не живе: модуль `quality` - це Enterprise.
Тут не спроба його замінити, а найпростіший папір, який справді просять на
виробництві: перелік параметрів із нормою, виміряне значення і висновок
«придатний / не придатний», прив'язаний до виробу, партії або доставки.

Що це навмисно НЕ робить: не блокує відвантаження, не створює контрольних
точок у маршруті, не веде вибірковий контроль. Якщо таке знадобиться, це вже
буде інший модуль на нативних `stock.move` і правилах, а не ця форма.
"""
from odoo import api, fields, models

# Мінімальний перелік, з якого починають майже всі: решту дописують руками.
DEFAULT_CHECKLIST = [
    ("Зовнішній огляд", "", "без пошкоджень"),
    ("Комплектність", "", "відповідає специфікації"),
    ("Маркування", "", "розбірливе, повне"),
    ("Пакування", "", "ціле"),
    ("Супровідні документи", "", "в наявності"),
]


class UaQualityProtocol(models.Model):
    _name = "ua.quality.protocol"
    _description = "Протокол перевірки якості"
    _order = "date desc, id desc"

    name = fields.Char("Номер", readonly=True, copy=False, default="Новий", index=True)
    date = fields.Date("Дата перевірки", required=True, default=fields.Date.context_today)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True,
        default=lambda self: self.env.company)
    product_id = fields.Many2one("product.product", string="Номенклатура", required=True)
    lot_id = fields.Many2one(
        "stock.lot", string="Партія / серійний номер",
        domain="[('product_id', '=', product_id)]")
    move_id = fields.Many2one(
        "stock.move", string="Переміщення",
        help="Рух, до якого належить перевірка: приймання, випуск, відвантаження.")
    picking_id = fields.Many2one(related="move_id.picking_id", string="Документ складу", store=True)
    quantity = fields.Float("Кількість", digits="Product Unit of Measure", default=1.0)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    inspector = fields.Char("Перевіряв (ПІБ)")
    state = fields.Selection(
        [("draft", "Чернетка"), ("passed", "Придатний"), ("failed", "Не придатний")],
        string="Висновок", default="draft", required=True, copy=False)
    line_ids = fields.One2many("ua.quality.protocol.line", "protocol_id", string="Параметри")
    note = fields.Text("Примітки")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", "Новий") in (False, "", "Новий"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.quality.protocol") or "Новий"
        return super().create(vals_list)

    def action_fill_checklist(self):
        """Типовий перелік параметрів. Уже заповнений протокол не чіпаємо."""
        for record in self:
            if record.line_ids:
                continue
            record.line_ids = [
                (0, 0, {"sequence": index * 10, "name": name, "uom": uom, "norm": norm})
                for index, (name, uom, norm) in enumerate(DEFAULT_CHECKLIST)
            ]
        return True

    def action_pass(self):
        self.write({"state": "passed"})
        return True

    def action_fail(self):
        self.write({"state": "failed"})
        return True


class UaQualityProtocolLine(models.Model):
    _name = "ua.quality.protocol.line"
    _description = "Параметр перевірки якості"
    _order = "sequence, id"

    protocol_id = fields.Many2one("ua.quality.protocol", required=True, ondelete="cascade")
    sequence = fields.Integer("Порядок", default=10)
    name = fields.Char("Параметр", required=True)
    uom = fields.Char("Од.")
    norm = fields.Char("Норма")
    value = fields.Char("Виміряно")
    result = fields.Selection(
        [("ok", "Норма"), ("fail", "Не в нормі")], string="Результат", default="ok")
