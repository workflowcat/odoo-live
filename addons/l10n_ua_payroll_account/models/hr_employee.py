from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_alimony_partner_id = fields.Many2one("res.partner", "Отримувач аліментів", groups="hr.group_hr_user",
                                            help="Контрагент для рядка 6851; за замовчуванням сам працівник")
