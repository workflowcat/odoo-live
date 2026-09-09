# -*- coding: utf-8 -*-
from odoo import fields, models


class UaEmployeeDocument(models.Model):
    _inherit = "ua.employee.document"

    type = fields.Selection(selection_add=[
        ("consent", "Згода на обробку персональних даних"),
        ("safety_briefing", "Інструктаж з охорони праці"),
    ], ondelete={"consent": "set default", "safety_briefing": "set default"})
