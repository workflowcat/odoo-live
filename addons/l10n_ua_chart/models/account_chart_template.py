# -*- coding: utf-8 -*-
"""Вигляд плану наводиться тоді, коли план з'являється.

Звичайний порядок на новій базі - спершу модулі, потім `try_loading("ua_psbo")`. До цього
моменту рахунків ще немає, тому `post_init_hook` нічого не знаходить і тихо нічого не
робить: коди лишаються шестизначними, назви англійськими. Тут чіпляємося на
`_post_load_data` - момент, коли план уже завантажено в компанію, - і робимо ту саму
роботу. Для компанії, чий план завантажили раніше за модуль, лишається post_init_hook.
"""
from odoo import models

from ..hooks import apply_chart_shape


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            apply_chart_shape(self.env)
        return result
