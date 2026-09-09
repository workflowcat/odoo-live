# -*- coding: utf-8 -*-
"""Обов'язковий пакет документів на працівника: настроювані вимоги і перевірка покриття
наявними ua.employee.document (за кодом типу) або наказами (наказ про прийняття)."""
from odoo import fields, models

APPLIES_TO = [
    ("employment", "трудовий договір"),
    ("gph", "договір ЦПХ"),
    ("fop", "ФОП"),
    ("all", "усі"),
]
MIL_LIABLE = ("conscript", "liable", "reserve")


class UaHrDocRequirement(models.Model):
    _name = "ua.hr.doc.requirement"
    _description = "Обов'язковий документ у пакеті працівника"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    applies_to = fields.Selection(APPLIES_TO, default="all", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    def _applies(self, kind):
        """kind: ua_contract_kind працівника (employment/gph/fop)."""
        self.ensure_one()
        return self.applies_to == "all" or self.applies_to == kind or (self.code == "gph_contract" and kind == "fop")

    def _is_covered(self, employee):
        """True/False - покрито чи ні; None - вимога не застосовна до цього працівника (н/п)."""
        self.ensure_one()
        emp = employee.sudo()
        if self.code == "military_id" and emp.ua_mil_status not in MIL_LIABLE:
            return None
        if self.code == "hire_order":
            return bool(self.env["ua.hr.order"].sudo().search_count([
                ("employee_id", "=", emp.id), ("order_type", "=", "hire"), ("state", "in", ("posted", "acknowledged")),
            ]))
        if self.code == "passport_rnokpp":
            types = emp.ua_document_ids.mapped("type")
            return "passport" in types and "rnokpp" in types
        return self.code in emp.ua_document_ids.mapped("type")
