# -*- coding: utf-8 -*-
"""Табель обліку робочого часу (типова форма П-5): документ з рядками, станом і друком."""
import calendar
from datetime import date, datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

DAY_CODES = {"VAC": "В", "SICK": "ТН", "UNPAID": "НА", "MAT": "ВП", "STUDY": "Н", "CHILD_VAC": "Д",
             "TRIP": "ВД", "CHILD3": "ДД", "SICK_CARE": "ТН"}
STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]


class UaTimesheetSheet(models.Model):
    _name = "ua.timesheet.sheet"
    _inherit = ["mail.thread"]
    _description = "Табель обліку робочого часу"
    _order = "year desc, month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", default=lambda s: date.today().year, required=True, tracking=True)
    month = fields.Integer("Місяць", default=lambda s: date.today().month, required=True, tracking=True)
    department_id = fields.Many2one("hr.department", "Підрозділ", tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.timesheet.line", "sheet_id", "Рядки")

    @api.depends("year", "month", "department_id.name")
    def _compute_name(self):
        for doc in self:
            name = "Табель %02d.%d" % (doc.month, doc.year) if doc.month and doc.year else "Табель"
            if doc.department_id:
                name = "%s, %s" % (name, doc.department_id.name)
            doc.name = name

    def _period(self):
        """Перший і останній день місяця табеля."""
        self.ensure_one()
        d1 = date(self.year, self.month, 1)
        d2 = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        return d1, d2

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку табеля.")

    def action_refill(self):
        """Видалити рядки і заповнити знову: працівник за день - код (Р, ВХ, В, ТН, НА, ВП, «-»)."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            d1, d2 = doc._period()
            dom = [("company_id", "=", doc.company_id.id)]
            if doc.department_id:
                dom.append(("department_id", "=", doc.department_id.id))
            vals_list = []
            for emp in self.env["hr.employee"].sudo().search(dom, order="name"):
                if (emp.ua_contract_kind or "employment") != "employment":
                    continue
                periods = [(v.contract_date_start, v.contract_date_end or date.max) for v in emp.version_ids if v.contract_date_start]
                if not any(a <= d2 and b >= d1 for a, b in periods):
                    continue
                leaves = self.env["hr.leave"].sudo().search([("employee_id", "=", emp.id), ("state", "=", "validate"), ("request_date_from", "<=", d2), ("request_date_to", ">=", d1)])
                hours_day = 8.0 * float(emp.ua_fte or "1")
                vals = {"employee_id": emp.id, "job_title": emp.job_title or "", "tab_number": str(emp.id), "hours_day": hours_day}
                d = d1
                idx = 1
                while d <= d2:
                    employed = any(a <= d <= b for a, b in periods)
                    if not employed:
                        code = "-"
                    elif d.weekday() >= 5:
                        code = "ВХ"
                    else:
                        lv = next((l for l in leaves if l.request_date_from <= d <= l.request_date_to), None)
                        code = DAY_CODES.get(lv.holiday_status_id.work_entry_type_id.code or "", "І") if lv else "Р"
                    vals["d%02d" % idx] = code
                    d += timedelta(days=1)
                    idx += 1
                vals_list.append(vals)
            doc.line_ids = [(0, 0, v) for v in vals_list]
        return True

    def action_recompute_payslips(self):
        """Перерахувати чернетки листків періоду за виправленим табелем."""
        self.ensure_one()
        if self.state != "confirmed":
            raise UserError("Спершу затвердьте табель: листки беруть години лише із затвердженого табеля.")
        d1, d2 = self._period()
        employees = self.line_ids.mapped("employee_id")
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", self.company_id.id), ("employee_id", "in", employees.ids),
            ("date_from", ">=", d1), ("date_to", "<=", d2), ("state", "in", ("draft", "verify")),
        ])
        if not slips:
            raise UserError("За цей місяць немає чернеток розрахункових листків.")
        slips.compute_sheet()
        self.message_post(body="Перераховано листків: %s." % len(slips))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "Табель", "message": "Перераховано листків: %s." % len(slips),
                       "type": "success", "sticky": False},
        }

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"


class UaTimesheetLine(models.Model):
    _name = "ua.timesheet.line"
    _description = "Рядок табеля обліку робочого часу"
    _order = "id"

    sheet_id = fields.Many2one("ua.timesheet.sheet", "Табель", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    job_title = fields.Char("Посада")
    tab_number = fields.Char("Таб. №")
    hours_day = fields.Float("Годин на день")
    d01 = fields.Char(size=3)
    d02 = fields.Char(size=3)
    d03 = fields.Char(size=3)
    d04 = fields.Char(size=3)
    d05 = fields.Char(size=3)
    d06 = fields.Char(size=3)
    d07 = fields.Char(size=3)
    d08 = fields.Char(size=3)
    d09 = fields.Char(size=3)
    d10 = fields.Char(size=3)
    d11 = fields.Char(size=3)
    d12 = fields.Char(size=3)
    d13 = fields.Char(size=3)
    d14 = fields.Char(size=3)
    d15 = fields.Char(size=3)
    d16 = fields.Char(size=3)
    d17 = fields.Char(size=3)
    d18 = fields.Char(size=3)
    d19 = fields.Char(size=3)
    d20 = fields.Char(size=3)
    d21 = fields.Char(size=3)
    d22 = fields.Char(size=3)
    d23 = fields.Char(size=3)
    d24 = fields.Char(size=3)
    d25 = fields.Char(size=3)
    d26 = fields.Char(size=3)
    d27 = fields.Char(size=3)
    d28 = fields.Char(size=3)
    d29 = fields.Char(size=3)
    d30 = fields.Char(size=3)
    d31 = fields.Char(size=3)
    days_worked = fields.Float("Факт днів", compute="_compute_totals", store=True, readonly=False,
                               help="Рахується з днів табеля. Бухгалтер може виправити - виправлення залишиться, "
                                    "поки не змінити дні в сітці.")
    hours = fields.Float("Факт годин", compute="_compute_totals", store=True, readonly=False,
                         help="Години за місяць. Якщо заповнено разом із нормою, оклад рахується за годинами.")
    norm_days = fields.Float("Норма днів", compute="_compute_norm", store=True)
    norm_hours = fields.Float("Норма годин", compute="_compute_norm", store=True)
    diff_days = fields.Float("Відхилення, днів", compute="_compute_norm", store=True,
                             help="Факт плюс дні відсутності мінус норма місяця.")
    days_vac = fields.Integer("В", compute="_compute_totals", store=True)
    days_sick = fields.Integer("ТН", compute="_compute_totals", store=True)
    days_unpaid = fields.Integer("НА", compute="_compute_totals", store=True)
    days_mat = fields.Integer("ВП", compute="_compute_totals", store=True)
    note = fields.Char("Примітка")

    @api.depends("employee_id", "sheet_id.year", "sheet_id.month", "days_worked",
                 "days_vac", "days_sick", "days_unpaid", "days_mat")
    def _compute_norm(self):
        """Норма місяця за графіком працівника: скільки днів і годин мав відпрацювати."""
        for line in self:
            sheet = line.sheet_id
            days = hours = 0.0
            if sheet and sheet.year and sheet.month and line.employee_id:
                d1, d2 = sheet._period()
                calendar_rec = (line.employee_id.sudo().resource_calendar_id
                                or sheet.company_id.resource_calendar_id)
                if calendar_rec:
                    data = calendar_rec.get_work_duration_data(
                        datetime.combine(d1, time.min), datetime.combine(d2, time.max), compute_leaves=False)
                    days, hours = data.get("days", 0.0), data.get("hours", 0.0)
            line.norm_days = days
            line.norm_hours = hours
            absent = line.days_vac + line.days_sick + line.days_unpaid + line.days_mat
            line.diff_days = round(line.days_worked + absent - days, 2)

    def _day_cells(self, last_day=31):
        """Список кодів днів 1..last_day (для звіту, без getattr - через __getitem__)."""
        self.ensure_one()
        return [self["d%02d" % i] or "" for i in range(1, last_day + 1)]

    @api.depends("d01", "d02", "d03", "d04", "d05", "d06", "d07", "d08", "d09", "d10", "d11", "d12", "d13", "d14", "d15", "d16",
                 "d17", "d18", "d19", "d20", "d21", "d22", "d23", "d24", "d25", "d26", "d27", "d28", "d29", "d30", "d31", "hours_day")
    def _compute_totals(self):
        for line in self:
            codes = line._day_cells()
            line.days_worked = codes.count("Р")
            line.hours = line.days_worked * line.hours_day
            line.days_vac = codes.count("В")
            line.days_sick = codes.count("ТН")
            line.days_unpaid = codes.count("НА")
            line.days_mat = codes.count("ВП")
