# -*- coding: utf-8 -*-
"""Вартість специфікації і відповідь «скільки можемо зібрати».

Нативний Odoo рахує вартість специфікації кнопкою на товарі
(`action_bom_cost`), але результат кладе у ціну товару і на самій специфікації
не показує; вкладені специфікації при цьому розгортає лише тоді, коли їх
окремо передали в перерахунок. Планувальник же питає інше і щодня: скільки
коштує один виріб за сьогоднішніми обліковими цінами і скільки штук вийде
зібрати з того, що лежить на складі.

Обидва числа - поля специфікації, без кнопок і без збереження: перерахунок
дешевий, а збережене число застаріває за годину.

Спрощення, які треба знати:

* вкладена специфікація розгортається рекурсивно, але глибина обмежена
  (`MAX_DEPTH`), щоб кільцева специфікація не повісила сервер;
* доступність рахується по самому компоненту, навіть якщо в нього є своя
  специфікація: «можемо зібрати» означає «з наявних комплектуючих», а не «з
  того, що ще встигнемо доробити»;
* операції беруться за плановою тривалістю і ставкою робочого центру.
"""
from odoo import api, fields, models

MAX_DEPTH = 10


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    ua_cost_material = fields.Monetary(
        string="Матеріали",
        currency_field="ua_currency_id",
        compute="_compute_ua_cost",
        help="Сума облікових цін компонентів на одиницю виробу, з розгорнутими "
             "вкладеними специфікаціями.",
    )
    ua_cost_operation = fields.Monetary(
        string="Операції",
        currency_field="ua_currency_id",
        compute="_compute_ua_cost",
        help="Планова тривалість операцій × вартість години робочого центру.",
    )
    ua_cost_total = fields.Monetary(
        string="Вартість за специфікацією",
        currency_field="ua_currency_id",
        compute="_compute_ua_cost",
        help="Матеріали плюс операції на одиницю виробу.",
    )
    ua_available_qty = fields.Float(
        string="Можемо зібрати",
        compute="_compute_ua_available_qty",
        digits="Product Unit of Measure",
        help="Скільки виробів вийде зібрати з наявних залишків: найменше з "
             "часток «залишок компонента / потреба на один виріб».",
    )
    ua_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Валюта",
    )

    # ------------------------------------------------------------------
    # Вартість
    # ------------------------------------------------------------------
    def _ua_operation_cost(self):
        """Вартість операцій на всю партію специфікації."""
        self.ensure_one()
        total = 0.0
        for operation in self.operation_ids:
            total += (operation.time_cycle_manual or 0.0) / 60.0 * (
                operation.workcenter_id.costs_hour or 0.0)
        return total

    def _ua_material_cost(self, depth=0):
        """Матеріали на всю партію специфікації, з вкладеними специфікаціями."""
        self.ensure_one()
        total = 0.0
        for line in self.bom_line_ids:
            quantity = line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id, round=False)
            child = line.child_bom_id
            if child and depth < MAX_DEPTH:
                batch = child.product_qty or 1.0
                child_cost = child._ua_material_cost(depth + 1) + child._ua_operation_cost()
                total += child_cost / batch * quantity
            else:
                total += (line.product_id.standard_price or 0.0) * quantity
        return total

    @api.depends("bom_line_ids.product_qty", "bom_line_ids.product_id",
                 "operation_ids.time_cycle_manual", "product_qty")
    def _compute_ua_cost(self):
        for bom in self:
            batch = bom.product_qty or 1.0
            material = bom._ua_material_cost() / batch
            operation = bom._ua_operation_cost() / batch
            bom.ua_cost_material = material
            bom.ua_cost_operation = operation
            bom.ua_cost_total = material + operation

    # ------------------------------------------------------------------
    # Доступність
    # ------------------------------------------------------------------
    @api.depends("bom_line_ids.product_qty", "bom_line_ids.product_id", "product_qty")
    def _compute_ua_available_qty(self):
        for bom in self:
            batch = bom.product_qty or 1.0
            possible = None
            for line in bom.bom_line_ids:
                per_unit = line.product_uom_id._compute_quantity(
                    line.product_qty, line.product_id.uom_id, round=False) / batch
                if per_unit <= 0:
                    continue
                stock = line.product_id.with_company(bom.company_id or self.env.company).qty_available
                share = stock // per_unit
                possible = share if possible is None else min(possible, share)
            bom.ua_available_qty = possible or 0.0
