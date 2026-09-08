from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = "hr.department"

    ua_expense_account_id = fields.Many2one("account.account", "Рахунок витрат на оплату праці",
                                            help="23, 91, 92, 93 або 94 залежно від підрозділу. Порожньо = 92")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_expense_account_id = fields.Many2one("account.account", "Рахунок витрат (перекриває підрозділ)", groups="hr.group_hr_user")
