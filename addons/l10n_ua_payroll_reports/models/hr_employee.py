from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_last_name = fields.Char("Прізвище", groups="hr.group_hr_user")
    ua_first_name = fields.Char("Ім'я", groups="hr.group_hr_user")
    ua_middle_name = fields.Char("По батькові", groups="hr.group_hr_user")
    ua_hire_date = fields.Date("Дата прийняття", groups="hr.group_hr_user")
    ua_dismissal_date = fields.Date("Дата звільнення", groups="hr.group_hr_user")
    ua_full_time = fields.Boolean("Повна зайнятість", default=True, groups="hr.group_hr_user")

    def _ua_name_parts(self):
        self.ensure_one()
        if self.ua_last_name:
            return self.ua_last_name, self.ua_first_name or "", self.ua_middle_name or ""
        parts = (self.name or "").split()
        return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else ""), (parts[2] if len(parts) > 2 else "")
