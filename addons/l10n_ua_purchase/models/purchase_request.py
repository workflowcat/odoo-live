"""Український шар на запиті OCA: підрозділ, рахунок витрат, ліміт погодження."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    def action_ua_pad(self):
        """Кнопка «Пад» у шапці списку: разовий діалог, з якого виходить запит."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Пад швидкого замовлення"),
            "res_model": "ua.purchase.pad",
            "view_mode": "form",
            "target": "new",
        }

    ua_department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Підрозділ",
        help="Підрозділ, для якого купуємо. Їде в замовлення і далі в рахунок.",
    )
    ua_expense_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Рахунок витрат",
        help="Рахунок, на який лягає витрата. Якщо порожній, рахунок бере "
             "Odoo з товару або категорії, як завжди.",
    )
    ua_over_limit = fields.Boolean(
        string="Понад ліміт погодження",
        compute="_compute_ua_over_limit",
        help="Орієнтовна вартість запиту більша за ліміт компанії, тому "
             "погодити може лише керівник закупівель.",
    )

    @api.depends("estimated_cost", "company_id.ua_purchase_approval_limit")
    def _compute_ua_over_limit(self):
        for request in self:
            limit = request.company_id.ua_purchase_approval_limit
            request.ua_over_limit = bool(limit) and request.estimated_cost > limit

    def _ua_check_approval_limit(self):
        """Понад ліміт запит погоджує лише керівник закупівель."""
        if self.env.user.has_group("purchase.group_purchase_manager"):
            return
        for request in self:
            limit = request.company_id.ua_purchase_approval_limit
            if not limit or request.estimated_cost <= limit:
                continue
            raise UserError(_(
                "Запит «%(name)s» на %(cost)s перевищує ліміт погодження "
                "%(limit)s. Погодити може керівник закупівель.",
                name=request.name,
                cost=formatLang(self.env, request.estimated_cost,
                                currency_obj=request.currency_id),
                limit=formatLang(self.env, limit,
                                 currency_obj=request.currency_id),
            ))

    def button_approved(self):
        self._ua_check_approval_limit()
        return super().button_approved()
