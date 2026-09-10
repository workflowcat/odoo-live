# -*- coding: utf-8 -*-
"""Заява-розрахунок до ПФУ: фінансування допомоги по тимчасовій непрацездатності та вагітності/пологах за пакетом листків."""
from odoo import api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]
# (код рядка листка, код виду відпустки, kind рядка заяви, назва)
SOURCES = [("SICK_PFU", "SICK", "sick", "Тимчасова непрацездатність"), ("MAT", "MAT", "mat", "Вагітність та пологи")]


class UaPfuClaim(models.Model):
    _name = "ua.pfu.claim"
    _inherit = ["mail.thread"]
    _description = "Заява-розрахунок до ПФУ"
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    payslip_run_id = fields.Many2one("hr.payslip.run", "Пакет листків", required=True, tracking=True)
    date = fields.Date("Дата", default=fields.Date.today, required=True, tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.pfu.claim.line", "claim_id", "Рядки")
    total = fields.Monetary("Разом", compute="_compute_total", store=True)

    @api.depends("payslip_run_id.date_start")
    def _compute_name(self):
        for doc in self:
            d = doc.payslip_run_id.date_start
            doc.name = "Заява-розрахунок ПФУ %02d.%d" % (d.month, d.year) if d else "Заява-розрахунок ПФУ"

    @api.depends("line_ids.amount")
    def _compute_total(self):
        for doc in self:
            doc.total = sum(doc.line_ids.mapped("amount"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку заяви-розрахунку.")

    def action_refill(self):
        """Видалити рядки і заповнити знову: рядки SICK_PFU і MAT листків пакета, відпустка з номером е-ЛН, дні з _ua_leave_calendar_days()."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            vals_list = []
            for slip in doc.payslip_run_id.slip_ids.sorted(lambda s: s.employee_id.name):
                emp = slip.employee_id.sudo()
                for code, leave_code, kind, _label in SOURCES:
                    amount = sum(slip.line_ids.filtered(lambda l: l.code == code).mapped("total"))
                    if not amount:
                        continue
                    lv = self.env["hr.leave"].sudo().search([
                        ("employee_id", "=", emp.id), ("state", "=", "validate"),
                        ("holiday_status_id.work_entry_type_id.code", "=", leave_code),
                        ("request_date_from", "<=", slip.date_to), ("request_date_to", ">=", slip.date_from),
                    ], limit=1)
                    days = slip._ua_leave_calendar_days()
                    nd = days.get("mat_days" if code == "MAT" else "sick_pfu_days", 0)
                    percent = 100.0 if code == "MAT" else (emp.ua_sick_percent or 100.0)
                    avg_day = (amount / nd / (percent / 100.0)) if nd else 0.0
                    vals_list.append({
                        "employee_id": emp.id, "kind": kind,
                        "sick_number": lv.ua_sick_number if lv else False,
                        "date_from": lv.request_date_from if lv else False,
                        "date_to": lv.request_date_to if lv else False,
                        "days": nd, "avg_day": avg_day, "percent": percent, "amount": amount,
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


class UaPfuClaimLine(models.Model):
    _name = "ua.pfu.claim.line"
    _description = "Рядок заяви-розрахунку до ПФУ"
    _order = "id"

    claim_id = fields.Many2one("ua.pfu.claim", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="claim_id.currency_id")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    kind = fields.Selection([("sick", "Тимчасова непрацездатність"), ("mat", "Вагітність та пологи")], "Вид", required=True)
    sick_number = fields.Char("№ е-ЛН")
    date_from = fields.Date("Від")
    date_to = fields.Date("До")
    days = fields.Integer("Днів за рахунок ПФУ")
    avg_day = fields.Float("Середньоденна")
    percent = fields.Float("%")
    amount = fields.Monetary("Сума")
    note = fields.Char("Примітка")
