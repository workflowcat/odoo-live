# -*- coding: utf-8 -*-
"""Підключення банку: чек-лист до того, як з'явиться ключ.

Ключів банку ще немає. Поки їх немає, виписку вантажать файлом, а підключення
готують за списком кроків: хто відкриває доступ, хто видає ключ, де ключ лежить,
хто його міняє. Кожен крок має виконавця і позначку про виконання.

Коли ключ з'явиться, кнопка «Створити з'єднання» робить запис постачальника виписок
із потрібною службою і рахунком. Сам ключ у чек-лист не пишемо.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

SERVICES = [("ua_privat", "ПриватБанк (Автоклієнт)"), ("ua_mono", "Monobank")]
STATES = [
    ("draft", "Готуємо"),
    ("requested", "Ключ замовлено"),
    ("received", "Ключ отримано"),
    ("connected", "Підключено"),
]
WHO = [("client", "Клієнт"), ("accountant", "Бухгалтер"), ("it", "Технічний спеціаліст")]

# Кроки за службою: (виконавець, крок, підказка)
STEPS = {
    "ua_privat": [
        ("client", "Перевірити доступ до Приват24 для бізнесу",
         "Потрібен користувач із правом підпису. Без нього банк ключ не видасть."),
        ("client", "Увімкнути Автоклієнт у Приват24 для бізнесу",
         "Меню «Налаштування» → «Автоклієнт». Доступ вмикає керівник."),
        ("client", "Отримати ідентифікатор клієнта і токен",
         "Банк показує токен один раз. Збережіть його одразу."),
        ("client", "Записати перелік рахунків під цим ключем",
         "Один ключ дає виписку за всіма рахунками клієнта."),
        ("client", "Передати ключ захищеним каналом",
         "Не надсилайте ключ поштою або в месенджері звичайним текстом."),
        ("it", "Покласти ключ у сховище",
         "Секрет Worker для хмари або поле з'єднання для локального стенду."),
        ("accountant", "Перевірити зв'язок і завантажити перший день",
         "Кнопка «Перевірити зв'язок» на екрані «Банк»."),
        ("accountant", "Поставити розклад завантаження",
         "Типово кожні 12 годин. Перше завантаження робимо вручну."),
    ],
    "ua_mono": [
        ("client", "Визначити вид рахунку",
         "Особистий рахунок або mono Бізнес. Ключі різні."),
        ("client", "Створити токен у кабінеті",
         "mono Бізнес: «Інтеграції» → «API». Особистий рахунок: index.monobank.ua."),
        ("client", "Отримати ідентифікатор рахунку",
         "Метод /personal/client-info повертає список рахунків."),
        ("client", "Передати ключ захищеним каналом",
         "Не надсилайте ключ поштою або в месенджері звичайним текстом."),
        ("it", "Покласти ключ у сховище",
         "Секрет Worker для хмари або поле з'єднання для локального стенду."),
        ("accountant", "Врахувати обмеження банку",
         "Один запит на 60 секунд. Одне вікно не більше 31 дня."),
        ("accountant", "Перевірити зв'язок і завантажити перший день",
         "Кнопка «Перевірити зв'язок» на екрані «Банк»."),
        ("accountant", "Поставити розклад завантаження",
         "Типово кожні 12 годин. Перше завантаження робимо вручну."),
    ],
}


class UaBankConnect(models.Model):
    _name = "ua.bank.connect"
    _description = "Підключення банку"
    _order = "id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda s: s.env.company)
    journal_id = fields.Many2one("account.journal", "Банківський журнал", required=True,
                                 domain="[('type', '=', 'bank')]")
    service = fields.Selection(SERVICES, "Служба банку", required=True, default="ua_privat")
    state = fields.Selection(STATES, "Стан", default="draft", required=True)
    account = fields.Char("Рахунок у банку", help="IBAN для ПриватБанку, ідентифікатор рахунку для Monobank")
    key_holder = fields.Char("Хто тримає ключ", help="Посада і прізвище людини, яка відповідає за ключ")
    key_place = fields.Selection([("worker", "Секрет Worker (хмара)"), ("odoo", "Поле з'єднання в Odoo")],
                                 "Де лежить ключ", default="worker")
    key_rotate_months = fields.Integer("Міняти ключ, місяців", default=12)
    requested_date = fields.Date("Ключ замовлено")
    received_date = fields.Date("Ключ отримано")
    provider_id = fields.Many2one("online.bank.statement.provider", "З'єднання", readonly=True)
    note = fields.Text("Примітка")
    step_ids = fields.One2many("ua.bank.connect.step", "connect_id", "Кроки")
    done_steps = fields.Integer("Виконано кроків", compute="_compute_progress")
    total_steps = fields.Integer("Усього кроків", compute="_compute_progress")

    @api.depends("journal_id", "service")
    def _compute_name(self):
        labels = dict(SERVICES)
        for rec in self:
            rec.name = "%s · %s" % (rec.journal_id.name or "-", labels.get(rec.service, ""))

    @api.depends("step_ids.done")
    def _compute_progress(self):
        for rec in self:
            rec.total_steps = len(rec.step_ids)
            rec.done_steps = len(rec.step_ids.filtered("done"))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.step_ids:
                rec.action_fill_steps()
        return records

    def action_fill_steps(self):
        """Наповнити чек-лист кроками для обраної служби."""
        for rec in self:
            rec.step_ids.unlink()
            rec.step_ids = [(0, 0, {
                "sequence": (index + 1) * 10, "who": who, "name": name, "hint": hint,
            }) for index, (who, name, hint) in enumerate(STEPS.get(rec.service, []))]
        return True

    def action_create_provider(self):
        """Зробити з'єднання, коли ключ уже є. Ключ вписує людина, не система."""
        self.ensure_one()
        if self.provider_id:
            raise UserError(_("З'єднання вже створено."))
        provider = self.env["online.bank.statement.provider"].create({
            "journal_id": self.journal_id.id,
            "service": self.service,
            "ua_account": self.account or "",
            "active": True,
        })
        self.write({"provider_id": provider.id, "state": "connected"})
        return {"type": "ir.actions.act_window", "res_model": "online.bank.statement.provider",
                "res_id": provider.id, "view_mode": "form", "views": [(False, "form")],
                "target": "current"}

    @api.model
    def for_journal(self, journal):
        """Картка підключення журналу. Створюємо порожню, якщо її ще немає."""
        journal_id = journal if isinstance(journal, int) else journal.id
        rec = self.search([("journal_id", "=", journal_id)], limit=1)
        if not rec:
            provider = self.env["account.journal"].browse(journal_id).online_bank_statement_provider_id
            rec = self.create({
                "journal_id": journal_id,
                "service": provider.service if provider.service in dict(SERVICES) else "ua_privat",
                "account": provider.ua_account or "",
                "state": "connected" if (provider and provider.password) else "draft",
                "provider_id": provider.id or False,
            })
        return rec


class UaBankConnectStep(models.Model):
    _name = "ua.bank.connect.step"
    _description = "Крок підключення банку"
    _order = "sequence, id"

    connect_id = fields.Many2one("ua.bank.connect", "Підключення", required=True, ondelete="cascade")
    sequence = fields.Integer("Порядок", default=10)
    name = fields.Char("Крок", required=True)
    hint = fields.Char("Підказка")
    who = fields.Selection(WHO, "Виконавець", default="accountant", required=True)
    done = fields.Boolean("Виконано")
    done_date = fields.Date("Дата", readonly=True)
    note = fields.Char("Примітка")

    def write(self, vals):
        if "done" in vals:
            vals["done_date"] = fields.Date.context_today(self) if vals["done"] else False
        return super().write(vals)
