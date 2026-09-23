# -*- coding: utf-8 -*-
"""«Завантажити виписку»: разова дія з кнопки на списку виписок.

Меню «Операції банку» знято 2026-09-22: пункт меню відкривав діалог із переліком дій
(ua.bank.ops.wizard), а меню має відкривати сторінку. Дії без параметрів стали кнопками
прямо на списку виписок і на формі журналу; параметр лишився один - за який рахунок і
місяць тягнути виписку, і саме він живе тут, у діалозі з трьох полів.

Бізнес-логіка лишається в ua.bank.ops (AbstractModel, без жодного рядка інтерфейсу).
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class UaBankPull(models.TransientModel):
    _name = "ua.bank.pull"
    _description = "Завантажити виписку"

    journal_id = fields.Many2one(
        "account.journal", string="Рахунок", required=True, domain=[("type", "=", "bank")],
        help="Порожньо неможливо: виписку тягнемо за конкретним рахунком. "
             "Для всіх рахунків одразу - кнопка «Завантажити за всі рахунки».")
    year = fields.Integer(string="Рік", required=True,
                          default=lambda self: fields.Date.context_today(self).year)
    month = fields.Selection(selection="_selection_month", string="Місяць", required=True,
                             default=lambda self: str(fields.Date.context_today(self).month))

    def _selection_month(self):
        months = self.env["ua.bank.ops"].MONTHS_UA
        return [(str(number), name.capitalize()) for number, name in months.items()]

    def action_pull(self):
        """Одна дія: завантажити виписку рахунку за місяць."""
        self.ensure_one()
        result = self.env["ua.bank.ops"].action_pull_month(
            self.journal_id.id, self.year, int(self.month))
        message = (result or {}).get("message")
        if not message:
            raise UserError(_("Банк нічого не повернув."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": "success", "next": {"type": "ir.actions.act_window_close"}},
        }
