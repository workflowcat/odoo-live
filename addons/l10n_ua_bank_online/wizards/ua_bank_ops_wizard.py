# -*- coding: utf-8 -*-
"""Майстер «Операції банку»: стандартний вхід до ua.bank.ops, поки екрана немає.

Екран «Банк» (l10n_ua_bank_ui, OWL) знято з полиці 2026-09-22 - продукт іде «голим Odoo».
Його клієнт (bank_board.js) слав ім'я методу з поля вводу, і run_action() викликало
будь-що публічне на моделі - відкрита поверхня. Тут дію обирають зі фіксованого списку
(Selection), і action_run() сам зіставляє ключ з методом ua.bank.ops: чужого ключа не
існує, підмінити його немає чим.

Бізнес-логіка лишається в ua.bank.ops (AbstractModel, без жодного рядка інтерфейсу) -
майстер лише збирає параметри форми і показує повідомлення, яке повертає операція.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class UaBankOpsWizard(models.TransientModel):
    _name = "ua.bank.ops.wizard"
    _description = "Операції банку"

    # Ключ -> яких параметрів форми потребує. Сам виклик - у action_run().
    OPERATIONS = [
        ("pull_month", "Завантажити виписку за місяць"),
        ("pull_all", "Завантажити за всі рахунки"),
        ("test", "Перевірити з'єднання"),
        ("match_payments", "Звести з платежами"),
        ("apply_rules", "Застосувати правила звірки"),
        ("open_provider", "Відкрити або створити з'єднання"),
    ]

    operation = fields.Selection(OPERATIONS, string="Дія", required=True, default="pull_month")
    journal_id = fields.Many2one(
        "account.journal", string="Рахунок", domain=[("type", "=", "bank")],
        help="Потрібен для «Завантажити за місяць», «Перевірити з'єднання» і «Відкрити/створити "
             "з'єднання». Для «Звести з платежами» і «Застосувати правила» без рахунку - усі "
             "незвірені рядки компанії; для «Завантажити за всі рахунки» рахунок не враховується.")
    year = fields.Integer(string="Рік", default=lambda self: fields.Date.context_today(self).year)
    month = fields.Selection(selection="_selection_month", string="Місяць",
                             default=lambda self: str(fields.Date.context_today(self).month))
    service = fields.Selection(selection="_selection_service", string="Служба банку",
                               help="Тільки для нового з'єднання - коли для рахунку його ще немає.")
    result_message = fields.Text(string="Результат", readonly=True)

    def _selection_month(self):
        months = self.env["ua.bank.ops"].MONTHS_UA
        return [(str(number), name.capitalize()) for number, name in months.items()]

    def _selection_service(self):
        return self.env["online.bank.statement.provider"]._get_available_services()

    def _period(self):
        today = fields.Date.context_today(self)
        return self.year or today.year, int(self.month) if self.month else today.month

    def _show_result(self, result):
        self.result_message = (result or {}).get("message") or ""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    def _action_open_provider(self):
        """«Відкрити або створити з'єднання»: одна кнопка, дві гілки ua.bank.ops.

        Без обраного рахунку - перелік усіх з'єднань компанії. З рахунком, що вже має
        з'єднання, - його форма. З рахунком без з'єднання - створення, для чого потрібна
        служба банку (тут її перевіряємо: action_create_provider сам цього не робить)."""
        ops = self.env["ua.bank.ops"]
        if not self.journal_id:
            return ops.action_open_providers(None)
        if self.journal_id.online_bank_statement_provider_id:
            return ops.action_open_providers(self.journal_id.id)
        if not self.service:
            raise UserError(_("Для нового з'єднання виберіть службу банку."))
        return ops.action_create_provider(self.journal_id.id, self.service)

    def action_run(self):
        """Одна дія за фіксованим ключем operation - решта веде до ua.bank.ops."""
        self.ensure_one()
        ops = self.env["ua.bank.ops"]
        journal_id = self.journal_id.id or None
        if self.operation == "pull_month":
            year, month = self._period()
            return self._show_result(ops.action_pull_month(self.journal_id.id, year, month))
        if self.operation == "pull_all":
            year, month = self._period()
            return self._show_result(ops.action_pull_all(year, month))
        if self.operation == "test":
            return self._show_result(ops.action_test(self.journal_id.id))
        if self.operation == "match_payments":
            return self._show_result(ops.action_match_payments(journal_id=journal_id))
        if self.operation == "apply_rules":
            return self._show_result(ops.action_apply_rules(journal_id=journal_id))
        if self.operation == "open_provider":
            return self._action_open_provider()
        raise UserError(_("Невідома дія: %s") % self.operation)
