# -*- coding: utf-8 -*-
"""Перевірка документів на дату: документ із рядком на кожну пару «працівник - вимога».

Раніше це був прохідний майстер (ua.hr.doc.pack.wizard), який нічого не зберігав і одразу
друкував матрицю. Перевірка документів - річ із датою: «станом на 1 вересня цих паперів не
було» має лишатися в базі, інакше наступного місяця нічим довести, що перевірку робили.
Тому це звичайний документ: чернетка, «Заповнити», «Затвердити», друк.

Покриття рахує сам довідник вимог (ua.hr.doc.requirement._is_covered) - другої реалізації
тут немає.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]
STATUS = [("have", "є"), ("missing", "немає"), ("not_needed", "н/п")]


class UaHrDocCheck(models.Model):
    _name = "ua.hr.doc.check"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Перевірка документів"
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda s: s.env.company)
    date = fields.Date("На дату", required=True, tracking=True,
                       default=lambda s: fields.Date.context_today(s))
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.hr.doc.check.line", "check_id", "Рядки")
    employee_count = fields.Integer("Працівників", compute="_compute_counts", store=True)
    missing_count = fields.Integer("Бракує документів", compute="_compute_counts", store=True)

    @api.depends("date")
    def _compute_name(self):
        for doc in self:
            doc.name = "Перевірка документів на %s" % (doc.date.strftime("%d.%m.%Y") if doc.date else "")

    @api.depends("line_ids.status", "line_ids.employee_id")
    def _compute_counts(self):
        for doc in self:
            doc.employee_count = len(doc.line_ids.mapped("employee_id"))
            doc.missing_count = len(doc.line_ids.filtered(lambda l: l.status == "missing"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку перевірки документів.")

    # ------------------------------------------------------------------ складання
    @api.model
    def ua_compose(self, company, year=None, month=None, date=None, **params):
        """Нова перевірка документів на дату, одразу заповнена."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        doc = self.create({
            "company_id": company.id,
            "date": date or fields.Date.context_today(self),
        })
        doc.action_refill()
        return doc

    def action_compose_today(self):
        """Кнопка списку «Створити на сьогодні»."""
        doc = self.ua_compose(self.env.company)
        return {"type": "ir.actions.act_window", "name": doc.name, "res_model": "ua.hr.doc.check",
                "view_mode": "form", "res_id": doc.id, "target": "current"}

    def action_refill(self):
        """Видалити рядки і заповнити знову: кожен працівник компанії x кожна вимога."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            employees = self.env["hr.employee"].sudo().search(
                [("company_id", "=", doc.company_id.id)], order="name")
            requirements = self.env["ua.hr.doc.requirement"].sudo().search([], order="sequence")
            vals_list = []
            for emp in employees:
                kind = emp.ua_contract_kind or "employment"
                for req in requirements:
                    covered = req._is_covered(emp) if req._applies(kind) else None
                    vals_list.append({
                        "employee_id": emp.id,
                        "employee_name": emp.name or "",
                        "requirement_id": req.id,
                        "requirement_name": req.name or "",
                        "sequence": req.sequence,
                        "source": req.source,
                        "status": "not_needed" if covered is None else ("have" if covered else "missing"),
                    })
            doc.line_ids = [(0, 0, v) for v in vals_list]
        return True

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"
        return True

    def action_draft(self):
        self.state = "draft"

    def matrix(self):
        """Матриця для друку: (працівники, вимоги, {(employee_id, requirement_id): мітка})."""
        self.ensure_one()
        labels = dict(STATUS)
        employees = []
        requirements = []
        cells = {}
        for line in self.line_ids:
            if line.employee_name not in employees:
                employees.append(line.employee_name)
            if line.requirement_name not in requirements:
                requirements.append(line.requirement_name)
            cells[(line.employee_name, line.requirement_name)] = labels.get(line.status, "")
        return {"employees": employees, "requirements": requirements, "cells": cells}

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        if not self.line_ids:
            out.append(self._check_error("Немає рядків", target=self._target_record(self)))
            return out
        out.append(self._check_ok("Працівників у перевірці", fact=self.employee_count))
        missing = self.line_ids.filtered(lambda l: l.status == "missing")
        if missing:
            out.append(self._check_error(
                "Бракує обов'язкових документів", fact=len(missing),
                target=self._target_records(missing, "ua.hr.doc.check.line")))
        else:
            out.append(self._check_ok("Обов'язкові документи зібрано"))
        from_employee = missing.filtered(lambda l: l.source == "employee")
        if from_employee:
            out.append(self._check_warn(
                "Документи від працівника, яких немає", fact=len(from_employee),
                target=self._target_records(from_employee, "ua.hr.doc.check.line")))
        now_missing = self.env["hr.employee"].sudo().search_count(
            [("company_id", "=", self.company_id.id)]) - self.employee_count
        if now_missing > 0:
            out.append(self._check_warn(
                "Працівників додалося після заповнення", fact=now_missing,
                target=self._target_record(self)))
        out.append(self._check_ok("Стан документа", fact=dict(STATES).get(self.state, self.state)))
        return out


class UaHrDocCheckLine(models.Model):
    _name = "ua.hr.doc.check.line"
    _description = "Рядок перевірки документів"
    _order = "employee_name, sequence, id"

    check_id = fields.Many2one("ua.hr.doc.check", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    employee_name = fields.Char("ПІБ")
    requirement_id = fields.Many2one("ua.hr.doc.requirement", "Вимога")
    requirement_name = fields.Char("Документ")
    sequence = fields.Integer("Порядок")
    source = fields.Selection([("employee", "від працівника"), ("company", "від компанії")],
                              string="Джерело")
    status = fields.Selection(STATUS, "Стан", required=True, default="missing")
