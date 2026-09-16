from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError


def _age_on(birthday, on_date):
    if not birthday:
        return None
    return on_date.year - birthday.year - ((on_date.month, on_date.day) < (birthday.month, birthday.day))


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

    # -- Додаткові відпустки за Законом «Про відпустки» ---------------------------------------
    # ua_veteran (УБД) і ua_child_ids/ua_single_parent (сім'я) визначені в l10n_ua_hr_card, що
    # залежить від цього модуля (не навпаки) - формальної залежності тут немає, тож читаємо їх
    # через getattr. На практиці l10n_ua_card_ui встановлює обидва модулі разом.
    ua_war_disability = fields.Boolean("Особа з інвалідністю внаслідок війни", groups="hr.group_hr_user",
                                       help="Додаткова відпустка 14 днів за ст. 16-2 ЗУ «Про відпустки», як і для УБД")
    ua_special_leave_days = fields.Integer("Днів додаткової відпустки за особливий характер праці", default=0, groups="hr.group_hr_user",
                                           help="До 7 днів на рік: ненормований робочий день, робота за комп'ютером тощо (ст. 8 ЗУ «Про відпустки»)")
    ua_soc_child_disabled_child = fields.Boolean("Є дитина з інвалідністю", groups="hr.group_hr_user",
                                                 help="Підстава для соціальної відпустки за ст. 19 ЗУ «Про відпустки»")

    ua_soc_child_allocated = fields.Float("СОЦ_ДІТИ: нараховано (накопичено)", default=0.0, digits=(6, 1), groups="hr.group_hr_user",
                                          help="Накопичений залишок днів соціальної відпустки на дітей; не згорає, переноситься без обмежень")
    ua_soc_child_last_year = fields.Integer("СОЦ_ДІТИ: рік останнього нарахування", default=0, groups="hr.group_hr_user")

    @api.constrains("ua_special_leave_days")
    def _check_ua_special_leave_days(self):
        for e in self:
            if not (0 <= (e.ua_special_leave_days or 0) <= 7):
                raise ValidationError("Додаткова відпустка за особливий характер праці - від 0 до 7 днів на рік.")

    # -- норми на рік (живі, не зберігаються - завжди відображають поточне право) ---------------
    ua_vac_ubd_days_year = fields.Integer("УБД: днів на рік", compute="_compute_ua_vac_ubd_days_year", groups="hr.group_hr_user")
    ua_soc_child_days_year = fields.Integer("СОЦ_ДІТИ: днів на рік", compute="_compute_ua_soc_child_days_year", groups="hr.group_hr_user")
    ua_special_allocated = fields.Integer("ОСОБЛИВІ УМОВИ: днів на рік", compute="_compute_ua_special_allocated", groups="hr.group_hr_user")

    @api.depends("ua_war_disability")
    def _compute_ua_vac_ubd_days_year(self):
        for e in self:
            e.ua_vac_ubd_days_year = 14 if (getattr(e, "ua_veteran", False) or e.ua_war_disability) else 0

    def _ua_soc_child_grounds(self):
        """Кількість підстав ст. 19: двоє+ дітей до 15, дитина з інвалідністю, одинокий батько/мати."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        children = getattr(self, "ua_child_ids", [])
        young = sum(1 for c in children if c.birthday and _age_on(c.birthday, today) is not None and _age_on(c.birthday, today) < 15)
        grounds = 0
        if young >= 2:
            grounds += 1
        if self.ua_soc_child_disabled_child:
            grounds += 1
        if getattr(self, "ua_single_parent", False):
            grounds += 1
        return grounds

    @api.depends("ua_soc_child_disabled_child")
    def _compute_ua_soc_child_days_year(self):
        for e in self:
            grounds = e._ua_soc_child_grounds()
            e.ua_soc_child_days_year = 17 if grounds >= 2 else (10 if grounds == 1 else 0)

    @api.depends("ua_special_leave_days")
    def _compute_ua_special_allocated(self):
        for e in self:
            e.ua_special_allocated = max(0, min(e.ua_special_leave_days or 0, 7))

    # -- використано / залишок (рахуються з проведених hr.leave, без @api.depends - як і ua_vacation_balance) --
    ua_vac_ubd_used = fields.Float("УБД: використано (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_vac_ubd_balance = fields.Float("УБД: залишок (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_soc_child_used = fields.Float("СОЦ_ДІТИ: використано (всі роки)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_soc_child_balance = fields.Float("СОЦ_ДІТИ: залишок (всі роки)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_special_used = fields.Float("ОСОБЛИВІ УМОВИ: використано (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_special_balance = fields.Float("ОСОБЛИВІ УМОВИ: залишок (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")

    def _ua_leave_days_for_code(self, code, date_from=None, date_to=None):
        """Календарні дні проведених hr.leave цього коду, за потреби обрізані вікном [date_from, date_to]."""
        self.ensure_one()
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "=", self.id), ("state", "=", "validate"),
            ("holiday_status_id.work_entry_type_id.code", "=", code),
        ])
        total = 0.0
        for lv in leaves:
            start = max(lv.request_date_from, date_from) if date_from else lv.request_date_from
            end = min(lv.request_date_to, date_to) if date_to else lv.request_date_to
            if start and end and end >= start:
                total += (end - start).days + 1
        return total

    def _compute_ua_leave_balances(self):
        today = fields.Date.context_today(self)
        year_start, year_end = date(today.year, 1, 1), date(today.year, 12, 31)
        for e in self:
            e.ua_vac_ubd_used = e._ua_leave_days_for_code("VAC_UBD", year_start, year_end)
            e.ua_vac_ubd_balance = (e.ua_vac_ubd_days_year or 0) - e.ua_vac_ubd_used
            e.ua_soc_child_used = e._ua_leave_days_for_code("SOC_CHILD")
            e.ua_soc_child_balance = (e.ua_soc_child_allocated or 0.0) - e.ua_soc_child_used
            e.ua_special_used = e._ua_leave_days_for_code("VAC_SPECIAL", year_start, year_end)
            e.ua_special_balance = (e.ua_special_allocated or 0) - e.ua_special_used

    def _ua_ensure_allocations(self, year=None):
        """Раз на рік (січень, на дату впровадження або на вимогу) додає належні дні соціальної
        відпустки на дітей (ст. 19) до накопиченого залишку - вона не згорає й переноситься без
        обмежень, тому нарахування адитивне, з захистом від подвійного нарахування за той самий рік.

        УБД і особливі умови праці не потребують нарахування: їхній залишок завжди - поточне
        право (ua_*_days_year) мінус використане в поточному році (ua_compute_ua_leave_balances),
        рахується наживо без окремого запису."""
        year = year or fields.Date.context_today(self).year
        for e in self:
            if e.ua_soc_child_last_year >= year:
                continue
            days = e._ua_soc_child_grounds()
            days = 17 if days >= 2 else (10 if days == 1 else 0)
            if days:
                e.ua_soc_child_allocated = (e.ua_soc_child_allocated or 0.0) + days
            e.ua_soc_child_last_year = year
        return True

    def ua_ensure_allocations(self, year=None):
        """Публічна обгортка над _ua_ensure_allocations - Odoo забороняє віддалений виклик методів
        з підкресленням через execute_kw (demo_company.py, leaves_check.py, кнопки)."""
        return self._ua_ensure_allocations(year=year)
