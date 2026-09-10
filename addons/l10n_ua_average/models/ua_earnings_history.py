import calendar

from odoo import api, fields, models


class UaEarningsHistory(models.Model):
    """Заробіток за місяць для розрахунку середньої. Заповнюється з проведених листків або вручну (вхідні залишки)."""
    _name = "ua.earnings.history"
    _description = "Історія заробітку (для середньої)"
    _order = "employee_id, month desc"

    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, index=True, ondelete="cascade")
    month = fields.Date("Місяць", required=True, help="Перше число місяця")
    gross = fields.Float("Заробіток у розрахунку", digits="Payroll", required=True,
                         help="Нарахування, що входять до середньої: оклад, доплати, премії, відпускні, лікарняні")
    calendar_days = fields.Integer("Календарних днів", help="Днів місяця в розрахунковому періоді")
    excluded_days = fields.Integer("Виключені дні", default=0,
                                   help="Дні, не відпрацьовані з поважних причин (без збереження зарплати тощо)")
    source = fields.Selection([("manual", "вручну"), ("payslip", "з листка")], "Джерело", default="manual", required=True)
    payslip_id = fields.Many2one("hr.payslip", "Листок", ondelete="set null")

    _sql_constraints = [("emp_month_uniq", "unique(employee_id, month)", "Один рядок на місяць для працівника.")]

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get("month"):
                d = fields.Date.to_date(v["month"])
                v["month"] = d.replace(day=1)
                if not v.get("calendar_days"):
                    v["calendar_days"] = calendar.monthrange(d.year, d.month)[1]
        return super().create(vals_list)
