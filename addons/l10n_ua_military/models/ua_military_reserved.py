# -*- coding: utf-8 -*-
"""Список заброньованих на дату: документ з рядками по кожному із ua_mil_reserved."""
from datetime import date as date_type, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]


def _month_end(year, month):
    """Останній день місяця."""
    return date_type(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)


class UaMilitaryReserved(models.Model):
    _name = "ua.military.reserved"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Список заброньованих"
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=lambda s: fields.Date.context_today(s), required=True, tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
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

    @api.model
    def ua_compose(self, company, year=None, month=None, date=None, **params):
        """Новий список заброньованих на дату, одразу заповнений.

        Дата - явна, якщо її передали, інакше останній день місяця («Папери» складають
        список періоду). Що в список входить - питання до самого списку, не до екрана."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        if not date:
            date = (_month_end(int(year), int(month)) if year and month
                    else fields.Date.context_today(self))
        doc = self.create({"company_id": company.id, "date": date})
        doc.action_refill()
        return doc

    def action_refill(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            employees = self.env["hr.employee"].sudo().search([
                ("company_id", "=", doc.company_id.id), ("ua_mil_reserved", "=", True),
                ("ua_contract_kind", "not in", ["gph", "fop"]),
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

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        expected = self.env["hr.employee"].sudo().search([
            ("company_id", "=", self.company_id.id), ("ua_mil_reserved", "=", True),
            ("ua_contract_kind", "not in", ["gph", "fop"])])
        have = self.line_ids.mapped("employee_id")
        missing = expected - have
        if missing:
            out.append(self._check_error(
                "Заброньований працівник відсутній у списку", fact=len(missing),
                target=self._target_records(missing, "hr.employee")))
        else:
            out.append(self._check_ok("Усі заброньовані працівники у списку", fact=len(have)))
        no_order = self.line_ids.filtered(lambda l: not l.reserve_order)
        if no_order:
            out.append(self._check_error(
                "Рядки без підстави бронювання", fact=len(no_order),
                target=self._target_records(no_order, "ua.military.reserved.line")))
        expired = self.line_ids.filtered(lambda l: l.reserve_until and l.days_left is not False and l.days_left < 0)
        if expired:
            out.append(self._check_error(
                "Бронювання прострочене", fact=len(expired),
                target=self._target_records(expired, "ua.military.reserved.line")))
        soon = self.line_ids.filtered(lambda l: l.days_left is not False and 0 <= l.days_left <= 14)
        if soon:
            out.append(self._check_warn(
                "Бронювання закінчується протягом 14 днів", fact=len(soon),
                target=self._target_records(soon, "ua.military.reserved.line")))
        out.append(self._check_ok("Стан документа", fact=dict(STATES).get(self.state, self.state)))
        return out


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
