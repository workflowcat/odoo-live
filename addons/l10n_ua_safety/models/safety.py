"""Охорона праці: інструктажі на робочому місці і медичні огляди.

Повторний інструктаж - через стільки місяців, скільки в посаді, від останнього пройденого
первинного, повторного або позапланового. Вступний строку не продовжує: це знайомство з
підприємством, а не з робочим місцем. Цільовий - на разову роботу, строку теж не продовжує.

Медогляд з висновком «придатний» або «придатний з обмеженнями» діє до дати в ньому
(за замовчуванням - дата + місяців з посади - 1 день). «Непридатний» - до роботи не допускати.
"""
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

TODO = "mail.mail_activity_data_todo"
BRIEFING_KINDS = [("introductory", "Вступний"), ("primary", "Первинний"), ("repeat", "Повторний"),
                  ("unscheduled", "Позаплановий"), ("targeted", "Цільовий")]
EXTENDS = ("primary", "repeat", "unscheduled")
EXAM_RESULTS = [("fit", "Придатний"), ("limited", "Придатний з обмеженнями"), ("unfit", "Непридатний")]


def _d(day):
    return day.strftime("%d.%m.%Y") if day else ""


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_briefing_months_hazard = fields.Integer(
        "Повторний інструктаж на роботах з підвищеною небезпекою, раз на (міс.)", default=3,
        help="Типове положення про навчання з питань охорони праці: перевірте чинну редакцію.")
    ua_briefing_months_other = fields.Integer("Повторний інструктаж на інших роботах, раз на (міс.)", default=6)
    ua_safety_notify_days = fields.Integer("Нагадувати про охорону праці за, днів", default=14)


