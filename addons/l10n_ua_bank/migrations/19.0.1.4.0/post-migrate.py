# -*- coding: utf-8 -*-
"""Банківським журналам баз, які вже жили без нього, - рахунок 333 «гроші в дорозі».

Заразом проганяє правила звірки: серед них з'явилося нове, про готівку в дорозі.
Проведених платежів міграція не чіпає: ті, що вже лягли на англомовний «Outstanding
Payments», лишаються як є - переписувати проводки закритих місяців ми не будемо."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.l10n_ua_bank.hooks import post_init_hook
    post_init_hook(env)
