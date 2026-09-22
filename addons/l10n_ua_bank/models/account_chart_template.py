# -*- coding: utf-8 -*-
"""Правила звірки і рахунок 333 з'являються разом із планом рахунків.

Модуль ставиться раніше, ніж компанія завантажує ua_psbo, тому на чистій базі
`post_init_hook` не бачить ані рахунку 661, ані 333 і не робить нічого. Чіпляємося на
`_post_load_data` - момент, коли план уже в компанії і банківський журнал уже створено, -
і робимо ту саму роботу там.

Для компанії, план якої завантажили раніше за модуль, лишається post_init_hook (hooks.py),
а для баз, що вже жили без 333, - міграція 19.0.1.4.0. Усі три шляхи ідемпотентні.
"""
from odoo import models

from ..hooks import create_reconcile_models, set_outstanding_accounts


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            company = company or self.env.company
            create_reconcile_models(self.env, company)
            set_outstanding_accounts(self.env, company)
        return result
