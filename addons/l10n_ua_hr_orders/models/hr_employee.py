# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_doc_missing_ids = fields.Many2many("ua.hr.doc.requirement", compute="_compute_ua_doc_missing",
                                          string="Відсутні документи", groups="hr.group_hr_user")
    ua_doc_missing_count = fields.Integer("Відсутніх документів", compute="_compute_ua_doc_missing",
                                          store=False, groups="hr.group_hr_user")

    @api.depends("ua_document_ids.type", "ua_contract_kind", "ua_mil_status")
    def _compute_ua_doc_missing(self):
        reqs = self.env["ua.hr.doc.requirement"].sudo().search([])
        for emp in self:
            kind = emp.ua_contract_kind or "employment"
            missing = self.env["ua.hr.doc.requirement"]
            for req in reqs.filtered(lambda r, k=kind: r._applies(k)):
                if req._is_covered(emp) is False:
                    missing |= req
            emp.ua_doc_missing_ids = missing
            emp.ua_doc_missing_count = len(missing)
