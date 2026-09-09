# -*- coding: utf-8 -*-
"""Майстри друку: «Журнал реєстрації наказів» (за реєстром і роком) і «Пакет документів»
(матриця документ x працівник). Обидва просто відкривають звіт QWeb на собі самих (без
проміжного персистентного документа)."""
from datetime import date

from odoo import fields, models

REGISTERS = [
    ("k1", "К-1, кадрові, 75 років"),
    ("v2", "В-2, відпустки і відрядження, 5 років"),
]


class UaHrOrderRegisterWizard(models.TransientModel):
    _name = "ua.hr.order.register.wizard"
    _description = "Журнал реєстрації наказів"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    year = fields.Integer(default=lambda s: date.today().year, required=True)
    register = fields.Selection(REGISTERS, default="k1", required=True)

    def action_print(self):
        self.ensure_one()
        return self.env.ref("l10n_ua_hr_orders.action_report_ua_hr_order_register").report_action(self)


class UaHrDocPackWizard(models.TransientModel):
    _name = "ua.hr.doc.pack.wizard"
    _description = "Пакет документів"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    employee_ids = fields.Many2many("hr.employee", string="Працівники",
                                    default=lambda s: s.env["hr.employee"].search([("company_id", "=", s.env.company.id)]))

    def action_print(self):
        self.ensure_one()
        return self.env.ref("l10n_ua_hr_orders.action_report_ua_hr_doc_pack").report_action(self)
