# -*- coding: utf-8 -*-
"""Кнопка «Заява-розрахунок ПФУ» на пакеті листків: створює документ (або відкриває чернетку) і показує форму."""
from odoo import models


class HrPayslipRun(models.Model):
    _inherit = "hr.payslip.run"

    def action_ua_pfu_claim(self):
        self.ensure_one()
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", self.id), ("state", "=", "draft")], limit=1)
        if not claim:
            claim = self.env["ua.pfu.claim"].create({"payslip_run_id": self.id, "company_id": self.company_id.id})
            claim.action_refill()
        return {
            "type": "ir.actions.act_window",
            "res_model": "ua.pfu.claim",
            "view_mode": "form",
            "res_id": claim.id,
            "target": "current",
        }
