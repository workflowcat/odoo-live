# -*- coding: utf-8 -*-
"""Картка працівника стояла першим видом у діях зі списком або деревом.

Через це «Оргструктура», «Військовозобов'язані» і «Потребують звірки» відкривались
порожньою формою нового запису. Ставимо форму після решти видів."""
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_card_ui.hooks import repair_form_first


def migrate(cr, version):
    repair_form_first(api.Environment(cr, SUPERUSER_ID, {}))
