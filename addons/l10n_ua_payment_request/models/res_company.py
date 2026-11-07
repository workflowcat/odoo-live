from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_payment_request_limit = fields.Monetary(
        "Ліміт заявки без директора", currency_field="currency_id",
        help="Заявку на оплату на більшу суму (у гривні) після фінансиста затверджує ще й "
             "директор. Нуль - директор затверджує кожну заявку.")
