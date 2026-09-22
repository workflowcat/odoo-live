# -*- coding: utf-8 -*-
"""Рахунок працівника для зарплатної відомості."""
from odoo import models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _ua_payment_bank(self):
        """Банківський рахунок працівника: основний, інакше перший зі списку."""
        self.ensure_one()
        return self.primary_bank_account_id or self.bank_account_ids[:1]

    def _ua_payment_account(self):
        """IBAN працівника рядком."""
        self.ensure_one()
        account = self._ua_payment_bank()
        return account.acc_number if account else ""
