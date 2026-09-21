"""Касовий ордер = нативний платіж у журналі типу «Каса».

Прибутковий касовий ордер (ПКО) - це account.payment типу inbound, видатковий (ВКО) -
outbound. Проводку робить сам Odoo: ліквідна сторона йде на рахунок каси журналу (301),
друга сторона - на кореспондуючий рахунок. Тому ПКО дає Дт 301 / Кт <кор. рахунок>,
а ВКО - Дт <кор. рахунок> / Кт 301, і платіж при цьому лишається звичайним платежем:
його можна звірити з рахунком клієнта чи постачальника нативними засобами.

Два місця, де нативну поведінку довелося підправити.

1. Рахунок ліквідної сторони. У Community Odoo, коли в способі оплати не заданий
   рахунок, платіж іде через «Outstanding Receipts» з префіксом банку (311). Для каси
   це неправильно: гроші справді лежать у касі. Тому для журналу типу cash беремо
   рахунок самого журналу (301).
2. Кореспондуючий рахунок (destination_account_id). Нативний розрахунок підставляє
   дебіторку або кредиторку партнера (361 / 631). У касі кореспондує що завгодно:
   3721 - підзвіт, 661 - зарплата, 92 - адмінвитрати. Тому вибір бухгалтера ми
   зберігаємо і не перезаписуємо.

Номер ордера ведеться окремо від номера проводки: свій реєстр на ПКО і на ВКО, з
початку кожного року нумерація починається заново (ПКО-2026-0001).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .tools import amount_in_words

ORDER_SEQUENCES = {
    "in": "l10n_ua_cash.order.in",
    "out": "l10n_ua_cash.order.out",
}
ORDER_FORM = {"in": "КО-1", "out": "КО-2"}


class AccountPayment(models.Model):
    _inherit = "account.payment"

    ua_order_kind = fields.Selection(
        [("in", "ПКО"), ("out", "ВКО")],
        string="Вид касового ордера",
        compute="_compute_ua_order_kind",
        store=True,
        help="ПКО - гроші надійшли в касу, ВКО - видані з каси. "
             "Визначається журналом (тип «Каса») і напрямом платежу.",
    )
    ua_order_number = fields.Char(
        "Номер ордера",
        copy=False,
        readonly=True,
        index="btree_not_null",
        help="Окремий реєстр на ПКО і на ВКО, з початку року нумерація починається заново.",
    )
    ua_person = fields.Char(
        "Прийнято від / Видати",
        help="Хто вносить або одержує готівку, як це написано в ордері. "
             "Заповнюється, коли особа не заведена контрагентом.",
    )
    ua_document = fields.Char(
        "Документ одержувача",
        help="Назва, номер, ким і коли виданий документ, що засвідчує особу одержувача "
             "(пункт 29 Положення НБУ № 148). Потрібен для ВКО.",
    )

    # ------------------------------------------------------------------
    # Обчислення
    # ------------------------------------------------------------------
    @api.depends("journal_id", "payment_type")
    def _compute_ua_order_kind(self):
        for payment in self:
            if payment.journal_id.type == "cash":
                payment.ua_order_kind = "in" if payment.payment_type == "inbound" else "out"
            else:
                payment.ua_order_kind = False

    @api.depends("payment_method_line_id", "journal_id")
    def _compute_outstanding_account_id(self):
        """Готівка лежить у касі, а не на транзитному рахунку банку."""
        super()._compute_outstanding_account_id()
        for payment in self:
            if payment.journal_id.type == "cash" and not payment.outstanding_account_id:
                payment.outstanding_account_id = payment.journal_id.default_account_id

    @api.depends("journal_id", "partner_id", "partner_type")
    def _compute_destination_account_id(self):
        """Кореспондуючий рахунок ордера вибирає бухгалтер - не перезаписуємо."""
        chosen = self.filtered(
            lambda payment: payment.journal_id.type == "cash" and payment.destination_account_id
        )
        super(AccountPayment, self - chosen)._compute_destination_account_id()

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------
    def action_post(self):
        res = super().action_post()
        self._ua_assign_order_number()
        return res

    def _ua_assign_order_number(self):
        """Номер із реєстру свого виду за рік дати ордера."""
        sequence = self.env["ir.sequence"]
        for payment in self:
            if not payment.ua_order_kind or payment.ua_order_number:
                continue
            number = sequence.with_company(payment.company_id).next_by_code(
                ORDER_SEQUENCES[payment.ua_order_kind], sequence_date=payment.date
            )
            if not number:
                raise UserError(
                    _("Не знайдено нумератор касових ордерів %s.")
                    % ORDER_SEQUENCES[payment.ua_order_kind]
                )
            payment.ua_order_number = number

    def action_ua_print_cash_order(self):
        """Друк КО-1 (ПКО) або КО-2 (ВКО)."""
        not_cash = self.filtered(lambda payment: not payment.ua_order_kind)
        if not_cash:
            raise UserError(_("Друкована форма є лише для платежів у журналі типу «Каса»."))
        return self.env.ref("l10n_ua_cash.action_report_ua_cash_order").report_action(self)

    # ------------------------------------------------------------------
    # Допоміжне для друку і касової книги
    # ------------------------------------------------------------------
    def _ua_order_label(self):
        """Номер ордера для форм і касової книги; до проведення - номер проводки."""
        self.ensure_one()
        return self.ua_order_number or self.name or ""

    def _ua_person_label(self):
        """Від кого прийнято (ПКО) або кому видано (ВКО)."""
        self.ensure_one()
        return self.ua_person or self.partner_id.name or ""

    def _ua_form_number(self):
        self.ensure_one()
        return ORDER_FORM.get(self.ua_order_kind, "")

    def _ua_amount_words(self):
        """Сума ордера прописом."""
        self.ensure_one()
        return amount_in_words(self.env, self.currency_id, self.amount)
