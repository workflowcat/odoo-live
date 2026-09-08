"""Аванс за першу половину місяця: заповнює вхід ADVANCE у листках місяця і показує відомість авансу."""
import calendar
from datetime import date

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

    def action_fill(self):
        self.ensure_one()
        d1 = date(self.year, self.month, 1); d2 = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
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
            amount = round(wage * float(emp.ua_fte or "1") * self.percent / 100.0, 2)
            line = slip.input_line_ids.filtered(lambda l: l.code == "ADVANCE")[:1]
            if line:
                line.amount = amount
            else:
                Input.create({"payslip_id": slip.id, "code": "ADVANCE", "name": "Аванс (виплачено)", "amount": amount,
                              "contract_id": slip.contract_id.id, "sequence": 5})
            slip.compute_sheet()
        return {"type": "ir.actions.act_window", "name": f"Відомість авансу {self.month:02d}.{self.year}", "res_model": "hr.payslip.input",
                "view_mode": "list", "domain": [("code", "=", "ADVANCE"), ("payslip_id", "in", slips.ids)],
                "context": {"ua_pay_date": str(self.pay_date)}}
