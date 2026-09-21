# -*- coding: utf-8 -*-
"""Дата впровадження обліку відпусток у компанії - підстава нарахувань усіх працівників,
у яких своєї дати немає. Змінили її - нарахування треба виписати заново, інакше залишки
лишаться від старої дати."""
from odoo import models


class ResCompany(models.Model):
    _inherit = "res.company"

    def write(self, vals):
        res = super().write(vals)
        if "ua_vacation_opening_date" in vals and not self.env.context.get("ua_skip_leave_allocations"):
            employees = self.env["hr.employee"].sudo().search([("company_id", "in", self.ids)])
            employees.with_context(ua_skip_leave_allocations=True)._ua_ensure_leave_allocations()
        return res
