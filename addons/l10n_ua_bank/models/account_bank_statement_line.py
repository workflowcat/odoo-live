# -*- coding: utf-8 -*-
"""Рядок виписки спершу шукає свій платіж і лише потім - правило за текстом призначення.

Бухгалтер, який веде виплати відомостями, має в базі обидві половини однієї операції:
проведений `account.payment` (Дт 661 / Кт 333) і рядок виписки (Дт 333 / Кт 311). Правило
звірки за текстом нічого про платіж не знає: воно просто кодує рядок на 661, і та сама
зарплата лягає на 661 двічі. Тому порядок такий:

1. `_ua_match_payment` - зводимо рядок з уже проведеним платежем: однаковий банк, напрям,
   сума до копійки, дата в межах тижня і - головне - той самий одержувач. Одержувача
   впізнаємо за IBAN у рядку виписки (банк пише рахунок контрагента), а як IBAN немає -
   за контрагентом рядка або за його назвою. Без жодної з цих ознак не зводимо: сума й
   дата самі по собі надто слабкі, щоб чіпати чужі гроші.
2. `_ua_payment_blocks_rule` - якщо платіж є, але зійтися з рядком не зміг (інша сума,
   часткова оплата), правило за текстом мовчить і рядок лишається бухгалтеру. Мовчазне
   подвоєння гірше, ніж рядок, який видно в «Незвірених».

Компанія, яка відомостей не веде, цього шару не помічає: платежів немає - шукати нічого,
працюють ті самі правила, що й раніше.
"""
from datetime import timedelta

from odoo import api, models

# Вікно навколо дати платежу, в якому банк показує ту саму операцію.
MATCH_DAYS = 7
# Ширше вікно, в якому наявність платежу забороняє правилу за текстом чіпати рядок.
BLOCK_DAYS = 31
# Стани платежу, за яких проводка вже є: Odoo 19 CE пише «в обробці», а платіж із
# рахунком типу «кошти» (333) одразу стає «оплаченим».
LIVE_STATES = ("in_process", "paid", "posted")


def _iban(value):
    return (value or "").replace(" ", "").upper()


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    # ------------------------------------------------------------------ ознаки рядка
    def _ua_outstanding_accounts(self):
        """Рахунки «гроші в дорозі» журналу для напряму цього рядка.

        Беремо їх у журналу, а не з коду: бухгалтер може поставити інший рахунок, і
        зведення має піти за ним. Сам рахунок банку сюди не рахуємо - на ньому платіж
        і так вважається таким, що дійшов, і зводити нема чого."""
        self.ensure_one()
        journal = self.journal_id
        accounts = (journal._get_journal_outbound_outstanding_payment_accounts()
                    if self.amount < 0
                    else journal._get_journal_inbound_outstanding_payment_accounts())
        return accounts.filtered(lambda a: a.reconcile and a != journal.default_account_id)

    def _ua_line_iban(self):
        """IBAN контрагента так, як його дав банк."""
        self.ensure_one()
        return _iban(self.account_number) or _iban(self.partner_bank_id.sanitized_acc_number)

    def _ua_line_partner(self):
        """Контрагент рядка: свій, з рахунку контрагента або за назвою."""
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        if self.partner_bank_id.partner_id:
            return self.partner_bank_id.partner_id
        name = (self.partner_name or "").strip()
        if not name:
            return self.env["res.partner"]
        return self.env["res.partner"].search([("name", "=", name)], limit=1)

    # ------------------------------------------------------------------ пошук платежу
    def _ua_payments(self, days, extra_domain=None):
        """Відкриті платежі цього банку, які може пояснювати цей рядок виписки.

        Відбір за грошима і датою робить база, за особою одержувача - ми: IBAN сильніший
        за назву, бо двом працівникам можуть нарахувати однакову суму."""
        self.ensure_one()
        accounts = self._ua_outstanding_accounts()
        if not accounts or not self.date or not self.amount:
            return self.env["account.payment"]
        domain = [
            ("company_id", "=", self.company_id.id),
            ("journal_id", "=", self.journal_id.id),
            ("payment_type", "=", "outbound" if self.amount < 0 else "inbound"),
            ("state", "in", LIVE_STATES),
            ("is_matched", "=", False),
            ("outstanding_account_id", "in", accounts.ids),
            ("date", ">=", self.date - timedelta(days=days)),
            ("date", "<=", self.date + timedelta(days=days)),
        ] + list(extra_domain or [])
        payments = self.env["account.payment"].search(domain)
        if not payments:
            return payments
        iban = self._ua_line_iban()
        if iban:
            return payments.filtered(
                lambda p: _iban(p.partner_bank_id.sanitized_acc_number) == iban)
        partner = self._ua_line_partner()
        if partner:
            return payments.filtered(lambda p: p.partner_id == partner)
        # Ні рахунку, ні імені - нема кого впізнавати.
        return self.env["account.payment"]

    def _ua_find_payment(self, exclude=None):
        """Один платіж, який пояснює цей рядок виписки. Інакше порожньо."""
        self.ensure_one()
        if self.is_reconciled:
            return self.env["account.payment"]
        currency = self.currency_id or self.company_id.currency_id
        amount = abs(self.amount)
        payments = self._ua_payments(MATCH_DAYS).filtered(
            lambda p: currency.is_zero(p.amount - amount) and p.move_id)
        if exclude:
            payments -= exclude
        if not payments:
            return self.env["account.payment"]
        # Кілька однакових платежів тому самому одержувачу - беремо найближчий за датою,
        # далі за номером: вибір має бути тим самим при кожному прогоні.
        return payments.sorted(key=lambda p: (abs((p.date - self.date).days), p.id))[:1]

    def _ua_payment_blocks_rule(self, account):
        """Чи закриває вже проведений платіж той самий рахунок тому самому одержувачу.

        Якщо так, правило за текстом не чіпає рядок: разом вони дали б подвійну суму."""
        self.ensure_one()
        return bool(self._ua_payments(BLOCK_DAYS, [("destination_account_id", "=", account.id)]))

    # ------------------------------------------------------------------ зведення
    def _ua_apply_payment(self, payment):
        """Поставити рядку виписки рахунок «грошей у дорозі» і звести його з платежем."""
        self.ensure_one()
        _liquidity, suspense, _other = self._seek_for_lines()
        if not suspense:
            return False
        account = payment.outstanding_account_id
        values = {"account_id": account.id}
        if payment.partner_id:
            values["partner_id"] = payment.partner_id.id
        suspense.with_context(check_move_validity=False, skip_readonly_check=True,
                              skip_account_move_synchronization=True).write(values)
        own = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == account and not line.reconciled)
        if own:
            (suspense | own).reconcile()
        return True

    def _ua_match_payment(self):
        """Звести рядки виписки з уже проведеними платежами. Повертає, скільки звелося."""
        matched = 0
        used = self.env["account.payment"]
        for line in self:
            if line.is_reconciled:
                continue
            payment = line._ua_find_payment(exclude=used)
            if not payment:
                continue
            if line._ua_apply_payment(payment):
                used |= payment
                matched += 1
        return matched

    @api.model
    def _ua_match_domain(self, company, journal_id=None):
        domain = [("company_id", "=", company.id), ("is_reconciled", "=", False)]
        if journal_id:
            domain.append(("journal_id", "=", int(journal_id)))
        return domain
