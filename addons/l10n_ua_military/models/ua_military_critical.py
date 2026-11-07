# -*- coding: utf-8 -*-
"""Статус критично важливого підприємства і квота бронювання.

Бронювати військовозобов'язаних працівників на період мобілізації та воєнний час
підприємство може, поки має чинне рішення про статус критично важливого (постанова КМУ
№ 76 від 27.01.2023 і її зміни). Рішення має строк. Квота - частка військовозобов'язаних
працівників, яку можна забронювати; критерій зарплати - кратність мінімальній зарплаті.
Обидва числа і строки беруться з рішення і чинної редакції постанови, тому вони стоять на
записі статусу: значення за замовчуванням - лише заготовка, яку звіряє кадровик.

Квота рахується так: військовозобов'язані працівники компанії (трудовий договір, не ЦПХ і
не ФОП) на дату, із них заброньовані з чинним строком бронювання; квота - ціла частина від
частки. Призовники й резервісти в базу квоти не входять.
"""
from datetime import timedelta
import math

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CRITERIA = [
    ("defense", "Оборонно-промисловий комплекс, оборонне замовлення"),
    ("forces", "Потреби Збройних Сил та інших військових формувань"),
    ("economy", "Значення для національної економіки"),
    ("life", "Забезпечення життєдіяльності населення"),
    ("other", "Інший критерій"),
]
QUOTA_STATUSES = ("liable",)
NOT_EMPLOYMENT = ("gph", "fop")
TODO = "mail.mail_activity_data_todo"


