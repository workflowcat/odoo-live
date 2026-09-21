# -*- coding: utf-8 -*-
"""Банківські операції: завантажити виписку, перевірити ключ, звірити за правилами,
створити з'єднання. Це логіка банку, не екран - у файлі немає жодного рядка для
інтерфейсу, і кликати її можна звідусіль (екран «Банк», крок «Період», cron).

Екран ua.bank.board лише направляє сюди свої ключі дій (run_action).
"""
import re
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UaBankOps(models.AbstractModel):
    _name = "ua.bank.ops"
    _inherit = ["ua.screen"]
    _description = "Банківські операції"

    # ------------------------------------------------------------------ рахунки
    def _journals(self, company):
        return self.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", company.id),
        ], order="sequence, id")

    def _provider(self, journal_id):
        if not journal_id:
            raise UserError(_("Виберіть рахунок зліва, щоб завантажити виписку."))
        journal = self.env["account.journal"].browse(int(journal_id))
        provider = journal.online_bank_statement_provider_id
        if not provider:
            raise UserError(_("Для журналу «%s» не налаштовано з'єднання з банком.") % journal.display_name)
        return provider

    # ------------------------------------------------------------------ виписки
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
        first, last = self._bounds(int(year), int(month))
        return self.action_pull(journal_id, fields.Date.to_string(first), fields.Date.to_string(last))

    @api.model
    def action_pull_all(self, year=None, month=None):
        """Завантажити виписку за місяць для всіх рахунків із з'єднанням."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
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

    # ------------------------------------------------------------------ з'єднання
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

    @api.model
    def action_open_providers(self, journal_id=None):
        """Форма з'єднання рахунку (або перелік усіх, якщо рахунок не вибрано).

        Живе тут, а не на екрані: сюди ж повертає action_create_provider, коли
        з'єднання для журналу вже є."""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account_statement_import_online.online_bank_statement_provider_action")
        if journal_id:
            provider = self.env["account.journal"].browse(int(journal_id)).online_bank_statement_provider_id
            if provider:
                action["res_id"] = provider.id
                action["view_mode"] = "form"
                action["views"] = [(False, "form")]
        return action
