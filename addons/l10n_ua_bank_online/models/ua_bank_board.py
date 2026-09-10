# -*- coding: utf-8 -*-
"""Дані для клієнтської дії «Банк»: рахунки, завантаження виписок, стан звірки.

Одна модель без збереження (AbstractModel), один публічний метод get_screen_data(year, month)
і кілька дій-кнопок. Логіка платежів не дублюється: рядки «що сплачено, що заплановано»
беремо з `ua.dashboard._get_payments`, як на «Зведенні».

Джерела: account.journal (банківські журнали), online.bank.statement.provider (з'єднання),
account.bank.statement / account.bank.statement.line (виписки і рядки), account.move.line
(залишок за рахунком журналу).
"""
import re
from datetime import date, datetime, time, timedelta

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
    _description = "Дані екрана «Банк»"

    # ------------------------------------------------------------------ хелпери
    @staticmethod
    def _r2(value):
        return round(value or 0.0, 2)

    @staticmethod
    def _month_bounds(year, month):
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return first, last

    def _dt(self, value):
        """Час у форматі 11.09.2026 09:15 у поясі користувача."""
        if not value:
            return ""
        return fields.Datetime.context_timestamp(self, value).strftime("%d.%m.%Y %H:%M")

    def _company(self):
        return self.env.company

    def _journals(self, company):
        return self.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", company.id),
        ], order="sequence, id")

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
        first, last = self._month_bounds(year, month)
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
            })
        return rows

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
        first, last = self._month_bounds(year, month)
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
        rows = self.env["ua.dashboard"]._get_payments(company, year, month)
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
            "period": {"year": year, "month": month},
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
    def _provider(self, journal_id):
        journal = self.env["account.journal"].browse(int(journal_id))
        provider = journal.online_bank_statement_provider_id
        if not provider:
            raise UserError(_("Для журналу «%s» не налаштовано з'єднання з банком.") % journal.display_name)
        return provider

    @api.model
    def action_pull(self, journal_id, date_from=None, date_to=None):
        """Завантажити виписку за період. Без дат - за поточний місяць до сьогодні."""
        provider = self._provider(journal_id)
        today = fields.Date.context_today(self)
        start = fields.Date.to_date(date_from) if date_from else today.replace(day=1)
        end = fields.Date.to_date(date_to) if date_to else today
        before = self.env["account.bank.statement.line"].search_count([("journal_id", "=", provider.journal_id.id)])
        provider._pull(datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min))
        after = self.env["account.bank.statement.line"].search_count([("journal_id", "=", provider.journal_id.id)])
        return {
            "created": after - before,
            "message": _("Завантажено рядків: %s (%s - %s).") % (
                after - before, start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y")),
        }

    @api.model
    def action_pull_month(self, journal_id, year, month):
        first, last = self._month_bounds(int(year), int(month))
        return self.action_pull(journal_id, fields.Date.to_string(first), fields.Date.to_string(last))

    @api.model
    def action_pull_all(self, year=None, month=None):
        """Завантажити виписку за місяць для всіх рахунків із з'єднанням."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._month_bounds(year, month)
        done, failed, created = [], [], 0
        for journal in self._journals(company):
            if not journal.online_bank_statement_provider_id:
                continue
            try:
                result = self.action_pull(journal.id, fields.Date.to_string(first), fields.Date.to_string(last))
            except UserError as error:
                failed.append("%s: %s" % (journal.name, error.args[0] if error.args else ""))
                continue
            created += result.get("created", 0)
            done.append("%s: %s" % (journal.name, result.get("created", 0)))
        if not done and not failed:
            raise UserError(_("Немає жодного рахунку зі з'єднанням."))
        message = _("Завантажено рядків: %s.") % created
        if done:
            message += "\n" + "; ".join(done)
        if failed:
            message += "\n" + _("Не вдалося: ") + "; ".join(failed)
        return {"created": created, "failed": len(failed), "message": message}

    @api.model
    def action_test(self, journal_id):
        provider = self._provider(journal_id)
        provider.action_ua_test()
        return {"message": _("Банк відповідає.")}


    # ------------------------------------------------------------------ правила звірки
    def _reconcile_models(self, company):
        return self.env["account.reconcile.model"].search([
            ("company_id", "=", company.id), ("match_label", "=", "match_regex"),
        ], order="sequence, id")

    @staticmethod
    def _rule_account(models_, text):
        """Перший рахунок за правилом, чий вираз збігається з призначенням платежу."""
        for model in models_:
            pattern = model.match_label_param or ""
            if not pattern:
                continue
            try:
                if not re.search(pattern, text or ""):
                    continue
            except re.error:
                continue
            account = model.line_ids[:1].account_id
            if account:
                return account, model
        return None, None

    def _rule_partner(self, line):
        if line.partner_id:
            return line.partner_id
        name = (line.partner_name or "").strip()
        if not name:
            return None
        return self.env["res.partner"].search([("name", "=", name)], limit=1) or None

    @api.model
    def action_apply_rules(self, journal_id=None):
        """Проставити рахунок незвіреним рядкам за правилами звірки.

        Правила - записи account.reconcile.model (їх бачить і змінює бухгалтер).
        Рядку замінюємо тимчасовий рахунок банку на рахунок з правила; після цього
        рядок вважається звіреним. Рядки без збігу лишаємо бухгалтеру.
        """
        company = self._company()
        domain = [("company_id", "=", company.id), ("is_reconciled", "=", False)]
        if journal_id:
            domain.append(("journal_id", "=", int(journal_id)))
        lines = self.env["account.bank.statement.line"].search(domain, order="date, id")
        models_ = self._reconcile_models(company)
        if not models_:
            raise UserError(_("Немає правил звірки. Створіть їх у розділі «Бухоблік → Правила звірки»."))
        applied, skipped = 0, 0
        by_rule = {}
        for line in lines:
            account, model = self._rule_account(models_, line.payment_ref or "")
            if not account:
                skipped += 1
                continue
            _liquidity, suspense, _other = line._seek_for_lines()
            if not suspense:
                skipped += 1
                continue
            values = {"account_id": account.id}
            partner = self._rule_partner(line)
            if partner:
                values["partner_id"] = partner.id
            suspense.with_context(check_move_validity=False, skip_readonly_check=True,
                                  skip_account_move_synchronization=True).write(values)
            applied += 1
            by_rule[model.name] = by_rule.get(model.name, 0) + 1
        detail = ", ".join("%s: %s" % (name, count) for name, count in sorted(by_rule.items()))
        return {
            "applied": applied,
            "skipped": skipped,
            "message": _("Звірено за правилами: %s. Лишилося вручну: %s.%s") % (
                applied, skipped, ("\n" + detail) if detail else ""),
        }

    @api.model
    def action_open_rules(self):
        return self.env["ir.actions.act_window"]._for_xml_id("account.action_account_reconcile_model")

    @api.model
    def action_open_reconcile(self, journal_id):
        journal = self.env["account.journal"].browse(int(journal_id))
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_reconcile_oca.action_bank_statement_line_reconcile")
        action["domain"] = [("journal_id", "=", journal.id)]
        action["context"] = {
            "default_journal_id": journal.id,
            "search_default_not_reconciled": True,
            "view_ref": "account_reconcile_oca.bank_statement_line_form_reconcile_view",
        }
        action["name"] = _("Звірка: %s") % journal.name
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
    def action_open_providers(self, journal_id=None):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_statement_import_online.online_bank_statement_provider_action")
        if journal_id:
            provider = self.env["account.journal"].browse(int(journal_id)).online_bank_statement_provider_id
            if provider:
                action["res_id"] = provider.id
                action["view_mode"] = "form"
                action["views"] = [(False, "form")]
        return action

    @api.model
    def action_create_provider(self, journal_id, service):
        """Створити з'єднання для журналу і відкрити його форму."""
        journal = self.env["account.journal"].browse(int(journal_id))
        if journal.online_bank_statement_provider_id:
            return self.action_open_providers(journal_id)
        provider = self.env["online.bank.statement.provider"].create({
            "journal_id": journal.id,
            "service": service,
            "statement_creation_mode": "monthly",
            "interval_type": "hours",
            "interval_number": 12,
            "ua_account": journal.bank_account_id.acc_number or "",
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "online.bank.statement.provider",
            "res_id": provider.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
