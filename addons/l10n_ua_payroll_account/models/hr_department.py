from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = "hr.department"

    ua_expense_account_id = fields.Many2one("account.account", "Рахунок витрат на оплату праці",
                                            help="23, 91, 92, 93 або 94 залежно від підрозділу. Порожньо = 92")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_expense_account_id = fields.Many2one("account.account", "Рахунок витрат (перекриває підрозділ)", groups="hr.group_hr_user")
    ua_payable_account_id = fields.Many2one(
        "account.account", "Рахунок розрахунків (замість 661)", groups="hr.group_hr_user",
        help="Для гіг-спеціаліста чи виконавця, якого облікова політика веде не на 661 (наприклад, 663 або 685): "
             "усі рядки проводок цієї людини, що йдуть на 661, підуть на цей рахунок - і нарахування, і утримання.")
