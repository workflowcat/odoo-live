# -*- coding: utf-8 -*-
"""Журнал каси з'являється разом із планом рахунків.

`_post_load_data` - момент, коли рахунок 301 уже створено в компанії. Для компанії, план
якої завантажили раніше за модуль, те саме робить post_init_hook (hooks.py).
"""
from odoo import models

from ..hooks import create_cash_journal


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            create_cash_journal(self.env, company or self.env.company)
        return result
