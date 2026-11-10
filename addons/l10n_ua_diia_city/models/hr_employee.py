from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_gig_currency_id = fields.Many2one(
        "res.currency", "Валюта винагороди", groups="hr.group_hr_user",
        help="Валюта, у якій гіг-контракт визначає винагороду. Порожньо - гривня компанії.")
    ua_gig_fee = fields.Monetary(
        "Винагорода за місяць у валюті договору", currency_field="ua_gig_currency_id", groups="hr.group_hr_user",
        help="Підставляється в новий акт гіг-спеціаліста. Гривнева сума рахується в акті за курсом НБУ на дату акта.")
