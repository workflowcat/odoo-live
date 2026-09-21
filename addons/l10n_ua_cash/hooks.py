# -*- coding: utf-8 -*-
"""Журнал «Каса» для компанії на ua_psbo.

Нативний план ua_psbo журналу каси не створює: є рахунок 301 «Готівка в національній
валюті», а журналу, у якому виписують ПКО і ВКО, немає. Без нього касові ордери нікуди
заводити - кожен скрипт і кожен бухгалтер створював журнал сам, руками і по-різному.

Два входи, одна робота. `post_init_hook` - для компанії, план якої вже завантажено; коли
модуль ставлять раніше за план, те саме робить `_post_load_data` у
models/account_chart_template.py. Ідемпотентно: якщо касовий журнал уже є, не чіпаємо.
"""
import logging

_logger = logging.getLogger(__name__)

JOURNAL_NAME = "Каса"
JOURNAL_CODE = "CASH"


def _cash_account(env, company):
    """Рахунок 301. Коди бувають скороченими (301) і доповненими нулями (301000)."""
    Account = env["account.account"].sudo().with_company(company)
    return Account.search([("code", "=", "301"), ("company_ids", "in", company.id)], limit=1) or \
        Account.search([("code", "=like", "301%"), ("company_ids", "in", company.id)],
                       order="code", limit=1)


def _free_code(env, company):
    Journal = env["account.journal"].sudo()
    code = JOURNAL_CODE
    for suffix in ("", "1", "2", "3"):
        candidate = (JOURNAL_CODE + suffix)[:5]
        if not Journal.search_count([("code", "=", candidate), ("company_id", "=", company.id)]):
            return candidate
    return code


def create_cash_journal(env, company):
    """Касовий журнал компанії. Повертає запис або порожній набір."""
    Journal = env["account.journal"].sudo()
    existing = Journal.search([("type", "=", "cash"), ("company_id", "=", company.id)], limit=1)
    if existing:
        return existing
    account = _cash_account(env, company)
    if not account:
        return Journal
    journal = Journal.create({
        "name": JOURNAL_NAME, "code": _free_code(env, company), "type": "cash",
        "company_id": company.id, "default_account_id": account.id,
    })
    # ті самі службові рахунки, які ядро проставляє банківським і касовим журналам
    journal.suspense_account_id = journal.suspense_account_id or company.account_journal_suspense_account_id
    journal.profit_account_id = journal.profit_account_id or company.default_cash_difference_income_account_id
    journal.loss_account_id = journal.loss_account_id or company.default_cash_difference_expense_account_id
    _logger.info("l10n_ua_cash: створено журнал «%s» для компанії %s", JOURNAL_NAME, company.name)
    return journal


def post_init_hook(env):
    made = 0
    companies = env["res.company"].sudo().search([("chart_template", "=", "ua_psbo")])
    for company in companies:
        if create_cash_journal(env, company):
            made += 1
    _logger.info("l10n_ua_cash: касових журналів на місці - %d з %d компаній",
                 made, len(companies))
