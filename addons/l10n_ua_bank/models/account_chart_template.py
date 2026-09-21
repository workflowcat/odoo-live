# -*- coding: utf-8 -*-
"""Правила звірки з'являються разом із планом рахунків.

Модуль ставиться раніше, ніж компанія завантажує ua_psbo, тому на чистій базі
`post_init_hook` не бачить рахунку 661 і не створює жодного правила. Чіпляємося на
`_post_load_data` - момент, коли план уже в компанії, - і створюємо їх там.

Для компанії, план якої завантажили раніше за модуль, те саме робить post_init_hook
(hooks.py). Обидва шляхи ідемпотентні.
"""
from odoo import models

from ..hooks import create_reconcile_models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            create_reconcile_models(self.env, company or self.env.company)
        return result
