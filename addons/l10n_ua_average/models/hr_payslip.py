import calendar
from datetime import date

from odoo import fields, models


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_average_window(self):
        """12 повних місяців перед місяцем листка."""
        first = self.date_from.replace(day=1)
        return _add_months(first, -12), first  # [start, end)

    def _ua_average_base(self):
        """Сума заробітку і календарні дні розрахункового періоду. Без історії - від окладу (п. 4 Постанови 100)."""
        start, end = self._ua_average_window()
        rows = self.env["ua.earnings.history"].search([("employee_id", "=", self.employee_id.id),
                                                       ("month", ">=", start), ("month", "<", end)])
        if not rows:
            wage = self.contract_id.wage or 0.0
            return wage * 12.0, 365.0
        holidays = self.env["ua.payroll.param"].get("holidays_per_year", self.date_to, self.company_id)
        total = sum(rows.mapped("gross"))
        days = sum(r.calendar_days or calendar.monthrange(r.month.year, r.month.month)[1] for r in rows)
        days -= sum(rows.mapped("excluded_days"))
        days -= holidays * len(rows) / 12.0
        return total, max(days, 1.0)

    def _ua_leave_calendar_days(self):
        """Календарні дні відпусток і лікарняних у періоді листка, з поділом лікарняних на роботодавця (1-5) і ПФУ (6+)."""
        out = {"vac_days": 0, "sick_emp_days": 0, "sick_pfu_days": 0}
        leaves = self.env["hr.leave"].search([("employee_id", "=", self.employee_id.id), ("state", "=", "validate"),
                                              ("request_date_from", "<=", self.date_to), ("request_date_to", ">=", self.date_from)])
        for lv in leaves:
            code = lv.holiday_status_id.work_entry_type_id.code or ""
            start = max(lv.request_date_from, self.date_from)
            end = min(lv.request_date_to, self.date_to)
            if end < start:
                continue
            if code == "VAC":
                out["vac_days"] += (end - start).days + 1
            elif code == "SICK":
                d = start
                while d <= end:
                    idx = (d - lv.request_date_from).days + 1
                    out["sick_emp_days" if idx <= 5 else "sick_pfu_days"] += 1
                    d = fields.Date.add(d, days=1)
        return out

    def _ua_payroll_values(self, contracts):
        res = super()._ua_payroll_values(contracts)
        total, days = self._ua_average_base()
        avg = total / days if days else 0.0
        res.update({
            "avg100_day": avg,          # середня за Постановою 100, грн за календарний день
            "avg1266_day": avg,         # те саме вікно; виключення - через excluded_days
            "sick_percent": self.employee_id.sudo().ua_sick_percent or 50.0,
            **self._ua_leave_calendar_days(),
        })
        return res

    def action_payslip_done(self):
        res = super().action_payslip_done()
        Hist = self.env["ua.earnings.history"]
        for slip in self:
            gross = sum(slip.line_ids.filtered(lambda l: l.category_id.code in ("BASIC", "ALW", "AVG")).mapped("total"))
            month = slip.date_from.replace(day=1)
            row = Hist.search([("employee_id", "=", slip.employee_id.id), ("month", "=", month)], limit=1)
            vals = {"employee_id": slip.employee_id.id, "month": month, "gross": gross, "source": "payslip", "payslip_id": slip.id}
            row.write(vals) if row else Hist.create(vals)
        return res
