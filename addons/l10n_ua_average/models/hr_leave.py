from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = "hr.leave"

    ua_sick_number = fields.Char("Номер е-лікарняного", help="Номер листка непрацездатності з Електронного реєстру; потрібен для Заяви-розрахунку до ПФУ")
    ua_order_ref = fields.Char("Наказ (№ і дата)", help="Наказ про надання відпустки")

    @api.constrains("holiday_status_id", "employee_id")
    def _check_ua_mat_female_only(self):
        """Відпустка у зв'язку з вагітністю та пологами (MAT) - лише жінкам (ст. 179 КЗпП)."""
        for lv in self:
            code = lv.holiday_status_id.work_entry_type_id.code
            if code == "MAT" and lv.employee_id and lv.employee_id.sex and lv.employee_id.sex != "female":
                raise ValidationError("Відпустку у зв'язку з вагітністю та пологами можна оформити лише жінці.")
