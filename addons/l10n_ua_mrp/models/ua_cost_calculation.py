# -*- coding: utf-8 -*-
"""Калькуляція собівартості за місяць.

Нативний Odoo показує собівартість замовлення на виробництво у звіті «Огляд
виробництва»: там видно матеріали, операції і залишок. Калькуляції за місяць -
таблиці «виріб × стаття витрат» з кількістю випуску і собівартістю одиниці -
немає, а саме вона потрібна і бухгалтеру, і плановому відділу, і її ж просять
у перевірці.

Документ збирає три статті прямо з нативних даних, нічого не вигадуючи:

* матеріали - сума `value` переміщень комплектуючих закритих замовлень
  (те саме число, яким нативна оцінка запасів кредитувала 201);
* оплата праці - `_cal_cost()` нарядів (години × вартість години робочого
  центру), те саме число, яким `mrp_account` дебетував 231;
* ЗВВ - частка проведених розподілів ЗВВ періоду, пропорційна годинам нарядів
  виробу.

Четвертої статті немає навмисно: якщо цех несе витрати, яких у нарядах і
комплектуючих не видно, вони приходять через 91 і потрапляють у ЗВВ.

Документ нічого не проводить. Це аркуш, а не проводка: проводки вже зробили
нативна оцінка запасів і документ розподілу ЗВВ.
"""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class UaCostCalculation(models.Model):
    _name = "ua.cost.calculation"
    _description = "Калькуляція собівартості"
    _order = "date_from desc, id desc"

    name = fields.Char("Номер", readonly=True, copy=False, default="Новий", index=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    date_from = fields.Date(
        "Початок періоду", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date("Кінець періоду", required=True, compute="_compute_date_to",
                          store=True, readonly=False, precompute=True)
    product_ids = fields.Many2many(
        "product.product", string="Вироби",
        help="Порожньо - беруться всі вироби, випущені в періоді.")
    line_ids = fields.One2many("ua.cost.calculation.line", "calculation_id", string="Рядки")
    amount_material = fields.Monetary(
        "Матеріали", currency_field="currency_id", compute="_compute_totals", store=True)
    amount_labour = fields.Monetary(
        "Оплата праці", currency_field="currency_id", compute="_compute_totals", store=True)
    amount_zvv = fields.Monetary(
        "ЗВВ", currency_field="currency_id", compute="_compute_totals", store=True)
    amount_total = fields.Monetary(
        "Виробнича собівартість", currency_field="currency_id",
        compute="_compute_totals", store=True)
    note = fields.Char("Примітка")

    _dates = models.Constraint(
        "CHECK (date_to >= date_from)",
        "Кінець періоду не може бути раніший за початок.",
    )

    @api.depends("date_from")
    def _compute_date_to(self):
        for record in self:
            if record.date_from:
                record.date_to = record.date_from + relativedelta(months=1, days=-1)

    @api.depends("line_ids.amount_material", "line_ids.amount_labour", "line_ids.amount_zvv")
    def _compute_totals(self):
        for record in self:
            record.amount_material = sum(record.line_ids.mapped("amount_material"))
            record.amount_labour = sum(record.line_ids.mapped("amount_labour"))
            record.amount_zvv = sum(record.line_ids.mapped("amount_zvv"))
            record.amount_total = sum(record.line_ids.mapped("amount_total"))

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", "Новий") in (False, "", "Новий"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.cost.calculation") or "Новий"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Збір
    # ------------------------------------------------------------------
    def _productions(self):
        """Замовлення на виробництво, закриті в періоді."""
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("date_finished", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("date_finished", "<", fields.Datetime.to_datetime(self.date_to) +
             relativedelta(days=1)),
        ]
        if self.product_ids:
            domain.append(("product_id", "in", self.product_ids.ids))
        return self.env["mrp.production"].search(domain)

    def _zvv_allocated(self):
        """Скільки ЗВВ розподілено в періоді проведеними документами."""
        self.ensure_one()
        allocations = self.env["ua.zvv.allocation"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "posted"),
            ("date_from", ">=", self.date_from),
            ("date_to", "<=", self.date_to),
        ])
        return sum(allocations.mapped("amount_allocated"))

    @staticmethod
    def _material_cost(production):
        """Матеріали замовлення: вартість закритих переміщень комплектуючих."""
        return sum(move.value for move in production.move_raw_ids if move.state == "done")

    @staticmethod
    def _labour_cost(production):
        return production.workorder_ids._cal_cost()

    @staticmethod
    def _hours(production):
        return sum(production.workorder_ids.mapped("duration")) / 60.0

    def action_compute(self):
        """Перезібрати рядки. Ідемпотентно: старі рядки замінюються новими."""
        for record in self:
            productions = record._productions()
            if not productions:
                raise UserError(
                    "За період %s - %s немає закритих замовлень на виробництво."
                    % (record.date_from, record.date_to))
            zvv_total = record._zvv_allocated()
            hours_total = sum(record._hours(mo) for mo in productions)
            buckets = {}
            for production in productions:
                key = production.product_id
                bucket = buckets.setdefault(key, {
                    "quantity": 0.0, "material": 0.0, "labour": 0.0,
                    "hours": 0.0, "orders": self.env["mrp.production"],
                })
                bucket["quantity"] += production.qty_produced
                bucket["material"] += record._material_cost(production)
                bucket["labour"] += record._labour_cost(production)
                bucket["hours"] += record._hours(production)
                bucket["orders"] |= production
            lines = []
            for product, bucket in sorted(buckets.items(), key=lambda item: item[0].display_name):
                if hours_total > 0:
                    zvv = round(zvv_total * bucket["hours"] / hours_total, 2)
                elif len(buckets) == 1:
                    zvv = zvv_total
                else:
                    zvv = 0.0
                lines.append((0, 0, {
                    "product_id": product.id,
                    "quantity": bucket["quantity"],
                    "amount_material": round(bucket["material"], 2),
                    "amount_labour": round(bucket["labour"], 2),
                    "amount_zvv": zvv,
                    "hours": round(bucket["hours"], 2),
                    "production_ids": [(6, 0, bucket["orders"].ids)],
                }))
            record.line_ids = [(5, 0, 0)] + lines
        return True


class UaCostCalculationLine(models.Model):
    _name = "ua.cost.calculation.line"
    _description = "Рядок калькуляції собівартості"
    _order = "id"

    calculation_id = fields.Many2one("ua.cost.calculation", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="calculation_id.company_id", store=True)
    currency_id = fields.Many2one(related="calculation_id.currency_id")
    product_id = fields.Many2one("product.product", string="Виріб", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    quantity = fields.Float("Випуск", digits="Product Unit of Measure")
    hours = fields.Float("Години нарядів")
    amount_material = fields.Monetary("Матеріали", currency_field="currency_id")
    amount_labour = fields.Monetary("Оплата праці", currency_field="currency_id")
    amount_zvv = fields.Monetary("ЗВВ", currency_field="currency_id")
    amount_total = fields.Monetary(
        "Разом", currency_field="currency_id", compute="_compute_amounts", store=True)
    amount_unit = fields.Monetary(
        "Собівартість одиниці", currency_field="currency_id",
        compute="_compute_amounts", store=True)
    production_ids = fields.Many2many("mrp.production", string="Замовлення")

    @api.depends("amount_material", "amount_labour", "amount_zvv", "quantity")
    def _compute_amounts(self):
        for line in self:
            total = line.amount_material + line.amount_labour + line.amount_zvv
            line.amount_total = total
            line.amount_unit = total / line.quantity if line.quantity else 0.0
