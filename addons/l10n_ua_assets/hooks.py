# -*- coding: utf-8 -*-
"""Компанія, план рахунків якої вже завантажено.

_post_load_data спрацьовує лише коли план ua_psbo встановлюють у компанію.
Якщо модуль ставлять на базу, де план уже стоїть, набір профілів треба
створити руками. Ідемпотентно: що вже є, того не чіпаємо.
"""
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    companies = env["res.company"].sudo().search([("chart_template", "=", "ua_psbo")])
    Profile = env["account.asset.profile"]
    total = 0
    for company in companies:
        total += len(Profile._ua_create_profiles(company))
    _logger.info(
        "l10n_ua_assets: створено профілів активів: %d для %d компаній",
        total,
        len(companies),
    )
