# -*- coding: utf-8 -*-
"""Заявка на оплату під бюджетом руху коштів.

Стаття заявки йде у створений платіж (і далі у форму № 3). Якщо на рік оплати є затверджений
бюджет із контролем, то при поданні:
- без статті заявку не подати;
- сума понад залишок статті на місяць оплати (план - факт - інші відкриті заявки):
  «погоджує директор» - до кроків додається директор, у стрічці - запис із цифрами;
  «заявку не подати» - помилка з цифрами.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UaPaymentRequest(models.Model):
    _inherit = "ua.payment.request"

    ua_cashflow_item_id = fields.Many2one(
        "ua.cashflow.item", string="Стаття руху коштів", tracking=True,
        domain=[("kind", "=", "out")],
        help="Стаття бюджету руху коштів і форми № 3. Переходить у платіж.")
    ua_budget_remaining = fields.Monetary(
        "Залишок бюджету статті", currency_field="company_currency_id",
        compute="_compute_ua_budget_remaining",
        help="План статті на місяць оплати мінус факт і мінус інші відкриті заявки.")
    ua_budget_has = fields.Boolean(compute="_compute_ua_budget_remaining")
    ua_budget_over = fields.Boolean(
        "Понад бюджет", readonly=True, copy=False, tracking=True,
        help="Під час подання сума була більша за залишок статті: потрібен директор.")

    @api.depends("ua_cashflow_item_id", "date_due", "company_id", "amount_company")
    def _compute_ua_budget_remaining(self):
        Budget = self.env["ua.cashflow.budget"].sudo()
        for request in self:
            budget = Budget.ua_active(request.company_id, request.date_due) \
                if request.company_id and request.date_due else Budget
            request.ua_budget_has = bool(budget) and budget.control != "none"
            if not budget or not request.ua_cashflow_item_id:
                request.ua_budget_remaining = 0.0
                continue
            request.ua_budget_remaining = request._ua_budget_left(budget)

    def _ua_budget_left(self, budget):
        """План - факт - інші відкриті заявки по статті на місяць оплати."""
        self.ensure_one()
        month = self.date_due.month
        item = self.ua_cashflow_item_id
        line = budget._ua_line(item, month)
        plan = line.plan if line else 0.0
        fact = budget._ua_fact(month).get(item, 0.0)
        committed = budget._ua_committed(item, month, exclude=self._origin or self)
        return plan - fact - committed

    def _ua_budget_check(self):
        """Перевірка при поданні; повертає True, якщо заявка понад бюджет."""
        self.ensure_one()
        budget = self.env["ua.cashflow.budget"].sudo().ua_active(self.company_id, self.date_due)
        if not budget or budget.control == "none":
            return False
        if not self.ua_cashflow_item_id:
            raise UserError(_("Виберіть статтю руху коштів: на %s рік затверджено бюджет.") % budget.year)
        left = self._ua_budget_left(budget)
        if self.company_currency_id.compare_amounts(self.amount_company, left) <= 0:
            return False
        text = _("Заявка %(name)s: %(amount).2f грн за статтею %(item)s, залишок бюджету на місяць "
                 "%(left).2f грн.") % {"name": self.name, "amount": self.amount_company,
                                       "item": self.ua_cashflow_item_id.display_name, "left": left}
        if budget.control == "block":
            raise UserError(_("Понад бюджет руху коштів. %s Змініть бюджет або суму.") % text)
        self.message_post(body=_("Понад бюджет: потрібне погодження директора. %s") % text)
        return True

    def action_submit(self):
        for request in self:
            if request.state in ("draft", "rejected"):
                request.ua_budget_over = request._ua_budget_check()
        return super().action_submit()

    def _steps(self):
        steps = super()._steps()
        if self.ua_budget_over and "director" not in steps:
            steps.append("director")
        return steps

    def action_create_payment(self):
        result = super().action_create_payment()
        for request in self.filtered("ua_cashflow_item_id"):
            request.payment_ids.filtered(lambda p: not p.ua_cashflow_item_id).sudo().write(
                {"ua_cashflow_item_id": request.ua_cashflow_item_id.id})
        return result
