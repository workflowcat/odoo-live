# -*- coding: utf-8 -*-
"""Рахунки виробництва зʼявляються разом із планом рахунків.

`_post_load_data` - момент, коли 231, 201 і 26 уже створено в компанії. Для
компанії, план якої завантажили раніше за модуль, те саме робить post_init_hook
(hooks.py).
"""
from odoo import models

from ..hooks import setup_costing


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            setup_costing(self.env, company or self.env.company)
        return result
