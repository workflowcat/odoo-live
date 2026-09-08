"""Штатний розпис на дату і табель обліку робочого часу (типова форма П-5) за місяць."""
import calendar
from datetime import date, timedelta

from odoo import fields, models

DAY_CODES = {"VAC": "В", "SICK": "ТН", "UNPAID": "НА", "MAT": "ВП"}


class UaStaffListWizard(models.TransientModel):
    _name = "ua.staff.list.wizard"
    _description = "Штатний розпис"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    date = fields.Date("На дату", default=fields.Date.today, required=True)
    order_ref = fields.Char("Затверджено наказом (№ і дата)")

    def _rows(self):
        """Рядки: підрозділ, посада, кількість штатних одиниць (сума ставок), оклад, місячний фонд."""
        self.ensure_one()
        versions = self.env["hr.version"].sudo().search([("employee_id.company_id", "=", self.company_id.id), ("contract_date_start", "<=", self.date), ("date_version", "<=", self.date),
                                                          "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", self.date)], order="employee_id, date_version desc")
        seen = set(); rows = {}
        for v in versions:
            if v.employee_id.id in seen:
                continue
            seen.add(v.employee_id.id)
            emp = v.employee_id.sudo()
            if (emp.ua_contract_kind or "employment") != "employment":
                continue
            fte = float(emp.ua_fte or "1")
            key = (v.department_id.name or emp.department_id.name or "-", v.ua_prof_name or v.job_title or emp.job_title or "-", v.ua_kp_code or "", v.wage)
            r = rows.setdefault(key, {"dept": key[0], "job": key[1], "kp": key[2], "wage": v.wage, "units": 0.0, "fund": 0.0})
            r["units"] += fte; r["fund"] += v.wage * fte
        return sorted(rows.values(), key=lambda r: (r["dept"], r["job"]))

    def action_print(self):
        return self.env.ref("l10n_ua_hr_docs.action_report_ua_staff_list").report_action(self)


class UaTimesheetWizard(models.TransientModel):
    _name = "ua.timesheet.wizard"
    _description = "Табель обліку робочого часу (П-5)"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", default=lambda s: date.today().year, required=True)
    month = fields.Integer("Місяць", default=lambda s: date.today().month, required=True)
    department_id = fields.Many2one("hr.department", "Підрозділ (порожньо = усі)")

    def _period(self):
        return date(self.year, self.month, 1), date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    def _rows(self):
        """Для кожного працівника: клітинки за днями (код, години) і підсумки."""
        self.ensure_one()
        d1, d2 = self._period()
        dom = [("company_id", "=", self.company_id.id)]
        if self.department_id:
            dom.append(("department_id", "=", self.department_id.id))
        rows = []
        for emp in self.env["hr.employee"].sudo().search(dom, order="name"):
            if (emp.ua_contract_kind or "employment") != "employment":
                continue
            periods = [(v.contract_date_start, v.contract_date_end or date.max) for v in emp.version_ids if v.contract_date_start]
            if not any(a <= d2 and b >= d1 for a, b in periods):
                continue
            leaves = self.env["hr.leave"].sudo().search([("employee_id", "=", emp.id), ("state", "=", "validate"), ("request_date_from", "<=", d2), ("request_date_to", ">=", d1)])
            hours_day = 8.0 * float(emp.ua_fte or "1")
            cells = []; tot = {"days": 0, "hours": 0.0, "В": 0, "ТН": 0, "НА": 0, "ВП": 0}
            d = d1
            while d <= d2:
                employed = any(a <= d <= b for a, b in periods)
                code, hrs = "", 0.0
                if not employed:
                    code = "-"
                elif d.weekday() >= 5:
                    code = "ВХ"
                else:
                    lv = next((l for l in leaves if l.request_date_from <= d <= l.request_date_to), None)
                    if lv:
                        code = DAY_CODES.get(lv.holiday_status_id.work_entry_type_id.code or "", "І")
                        tot[code] = tot.get(code, 0) + 1
                    else:
                        code, hrs = "Р", hours_day
                        tot["days"] += 1; tot["hours"] += hrs
                cells.append({"day": d.day, "code": code, "hours": hrs, "weekend": d.weekday() >= 5})
                d += timedelta(days=1)
            rows.append({"emp": emp, "cells": cells, "tot": tot})
        return rows

    def action_print(self):
        return self.env.ref("l10n_ua_hr_docs.action_report_ua_timesheet").report_action(self)
