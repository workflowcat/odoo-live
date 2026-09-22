# -*- coding: utf-8 -*-
"""Рядок відомості на перерахування = рядок платіжного доручення OCA.

Два поля понад OCA. `ua_employee_id` - працівник, якого видно в списку і в друкованій
формі (контрагент у платежі - його ж контакт, але шукати людину зручніше за карткою).
`ua_account_id` - рахунок, який цей платіж закриває: 661 працівникові, 6411/6415/651
бюджету. Без нього Odoo взяв би типовий рахунок розрахунків з постачальником (63), бо
рядок відомості не походить із рахунка-фактури й не має `move_line_id`.
"""
from odoo import api, fields, models


class AccountPaymentLine(models.Model):
    _inherit = "account.payment.line"

    ua_employee_id = fields.Many2one("hr.employee", "Працівник", ondelete="restrict", index=True)
    ua_label = fields.Char("Рядок", help="Назва платежу, коли одержувач не працівник (ПДФО, ЄСВ).")
    ua_account_id = fields.Many2one(
        "account.account", "Рахунок, який закриває платіж", ondelete="restrict",
        help="661 для виплати працівникові, 6411 / 6415 / 651 для платежу до бюджету.")
    ua_payee_name = fields.Char("Одержувач", compute="_compute_ua_payee")
    ua_payee_code = fields.Char("РНОКПП / ЄДРПОУ", compute="_compute_ua_payee")
    ua_payee_iban = fields.Char("IBAN одержувача", compute="_compute_ua_payee",
                                help="Рахунок суцільним рядком, без пробілів: так його чекає банк "
                                     "у файлі зарплатного проєкту.")

    @api.depends("ua_employee_id", "ua_label", "partner_id", "partner_bank_id")
    def _compute_ua_payee(self):
        for line in self:
            employee = line.ua_employee_id.sudo()
            bank = line.partner_bank_id
            line.ua_payee_name = employee.name or line.ua_label or line.partner_id.name or ""
            line.ua_payee_code = (employee.ua_rnokpp if employee else (line.partner_id.vat or "")) or ""
            # base_iban показує рахунок групами по чотири; у файл і в бланк іде суцільний рядок
            line.ua_payee_iban = (bank.sanitized_acc_number or bank.acc_number or "") if bank else ""

    @api.model
    def _get_payment_line_grouping_fields(self):
        """Рядки з різними рахунками закриття не зливаються в один платіж."""
        return super()._get_payment_line_grouping_fields() + ["ua_account_id"]

    def _prepare_account_payment_vals(self):
        vals = super()._prepare_account_payment_vals()
        line = self[:1]
        order = line.order_id
        if not order.ua_kind:
            return vals
        if line.ua_account_id:
            vals["destination_account_id"] = line.ua_account_id.id
        if order.ua_pay_date:
            vals["date"] = order.ua_pay_date
        vals["partner_type"] = "supplier"
        return vals
