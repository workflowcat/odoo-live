# -*- coding: utf-8 -*-
"""Рахунок працівника для зарплатної відомості."""
from odoo import models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _ua_payment_account(self):
        """IBAN працівника: основний рахунок, інакше перший зі списку."""
        self.ensure_one()
        account = self.primary_bank_account_id or self.bank_account_ids[:1]
        return account.acc_number if account else ""
