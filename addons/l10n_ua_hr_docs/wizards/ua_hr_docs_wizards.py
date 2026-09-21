# -*- coding: utf-8 -*-
"""Майстри, що створюють документи «Штатний розпис» і «Табель обліку робочого часу» (типова форма П-5).

Заповнення рядків - у ua.staff.list.action_refill() / ua.timesheet.sheet.action_refill()."""
from datetime import date

from odoo import fields, models


class UaStaffListWizard(models.TransientModel):
    _name = "ua.staff.list.wizard"
    _description = "Штатний розпис"

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=lambda s: fields.Date.context_today(s), required=True)
    order_ref = fields.Char("Затверджено наказом (№ і дата)")

    def action_create(self):
        """Створити документ і відкрити його форму; якщо на цю дату вже є чернетка - відкрити її."""
        self.ensure_one()
        doc = self.env["ua.staff.list"].search([("company_id", "=", self.company_id.id), ("date", "=", self.date), ("state", "=", "draft")], limit=1)
        if not doc:
            doc = self.env["ua.staff.list"].create({"company_id": self.company_id.id, "date": self.date, "order_ref": self.order_ref})
            doc.action_refill()
        elif self.order_ref:
            doc.order_ref = self.order_ref
        return {"type": "ir.actions.act_window", "res_model": "ua.staff.list", "view_mode": "form", "res_id": doc.id, "target": "current"}


class UaTimesheetWizard(models.TransientModel):
    _name = "ua.timesheet.wizard"
    _description = "Табель обліку робочого часу (П-5)"

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", default=lambda s: date.today().year, required=True)
    month = fields.Integer("Місяць", default=lambda s: date.today().month, required=True)
    department_id = fields.Many2one("hr.department", "Підрозділ (порожньо = усі)")

    def action_create(self):
        """Створити документ і відкрити його форму; якщо на цей період уже є чернетка - відкрити її."""
        self.ensure_one()
        doc = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company_id.id), ("year", "=", self.year), ("month", "=", self.month),
            ("department_id", "=", self.department_id.id if self.department_id else False), ("state", "=", "draft"),
        ], limit=1)
        if not doc:
            doc = self.env["ua.timesheet.sheet"].create({"company_id": self.company_id.id, "year": self.year, "month": self.month, "department_id": self.department_id.id})
            doc.action_refill()
        return {"type": "ir.actions.act_window", "res_model": "ua.timesheet.sheet", "view_mode": "form", "res_id": doc.id, "target": "current"}
