from odoo import fields, models

ESV_CATEGORY = [("standard", "22 % (загальна)"), ("disabled", "8,41 % (працівник з інвалідністю)")]
PSP = [("none", "немає"), ("base", "базова (100 %)"), ("child", "на дітей (100 % на кожну дитину)"),
       ("child150", "на дітей (150 %)"), ("s150", "підвищена 150 %"), ("s200", "підвищена 200 %")]
KIND = [("employment", "трудовий договір"), ("gph", "договір ЦПХ"), ("fop", "ФОП-підрядник")]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_rnokpp = fields.Char("РНОКПП", groups="hr.group_hr_user")
    ua_contract_kind = fields.Selection(KIND, "Вид відносин", default="employment", groups="hr.group_hr_user")
    ua_main_job = fields.Boolean("Основне місце роботи", default=True, groups="hr.group_hr_user",
                                 help="Вимкнено для зовнішнього сумісника: ЄСВ без доплати до мінімалки")
    ua_esv_category = fields.Selection(ESV_CATEGORY, "Категорія ЄСВ", default="standard", groups="hr.group_hr_user")
    ua_psp = fields.Selection(PSP, "Податкова соціальна пільга", default="none", groups="hr.group_hr_user",
                              help="За заявою працівника; застосовується лише за одним місцем роботи")
    ua_psp_children = fields.Integer("Дітей до 18 років", default=0, groups="hr.group_hr_user")
