from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_payroll_ui.hooks import post_init_hook


def migrate(cr, version):
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
