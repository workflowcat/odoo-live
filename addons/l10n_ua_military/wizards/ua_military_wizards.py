# -*- coding: utf-8 -*-
"""Майстри, що створюють документи військового обліку і відкривають їх форму.

Заповнення рядків - у ua.military.*.action_refill()."""
from datetime import date

from odoo import fields, models


class UaMilitaryListWizard(models.TransientModel):
    _name = "ua.military.list.wizard"
    _description = "Список персонального військового обліку"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True)

    def action_create(self):
        self.ensure_one()
        doc = self.env["ua.military.list"].search([("company_id", "=", self.company_id.id), ("date", "=", self.date), ("state", "=", "draft")], limit=1)
        if not doc:
            doc = self.env["ua.military.list"].create({"company_id": self.company_id.id, "date": self.date})
            doc.action_refill()
        return {"type": "ir.actions.act_window", "res_model": "ua.military.list", "view_mode": "form", "res_id": doc.id, "target": "current"}


class UaMilitaryNoticeWizard(models.TransientModel):
    _name = "ua.military.notice.wizard"
    _description = "Повідомлення про зміну облікових даних"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    date_from = fields.Date("Період з", default=lambda s: date.today().replace(day=1), required=True)
    date_to = fields.Date("Період по", default=fields.Date.today, required=True)

    def action_create(self):
        self.ensure_one()
        doc = self.env["ua.military.notice"].search([
            ("company_id", "=", self.company_id.id), ("date_from", "=", self.date_from), ("date_to", "=", self.date_to), ("state", "=", "draft"),
        ], limit=1)
        if not doc:
            doc = self.env["ua.military.notice"].create({"company_id": self.company_id.id, "date_from": self.date_from, "date_to": self.date_to})
            doc.action_refill()
        return {"type": "ir.actions.act_window", "res_model": "ua.military.notice", "view_mode": "form", "res_id": doc.id, "target": "current"}


class UaMilitaryReservedWizard(models.TransientModel):
    _name = "ua.military.reserved.wizard"
    _description = "Список заброньованих"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True)

    def action_create(self):
        self.ensure_one()
        doc = self.env["ua.military.reserved"].search([("company_id", "=", self.company_id.id), ("date", "=", self.date), ("state", "=", "draft")], limit=1)
        if not doc:
            doc = self.env["ua.military.reserved"].create({"company_id": self.company_id.id, "date": self.date})
            doc.action_refill()
        return {"type": "ir.actions.act_window", "res_model": "ua.military.reserved", "view_mode": "form", "res_id": doc.id, "target": "current"}
