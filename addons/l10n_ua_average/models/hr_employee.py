from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_insurance_years = fields.Float("Страховий стаж, років", digits=(6, 2), groups="hr.group_hr_user",
                                      help="На дату початку хвороби. Визначає відсоток лікарняних (ст. 24 ЗУ 1105)")
    ua_sick_full = fields.Boolean("Лікарняні 100 % незалежно від стажу", groups="hr.group_hr_user",
                                  help="Пільгові категорії за ст. 24 ЗУ 1105")
    ua_sick_percent = fields.Float("Відсоток лікарняних", compute="_compute_ua_sick_percent", groups="hr.group_hr_user")

    @api.depends("ua_insurance_years", "ua_sick_full")
    def _compute_ua_sick_percent(self):
        for e in self:
            y = e.ua_insurance_years or 0.0
            e.ua_sick_percent = 100.0 if (e.ua_sick_full or y >= 8) else 70.0 if y >= 5 else 60.0 if y >= 3 else 50.0
