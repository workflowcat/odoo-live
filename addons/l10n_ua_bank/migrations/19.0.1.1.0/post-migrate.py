"""Оновити правила звірки: винагорода за ЦПХ на 661, оплата ФОП-підряднику на 6851."""
from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_bank.hooks import post_init_hook


def migrate(cr, version):
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
