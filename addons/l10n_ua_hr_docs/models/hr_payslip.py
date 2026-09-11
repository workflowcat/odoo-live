# -*- coding: utf-8 -*-
"""Затверджений табель - джерело відпрацьованого часу для розрахункового листка.

Без табеля листок рахує дні за графіком, як раніше. Коли за місяць є затверджений табель,
дні і години у листку беруться з нього, а оклад рахується пропорційно: за годинами, якщо
заповнені норма і факт годин, інакше за днями.

Так бухгалтер виправляє час в одному місці - у табелі - і натискає «Перерахувати листки».
"""
from odoo import models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_timesheet_line(self):
        """Рядок затвердженого табеля за місяць листка, якщо він є."""
        self.ensure_one()
        if not self.employee_id or not self.date_from:
            return None
        line = self.env["ua.timesheet.line"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("sheet_id.state", "=", "confirmed"),
            ("sheet_id.year", "=", self.date_from.year),
            ("sheet_id.month", "=", self.date_from.month),
            ("sheet_id.company_id", "=", self.company_id.id),
        ], limit=1)
        return line or None

    def get_worked_day_lines(self, contracts, date_from, date_to):
        """Дні і години WORK100 з табеля. Дні відсутності лишаються окремими рядками,
        тому у WORK100 тримаємо суму «факт + відсутності», як це робить рушій OCA."""
        res = super().get_worked_day_lines(contracts, date_from, date_to)
        line = self._ua_timesheet_line()
        if not line:
            return res
        absent_days = line.days_vac + line.days_sick + line.days_unpaid + line.days_mat
        hours_day = line.hours_day or (line.norm_hours / line.norm_days if line.norm_days else 8.0)
        for vals in res:
            if vals.get("code") == "WORK100":
                vals["number_of_days"] = line.days_worked + absent_days
                vals["number_of_hours"] = line.hours + absent_days * hours_day
        return res

    def compute_sheet(self):
        """Перед розрахунком оновлюємо відпрацьований час із затвердженого табеля.

        OCA рахує рядки листка, але не переписує «Відпрацьовано», тому робимо це самі:
        інакше у друкованому листку лишилися б дні за графіком, а сума - за табелем.
        """
        for slip in self:
            if not slip._ua_timesheet_line():
                continue
            contracts = slip._get_employee_contracts()
            if not contracts:
                continue
            worked = slip.get_worked_day_lines(contracts, slip.date_from, slip.date_to)
            slip.worked_days_line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in worked]
        return super().compute_sheet()

    def _ua_payroll_values(self, contracts):
        values = super()._ua_payroll_values(contracts)
        line = self._ua_timesheet_line()
        ratio = -1.0
        if line:
            # норма годин у графіку - на повну ставку; очікувані години працівника меншають разом зі ставкою
            fte = values.get("fte") or 1.0
            expected_hours = line.norm_hours * fte
            if expected_hours and line.hours:
                ratio = line.hours / expected_hours
            elif line.norm_days:
                ratio = line.days_worked / line.norm_days
            ratio = min(max(ratio, 0.0), 1.0) if ratio >= 0 else -1.0
        values["time_ratio"] = ratio
        return values
