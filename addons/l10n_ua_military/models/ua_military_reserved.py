# -*- coding: utf-8 -*-
"""Список заброньованих на дату: документ з рядками по кожному із ua_mil_reserved."""
from odoo import api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]


class UaMilitaryReserved(models.Model):
    _name = "ua.military.reserved"
    _inherit = ["mail.thread"]
    _description = "Список заброньованих"
    _order = "date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True, tracking=True)
    state = fields.Selection(STATES, default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.military.reserved.line", "reserved_id", "Рядки")

    @api.depends("date")
    def _compute_name(self):
        for doc in self:
            doc.name = "Список заброньованих на %s" % (doc.date.strftime("%d.%m.%Y") if doc.date else "")

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку списку заброньованих.")

    def action_refill(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            employees = self.env["hr.employee"].sudo().search([
                ("company_id", "=", doc.company_id.id), ("ua_mil_reserved", "=", True),
            ], order="name")
            vals_list = []
            for emp in employees:
                ln, fn, mn = emp._ua_name_parts()
                days_left = (emp.ua_mil_reserve_until - doc.date).days if emp.ua_mil_reserve_until else False
                vals_list.append({
                    "employee_id": emp.id,
                    "full_name": " ".join(p for p in [ln, fn, mn] if p),
                    "job_title": emp.job_title or "",
                    "reserve_order": emp.ua_mil_reserve_order or "",
                    "reserve_until": emp.ua_mil_reserve_until,
                    "days_left": days_left,
                })
            doc.line_ids = [(0, 0, v) for v in vals_list]
        return True

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"


class UaMilitaryReservedLine(models.Model):
    _name = "ua.military.reserved.line"
    _description = "Рядок списку заброньованих"
    _order = "reserve_until, full_name"

    reserved_id = fields.Many2one("ua.military.reserved", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    full_name = fields.Char("ПІБ")
    job_title = fields.Char("Посада")
    reserve_order = fields.Char("Підстава")
    reserve_until = fields.Date("До дати")
    days_left = fields.Integer("Днів до закінчення")
