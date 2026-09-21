# -*- coding: utf-8 -*-
"""Компанія, план рахунків якої вже завантажено.

Хуки @template спрацьовують лише коли план ua_psbo встановлюють у компанію.
Якщо модуль ставлять на базу, де план уже стоїть, ті самі дві правки треба
зробити руками: маркер виду нуля на групах ПДВ і групи на нульових податках.
Ідемпотентно: що вже стоїть, того не чіпаємо.
"""
import logging

from .models.template_ua_psbo import UA_ZERO_GROUPS, UA_ZERO_TAXES

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    companies = env["res.company"].search([("chart_template", "=", "ua_psbo")])
    Template = env["account.chart.template"]
    for company in companies:
        chart = Template.with_company(company)
        for xmlid, kind in UA_ZERO_GROUPS.items():
            group = chart.ref(xmlid, raise_if_not_found=False)
            if group and not group.x_ua_vat_zero_kind:
                group.x_ua_vat_zero_kind = kind
        for tax_xmlid, group_xmlid in UA_ZERO_TAXES.items():
            tax = chart.ref(tax_xmlid, raise_if_not_found=False)
            group = chart.ref(group_xmlid, raise_if_not_found=False)
            if tax and group and not tax.tax_group_id:
                tax.tax_group_id = group
    _logger.info("l10n_ua_vat: нульові групи ПДВ позначено для %d компаній",
                 len(companies))
