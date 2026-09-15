from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_hr_orders.hooks import backfill_leave_orders


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    backfill_leave_orders(env)
