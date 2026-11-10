from datetime import date

from odoo import api, fields, models

ESV_CATEGORY = [("standard", "22 % (загальна)"), ("disabled", "8,41 % (працівник з інвалідністю)")]
PSP = [("none", "немає"), ("base", "базова (100 %)"), ("child", "на дітей (100 % на кожну дитину)"),
       ("child150", "на дітей (150 %)"), ("s150", "підвищена 150 %"), ("s200", "підвищена 200 %")]
KIND = [("employment", "трудовий договір"), ("gph", "договір ЦПХ"), ("gig", "гіг-контракт (Дія Сіті)"),
        ("fop", "ФОП-підрядник")]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_rnokpp = fields.Char("РНОКПП", groups="hr.group_hr_user")
    ua_contract_kind = fields.Selection(KIND, "Вид відносин", default="employment", groups="hr.group_hr_user")
    ua_gph_contract_ref = fields.Char("Договір ЦПХ №", groups="hr.group_hr_user",
                                      help="Номер договору цивільно-правового характеру (ЦПХ) або договору підряду з ФОП")
    ua_gph_contract_date = fields.Date("Дата договору ЦПХ", groups="hr.group_hr_user")
    ua_gph_contract_end = fields.Date("Договір діє до", groups="hr.group_hr_user")
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
                                       help="Накопичено за відпрацьований час з дати прийняття (або з дати впровадження обліку) мінус використані щорічні відпустки і виплачені компенсації, плюс залишок на дату впровадження")
    ua_vacation_opening_balance = fields.Float("Залишок на дату впровадження", default=0, digits=(6, 1), groups="hr.group_hr_user")
    ua_vacation_opening_date = fields.Date("Дата впровадження обліку відпусток", groups="hr.group_hr_user",
                                           help="Накопичення рахується з цієї дати; до неї береться залишок вручну")

    @api.depends("ua_disability_group", "birthday")
    def _compute_ua_vacation_days_year(self):
        today = date.today()
        for e in self:
            minor = False
            if e.birthday:
                age = today.year - e.birthday.year - ((today.month, today.day) < (e.birthday.month, e.birthday.day))
                minor = age < 18
            e.ua_vacation_days_year = 31 if minor else {"1": 30, "2": 30, "3": 26}.get(e.ua_disability_group or "none", 24)

    def _compute_ua_vacation_balance(self):
        today = date.today()
        Leave = self.env["hr.leave"].sudo()
        Input = self.env["hr.payslip.input"].sudo() if "hr.payslip.input" in self.env else None
        for e in self:
            opening_date = e.ua_vacation_opening_date or e.sudo().company_id.ua_vacation_opening_date
            # дублікати версій одного контракту (однакові дати) не рахуємо двічі; накопичення - лише від дати впровадження, якщо вона є
            seen = set(); days = 0
            for v in e.sudo().version_ids:
                key = (v.contract_date_start, v.contract_date_end)
                if v.contract_date_start and key not in seen:
                    seen.add(key)
                    start = max(v.contract_date_start, opening_date) if opening_date else v.contract_date_start
                    end = min(v.contract_date_end or today, today)
                    if end >= start:
                        days += (end - start).days + 1
            accrued = round((e.ua_vacation_days_year or 24) * days / 365.0, 1)
            used = 0.0
            leave_domain = [("employee_id", "=", e.id), ("state", "=", "validate"), ("holiday_status_id.work_entry_type_id.code", "=", "VAC")]
            if opening_date:
                leave_domain.append(("request_date_from", ">=", opening_date))
            for lv in Leave.search(leave_domain):
                used += (lv.request_date_to - lv.request_date_from).days + 1
            if Input is not None:
                input_domain = [("payslip_id.employee_id", "=", e.id), ("code", "=", "COMP_DAYS"), ("payslip_id.state", "=", "done")]
                if opening_date:
                    input_domain.append(("payslip_id.date_to", ">=", opening_date))
                used += sum(Input.search(input_domain).mapped("amount"))
            opening_balance = e.ua_vacation_opening_balance if opening_date else 0.0
            e.ua_vacation_accrued = accrued; e.ua_vacation_used = used
            e.ua_vacation_balance = round(opening_balance + accrued - used, 1)
