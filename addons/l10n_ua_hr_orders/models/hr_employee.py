# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


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

    def action_ua_print_last_order(self):
        """Друк останнього проведеного наказу працівника (будь-якого виду). Якщо наказу в реєстрі
        немає (працівника перенесено з історії), друкує застарілою формою l10n_ua_hr_docs."""
        self.ensure_one()
        version = self.sudo().current_version_id
        if not version:
            raise UserError("У працівника немає жодної версії контракту.")
        order = self.env["ua.hr.order"].search(
            [("employee_id", "=", self.id), ("state", "in", ("posted", "acknowledged"))],
            limit=1, order="date desc, id desc")
        if order:
            return self.env.ref("l10n_ua_hr_orders.action_report_ua_hr_order").report_action(order)
        is_dismissal = bool(version.contract_date_end and version.ua_end_order_ref)
        xmlid = ("l10n_ua_hr_docs.action_report_ua_order_dismiss" if is_dismissal
                 else "l10n_ua_hr_docs.action_report_ua_order_hire")
        report = self.env.ref(xmlid, raise_if_not_found=False)
        if not report:
            raise UserError("Модуль наказів (l10n_ua_hr_docs) не встановлено.")
        return report.report_action(self)
