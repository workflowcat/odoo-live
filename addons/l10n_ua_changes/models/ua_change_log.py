# -*- coding: utf-8 -*-
"""Журнал змін: один рядок на одну зміну одного поля одного запису.

Журнал пише сама система, руками рядки не створюють. Бухгалтер читає журнал за
місяць, приймає кожен рядок і тільки після цього закриває період. Рядок з ознакою
«нова» блокує закриття місяця.

Ловить зміни OCA-модуль `auditlog`, рядок черги робить із його запису
models/ua_change_source.py. Тут лишилася сама черга: слова бухгалтера, період,
прийняття і відкат. `auditlog_log_id` веде до технічного запису аудиту (рядки,
старші за прибирання auditlog, лишаються в черзі з порожнім посиланням).
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

AREAS = [
    ("hr", "Кадри"),
    ("time", "Табель"),
    ("payroll", "Зарплата"),
    ("account", "Облік"),
    ("bank", "Банк"),
    ("report", "Звітність"),
    ("setup", "Налаштування"),
]
OPERATIONS = [
    ("create", "Створено"),
    ("write", "Змінено"),
    ("unlink", "Видалено"),
]
STATES = [("new", "Нова"), ("accepted", "Прийнято")]


class UaChangeLog(models.Model):
    _name = "ua.change.log"
    _description = "Журнал змін"
    _order = "date desc, id desc"
    _rec_name = "res_name"

    date = fields.Datetime("Час", required=True, index=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", "Користувач", required=True, index=True,
                              default=lambda s: s.env.user)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda s: s.env.company)
    area = fields.Selection(AREAS, "Ділянка", required=True, index=True)
    operation = fields.Selection(OPERATIONS, "Дія", required=True, index=True)
    model_name = fields.Char("Модель", required=True)
    res_id = fields.Integer("Запис")
    res_name = fields.Char("Назва запису", required=True)
    what = fields.Char("Що змінено")
    old_value = fields.Char("Було")
    new_value = fields.Char("Стало")
    amount = fields.Float("Різниця, грн", digits=(16, 2))
    year = fields.Integer("Рік", required=True, index=True)
    month = fields.Integer("Місяць", required=True, index=True)
    period_label = fields.Char("Період", compute="_compute_period_label", store=True)
    state = fields.Selection(STATES, "Стан", required=True, default="new", index=True)
    accepted_user_id = fields.Many2one("res.users", "Прийняв", readonly=True)
    accepted_date = fields.Datetime("Прийнято", readonly=True)
    note = fields.Char("Примітка бухгалтера")
    auditlog_log_id = fields.Many2one("auditlog.log", "Запис аудиту", readonly=True,
                                      index=True, ondelete="set null")

    _period_ok = models.Constraint("CHECK (month BETWEEN 1 AND 12)", "Місяць від 1 до 12.")

    @api.depends("year", "month")
    def _compute_period_label(self):
        months = self.env["ua.period.close"]._months()
        for rec in self:
            rec.period_label = "%s %s" % (months.get(rec.month, rec.month), rec.year)

    # ------------------------------------------------------------------ дії
    def action_accept(self):
        for rec in self.filtered(lambda r: r.state == "new"):
            rec.write({"state": "accepted", "accepted_user_id": self.env.user.id,
                       "accepted_date": fields.Datetime.now()})
        return True

    def action_reset(self):
        self.write({"state": "new", "accepted_user_id": False, "accepted_date": False})
        return True

    def action_open_record(self):
        self.ensure_one()
        if not self.res_id or self.model_name not in self.env:
            raise UserError(_("Запис уже видалено."))
        if not self.env[self.model_name].browse(self.res_id).exists():
            raise UserError(_("Запис уже видалено."))
        return {"type": "ir.actions.act_window", "res_model": self.model_name,
                "res_id": self.res_id, "view_mode": "form", "views": [(False, "form")],
                "target": "current"}

    @api.model
    def count_new(self, company, year, month):
        company_id = company if isinstance(company, int) else company.id
        return self.search_count([
            ("company_id", "=", company_id), ("year", "=", int(year)),
            ("month", "=", int(month)), ("state", "=", "new"),
        ])

    @api.model
    def accept_period(self, year, month):
        """Прийняти всі нові зміни місяця однією дією."""
        rows = self.search([("company_id", "=", self.env.company.id),
                            ("year", "=", int(year)), ("month", "=", int(month)),
                            ("state", "=", "new")])
        rows.action_accept()
        return len(rows)

    @api.model
    def undo_accept_period(self, year, month, seconds=25):
        """Відкат «Прийняти всі зміни»: щойно прийняті рядки знову стають новими.

        Чесний відкат, не приховування результату. Які саме рядки повертати -
        визначає вікно часу: прийняті цим користувачем за останні `seconds` секунд
        (з запасом над 20-секундною смугою скасування на екрані), бо сама дія
        скасування не знає переліку рядків, які прийняв попередній виклик."""
        since = fields.Datetime.now() - timedelta(seconds=seconds)
        rows = self.search([
            ("company_id", "=", self.env.company.id),
            ("year", "=", int(year)), ("month", "=", int(month)),
            ("state", "=", "accepted"), ("accepted_user_id", "=", self.env.uid),
            ("accepted_date", ">=", since),
        ])
        rows.action_reset()
        return len(rows)
