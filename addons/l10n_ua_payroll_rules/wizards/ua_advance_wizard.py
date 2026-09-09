"""Аванс за першу половину місяця: створює (або відкриває чинну чернетку) авансову відомість."""
from datetime import date

from odoo import fields, models


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
        Sheet = self.env["ua.advance.sheet"]
        sheet = Sheet.search([("company_id", "=", self.company_id.id), ("year", "=", self.year),
                              ("month", "=", self.month), ("state", "=", "draft")], limit=1)
        if sheet:
            sheet.write({"percent": self.percent, "pay_date": self.pay_date})
        else:
            sheet = Sheet.create({"company_id": self.company_id.id, "year": self.year, "month": self.month,
                                  "percent": self.percent, "pay_date": self.pay_date})
        sheet.action_refill()
        return {"type": "ir.actions.act_window", "name": sheet.name, "res_model": "ua.advance.sheet",
                "view_mode": "form", "res_id": sheet.id, "target": "current"}
