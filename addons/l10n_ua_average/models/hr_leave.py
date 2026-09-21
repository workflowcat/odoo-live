from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = "hr.leave"

    ua_sick_number = fields.Char("Номер е-лікарняного", help="Номер листка непрацездатності з Електронного реєстру; потрібен для Заяви-розрахунку до ПФУ")
    ua_order_ref = fields.Char("Наказ (№ і дата)", help="Наказ про надання відпустки")

    def _get_durations(self, check_leave_type=True, resource_calendar=None):
        """Види з ua_calendar_days рахуються календарними днями (ст. 5 ЗУ «Про відпустки»).

        Рідний Odoo рахує дні заявки за графіком роботи: 14 календарних днів при п'ятиденці
        дають 10. Нарахування (hr.leave.allocation) ми ведемо в календарних днях - стільки ж,
        скільки в наказі В-2 і в розрахунку відпускних - тому й списання має бути календарним,
        інакше залишок поповзе.

        Свята з періоду не виключаються: на час воєнного стану перенесення святкових днів
        зупинено (ст. 6 ЗУ 2136-IX), і розрахунок відпускних уже рахує так само.

        Годин не чіпаємо: їх читають табель і робочі записи, там правильні саме робочі години.
        check_leave_type = False - службовий виклик рідного коду, який навмисно питає «скільки
        це робочих днів»; там теж не втручаємось.
        """
        result = super()._get_durations(check_leave_type=check_leave_type, resource_calendar=resource_calendar)
        if not check_leave_type:
            return result
        for leave in self:
            if not leave.holiday_status_id.ua_calendar_days or leave.id not in result:
                continue
            start = leave.request_date_from or (leave.date_from and leave.date_from.date())
            end = leave.request_date_to or (leave.date_to and leave.date_to.date())
            if not start or not end or end < start:
                continue
            result[leave.id] = (float((end - start).days + 1), result[leave.id][1])
        return result

    @api.constrains("holiday_status_id", "employee_id")
    def _check_ua_mat_female_only(self):
        """Відпустка у зв'язку з вагітністю та пологами (MAT) - лише жінкам (ст. 179 КЗпП)."""
        for lv in self:
            code = lv.holiday_status_id.work_entry_type_id.code
            if code == "MAT" and lv.employee_id and lv.employee_id.sex and lv.employee_id.sex != "female":
                raise ValidationError("Відпустку у зв'язку з вагітністю та пологами можна оформити лише жінці.")
