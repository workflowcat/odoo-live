from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

ID_DOC_TYPES = [
    ("passport_book", "паспорт-книжка"),
    ("id_card", "ID-картка"),
    ("residence_permit", "посвідка на проживання"),
]
CHERNOBYL = [
    ("none", "немає"),
    ("1", "1 категорія"),
    ("2", "2 категорія"),
    ("3", "3 категорія"),
    ("4", "4 категорія"),
]


MARITAL_UA = [
    ("single", "Неодружений / незаміжня"),
    ("married", "Одружений / заміжня"),
    ("cohabitant", "У цивільному шлюбі"),
    ("widower", "Вдівець / вдова"),
    ("divorced", "Розлучений / розлучена"),
]

class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # -- Документ, що посвідчує особу -----------------------------------------------
    # ядро Odoo пише «Одружений(заміжня)»; у картці це виглядає як помилка
    marital = fields.Selection(selection=MARITAL_UA)
    ua_id_doc_type = fields.Selection(ID_DOC_TYPES, "Тип документа", groups="hr.group_hr_user")
    ua_id_doc_series = fields.Char("Серія", groups="hr.group_hr_user")
    ua_id_doc_number = fields.Char("Номер документа", groups="hr.group_hr_user")
    ua_id_doc_issued_by = fields.Char("Ким виданий", groups="hr.group_hr_user")
    ua_id_doc_date = fields.Date("Дата видачі", groups="hr.group_hr_user")
    ua_id_doc_unzr = fields.Char("УНЗР", groups="hr.group_hr_user", help="Унікальний номер запису в реєстрі, 13 символів")

    # -- Адреси і контакти ------------------------------------------------------------
    ua_actual_address = fields.Char("Фактична адреса", groups="hr.group_hr_user")

    # -- Сім'я --------------------------------------------------------------------------
    ua_child_ids = fields.One2many("ua.employee.child", "employee_id", string="Діти", groups="hr.group_hr_user")

    # -- Освіта -------------------------------------------------------------------------
    ua_education_year = fields.Integer("Рік закінчення", groups="hr.group_hr_user")
    ua_diploma_number = fields.Char("Номер диплома", groups="hr.group_hr_user")
    ua_science_degree = fields.Char("Науковий ступінь", groups="hr.group_hr_user")
    ua_languages = fields.Char("Мови", groups="hr.group_hr_user")

    # -- Пільги і особливий статус ------------------------------------------------------
    ua_chernobyl_category = fields.Selection(CHERNOBYL, "Категорія ЧАЕС", default="none", groups="hr.group_hr_user")
    ua_veteran = fields.Boolean("УБД / ветеран", groups="hr.group_hr_user")
    ua_large_family = fields.Boolean("Багатодітна сім'я", groups="hr.group_hr_user")
    ua_single_parent = fields.Boolean("Одинокий батько/мати", groups="hr.group_hr_user")

    # -- Трудова книжка і стаж ------------------------------------------------------------
    ua_labor_book_number = fields.Char("Номер трудової книжки", groups="hr.group_hr_user")
    ua_labor_book_date = fields.Date("Дата заведення", groups="hr.group_hr_user")
    ua_electronic_labor_book = fields.Boolean("Електронна трудова", groups="hr.group_hr_user")
    ua_prior_job_ids = fields.One2many("ua.employee.prior.job", "employee_id", string="Попередні місця роботи", groups="hr.group_hr_user")

    # -- Документи ------------------------------------------------------------------------
    ua_document_ids = fields.One2many("ua.employee.document", "employee_id", string="Документи", groups="hr.group_hr_user")
    ua_docs_expiring = fields.Integer("Документи, що закінчуються за 30 днів", compute="_compute_ua_docs_expiring", groups="hr.group_hr_user")

    @api.depends("ua_document_ids.valid_until")
    def _compute_ua_docs_expiring(self):
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=30)
        for employee in self:
            employee.ua_docs_expiring = len(employee.ua_document_ids.filtered(
                lambda d: d.valid_until and today <= d.valid_until <= limit))

    @api.constrains("ua_id_doc_unzr")
    def _check_ua_id_doc_unzr(self):
        for employee in self:
            if employee.ua_id_doc_unzr and len(employee.ua_id_doc_unzr) != 13:
                raise ValidationError("УНЗР має містити 13 символів.")

    # -- Огляд ------------------------------------------------------------------------------
    ua_days_in_company = fields.Integer("Днів у компанії", compute="_compute_ua_days_in_company", groups="hr.group_hr_user")
    ua_first_hire_date = fields.Date("Прийнято вперше", compute="_compute_ua_first_hire_date", store=True, groups="hr.group_hr_user")
    ua_current_wage = fields.Monetary("Поточний оклад", compute="_compute_ua_current_wage", currency_field="currency_id", groups="hr.group_hr_user")
    ua_docs_count = fields.Integer("Документів", compute="_compute_ua_docs_count", groups="hr.group_hr_user")
    ua_overview_alert_count = fields.Integer("Потребує уваги", compute="_compute_ua_overview_alert_count", groups="hr.group_hr_user")

    @api.depends("version_ids.contract_date_start", "version_ids.contract_date_end")
    def _compute_ua_days_in_company(self):
        today = fields.Date.context_today(self)
        for employee in self:
            seen = set()
            days = 0
            for v in employee.sudo().version_ids:
                key = (v.contract_date_start, v.contract_date_end)
                if v.contract_date_start and key not in seen:
                    seen.add(key)
                    end = min(v.contract_date_end or today, today)
                    if end >= v.contract_date_start:
                        days += (end - v.contract_date_start).days + 1
            employee.ua_days_in_company = days

    @api.depends("version_ids.contract_date_start")
    def _compute_ua_first_hire_date(self):
        for employee in self:
            starts = employee.sudo().version_ids.mapped("contract_date_start")
            employee.ua_first_hire_date = min(starts) if starts else False

    @api.depends("version_id.wage")
    def _compute_ua_current_wage(self):
        for employee in self:
            employee.ua_current_wage = employee.sudo().version_id.wage or 0.0

    @api.depends("ua_document_ids")
    def _compute_ua_docs_count(self):
        for employee in self:
            employee.ua_docs_count = len(employee.ua_document_ids)

    @api.depends("ua_document_ids.valid_until", "ua_rnokpp", "ua_id_doc_type", "ua_id_doc_number",
                 "ua_mil_needs_check", "ua_vacation_balance")
    def _compute_ua_overview_alert_count(self):
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=30)
        for employee in self:
            emp = employee.sudo()
            count = 0
            if any(d.valid_until and d.valid_until <= limit for d in emp.ua_document_ids):
                count += 1
            if not emp.ua_rnokpp:
                count += 1
            if not (emp.ua_id_doc_type and emp.ua_id_doc_number):
                count += 1
            if emp.ua_mil_needs_check:
                count += 1
            if (emp.ua_vacation_balance or 0.0) > 60:
                count += 1
            employee.ua_overview_alert_count = count

    def action_view_ua_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Документи",
            "res_model": "ua.employee.document",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }
