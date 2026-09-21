# -*- coding: utf-8 -*-
"""Податкові дані ПДВ поверх нативного плану ua_psbo.

Нативний l10n_ua 19 уже дає все головне:

* податки продажу і придбання 20 %, 14 %, 7 %, 0 %, «звільнено», «не є об'єктом»
  (xmlid sale_tax_template_vat20_psbo ... purchase_tax_template_vat_not_psbo);
* групи податків ПДВ 20 %, 15 %, 14 %, 7 %, 0 %, «Звільнено від ПДВ», «Не є ПДВ»
  (tax_group_vat20 ... tax_group_not_vat);
* рахунки: ПДВ продажу лягає на 6432 «Податкові зобов'язання непідтверджені»,
  ПДВ придбання - на 6442 «Податковий кредит непідтверджений»;
* 6412 «Розрахунки за ПДВ» з тегом ПДВ.

Своїх податків ми НЕ створюємо. Бракує рівно двох речей, і їх ми й додаємо:

1. Три нульові податки (0 %, звільнено, не є об'єктом) залишені без групи -
   отже нічим відрізнити експорт від пільги. Чіпляємо на них ті групи, які
   нативний модуль уже створив, але не призначив.
2. Групи не кажуть, який це вид нуля. Ставимо маркер ua_vat_zero_kind, за
   яким податкова накладна обирає код ставки графи 8: 901 експорт, 903
   звільнено.

Хуки @template віддають лише ті поля, які міняємо: Odoo зливає словники
шаблонів по xmlid (chart_template._get_chart_template_data), тож решта
нативних полів лишається як є. Для компанії, чий план уже завантажено, те
саме робить post_init_hook (hooks.py).
"""
from odoo import models
from odoo.addons.account.models.chart_template import template

# Нульові групи нативного l10n_ua і вид нуля, яким вони є для ПДВ.
UA_ZERO_GROUPS = {
    "tax_group_vat0": "export",
    "tax_group_vat_free": "exempt",
    "tax_group_not_vat": "not_object",
}

# Нульовий податок -> група, якої йому бракує.
UA_ZERO_TAXES = {
    "sale_tax_template_vat0_psbo": "tax_group_vat0",
    "sale_tax_template_vat_free_psbo": "tax_group_vat_free",
    "sale_tax_template_vat_not_psbo": "tax_group_not_vat",
    "purchase_tax_template_vat0_psbo": "tax_group_vat0",
    "purchase_tax_template_vat_free_psbo": "tax_group_vat_free",
    "purchase_tax_template_vat_not_psbo": "tax_group_not_vat",
}


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    @template("ua_psbo", "account.tax.group")
    def _get_ua_psbo_vat_tax_group(self):
        """Маркер виду нульової ставки на нативних групах ПДВ."""
        return {
            xmlid: {"ua_vat_zero_kind": kind}
            for xmlid, kind in UA_ZERO_GROUPS.items()
        }

    @template("ua_psbo", "account.tax")
    def _get_ua_psbo_vat_tax(self):
        """Нативні нульові податки без групи - дочіпляємо нативні ж групи."""
        return {
            tax_xmlid: {"tax_group_id": group_xmlid}
            for tax_xmlid, group_xmlid in UA_ZERO_TAXES.items()
        }
