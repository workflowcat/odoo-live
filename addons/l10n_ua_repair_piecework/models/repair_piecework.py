"""Роботи ремонту в документі «Виробіток».

Робота ремонту - виконавець, типова робота (розцінка і норма часу), кількість. Ремонт
завершено - дата завершення стоїть на замовленні, і виробіток за період, що її містить, бере
роботу рядком: кількість × розцінка. Рядки ремонтів перебудовує «Заповнити», як і рядки операцій.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UaRepairOperation(models.Model):
    _name = "ua.repair.operation"
    _description = "Типова робота ремонту"
    _order = "name"

    name = fields.Char("Робота", required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", "Компанія", help="Порожньо - для всіх компаній.")
    rate = fields.Float("Розцінка, грн за одиницю", digits="Product Price", required=True)
    minutes = fields.Float("Норма часу, хв на одиницю", digits=(10, 2))


class UaRepairLabour(models.Model):
    _name = "ua.repair.labour"
    _description = "Робота в ремонті"
    _order = "repair_id, id"

    repair_id = fields.Many2one("repair.order", "Ремонт", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="repair_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    employee_id = fields.Many2one("hr.employee", "Виконавець", required=True, check_company=True)
    operation_id = fields.Many2one("ua.repair.operation", "Робота", required=True)
    quantity = fields.Float("Кількість", digits="Product Unit", default=1.0, required=True)
    rate = fields.Float("Розцінка", digits="Product Price", compute="_compute_rate", store=True, readonly=False)
    amount = fields.Monetary("Сума", compute="_compute_amount", store=True)
    piecework_line_ids = fields.One2many("ua.piecework.line", "repair_labour_id", "Виробіток", readonly=True)
    in_piecework = fields.Boolean("У виробітку", compute="_compute_in_piecework")

    @api.depends("operation_id")
    def _compute_rate(self):
        for labour in self:
            labour.rate = labour.operation_id.rate

    @api.depends("quantity", "rate")
    def _compute_amount(self):
        for labour in self:
            labour.amount = (labour.currency_id or self.env.company.currency_id).round(labour.quantity * labour.rate)

    @api.depends("piecework_line_ids.state")
    def _compute_in_piecework(self):
        for labour in self:
            labour.in_piecework = bool(labour.piecework_line_ids.filtered(lambda l: l.state != "cancel"))

    def write(self, vals):
        if self.filtered("in_piecework") and set(vals) & {"employee_id", "operation_id", "quantity", "rate"}:
            raise UserError(_("Робота вже у виробітку. Змініть її після скасування виробітку."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_not_in_piecework(self):
        if self.filtered("in_piecework"):
            raise UserError(_("Робота вже у виробітку. Видаліть її після скасування виробітку."))


class RepairOrder(models.Model):
    _inherit = "repair.order"

    ua_labour_ids = fields.One2many("ua.repair.labour", "repair_id", "Роботи")
    ua_labour_amount = fields.Monetary("Відрядна оплата", compute="_compute_ua_labour_amount",
                                       currency_field="ua_currency_id")
    ua_currency_id = fields.Many2one(related="company_id.currency_id")
    ua_date_done = fields.Date("Завершено", readonly=True, copy=False, index=True)

    @api.depends("ua_labour_ids.amount")
    def _compute_ua_labour_amount(self):
        for repair in self:
            repair.ua_labour_amount = sum(repair.ua_labour_ids.mapped("amount"))

    def action_repair_done(self):
        result = super().action_repair_done()
        self.filtered(lambda r: r.state == "done" and not r.ua_date_done).write(
            {"ua_date_done": fields.Date.context_today(self)})
        return result


class UaPiecework(models.Model):
    _inherit = "ua.piecework"

    def _ua_auto_lines(self):
        return super()._ua_auto_lines() | self.line_ids.filtered("repair_labour_id")

    def _ua_fill_values(self):
        values = super()._ua_fill_values()
        taken = self.env["ua.piecework.line"].search([
            ("piecework_id", "!=", self.id), ("piecework_id.state", "!=", "cancel"),
            ("repair_labour_id", "!=", False), ("company_id", "=", self.company_id.id)]).repair_labour_id
        labours = self.env["ua.repair.labour"].search([
            ("company_id", "=", self.company_id.id), ("repair_id.state", "=", "done"),
            ("repair_id.ua_date_done", ">=", self.date_from), ("repair_id.ua_date_done", "<=", self.date_to),
            ("rate", ">", 0.0)], order="repair_id, id") - taken
        for labour in labours:
            values.append({"piecework_id": self.id, "repair_labour_id": labour.id,
                           "employee_id": labour.employee_id.id, "quantity": labour.quantity, "rate": labour.rate})
        return values


class UaPieceworkLine(models.Model):
    _inherit = "ua.piecework.line"

    repair_labour_id = fields.Many2one("ua.repair.labour", "Робота ремонту", index="btree_not_null",
                                       ondelete="restrict")
    repair_id = fields.Many2one(related="repair_labour_id.repair_id", store=True, string="Ремонт")

    def _ua_source_name(self):
        if self.repair_labour_id:
            return "%s: %s" % (self.repair_id.name, self.repair_labour_id.operation_id.name)
        return super()._ua_source_name()

    def _ua_doc_name(self):
        return self.repair_id.name if self.repair_labour_id else super()._ua_doc_name()

    def _ua_work_name(self):
        return self.repair_labour_id.operation_id.name if self.repair_labour_id else super()._ua_work_name()

    def _ua_norm_minutes(self):
        if self.repair_labour_id:
            return self.quantity * (self.repair_labour_id.operation_id.minutes or 0.0)
        return super()._ua_norm_minutes()