class UaMilitaryCritical(models.Model):
    _name = "ua.military.critical"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Статус критично важливого підприємства"
    _order = "date_from desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda s: s.env.company)
    authority = fields.Char("Хто прийняв рішення", required=True, tracking=True,
                            help="Міністерство, інший центральний орган або обласна військова "
                                 "адміністрація.")
    decision_number = fields.Char("Рішення №", tracking=True)
    decision_date = fields.Date("Рішення від")
    criterion = fields.Selection(CRITERIA, "Критерій", required=True, default="defense")
    date_from = fields.Date("Діє з", required=True, tracking=True)
    date_to = fields.Date("Діє до", required=True, tracking=True)
    quota_percent = fields.Float(
        "Квота бронювання, %", default=50.0, tracking=True,
        help="Частка військовозобов'язаних працівників, яку можна забронювати. Звірте з "
             "рішенням і чинною редакцією постанови № 76.")
    wage_multiplier = fields.Float(
        "Зарплата заброньованого, мінімальних", default=0.0, tracking=True,
        help="Оклад заброньованого працівника - не менше стількох мінімальних зарплат на дату. "
             "0 - не перевіряти.")
    notify_days = fields.Integer(
        "Нагадати за, днів", default=30,
        help="За скільки днів до кінця статусу чи бронювання працівника ставити нагадування.")
    dismissal_days = fields.Integer(
        "Повідомити про звільнення за, днів", default=5,
        help="Строк повідомлення після звільнення заброньованого працівника. Звірте з чинною "
             "редакцією постанови № 76.")
    user_id = fields.Many2one("res.users", "Відповідальний за бронювання", required=True,
                              default=lambda s: s.env.user, tracking=True)
    note = fields.Text("Примітка")
    is_current = fields.Boolean("Чинний сьогодні", compute="_compute_is_current")

    @api.depends("date_from", "date_to", "authority")
    def _compute_name(self):
        for status in self:
            period = "%s - %s" % (status.date_from.strftime("%d.%m.%Y") if status.date_from else "",
                                  status.date_to.strftime("%d.%m.%Y") if status.date_to else "")
            status.name = _("Критично важливе підприємство, %s") % period

    @api.depends("date_from", "date_to")
    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for status in self:
            status.is_current = bool(status.date_from and status.date_to
                                     and status.date_from <= today <= status.date_to)

    @api.constrains("date_from", "date_to", "company_id", "quota_percent")
    def _check_period(self):
        for status in self:
            if status.date_from > status.date_to:
                raise ValidationError(_("Статус закінчується раніше, ніж починається."))
            if not 0 < status.quota_percent <= 100:
                raise ValidationError(_("Квота - від 0 до 100 відсотків."))
            overlap = self.search_count([
                ("id", "!=", status.id), ("company_id", "=", status.company_id.id),
                ("date_from", "<=", status.date_to), ("date_to", ">=", status.date_from)])
            if overlap:
                raise ValidationError(_("На ці дати в компанії вже є статус критично важливого. "
                                        "Новий статус починається після кінця попереднього."))

    @api.model
    def _current(self, company, date=None):
        """Статус, чинний на дату, або порожній запис."""
        date = date or fields.Date.context_today(self)
        return self.search([("company_id", "=", company.id), ("date_from", "<=", date),
                            ("date_to", ">=", date)], limit=1)

    def _min_wage(self, date):
        """Мінімальна зарплата на дату: запис компанії, а без нього - загальний."""
        Param = self.env["ua.payroll.param"].sudo()
        for company in (self.company_id.id, False):
            param = Param.search([("key", "=", "min_wage"), ("valid_from", "<=", date),
                                  ("company_id", "=", company)], order="valid_from desc", limit=1)
            if param:
                return param.value
        return 0.0

    def wage_floor(self, date=None):
        """Нижня межа окладу заброньованого на дату; 0 - межі немає або невідома МЗП."""
        self.ensure_one()
        if not self.wage_multiplier:
            return 0.0
        return round(self._min_wage(date or fields.Date.context_today(self)) * self.wage_multiplier, 2)

    def quota_counts(self, date=None):
        """{liable, reserved, quota, free} для компанії статусу на дату."""
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        Employee = self.env["hr.employee"]
        liable = Employee._ua_quota_base(self.company_id)
        reserved = liable.filtered(lambda e: e._ua_is_reserved(date))
        quota = math.floor(len(liable) * self.quota_percent / 100.0 + 1e-9)
        return {"liable": len(liable), "reserved": len(reserved), "quota": quota,
                "free": quota - len(reserved)}

    # --------------------------------------------------------------- нагадування
    def _remind(self, record, summary, deadline):
        """Одне нагадування з таким текстом на запис: повтор не ставимо."""
        todo = self.env.ref(TODO)
        if record.activity_ids.filtered(lambda a: a.activity_type_id == todo
                                        and a.summary == summary):
            return False
        record.activity_schedule(TODO, date_deadline=deadline, summary=summary,
                                 user_id=self.user_id.id)
        return True

    @api.model
    def _cron_reminders(self):
        """Щодня: кінець статусу і кінець бронювання працівників - за notify_days днів."""
        today = fields.Date.context_today(self)
        Employee = self.env["hr.employee"].sudo()
        for company in self.env["res.company"].search([]):
            status = self.search([("company_id", "=", company.id), ("date_from", "<=", today)],
                                 limit=1)
            if not status:
                continue
            horizon = today + timedelta(days=status.notify_days)
            if today <= status.date_to <= horizon:
                status._remind(status, _("Продовжити статус критично важливого: діє до %s")
                               % status.date_to.strftime("%d.%m.%Y"), status.date_to)
            for employee in Employee.search([
                    ("company_id", "=", company.id), ("ua_mil_reserved", "=", True),
                    ("ua_mil_reserve_until", ">=", today),
                    ("ua_mil_reserve_until", "<=", horizon)]):
                status._remind(employee, _("Продовжити бронювання: до %s")
                               % employee.ua_mil_reserve_until.strftime("%d.%m.%Y"),
                               employee.ua_mil_reserve_until)

    def action_reserved_list(self):
        """Список заброньованих на сьогодні з квотою цього статусу."""
        self.ensure_one()
        return self.env["ua.military.reserved"].with_company(self.company_id).action_compose_today()


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def _ua_quota_base(self, company):
        """Військовозобов'язані працівники компанії за трудовим договором - база квоти."""
        return self.sudo().search([
            ("company_id", "=", company.id), ("ua_mil_status", "in", QUOTA_STATUSES),
            ("ua_contract_kind", "not in", NOT_EMPLOYMENT)])

    def _ua_is_reserved(self, date):
        self.ensure_one()
        employee = self.sudo()
        return bool(employee.ua_mil_reserved and (
            not employee.ua_mil_reserve_until or employee.ua_mil_reserve_until >= date))

    def write(self, vals):
        leaving = self.env["hr.employee"]
        if vals.get("active") is False:
            leaving = self.sudo().filtered(lambda e: e.active and e.ua_mil_reserved)
        result = super().write(vals)
        if leaving:
            leaving._ua_reserved_left()
        return result

    def _ua_reserved_left(self):
        """Звільнено заброньованого: подія обліку і нагадування повідомити про звільнення."""
        today = fields.Date.context_today(self)
        Status = self.env["ua.military.critical"].sudo()
        for employee in self.sudo():
            self.env["ua.military.event"].sudo().create({
                "employee_id": employee.id, "date": today, "kind": "reserve",
                "note": _("Звільнення заброньованого працівника: бронювання припиняється")})
            status = Status._current(employee.company_id, today) or Status.search(
                [("company_id", "=", employee.company_id.id)], limit=1)
            if status:
                status._remind(status, _("Повідомити про звільнення заброньованого: %s")
                               % employee.name, today + timedelta(days=status.dismissal_days))
