# -*- coding: utf-8 -*-
"""Прийняття, звільнення і повторне прийняття міняють відпрацьований час, а з ним і нарахування
щорічної відпустки. Тому зміна дат контракту одразу перевиписує нарахування працівника."""
from odoo import api, models

CONTRACT_DATE_FIELDS = {"contract_date_start", "contract_date_end", "employee_id"}


class HrVersion(models.Model):
    _inherit = "hr.version"

    def _ua_refresh_leave_allocations(self):
        employees = self.mapped("employee_id").filtered("active")
        if employees:
            employees.sudo().with_context(ua_skip_leave_allocations=True)._ua_ensure_leave_allocations()

    def write(self, vals):
        res = super().write(vals)
        if CONTRACT_DATE_FIELDS & set(vals) and not self.env.context.get("ua_skip_leave_allocations"):
            self._ua_refresh_leave_allocations()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        versions = super().create(vals_list)
        if not self.env.context.get("ua_skip_leave_allocations"):
            versions._ua_refresh_leave_allocations()
        return versions
