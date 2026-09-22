# -*- coding: utf-8 -*-
"""Рахунок втрат зʼявляється разом із планом рахунків.

`_post_load_data` - момент, коли 947 уже створено в компанії. Для компанії,
план якої завантажили раніше за модуль, те саме робить post_init_hook.
"""
from odoo import models

from ..hooks import setup_loss_accounts


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            setup_loss_accounts(self.env, company or self.env.company)
        return result
