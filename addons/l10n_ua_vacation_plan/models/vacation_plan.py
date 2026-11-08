# -*- coding: utf-8 -*-
"""Графік відпусток на рік (ст. 10, 12 ЗУ «Про відпустки»).

- Графік затверджує роботодавець за погодженням із профспілкою або іншим представницьким органом
  працівників: без запису «з ким погоджено» графік не затвердити.
- Щорічну відпустку можна ділити на частини, але одна безперервна частина - щонайменше 14
  календарних днів (налаштування графіка, типово 14).
- Про дату початку відпустки працівника письмово повідомляють щонайменше за два тижні (налаштування
  графіка, типово 14 днів): щоденний крон ставить кадровику завдання, друкується повідомлення.
- Днів у працівника: залишок нарахувань виду відпустки на 1 січня плюс річне право (типово 24).
Дні - календарні; святкові дні на час воєнного стану з відпустки не виключаються, як і в
l10n_ua_average. Числа - налаштування; перевіряйте чинну редакцію закону.
"""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PLAN_STATES = [("draft", "Чернетка"), ("approved", "Затверджено")]
LINE_STATES = [
    ("planned", "Заплановано"),
    ("notified", "Повідомлено"),
    ("leave", "Заявку створено"),
    ("moved", "Перенесено"),
]


def _ua_date(day):
    return day.strftime("%d.%m.%Y") if day else ""


