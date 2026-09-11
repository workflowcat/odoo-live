# -*- coding: utf-8 -*-
"""Переставити правила звірки: спеціальні перші, зарплата остання.

Без порядку платіж «ПДФО з авансу» потрапляв на 661, бо правило зарплати містить
слово «аванс» і спрацьовувало першим."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.l10n_ua_bank.hooks import post_init_hook
    post_init_hook(env)
