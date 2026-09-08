from datetime import date

from odoo import api, fields, models

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
    ua_fte = fields.Selection([("1", "повна ставка"), ("0.75", "0,75 ставки"), ("0.5", "0,5 ставки"), ("0.25", "0,25 ставки")],
                              "Ставка", default="1", required=True, groups="hr.group_hr_user",
                              help="Оклад у контракті вказано за повну ставку; нарахування = оклад × ставка")
    ua_disability_group = fields.Selection([("none", "немає"), ("1", "I група"), ("2", "II група"), ("3", "III група")], "Група інвалідності", default="none", groups="hr.group_hr_user")
    ua_vacation_days_year = fields.Integer("Днів щорічної відпустки на рік", compute="_compute_ua_vacation_days_year", store=True, readonly=False, groups="hr.group_hr_user",
                                           help="24 (ст. 6 ЗУ про відпустки); 26 для III групи, 30 для I-II групи інвалідності (ст. 6 ЗУ про відпустки)")
    ua_vacation_accrued = fields.Float("Накопичено днів", compute="_compute_ua_vacation_balance", digits=(6, 1), groups="hr.group_hr_user")
    ua_vacation_used = fields.Float("Використано днів", compute="_compute_ua_vacation_balance", digits=(6, 1), groups="hr.group_hr_user")
    ua_vacation_balance = fields.Float("Залишок днів відпустки", compute="_compute_ua_vacation_balance", digits=(6, 1), groups="hr.group_hr_user",
                                       help="Накопичено за відпрацьований час з дати прийняття (пропорційно до календарних днів) мінус використані щорічні відпустки і виплачені компенсації")

    @api.depends("ua_disability_group")
    def _compute_ua_vacation_days_year(self):
        for e in self:
            e.ua_vacation_days_year = {"1": 30, "2": 30, "3": 26}.get(e.ua_disability_group or "none", 24)

    def _compute_ua_vacation_balance(self):
        today = date.today()
        Leave = self.env["hr.leave"].sudo()
        Input = self.env["hr.payslip.input"].sudo() if "hr.payslip.input" in self.env else None
        for e in self:
            days = 0
            for v in e.sudo().version_ids:
                if v.contract_date_start:
                    end = min(v.contract_date_end or today, today)
                    if end >= v.contract_date_start:
                        days += (end - v.contract_date_start).days + 1
            # дублікати версій одного контракту (однакові дати) не рахуємо двічі
            seen = set(); days = 0
            for v in e.sudo().version_ids:
                key = (v.contract_date_start, v.contract_date_end)
                if v.contract_date_start and key not in seen:
                    seen.add(key)
                    end = min(v.contract_date_end or today, today)
                    if end >= v.contract_date_start:
                        days += (end - v.contract_date_start).days + 1
            accrued = round((e.ua_vacation_days_year or 24) * days / 365.0, 1)
            used = 0.0
            for lv in Leave.search([("employee_id", "=", e.id), ("state", "=", "validate"), ("holiday_status_id.work_entry_type_id.code", "=", "VAC")]):
                used += (lv.request_date_to - lv.request_date_from).days + 1
            if Input is not None:
                used += sum(Input.search([("payslip_id.employee_id", "=", e.id), ("code", "=", "COMP_DAYS"), ("payslip_id.state", "=", "done")]).mapped("amount"))
            e.ua_vacation_accrued = accrued; e.ua_vacation_used = used; e.ua_vacation_balance = round(accrued - used, 1)
