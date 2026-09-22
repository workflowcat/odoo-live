# -*- coding: utf-8 -*-
"""Рахунок втрат на локаціях списання.

Нативний Odoo 19 тримає на локації один рахунок оцінки, і саме він стає другою
стороною проводки при коригуванні залишків. Порожній рахунок означає, що
інвентаризація не дає жодної проводки взагалі. Для українського плану це 947
«Нестачі і втрати від псування цінностей»: нестача лягає туди правильно, а
лишок цей модуль перекидає на 719 окремою проводкою (див. ua_stock_inventory).

Повний набір налаштувань оцінки запасів - постійна оцінка, рахунки категорій,
рахунок виробництва - робить l10n_ua_mrp. Тут тільки те, без чого не працює сам
документ інвентаризації, і робиться воно ідемпотентно: заповнений рахунок не
чіпаємо.
"""
import logging

_logger = logging.getLogger(__name__)

ACC_SHORTAGE = "ua_psbp_947"


def _account(env, company, xmlid):
    chart = env["account.chart.template"].with_company(company).sudo()
    account = chart.ref(xmlid, raise_if_not_found=False)
    if account:
        return account
    code = xmlid.rsplit("_", 1)[-1]
    Account = env["account.account"].sudo().with_company(company)
    for candidate in Account.search(
        [("code", "=like", code + "%"), ("company_ids", "in", company.ids)], order="code"
    ):
        if candidate.code.rstrip("0") == code or candidate.code == code:
            return candidate
    return Account.browse()


def setup_loss_accounts(env, company):
    account = _account(env, company, ACC_SHORTAGE)
    if not account:
        return 0
    locations = env["stock.location"].sudo().search(
        [("usage", "=", "inventory"), ("company_id", "=", company.id)])
    touched = 0
    for location in locations:
        if not location.valuation_account_id:
            location.valuation_account_id = account
            touched += 1
    return touched


def post_init_hook(env):
    companies = env["res.company"].sudo().search([("chart_template", "=", "ua_psbo")])
    total = sum(setup_loss_accounts(env, company) for company in companies)
    _logger.info("l10n_ua_stock_docs: рахунок 947 проставлено на %d локаціях списання", total)
