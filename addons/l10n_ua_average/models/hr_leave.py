from odoo import fields, models


class HrLeave(models.Model):
    _inherit = "hr.leave"

    ua_sick_number = fields.Char("Номер е-лікарняного", help="Номер листка непрацездатності з Електронного реєстру; потрібен для Заяви-розрахунку до ПФУ")
    ua_order_ref = fields.Char("Наказ (№ і дата)", help="Наказ про надання відпустки")
