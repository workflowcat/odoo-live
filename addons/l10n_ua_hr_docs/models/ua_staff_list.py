# -*- coding: utf-8 -*-
"""Штатний розпис на дату: документ з рядками (підрозділ, посада, ставки, оклад, фонд)."""
from odoo import api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]


class UaStaffList(models.Model):
    _name = "ua.staff.list"
    _inherit = ["mail.thread"]
    _description = "Штатний розпис"
    _order = "date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("На дату", default=fields.Date.today, required=True, tracking=True)
    order_ref = fields.Char("Затверджено наказом", tracking=True)
    state = fields.Selection(STATES, default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.staff.list.line", "list_id", "Рядки")
    total_units = fields.Float("Штатних одиниць, разом", compute="_compute_totals", store=True)
    total_fund = fields.Monetary("Місячний фонд, разом", compute="_compute_totals", store=True)

    @api.depends("date")
    def _compute_name(self):
        for doc in self:
            doc.name = "Штатний розпис на %s" % (doc.date.strftime("%d.%m.%Y") if doc.date else "")

    @api.depends("line_ids.units", "line_ids.fund")
    def _compute_totals(self):
        for doc in self:
            doc.total_units = sum(doc.line_ids.mapped("units"))
            doc.total_fund = sum(doc.line_ids.mapped("fund"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку штатного розпису.")

    def action_refill(self):
        """Видалити рядки і заповнити знову: підрозділ / посада / код КП / оклад -> сума ставок і фонд."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            versions = self.env["hr.version"].sudo().search([
                ("employee_id.company_id", "=", doc.company_id.id),
                ("contract_date_start", "<=", doc.date), ("date_version", "<=", doc.date),
                "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", doc.date),
            ], order="employee_id, date_version desc")
            seen = set()
            rows = {}
            for v in versions:
                if v.employee_id.id in seen:
                    continue
                seen.add(v.employee_id.id)
                emp = v.employee_id.sudo()
                if (emp.ua_contract_kind or "employment") != "employment":
                    continue
                fte = float(emp.ua_fte or "1")
                dept = v.department_id or emp.department_id
                job = v.ua_prof_name or v.job_title or emp.job_title or "-"
                key = (dept.id, job, v.ua_kp_code or "", v.wage)
                r = rows.setdefault(key, {"department_id": dept.id, "department_name": dept.name or "-", "job_title": job, "kp_code": v.ua_kp_code or "", "wage": v.wage, "units": 0.0})
                r["units"] += fte
            vals_list = sorted(rows.values(), key=lambda r: (r["department_name"], r["job_title"]))
            doc.line_ids = [(0, 0, {"department_id": r["department_id"], "job_title": r["job_title"], "kp_code": r["kp_code"], "wage": r["wage"], "units": r["units"]}) for r in vals_list]
        return True

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"


class UaStaffListLine(models.Model):
    _name = "ua.staff.list.line"
    _description = "Рядок штатного розпису"
    _order = "department_id, job_title"

    list_id = fields.Many2one("ua.staff.list", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="list_id.currency_id")
    department_id = fields.Many2one("hr.department", "Підрозділ")
    job_title = fields.Char("Посада", required=True)
    kp_code = fields.Char("Код КП")
    units = fields.Float("Штатних одиниць")
    wage = fields.Monetary("Оклад")
    fund = fields.Monetary("Місячний фонд", compute="_compute_fund", store=True)
    note = fields.Char("Примітка")

    @api.depends("units", "wage")
    def _compute_fund(self):
        for line in self:
            line.fund = line.units * line.wage
