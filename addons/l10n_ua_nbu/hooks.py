# -*- coding: utf-8 -*-
"""Провайдер «НБУ» для компаній з гривнею.

Записом у XML це не зробити: провайдер прив'язаний до компанії і має
список валют, а валюта компанії відома лише в базі. Тому створюємо в
post_init - по одному провайдеру на гривневу компанію, щодня, з валютами
USD EUR PLN GBP. Ідемпотентно: якщо провайдер уже є, не чіпаємо (в OCA на
пару service+company_id стоїть UNIQUE).
"""
import logging

from odoo import fields

_logger = logging.getLogger(__name__)

# Валюти за замовчуванням: те, чим реально розраховуються українські компанії.
DEFAULT_CURRENCIES = ["USD", "EUR", "PLN", "GBP"]


def _currencies(env):
    return env["res.currency"].with_context(active_test=False).search(
        [("name", "in", DEFAULT_CURRENCIES)]
    )


def create_nbu_providers(env, companies=None):
    """Створити провайдера НБУ для кожної гривневої компанії без нього."""
    Provider = env["res.currency.rate.provider"].sudo()
    if companies is None:
        companies = env["res.company"].sudo().search([])
    currencies = _currencies(env)
    # Без активної валюти курс нікуди не підставиться, тож вмикаємо саме ці чотири.
    currencies.filtered(lambda c: not c.active).sudo().write({"active": True})
    created = Provider.browse()
    for company in companies:
        if company.currency_id.name != "UAH":
            continue
        if Provider.search_count(
            [("service", "=", "NBU"), ("company_id", "=", company.id)]
        ):
            continue
        created |= Provider.create({
            "service": "NBU",
            "company_id": company.id,
            "currency_ids": [(6, 0, currencies.ids)],
            "interval_type": "days",
            "interval_number": 1,
            "next_run": fields.Date.context_today(Provider),
        })
    return created


def post_init_hook(env):
    created = create_nbu_providers(env)
    _logger.info("l10n_ua_nbu: створено провайдерів НБУ: %d", len(created))
