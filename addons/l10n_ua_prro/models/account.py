"""Зв'язок ПРРО з обліком: журнал оплат знає свою касу, податок - свою літеру в чеку,
оплата покупця в журналі каси створює і надсилає фіскальний чек."""
from odoo import _, api, fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    ua_prro_register_id = fields.Many2one(
        "ua.prro.register", "Каса ПРРО", check_company=True,
        help="Оплати покупців у цьому журналі фіскалізуються через цю касу.")
    ua_prro_payment_type = fields.Selection(
        [("cash", "Готівка"), ("card", "Картка"), ("cashless", "Безготівково")],
        "Форма оплати в чеку", compute="_compute_ua_prro_payment_type", store=True,
        readonly=False)

    @api.depends("type")
    def _compute_ua_prro_payment_type(self):
        for journal in self:
            if not journal.ua_prro_payment_type:
                journal.ua_prro_payment_type = "cash" if journal.type == "cash" else "card"


class AccountTax(models.Model):
    _inherit = "account.tax"

    ua_prro_letter = fields.Char(
        "Літера в чеку ПРРО", size=2,
        help="Літерне позначення ставки, як його налаштовано в касі ПРРО (наприклад, А - ПДВ 20%).")


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_prro_receipt_ids = fields.Many2many(
        "ua.prro.receipt", "ua_prro_receipt_move_rel", "move_id", "receipt_id",
        "Фіскальні чеки", readonly=True, copy=False)
    ua_prro_receipt_count = fields.Integer(compute="_compute_ua_prro_receipt_count")

    @api.depends("ua_prro_receipt_ids")
    def _compute_ua_prro_receipt_count(self):
        for move in self:
            move.ua_prro_receipt_count = len(move.ua_prro_receipt_ids)

    def action_ua_prro_receipts(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Фіскальні чеки"),
                "res_model": "ua.prro.receipt", "view_mode": "list,form",
                "domain": [("id", "in", self.ua_prro_receipt_ids.ids)]}


class AccountPayment(models.Model):
    _inherit = "account.payment"

    ua_prro_receipt_ids = fields.One2many("ua.prro.receipt", "payment_id", "Фіскальні чеки",
                                          readonly=True)


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _create_payments(self):
        payments = super()._create_payments()
        Receipt = self.env["ua.prro.receipt"]
        for payment in payments:
            register = payment.journal_id.ua_prro_register_id
            if not register or not register.auto_send:
                continue
            moves = payment.reconciled_invoice_ids or payment.invoice_ids
            if not moves and len(payments) == 1:
                moves = self.line_ids.move_id
            receipt = Receipt._from_payment(payment, moves)
            if receipt:
                # Помилка сервісу не скасовує оплату: чек лишається «не надіслано» і чекає повтору.
                receipt.action_send()
                if receipt.state == "error":
                    payment.message_post(body=_("Фіскальний чек %(name)s не надіслано: %(error)s",
                                                name=receipt.name, error=receipt.error))
        return payments
