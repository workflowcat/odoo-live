# -*- coding: utf-8 -*-
"""Список персонального військового обліку на дату: документ з рядками по кожному, хто підлягає обліку."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from .hr_employee import CATEGORY, DOC_TYPE, FITNESS, GROUP, LIABLE_STATUSES

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]


class UaMilitaryList(models.Model):
    _name = "ua.military.list"
    _inherit = ["mail.thread"]
    _description = "Список персонального військового обліку"
    _order = "date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True, tracking=True)
    state = fields.Selection(STATES, default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.military.list.line", "list_id", "Рядки")

    @api.depends("date")
    def _compute_name(self):
        for doc in self:
            doc.name = "Список персонального обліку на %s" % (doc.date.strftime("%d.%m.%Y") if doc.date else "")

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку списку персонального обліку.")

    def action_refill(self):
        """Видалити рядки і заповнити знову з hr.employee: усі, хто підлягає обліку (призовник / військовозобов'язаний / резервіст)."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            employees = self.env["hr.employee"].sudo().search([
                ("company_id", "=", doc.company_id.id), ("ua_mil_status", "in", list(LIABLE_STATUSES)),
            ], order="name")
            cat_labels = dict(CATEGORY)
            grp_labels = dict(GROUP)
            fit_labels = dict(FITNESS)
            doc_labels = dict(DOC_TYPE)
            vals_list = []
            for emp in employees:
                ln, fn, mn = emp._ua_name_parts()
                reg_address = ", ".join(p for p in [emp.private_street, emp.private_city, emp.private_zip] if p)
                doc_bits = " ".join(p for p in [doc_labels.get(emp.ua_mil_doc_type, ""), emp.ua_mil_doc_series, emp.ua_mil_doc_number] if p)
                if emp.ua_mil_doc_date:
                    doc_bits = ("%s від %s" % (doc_bits, emp.ua_mil_doc_date.strftime("%d.%m.%Y"))).strip()
                vals_list.append({
                    "employee_id": emp.id,
                    "full_name": " ".join(p for p in [ln, fn, mn] if p),
                    "birthday": emp.birthday,
                    "rnokpp": emp.ua_rnokpp or "",
                    "reg_address": reg_address,
                    "actual_address": getattr(emp, "ua_actual_address", "") or "",
                    "job_title": emp.job_title or "",
                    "rank": emp.ua_mil_rank or "",
                    "vos": emp.ua_mil_vos or "",
                    "category": cat_labels.get(emp.ua_mil_category, ""),
                    "grp": grp_labels.get(emp.ua_mil_group, ""),
                    "tcc": emp.ua_mil_tcc or "",
                    "doc_info": doc_bits,
                    "fitness": fit_labels.get(emp.ua_mil_fitness, ""),
                    "reserved_until": emp.ua_mil_reserve_until if emp.ua_mil_reserved else False,
                    "last_check": emp.ua_mil_last_check,
                    "note": emp.ua_mil_note or "",
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


class UaMilitaryListLine(models.Model):
    _name = "ua.military.list.line"
    _description = "Рядок списку персонального обліку"
    _order = "full_name"

    list_id = fields.Many2one("ua.military.list", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    full_name = fields.Char("ПІБ")
    birthday = fields.Date("Дата народження")
    rnokpp = fields.Char("РНОКПП")
    reg_address = fields.Char("Адреса реєстрації")
    actual_address = fields.Char("Фактична адреса")
    job_title = fields.Char("Посада")
    rank = fields.Char("Звання")
    vos = fields.Char("ВОС")
    category = fields.Char("Категорія обліку")
    grp = fields.Char("Група обліку")
    tcc = fields.Char("ТЦК")
    doc_info = fields.Char("Документ")
    fitness = fields.Char("Придатність")
    reserved_until = fields.Date("Бронювання до")
    last_check = fields.Date("Дата звірки")
    note = fields.Char("Примітка")
