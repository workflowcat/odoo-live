from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_vacation_opening_date = fields.Date("Дата впровадження обліку відпусток",
                                           help="Типова дата впровадження для працівників, у яких власна дата не задана")