class UaVacationPlan(models.Model):
    _name = "ua.vacation.plan"
    _description = "Графік відпусток"
    _inherit = ["mail.thread", "mail.activity.mixin", "ua.checks.mixin"]
    _order = "year desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True, default=lambda self: self.env.company)
    year = fields.Integer(
        "Рік", required=True, tracking=True, default=lambda self: fields.Date.context_today(self).year + 1)
    department_id = fields.Many2one(
        "hr.department", string="Підрозділ", help="Порожньо - уся компанія.")
    user_id = fields.Many2one(
        "res.users", string="Відповідальний кадровик", default=lambda self: self.env.user, tracking=True)
    leave_type_id = fields.Many2one(
        "hr.leave.type", string="Вид відпустки", required=True,
        default=lambda self: self.env.ref("l10n_ua_average.lt_vac", raise_if_not_found=False))
    state = fields.Selection(PLAN_STATES, string="Стан", default="draft", required=True, tracking=True)
    agreed_with = fields.Char(
        "Погоджено з", tracking=True,
        help="Профспілковий комітет або інший представницький орган працівників, протокол і дата.")
    approved_date = fields.Date("Дата затвердження", tracking=True)
    days_per_year = fields.Float(
        "Днів на рік", default=24.0,
        help="Річне право на щорічну основну відпустку для підказки «днів є» (ст. 6 ЗУ «Про відпустки»).")
    min_part_days = fields.Integer(
        "Найкоротша основна частина, днів", default=14,
        help="Одна безперервна частина щорічної відпустки щонайменше стільки календарних днів (ст. 12).")
    notice_days = fields.Integer(
        "Повідомити за, днів", default=14,
        help="За скільки днів до початку відпустки письмово повідомити працівника (ст. 10).")
    line_ids = fields.One2many("ua.vacation.plan.line", "plan_id", string="Відпустки")
    employee_count = fields.Integer("Працівників", compute="_compute_counts")
    days_total = fields.Float("Днів заплановано", compute="_compute_counts")

    @api.depends("year", "department_id")
    def _compute_name(self):
        for plan in self:
            plan.name = _("Графік відпусток на %s рік") % plan.year + (
                " - %s" % plan.department_id.name if plan.department_id else "")

    @api.depends("line_ids.employee_id", "line_ids.days")
    def _compute_counts(self):
        for plan in self:
            plan.employee_count = len(plan.line_ids.employee_id)
            plan.days_total = sum(plan.line_ids.mapped("days"))

    # ------------------------------------------------------------------ працівники
    def _ua_employees(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id)]
        if self.department_id:
            domain.append(("department_id", "child_of", self.department_id.id))
        employees = self.env["hr.employee"].search(domain)
        if "ua_contract_kind" in employees._fields:
            employees = employees.sudo().filtered(lambda e: e.ua_contract_kind == "employment")
        return employees

    def ua_balance(self, employee):
        """Невикористані дні виду відпустки за затвердженими нарахуваннями на 1 січня року."""
        self.ensure_one()
        start = date(self.year, 1, 1)
        allocations = self.env["hr.leave.allocation"].sudo().search([
            ("employee_id", "=", employee.id), ("holiday_status_id", "=", self.leave_type_id.id),
            ("state", "=", "validate"), ("date_from", "<", start)])
        return round(sum(a.number_of_days - a.leaves_taken for a in allocations), 2)

    # ------------------------------------------------------------------ дії
    def action_fill(self):
        """Рядок без дат кожному працівнику, якого ще немає в графіку."""
        for plan in self:
            if plan.state != "draft":
                raise UserError(_("Заповнюють чернетку графіка."))
            present = plan.line_ids.employee_id
            for employee in plan._ua_employees() - present:
                self.env["ua.vacation.plan.line"].create({"plan_id": plan.id, "employee_id": employee.id})
        return True

    def action_approve(self):
        for plan in self:
            if not (plan.agreed_with or "").strip():
                raise UserError(_("Графік затверджують за погодженням із профспілкою або іншим "
                                  "представницьким органом: заповніть «Погоджено з»."))
            errors = [c for c in plan._checks() if c["level"] == "error"]
            if errors:
                raise UserError(_("Графік має помилки:\n%s") % "\n".join(
                    "- %s: %s" % (c["text"], c["fact"]) for c in errors))
            plan.write({"state": "approved", "approved_date": plan.approved_date or fields.Date.context_today(plan)})
        return True

    def action_draft(self):
        for plan in self:
            if plan.line_ids.filtered("leave_id"):
                raise UserError(_("За графіком уже створено заявки на відпустку: змінюйте рядки переносом."))
            plan.state = "draft"
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_vacation_plan.action_report_ua_vacation_plan").report_action(self)

    @api.model
    def ua_date_text(self, day):
        """Дата для друку: 01.07.2026; порожньо - підкреслення."""
        return _ua_date(day) or "__.__.____"

    @api.model
    def _ua_cron_notices(self):
        """Завдання кадровику: настав день письмово повідомити працівника про початок відпустки."""
        today = fields.Date.context_today(self)
        lines = self.env["ua.vacation.plan.line"].search([
            ("plan_id.state", "=", "approved"), ("state", "in", ("planned", "moved")),
            ("notice_date", "<=", today), ("date_from", ">=", today)])
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for line in lines:
            if line.activity_done:
                continue
            line.plan_id.activity_schedule(
                activity_type_id=activity_type.id if activity_type else False,
                summary=_("Повідомити про відпустку: %s") % line.employee_id.name,
                note=_("Відпустка з %(start)s по %(end)s. Надрукуйте повідомлення й отримайте підпис.",
                       start=_ua_date(line.date_from), end=_ua_date(line.date_to)),
                user_id=(line.plan_id.user_id or self.env.user).id, date_deadline=line.notice_date)
            line.activity_done = True
        return True

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        checks = []
        lines = self.line_ids
        undated = lines.filtered(lambda l: not (l.date_from and l.date_to))
        if undated:
            checks.append(self._check_error("Немає дат відпустки", len(undated),
                                            self._target_records(undated)))
        bad = lines.filtered(lambda l: l.date_from and l.date_to and l.date_from > l.date_to)
        if bad:
            checks.append(self._check_error("Початок пізніше за кінець", len(bad), self._target_records(bad)))
        outside = lines.filtered(lambda l: l.date_from and l.date_from.year != self.year)
        if outside:
            checks.append(self._check_error("Початок не в році графіка", len(outside),
                                            self._target_records(outside)))
        overlap, short, over = self.env["ua.vacation.plan.line"], [], []
        for employee in lines.employee_id:
            own = lines.filtered(lambda l: l.employee_id == employee and l.date_from and l.date_to)
            ordered = own.sorted("date_from")
            for first, second in zip(ordered, ordered[1:]):
                if second.date_from <= first.date_to:
                    overlap |= first | second
            total = sum(own.mapped("days"))
            if total >= self.min_part_days and max(own.mapped("days") or [0]) < self.min_part_days:
                short.append(employee.name)
            available = own[:1].days_available if own else 0.0
            if own and total > available:
                over.append("%s (%s з %s)" % (employee.name, int(total), int(available)))
        if overlap:
            checks.append(self._check_error("Частини відпустки перетинаються", len(overlap),
                                            self._target_records(overlap)))
        if short:
            checks.append(self._check_warn(
                "Немає безперервної частини щонайменше %s днів" % self.min_part_days, ", ".join(short)))
        if over:
            checks.append(self._check_warn("Заплановано більше, ніж є днів", ", ".join(over)))
        missing = self._ua_employees() - self.line_ids.employee_id
        if missing:
            checks.append(self._check_warn("Працівники без відпустки в графіку", ", ".join(missing.mapped("name")),
                                           self._target_records(missing)))
        if not checks:
            checks.append(self._check_ok("Графік без зауважень", len(self.line_ids)))
        return checks


