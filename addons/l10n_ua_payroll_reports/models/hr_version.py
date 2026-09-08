from odoo import fields, models


class HrVersion(models.Model):
    _inherit = "hr.version"

    ua_order_ref = fields.Char("Наказ про прийняття (№ і дата)", groups="hr.group_hr_user", help="Наприклад: Наказ № 12 від 17.08.2026")
    ua_end_order_ref = fields.Char("Наказ про звільнення (№ і дата)", groups="hr.group_hr_user")
    ua_dismissal_basis = fields.Char("Підстава припинення", groups="hr.group_hr_user", help="Наприклад: п. 1 ст. 36 КЗпП (угода сторін)")
    ua_kp_code = fields.Char("Код КП", size=10, groups="hr.group_hr_user", help="Код за Класифікатором професій ДК 003, наприклад 2411.2")
    ua_prof_name = fields.Char("Професійна назва роботи", groups="hr.group_hr_user")
    ua_internal_parttime = fields.Boolean("Внутрішній сумісник", groups="hr.group_hr_user")
