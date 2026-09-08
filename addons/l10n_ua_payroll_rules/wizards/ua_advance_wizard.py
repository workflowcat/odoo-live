"""Аванс за першу половину місяця: заповнює вхід ADVANCE у листках місяця і показує відомість авансу."""
import calendar
from datetime import date, timedelta

from odoo import fields, models
from odoo.exceptions import UserError


class UaPayrollAdvanceWizard(models.TransientModel):
    _name = "ua.payroll.advance.wizard"
    _description = "Аванс за місяць"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", default=lambda s: date.today().year, required=True)
    month = fields.Integer("Місяць", default=lambda s: date.today().month, required=True)
    percent = fields.Float("Відсоток окладу", default=50.0, required=True,
                           help="Аванс не менший за оплату фактично відпрацьованого часу першої половини місяця (ст. 115 КЗпП); типово 50 %")
    pay_date = fields.Date("Дата виплати", required=True, default=lambda s: date.today().replace(day=20),
                           help="Типово 20-те число; якщо вихідний, платити напередодні")

    @staticmethod
    def _workdays(a, b):
        """Робочі дні (пн-пт) у проміжку [a, b]; під час воєнного стану святкових днів немає."""
        return sum(1 for i in range((b - a).days + 1) if (a + timedelta(days=i)).weekday() < 5) if b >= a else 0

    def _first_half_ratio(self, slip, h1, h2):
        """Частка відпрацьованих робочих днів першої половини місяця (ст. 115 КЗпП: аванс за фактично відпрацьований час)."""
        v = slip.contract_id.sudo()
        a = max(h1, v.contract_date_start) if v.contract_date_start else h1
        b = min(h2, v.contract_date_end) if v.contract_date_end else h2
        total = self._workdays(h1, h2)
        worked = self._workdays(a, b)
        leaves = self.env["hr.leave"].sudo().search([("employee_id", "=", slip.employee_id.id), ("state", "=", "validate"),
                                                     ("date_from", "<=", fields.Datetime.to_datetime(h2) + timedelta(days=1)), ("date_to", ">=", fields.Datetime.to_datetime(h1))])
        for lv in leaves:
            la = max(a, lv.date_from.date()); lb = min(b, lv.date_to.date())
            worked -= self._workdays(la, lb)
        return max(worked, 0) / total if total else 0.0

    def action_fill(self):
        self.ensure_one()
        d1 = date(self.year, self.month, 1); d2 = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        h1, h2 = d1, date(self.year, self.month, 15)
        slips = self.env["hr.payslip"].search([("company_id", "=", self.company_id.id), ("state", "in", ("draft", "verify")),
                                               ("date_from", ">=", d1), ("date_to", "<=", d2)])
        if not slips:
            raise UserError("Немає чернеток листків за цей місяць. Створіть пакет листків, потім рахуйте аванс.")
        Input = self.env["hr.payslip.input"]
        for slip in slips:
            emp = slip.employee_id.sudo()
            if (emp.ua_contract_kind or "employment") != "employment":
                continue
            wage = slip.contract_id.wage or 0.0
            amount = round(wage * float(emp.ua_fte or "1") * self.percent / 100.0 * self._first_half_ratio(slip, h1, h2), 2)
            line = slip.input_line_ids.filtered(lambda l: l.code == "ADVANCE")[:1]
            if not amount:
                line.unlink()
                slip.compute_sheet()
                continue
            if line:
                line.amount = amount
            else:
                Input.create({"payslip_id": slip.id, "code": "ADVANCE", "name": "Аванс (виплачено)", "amount": amount,
                              "contract_id": slip.contract_id.id, "sequence": 5})
            slip.compute_sheet()
        return {"type": "ir.actions.act_window", "name": f"Відомість авансу {self.month:02d}.{self.year}", "res_model": "hr.payslip.input",
                "view_mode": "list", "domain": [("code", "=", "ADVANCE"), ("payslip_id", "in", slips.ids)],
                "context": {"ua_pay_date": str(self.pay_date)}}
