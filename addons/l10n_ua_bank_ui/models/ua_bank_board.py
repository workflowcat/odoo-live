# -*- coding: utf-8 -*-
"""Дані для клієнтської дії «Банк»: рахунки, завантаження виписок, стан звірки.

Одна модель без збереження (AbstractModel), один публічний метод get_screen_data(year, month)
і перелік ключів дій. Логіка тут не живе: банківські операції - в ua.bank.ops (цей же
модуль, файл без жодного рядка інтерфейсу), рядки «що сплачено, що заплановано» -
в ua.payments.plan (l10n_ua_payments), звідки їх читає і «Зведення».

Джерела: account.journal (банківські журнали), online.bank.statement.provider (з'єднання),
account.bank.statement / account.bank.statement.line (виписки і рядки), account.move.line
(залишок за рахунком журналу).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

INTERVAL_UA = {"minutes": "хв", "hours": "год", "days": "дн", "weeks": "тиж"}
SERVICE_LABEL = {
    "ua_privat": "ПриватБанк (Автоклієнт)",
    "ua_mono": "Monobank",
    "dummy": "Тестовий",
}


class UaBankBoard(models.AbstractModel):
    _name = "ua.bank.board"
    _inherit = ["ua.screen"]
    _description = "Дані екрана «Банк»"

    # ------------------------------------------------------------------ хелпери
    # _r2 / _bounds / _company / _period_block / open_target - у ua.screen
    def _dt(self, value):
        """Час у форматі 11.09.2026 09:15 у поясі користувача."""
        if not value:
            return ""
        return fields.Datetime.context_timestamp(self, value).strftime("%d.%m.%Y %H:%M")

    def _ops(self):
        """Банківські операції і перелік рахунків - логіка, спільна з кроками «Періоду»."""
        return self.env["ua.bank.ops"]

    def _journals(self, company):
        return self._ops()._journals(company)

    @staticmethod
    def _schedule_label(provider):
        """Розклад українською: OCA пише «12 Hour(s)»."""
        if not provider or not provider.active:
            return ""
        return "кожні %s %s" % (provider.interval_number, INTERVAL_UA.get(provider.interval_type, ""))

    def _journal_balance(self, journal):
        """Залишок за рахунком журналу. Валютний рахунок рахуємо у своїй валюті."""
        account = journal.default_account_id
        if not account:
            return 0.0
        company_currency = journal.company_id.currency_id
        foreign = journal.currency_id and journal.currency_id != company_currency
        column = "amount_currency" if foreign else "balance"
        self.env.cr.execute(
            """SELECT COALESCE(SUM(aml.%s), 0) FROM account_move_line aml
               JOIN account_move am ON am.id = aml.move_id
               WHERE aml.account_id = %%s AND am.state = 'posted'""" % column,
            (account.id,),
        )
        return self._r2(self.env.cr.fetchone()[0])

    # ------------------------------------------------------------------ секції
    def _get_accounts(self, company, year, month):
        first, last = self._bounds(year, month)
        Line = self.env["account.bank.statement.line"]
        rows = []
        for journal in self._journals(company):
            provider = journal.online_bank_statement_provider_id
            month_lines = Line.search([
                ("journal_id", "=", journal.id), ("date", ">=", first), ("date", "<=", last),
            ])
            unreconciled = month_lines.filtered(lambda line: not line.is_reconciled)
            amounts = month_lines.mapped("amount")
            rows.append({
                "journal_id": journal.id,
                "name": journal.name,
                "iban": journal.bank_account_id.acc_number or provider.ua_account or "",
                "bank": journal.bank_id.name or "",
                "currency": (journal.currency_id or company.currency_id).name,
                "balance": self._journal_balance(journal),
                "provider_id": provider.id or False,
                "service": provider.service or "",
                "service_label": SERVICE_LABEL.get(provider.service, provider.service or ""),
                "demo": bool(provider.ua_demo),
                "has_token": bool(provider.password),
                "account": provider.ua_account or journal.bank_account_id.acc_number or "",
                "last_run": self._dt(provider.last_successful_run),
                "next_run": self._dt(provider.next_run),
                "schedule": self._schedule_label(provider),
                "active_sync": bool(provider) and provider.active,
                "lines_month": len(month_lines),
                "unreconciled": len(unreconciled),
                "amount_in": self._r2(sum(a for a in amounts if a > 0)),
                "amount_out": self._r2(sum(a for a in amounts if a < 0)),
                "connect": self._connect_row(journal),
            })
        return rows


    def _connect_row(self, journal):
        """Стан підготовки до підключення банку: скільки кроків пройдено і чого чекаємо."""
        connect = self.env["ua.bank.connect"].search([("journal_id", "=", journal.id)], limit=1)
        provider = journal.online_bank_statement_provider_id
        if provider and provider.password and not provider.ua_demo:
            state, label = "live", "ключ працює"
        elif provider and provider.ua_demo:
            state, label = "demo", "демо-дані"
        elif connect and connect.state == "received":
            state, label = "key", "ключ є, треба з'єднати"
        elif connect and connect.done_steps:
            state, label = "prep", "%s з %s кроків" % (connect.done_steps, connect.total_steps)
        else:
            state, label = "none", "не підключено"
        return {"state": state, "label": label, "id": connect.id or False,
                "done": connect.done_steps if connect else 0,
                "total": connect.total_steps if connect else 0}

    def _get_unreconciled(self, company, limit=40):
        lines = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id), ("is_reconciled", "=", False),
        ], order="date desc, id desc", limit=limit)
        return [{
            "id": line.id,
            "journal_id": line.journal_id.id,
            "journal": line.journal_id.name,
            "date": line.date.strftime("%d.%m.%Y") if line.date else "",
            "ref": line.payment_ref or "",
            "partner": line.partner_name or (line.partner_id.name or ""),
            "amount": self._r2(line.amount),
        } for line in lines]

    def _get_statements(self, company, year, month, limit=24):
        first, last = self._bounds(year, month)
        statements = self.env["account.bank.statement"].search([
            ("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
        ], order="date desc, id desc", limit=limit)
        return [{
            "id": statement.id,
            "journal_id": statement.journal_id.id,
            "name": statement.name or "",
            "journal": statement.journal_id.name,
            "date": statement.date.strftime("%d.%m.%Y") if statement.date else "",
            "lines": len(statement.line_ids),
            "amount": self._r2(sum(statement.line_ids.mapped("amount"))),
        } for statement in statements]

    def _get_payments(self, company, year, month):
        rows = self.env["ua.payments.plan"].month_rows(company, year, month)
        return [row for row in rows if row.get("amount")]

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, year=None, month=None):
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        accounts = self._get_accounts(company, year, month)
        return {
            "company": {"name": company.name, "currency": company.currency_id.name},
            "period": self._period_block(year, month),
            "accounts": accounts,
            "payments": self._get_payments(company, year, month),
            "unreconciled": self._get_unreconciled(company),
            "statements": self._get_statements(company, year, month),
            "totals": {
                "balance": self._r2(sum(a["balance"] for a in accounts)),
                "unreconciled": sum(a["unreconciled"] for a in accounts),
                "connected": sum(1 for a in accounts if a["provider_id"]),
                "journals": len(accounts),
            },
        }

    # ------------------------------------------------------------------ дії
    # Клієнт називає ключ дії, не метод. Раніше bank_board.js слав ім'я методу,
    # і викликати можна було будь-що публічне на моделі - відкрита поверхня.
    ACTIONS = {
        "pull": "action_pull",
        "pull_month": "action_pull_month",
        "pull_all": "action_pull_all",
        "test": "action_test",
        "apply_rules": "action_apply_rules",
        "import_file": "action_import_file",
        "create_provider": "action_create_provider",
        "open_rules": "action_open_rules",
        "open_reconcile": "action_open_reconcile",
        "open_lines": "action_open_lines",
        "open_statements": "action_open_statements",
        "open_providers": "action_open_providers",
        "open_connect": "action_open_connect",
    }

    # Ключі, за якими стоїть банківська логіка, а не екран: їх виконує ua.bank.ops.
    OPS_ACTIONS = ("pull", "pull_month", "pull_all", "test", "apply_rules",
                   "create_provider", "open_providers")

    @api.model
    def run_action(self, key, params=None):
        """Одна дія екрана за ключем зі списку ACTIONS. Чужий ключ - відмова."""
        method = self.ACTIONS.get(key)
        if not method:
            raise UserError(_("Невідома дія: %s") % key)
        target = self._ops() if key in self.OPS_ACTIONS else self
        return getattr(target, method)(**dict(params or {}))

    @api.model
    def action_open_rules(self):
        return self.env["ir.actions.act_window"]._for_xml_id("account.action_account_reconcile_model")

    @api.model
    def _journal_or_all(self, journal_id):
        """Журнал за номером. Без номера - усі банківські журнали компанії.

        Прямий перехід до звірки не має падати: якщо рахунок не вибрано, показуємо всі."""
        company = self._company()
        if journal_id:
            journal = self.env["account.journal"].browse(int(journal_id)).exists()
            if journal and journal.company_id == company:
                return journal
        return self._journals(company)

    @api.model
    def action_open_reconcile(self, journal_id=None):
        journals = self._journal_or_all(journal_id)
        if not journals:
            raise UserError(_("У компанії немає банківського журналу."))
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_reconcile_oca.action_bank_statement_line_reconcile")
        action["domain"] = [("journal_id", "in", journals.ids)]
        action["context"] = {
            "default_journal_id": journals[:1].id,
            "search_default_not_reconciled": True,
            "view_ref": "account_reconcile_oca.bank_statement_line_form_reconcile_view",
        }
        action["name"] = _("Звірка: %s") % (journals.name if len(journals) == 1 else _("усі рахунки"))
        return action

    @api.model
    def action_open_lines(self, journal_id=None):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_statement_base.action_bank_statement_line")
        if journal_id:
            action["domain"] = [("journal_id", "=", int(journal_id))]
        return action

    @api.model
    def action_open_statements(self, journal_id=None):
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_bank_statement_tree")
        if journal_id:
            action["domain"] = [("journal_id", "=", int(journal_id))]
        return action

    @api.model
    def action_open_connect(self, journal_id):
        if not journal_id:
            raise UserError(_("Виберіть рахунок зліва."))
        """Відкрити чек-лист підключення банку. Якщо його немає, створити."""
        connect = self.env["ua.bank.connect"].for_journal(int(journal_id))
        return {"type": "ir.actions.act_window", "res_model": "ua.bank.connect",
                "res_id": connect.id, "view_mode": "form", "views": [(False, "form")],
                "target": "current"}

    @api.model
    def action_import_file(self, journal_id=None):
        """Завантажити виписку файлом. Працює, поки немає ключа банку."""
        action = dict(self.env["ir.actions.actions"]._for_xml_id(
            "account_statement_import_file.account_statement_import_action"))
        if journal_id:
            action["context"] = {"journal_id": int(journal_id),
                                 "default_journal_id": int(journal_id)}
        return action
