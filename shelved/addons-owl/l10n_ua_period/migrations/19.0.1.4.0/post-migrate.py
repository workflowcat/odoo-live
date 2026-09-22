# -*- coding: utf-8 -*-
"""Домашня дія - «Період». Раніше стояло «Зведення»."""
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_period.hooks import post_init_hook


def migrate(cr, version):
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
