# -*- coding: utf-8 -*-
"""Профілі активів зʼявляються разом із планом рахунків.

Хуки @template віддають лише словники значень для записів шаблону, а нам
треба створити записи іншої моделі (account.asset.profile), для якої
потрібні вже створені рахунки і журнал. Тому чіпляємося на
_post_load_data - момент, коли план уже завантажено в компанію.

Для компанії, план якої завантажили раніше за цей модуль, те саме робить
post_init_hook (hooks.py).
"""
from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        result = super()._post_load_data(template_code, company, template_data)
        if template_code == "ua_psbo":
            company = company or self.env.company
            self.env["account.asset.profile"]._ua_create_profiles(company)
        return result