class HrJob(models.Model):
    _inherit = "hr.job"

    ua_hazardous = fields.Boolean("Роботи з підвищеною небезпекою")
    ua_briefing_months = fields.Integer("Повторний інструктаж, раз на (міс.)", compute="_compute_ua_briefing_months",
                                        store=True, readonly=False)
    ua_medical_months = fields.Integer("Медогляд, раз на (міс.)", help="0 - періодичний медогляд не потрібен.")
    ua_safety_instructions = fields.Char("Інструкції з охорони праці", help="Номери інструкцій для цієї посади.")

    @api.depends("ua_hazardous", "company_id")
    def _compute_ua_briefing_months(self):
        for job in self:
            company = job.company_id or self.env.company
            job.ua_briefing_months = (company.ua_briefing_months_hazard if job.ua_hazardous
                                      else company.ua_briefing_months_other)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_briefing_line_ids = fields.One2many("ua.safety.briefing.line", "employee_id", "Інструктажі")
    ua_medical_exam_ids = fields.One2many("ua.medical.exam", "employee_id", "Медогляди")
    ua_briefing_last = fields.Date("Останній інструктаж на робочому місці", compute="_compute_ua_safety", store=True)
    ua_briefing_due = fields.Date("Повторний інструктаж до", compute="_compute_ua_safety", store=True)
    ua_medical_valid_until = fields.Date("Медогляд дійсний до", compute="_compute_ua_safety", store=True)
    ua_medical_result = fields.Selection(EXAM_RESULTS, "Висновок медогляду", compute="_compute_ua_safety", store=True)
    ua_safety_alert = fields.Boolean("Не допускати до роботи", compute="_compute_ua_safety_alert",
                                     help="Сьогодні є прострочений інструктаж або медогляд.")

    @api.depends("ua_briefing_line_ids", "ua_briefing_last", "ua_briefing_due", "ua_medical_result",
                 "ua_medical_valid_until", "job_id.ua_medical_months")
    def _compute_ua_safety_alert(self):
        today = fields.Date.context_today(self)
        for employee in self:
            employee.ua_safety_alert = bool(employee.ua_briefing_line_ids) and bool(employee.ua_safety_problems(today))

    @api.depends("ua_briefing_line_ids.passed", "ua_briefing_line_ids.date", "ua_briefing_line_ids.kind",
                 "ua_briefing_line_ids.state", "job_id.ua_briefing_months", "ua_medical_exam_ids.date",
                 "ua_medical_exam_ids.result", "ua_medical_exam_ids.valid_until")
    def _compute_ua_safety(self):
        for employee in self:
            lines = employee.ua_briefing_line_ids.filtered(
                lambda l: l.passed and l.state == "done" and l.kind in EXTENDS)
            last = max(lines.mapped("date"), default=False)
            months = employee.job_id.ua_briefing_months
            employee.ua_briefing_last = last
            employee.ua_briefing_due = last + relativedelta(months=months) - timedelta(days=1) \
                if last and months > 0 else False
            exam = employee.ua_medical_exam_ids.sorted(lambda e: (e.date or date.min, e._origin.id or 0))[-1:]
            employee.ua_medical_result = exam.result or False
            employee.ua_medical_valid_until = exam.valid_until if exam.result in ("fit", "limited") else False

    def ua_safety_problems(self, day=None):
        """Що заважає допустити працівника до роботи в цей день."""
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        problems = []
        if not self.ua_briefing_last:
            problems.append(_("немає інструктажу на робочому місці"))
        elif self.ua_briefing_due and self.ua_briefing_due < day:
            problems.append(_("повторний інструктаж прострочено з %s") % _d(self.ua_briefing_due))
        if self.job_id.ua_medical_months > 0:
            if self.ua_medical_result == "unfit":
                problems.append(_("за медоглядом непридатний"))
            elif not self.ua_medical_valid_until:
                problems.append(_("немає медогляду"))
            elif self.ua_medical_valid_until < day:
                problems.append(_("медогляд прострочено з %s") % _d(self.ua_medical_valid_until))
        return problems

    @api.model
    def _ua_cron_safety(self):
        today = fields.Date.context_today(self)
        todo = self.env.ref(TODO)
        for employee in self.search([("ua_briefing_line_ids", "!=", False)]):
            horizon = today + timedelta(days=max(employee.company_id.ua_safety_notify_days, 0))
            due = []
            if employee.ua_briefing_due and employee.ua_briefing_due <= horizon:
                due.append((_("Повторний інструктаж: %(name)s - до %(date)s", name=employee.name,
                              date=_d(employee.ua_briefing_due)), employee.ua_briefing_due))
            if employee.job_id.ua_medical_months > 0 and employee.ua_medical_valid_until \
                    and employee.ua_medical_valid_until <= horizon:
                due.append((_("Медогляд: %(name)s - до %(date)s", name=employee.name,
                              date=_d(employee.ua_medical_valid_until)), employee.ua_medical_valid_until))
            user = employee.parent_id.user_id or self.env.user
            for summary, deadline in due:
                if employee.activity_ids.filtered(lambda a: a.activity_type_id == todo and a.summary == summary):
                    continue
                employee.activity_schedule(TODO, date_deadline=deadline, summary=summary, user_id=user.id)
        return True


