# -*- coding: utf-8 -*-
"""Наслідки наказу: що система створила або змінила після проведення.

Бухгалтер вводить подію один раз. Далі він має бачити в одному місці все, що з неї
вийшло: версію договору, відсутність, листок місяця, рядок виплати. Кнопки ведуть
до самих документів, тому нічого не треба шукати списками.
"""
from odoo import _, api, fields, models


class UaHrOrder(models.Model):
    _inherit = "ua.hr.order"

    ua_effect_slip_count = fields.Integer("Листки місяця", compute="_compute_ua_effects")
    ua_effect_payment_count = fields.Integer("Рядки виплати", compute="_compute_ua_effects")
    ua_effect_note = fields.Char("Наслідки", compute="_compute_ua_effects")

    def _ua_effect_period(self):
        """Місяць, на який впливає наказ."""
        self.ensure_one()
        day = self.date_from or self.date or fields.Date.context_today(self)
        return day.replace(day=1), day

    def _ua_effect_slips(self):
        self.ensure_one()
        if not self.employee_id:
            return self.env["hr.payslip"]
        first, _day = self._ua_effect_period()
        return self.env["hr.payslip"].search([
            ("employee_id", "=", self.employee_id.id), ("date_from", ">=", first),
            ("date_from", "<=", first), ("state", "!=", "cancel"),
        ])

    def _ua_effect_payments(self):
        """Рядки відомості на перерахування за місяць наказу.

        Відомості живуть в l10n_ua_payments, який не є залежністю наказів: без нього
        просто немає рядків виплати, а не помилка."""
        self.ensure_one()
        if "account.payment.line" not in self.env:
            return []
        Line = self.env["account.payment.line"]
        if not self.employee_id:
            return Line
        first, _day = self._ua_effect_period()
        return Line.search([
            ("ua_employee_id", "=", self.employee_id.id),
            ("order_id.ua_year", "=", first.year), ("order_id.ua_month", "=", first.month),
        ])

    @api.depends("state", "employee_id", "date", "date_from", "version_id", "leave_id")
    def _compute_ua_effects(self):
        for order in self:
            slips = order._ua_effect_slips()
            payments = order._ua_effect_payments()
            order.ua_effect_slip_count = len(slips)
            order.ua_effect_payment_count = len(payments)
            parts = []
            if order.version_id:
                parts.append(_("версія договору"))
            if order.leave_id:
                parts.append(_("відсутність"))
            if order.comp_days_input_id:
                parts.append(_("введення в листок"))
            if slips:
                parts.append(_("листок місяця"))
            if payments:
                parts.append(_("рядок виплати"))
            order.ua_effect_note = ", ".join(parts) if parts else _("наказ ще нічого не створив")

    def action_ua_open_version(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "hr.version", "res_id": self.version_id.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def action_ua_open_leave(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "hr.leave", "res_id": self.leave_id.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def action_ua_open_slips(self):
        self.ensure_one()
        slips = self._ua_effect_slips()
        return {"type": "ir.actions.act_window", "res_model": "hr.payslip", "name": _("Листки місяця"),
                "domain": [("id", "in", slips.ids)], "view_mode": "list,form",
                "views": [(False, "list"), (False, "form")], "target": "current"}

    def action_ua_open_payments(self):
        self.ensure_one()
        lines = self._ua_effect_payments()
        return {"type": "ir.actions.act_window", "res_model": "account.payment.line", "name": _("Рядки виплати"),
                "domain": [("id", "in", lines.ids if lines else [])], "view_mode": "list,form",
                "views": [(False, "list"), (False, "form")], "target": "current"}
