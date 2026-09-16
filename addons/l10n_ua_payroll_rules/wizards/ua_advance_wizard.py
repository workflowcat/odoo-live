"""Аванс за першу половину місяця: створює (або відкриває чинну чернетку) авансову відомість."""
from datetime import date

from odoo import fields, models


class UaPayrollAdvanceWizard(models.TransientModel):
    _name = "ua.payroll.advance.wizard"
    _description = "Аванс за місяць"

    def _default_percent(self):
        return self.env.company._ua_pay_terms()["advance_percent"]

    def _default_pay_date(self):
        day = self.env.company._ua_pay_terms()["advance_day"] or 20
        return date.today().replace(day=min(day, 28))

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", default=lambda s: date.today().year, required=True)
    month = fields.Integer("Місяць", default=lambda s: date.today().month, required=True)
    percent = fields.Float("Відсоток окладу", default=_default_percent, required=True,
                           help="Аванс не менший за оплату фактично відпрацьованого часу до дня авансу (ст. 115 КЗпП); типово 50 %, читає res.company.ua_advance_percent")
    pay_date = fields.Date("Дата виплати", required=True, default=_default_pay_date,
                           help="Типово день авансу компанії (res.company.ua_advance_day); якщо вихідний, платити напередодні")

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