class UaVacationPlanLine(models.Model):
    _name = "ua.vacation.plan.line"
    _description = "Відпустка в графіку"
    _order = "plan_id, department_name, employee_name, date_from"

    plan_id = fields.Many2one("ua.vacation.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True)
    plan_state = fields.Selection(related="plan_id.state")
    employee_id = fields.Many2one("hr.employee", string="Працівник", required=True, ondelete="restrict")
    employee_name = fields.Char(related="employee_id.name", store=True)
    department_name = fields.Char(related="employee_id.department_id.name", store=True, string="Підрозділ")
    job_title = fields.Char(related="employee_id.job_title", string="Посада")
    date_from = fields.Date("З")
    date_to = fields.Date("По")
    days = fields.Integer("Днів", compute="_compute_days", store=True)
    days_available = fields.Float(
        "Днів є", compute="_compute_days_available",
        help="Невикористаний залишок на 1 січня плюс річне право з налаштувань графіка.")
    convenient_time = fields.Boolean(
        "Право на зручний час", help="Категорії, яким відпустку надають у зручний для них час (ст. 10).")
    note = fields.Char("Примітка")
    notice_date = fields.Date("Повідомити до", compute="_compute_notice_date", store=True)
    notified_date = fields.Date("Повідомлено", copy=False)
    activity_done = fields.Boolean(copy=False)
    original_from = fields.Date("Було з", readonly=True, copy=False)
    original_to = fields.Date("Було по", readonly=True, copy=False)
    move_reason = fields.Char("Підстава переносу", copy=False)
    leave_id = fields.Many2one("hr.leave", string="Заявка на відпустку", copy=False, readonly=True)
    state = fields.Selection(LINE_STATES, string="Стан", compute="_compute_state", store=True)

    @api.depends("date_from", "date_to")
    def _compute_days(self):
        for line in self:
            if line.date_from and line.date_to and line.date_to >= line.date_from:
                line.days = (line.date_to - line.date_from).days + 1
            else:
                line.days = 0

    @api.depends("employee_id", "plan_id.year", "plan_id.leave_type_id", "plan_id.days_per_year")
    def _compute_days_available(self):
        for line in self:
            if line.employee_id and line.plan_id:
                line.days_available = line.plan_id.ua_balance(line.employee_id) + line.plan_id.days_per_year
            else:
                line.days_available = 0.0

    @api.depends("date_from", "plan_id.notice_days")
    def _compute_notice_date(self):
        for line in self:
            line.notice_date = line.date_from - timedelta(days=line.plan_id.notice_days or 0) \
                if line.date_from else False

    @api.depends("notified_date", "leave_id", "original_from")
    def _compute_state(self):
        for line in self:
            if line.leave_id:
                line.state = "leave"
            elif line.notified_date:
                line.state = "notified"
            elif line.original_from:
                line.state = "moved"
            else:
                line.state = "planned"

    def write(self, vals):
        if {"date_from", "date_to", "employee_id"} & set(vals) and \
                self.filtered(lambda l: l.plan_id.state == "approved") and not self.env.context.get("ua_vacation_move"):
            raise UserError(_("Дати затвердженого графіка змінюють переносом: кнопка «Перенести» з підставою."))
        return super().write(vals)

    def action_move(self, date_from, date_to, reason):
        """Перенести відпустку: старі дати лишаються в рядку, нові - з підставою."""
        for line in self:
            if not (reason or "").strip():
                raise UserError(_("Напишіть підставу переносу (заява працівника, наказ)."))
            if line.leave_id:
                raise UserError(_("За відпусткою вже є заявка: скасуйте її перед переносом."))
            values = {"date_from": date_from, "date_to": date_to, "move_reason": reason,
                      "notified_date": False, "activity_done": False}
            if not line.original_from:
                values.update({"original_from": line.date_from, "original_to": line.date_to})
            line.with_context(ua_vacation_move=True).write(values)
            line.plan_id.message_post(body=_("%(name)s: відпустку перенесено з %(old)s на %(new)s. %(why)s",
                                             name=line.employee_id.name, old=_ua_date(values.get("original_from") or line.original_from),
                                             new=_ua_date(date_from), why=reason))
        return True

    def action_open_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Перенести відпустку"),
            "res_model": "ua.vacation.move.wizard", "view_mode": "form", "target": "new",
            "context": {"default_line_id": self.id, "default_date_from": self.date_from,
                        "default_date_to": self.date_to},
        }

    def action_notified(self):
        for line in self:
            line.notified_date = fields.Date.context_today(line)
        return True

    def action_print_notice(self):
        self.filtered(lambda l: not l.notified_date).action_notified()
        return self.env.ref("l10n_ua_vacation_plan.action_report_ua_vacation_notice").report_action(self)

    def action_create_leave(self):
        """Заявка на відпустку за датами графіка; погоджують її звичайним порядком."""
        for line in self:
            if line.plan_id.state != "approved":
                raise UserError(_("Заявки створюють за затвердженим графіком."))
            if line.leave_id:
                continue
            if not (line.date_from and line.date_to):
                raise UserError(_("У рядку немає дат відпустки."))
            leave = self.env["hr.leave"].sudo().create({
                "employee_id": line.employee_id.id, "holiday_status_id": line.plan_id.leave_type_id.id,
                "request_date_from": line.date_from, "request_date_to": line.date_to,
            })
            line.leave_id = leave
        return True

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for line in self:
            if line.date_from and line.date_to and line.date_from > line.date_to:
                raise ValidationError(_("Початок відпустки пізніше за кінець."))