class UaSafetyBriefing(models.Model):
    _name = "ua.safety.briefing"
    _description = "Інструктаж з охорони праці"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    kind = fields.Selection(BRIEFING_KINDS, "Вид", required=True, default="primary", tracking=True)
    instructor_id = fields.Many2one("hr.employee", "Хто проводив", check_company=True)
    instructions = fields.Char("Інструкції", help="Номери або назви інструкцій, за якими проведено.")
    reason = fields.Char("Причина", help="Для позапланового - причина, для цільового - яка робота.")
    job_id = fields.Many2one("hr.job", "Посада", help="Щоб заповнити працівників посади.")
    line_ids = fields.One2many("ua.safety.briefing.line", "briefing_id", "Працівники", copy=True)
    state = fields.Selection([("draft", "Чернетка"), ("done", "Проведено")], "Стан", required=True,
                             default="draft", tracking=True)

    @api.depends("kind", "date")
    def _compute_display_name(self):
        kinds = dict(BRIEFING_KINDS)
        for briefing in self:
            briefing.display_name = "%s %s" % (kinds.get(briefing.kind, ""), _d(briefing.date))

    @api.onchange("job_id")
    def _onchange_job_id(self):
        if self.job_id and not self.instructions:
            self.instructions = self.job_id.ua_safety_instructions

    def action_fill_job(self):
        for briefing in self:
            if not briefing.job_id:
                raise UserError(_("Оберіть посаду."))
            have = briefing.line_ids.employee_id
            employees = self.env["hr.employee"].search([("job_id", "=", briefing.job_id.id),
                                                        ("company_id", "=", briefing.company_id.id)]) - have
            briefing.line_ids = [(0, 0, {"employee_id": employee.id}) for employee in employees]
            if not briefing.instructions:
                briefing.instructions = briefing.job_id.ua_safety_instructions
        return True

    def action_done(self):
        for briefing in self:
            if not briefing.line_ids:
                raise UserError(_("В інструктажі немає працівників."))
            if briefing.kind in ("unscheduled", "targeted") and not briefing.reason:
                raise UserError(_("Для позапланового і цільового інструктажу вкажіть причину."))
        self.write({"state": "done"})
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_safety.action_report_ua_safety_journal").report_action(self)

    def ua_kind_label(self):
        self.ensure_one()
        return dict(BRIEFING_KINDS).get(self.kind, "")

    def ua_date(self, day):
        return _d(day)

    def ua_journal_rows(self):
        """Рядки журналу за датою: № з/п, дата, працівник, посада, вид, інструкції, інструктор."""
        rows = []
        for briefing in self.sorted(lambda b: (b.date, b.id)):
            kind = briefing.ua_kind_label()
            if briefing.reason:
                kind = "%s (%s)" % (kind, briefing.reason)
            instructor = briefing.instructor_id
            who = ", ".join(part for part in (instructor.name, instructor.job_title or instructor.job_id.name) if part)
            for line in briefing.line_ids:
                rows.append({
                    "n": len(rows) + 1, "date": _d(briefing.date), "employee": line.employee_id.name,
                    "job": line.job_name or "", "kind": kind, "instructions": briefing.instructions or "",
                    "instructor": who, "passed": line.passed, "note": line.note or "",
                })
        return rows

    def unlink(self):
        if any(briefing.state == "done" for briefing in self):
            raise UserError(_("Проведений інструктаж з журналу не видаляють."))
        return super().unlink()


class UaSafetyBriefingLine(models.Model):
    _name = "ua.safety.briefing.line"
    _description = "Працівник в інструктажі"
    _order = "date desc, id"

    briefing_id = fields.Many2one("ua.safety.briefing", "Інструктаж", required=True, index=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, index=True)
    job_name = fields.Char("Посада", compute="_compute_job_name", store=True, readonly=False)
    passed = fields.Boolean("Пройшов", default=True, help="Знання перевірено, допущено до роботи.")
    note = fields.Char("Примітка")
    date = fields.Date(related="briefing_id.date", store=True)
    kind = fields.Selection(related="briefing_id.kind", store=True)
    state = fields.Selection(related="briefing_id.state", store=True)

    _employee_uniq = models.Constraint("UNIQUE(briefing_id, employee_id)", "Працівник в інструктажі - один раз.")

    @api.depends("employee_id")
    def _compute_job_name(self):
        for line in self:
            if not line.job_name:
                line.job_name = line.employee_id.job_id.name or line.employee_id.job_title or ""


class UaMedicalExam(models.Model):
    _name = "ua.medical.exam"
    _description = "Медичний огляд працівника"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, index=True, check_company=True,
                                  tracking=True)
    kind = fields.Selection([("preliminary", "Попередній"), ("periodic", "Періодичний"),
                             ("extra", "Позачерговий")], "Вид", required=True, default="periodic")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    result = fields.Selection(EXAM_RESULTS, "Висновок", required=True, default="fit", tracking=True)
    restrictions = fields.Char("Обмеження")
    valid_until = fields.Date("Дійсний до", compute="_compute_valid_until", store=True, readonly=False,
                              precompute=True, tracking=True)
    clinic = fields.Char("Заклад охорони здоров'я")
    document = fields.Char("Акт, довідка №")

    @api.depends("date", "result", "employee_id.job_id.ua_medical_months")
    def _compute_valid_until(self):
        for exam in self:
            months = exam.employee_id.job_id.ua_medical_months
            if exam.result in ("fit", "limited") and exam.date and months > 0:
                exam.valid_until = exam.date + relativedelta(months=months) - timedelta(days=1)
            else:
                exam.valid_until = False

    @api.depends("employee_id", "date")
    def _compute_display_name(self):
        for exam in self:
            exam.display_name = "%s %s" % (exam.employee_id.name or "", _d(exam.date))
