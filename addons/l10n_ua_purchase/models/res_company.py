from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_purchase_approval_limit = fields.Monetary(
        string="Ліміт погодження запиту",
        currency_field="currency_id",
        default=0.0,
        help="Сума орієнтовної вартості запиту на закупівлю, вище якої запит "
             "погоджує лише керівник закупівель. Нуль - ліміт не встановлено. "
             "Погодження самого замовлення йде нативним двоступеневим "
             "механізмом Odoo (Налаштування закупівель, «Погодження замовлень»).",
    )
