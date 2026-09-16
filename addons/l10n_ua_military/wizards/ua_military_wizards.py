# -*- coding: utf-8 -*-
"""Майстри, що створюють документи військового обліку і відкривають їх форму.

Заповнення рядків - у ua.military.*.action_refill()."""
from datetime import date

from odoo import fields, models
from odoo.exceptions import UserError

from ..models.ua_military_list import VARIANT


class UaMilitaryListWizard(models.TransientModel):
    _name = "ua.military.list.wizard"
    _description = "Список персонального військового обліку"

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True)
    tcc = fields.Char("ТЦК та СП", help="Порожньо для кнопки «Створити списки по всіх ТЦК» - тоді буде по одному списку на кожен ТЦК.")
    variant = fields.Selection(VARIANT, "Розділ", default="all", required=True)

    def action_create(self):
        self.ensure_one()
        if not self.tcc:
            raise UserError("Вкажіть ТЦК та СП, або натисніть «Створити списки по всіх ТЦК».")
        doc = self.env["ua.military.list"].search([
            ("company_id", "=", self.company_id.id), ("date", "=", self.date),
            ("tcc", "=", self.tcc), ("variant", "=", self.variant), ("state", "=", "draft")], limit=1)
        if not doc:
            doc = self.env["ua.military.list"].create({
                "company_id": self.company_id.id, "date": self.date, "tcc": self.tcc, "variant": self.variant})
            doc.action_refill()
        return {"type": "ir.actions.act_window", "res_model": "ua.military.list", "view_mode": "form", "res_id": doc.id, "target": "current"}

    def action_create_all(self):
        """Створити списки по всіх ТЦК, де є хоча б один військовозобов'язаний."""
        self.ensure_one()
        ids = self.env["ua.military.list"].action_create_all_tcc(self.company_id.id, self.date, self.variant)
        return {"type": "ir.actions.act_window", "res_model": "ua.military.list", "view_mode": "list,form",
                "domain": [("id", "in", ids)], "target": "current"}


class UaMilitaryNoticeWizard(models.TransientModel):
    _name = "ua.military.notice.wizard"
    _description = "Повідомлення про зміну облікових даних"

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
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

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True)

    def action_create(self):
        self.ensure_one()
        doc = self.env["ua.military.reserved"].search([("company_id", "=", self.company_id.id), ("date", "=", self.date), ("state", "=", "draft")], limit=1)
        if not doc:
            doc = self.env["ua.military.reserved"].create({"company_id": self.company_id.id, "date": self.date})
            doc.action_refill()
        return {"type": "ir.actions.act_window", "res_model": "ua.military.reserved", "view_mode": "form", "res_id": doc.id, "target": "current"}
