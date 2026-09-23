# -*- coding: utf-8 -*-
"""Кнопки банківських операцій там, де людина на них дивиться: список виписок і форма
журналу.

Меню «Операції банку» знято 2026-09-22 (рішення: меню відкриває сторінку, діалог буває
лише з кнопки). Дії, яким не потрібні параметри, стали кнопками; єдиний параметр -
рахунок і місяць для завантаження - живе в діалозі ua.bank.pull з кнопки «Завантажити
виписку». Логіка вся в ua.bank.ops, тут лише виклики.
"""
from odoo import _, fields, models


def _notify(message):
    return {
        "type": "ir.actions.client",
        "tag": "display_notification",
        "params": {"message": message or _("Готово."), "type": "success", "sticky": False},
    }


class AccountBankStatement(models.Model):
    _inherit = "account.bank.statement"

    def action_ua_pull(self):
        """«Завантажити виписку»: діалог з трьох полів - рахунок, рік, місяць."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Завантажити виписку"),
            "res_model": "ua.bank.pull",
            "view_mode": "form",
            "target": "new",
        }

    def action_ua_pull_all(self):
        """«Завантажити за всі рахунки»: поточний місяць, усі підключені рахунки."""
        today = fields.Date.context_today(self)
        result = self.env["ua.bank.ops"].action_pull_all(today.year, today.month)
        return _notify((result or {}).get("message"))

    def action_ua_match_payments(self):
        """«Звести з платежами»: усі незвірені рядки компанії."""
        result = self.env["ua.bank.ops"].action_match_payments()
        return _notify((result or {}).get("message"))

    def action_ua_apply_rules(self):
        """«Застосувати правила звірки»: усі незвірені рядки компанії."""
        result = self.env["ua.bank.ops"].action_apply_rules()
        return _notify((result or {}).get("message"))


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def action_ua_bank_test(self):
        """«Перевірити з'єднання» на формі банківського журналу."""
        self.ensure_one()
        result = self.env["ua.bank.ops"].action_test(self.id)
        return _notify((result or {}).get("message"))

    def action_ua_bank_provider(self):
        """«З'єднання з банком»: наявне відкриваємо, відсутнє - показуємо перелік."""
        self.ensure_one()
        if self.online_bank_statement_provider_id:
            return self.env["ua.bank.ops"].action_open_providers(self.id)
        return self.env["ua.bank.ops"].action_open_providers(None)
