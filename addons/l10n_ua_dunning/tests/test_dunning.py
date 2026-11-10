# -*- coding: utf-8 -*-
"""Нагадування про борг: хто отримує лист, на якому рівні і коли вдруге.

Три рахунки одного покупця, прострочені на 5, 20 і 36 днів на 31 жовтня 2026: один лист рівня
«30 днів» з усіма трьома. Повторний прохід того ж дня листа не дублює; після надсилання рахунки
пам'ятають рівень, і новий лист з'являється лише тоді, коли хоч один рахунок дійде вищого рівня.

Запуск: чиста база, тег ua_dunning.
"""
from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

TODAY = date(2026, 10, 31)


@tagged("post_install", "-at_install", "ua_dunning")
class TestUaDunning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        cls.company.invalidate_recordset()
        cls.income = cls.env["account.account"].search(
            [("code", "=like", "70%"), ("company_ids", "in", cls.company.id)], limit=1, order="code")
        cls.sale_journal = cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", cls.company.id)], limit=1)
        cls.Letter = cls.env["ua.dunning.letter"]
        cls.levels = cls.env["ua.dunning.level"]._ua_levels(cls.company)
        cls.l3, cls.l15, cls.l30 = (cls.env.ref("l10n_ua_dunning.level_%s" % d) for d in (3, 15, 30))
        Partner = cls.env["res.partner"]
        cls.buyer = Partner.create({"name": "ТОВ Боржник (тест)", "is_company": True, "email": "buh@borzhnyk.example"})
        cls.other = Partner.create({"name": "ТОВ Інший покупець (тест)", "is_company": True})

    def _invoice(self, amount, due, partner=None, contract=None):
        vals = {"move_type": "out_invoice", "partner_id": (partner or self.buyer).id, "invoice_date": due,
                "invoice_date_due": due, "journal_id": self.sale_journal.id,
                "invoice_line_ids": [Command.create({"name": "Поставка (тест)", "quantity": 1, "price_unit": amount,
                                                     "tax_ids": [Command.clear()], "account_id": self.income.id})]}
        if contract is not None:
            vals["ua_contract_id"] = contract.id
        move = self.env["account.move"].create(vals)
        if move.invoice_date_due != due:
            move.invoice_date_due = due
        move.action_post()
        self.assertEqual(move.invoice_date_due, due)
        return move

    def _letters(self, partner=None):
        return self.Letter.search([("partner_id", "=", (partner or self.buyer).id)])

    def test_levels_and_no_duplicates(self):
        self.assertEqual(self.levels.mapped("days")[:3], [30, 15, 3], "типові рівні за спаданням")
        c = self._invoice(3000.0, date(2026, 9, 25))
        b = self._invoice(2000.0, date(2026, 10, 11))
        a = self._invoice(1000.0, date(2026, 10, 26))
        self.Letter._ua_generate(self.company, TODAY)
        letter = self._letters()
        self.assertEqual(len(letter), 1, "один лист на контрагента")
        self.assertEqual(letter.level_id, self.l30, "рівень листа - найвищий серед рахунків")
        by_move = {line.move_id: (line.days_overdue, line.level_id) for line in letter.line_ids}
        self.assertEqual(by_move, {a: (5, self.l3), b: (20, self.l15), c: (36, self.l30)})
        self.assertEqual(letter.amount_total, 6000.0)
        self.assertIn(c.name, letter.body_html)
        self.assertIn("ст. 625", letter.body_html, "текст рівня 30 днів")

        self.Letter._ua_generate(self.company, TODAY)
        self.assertEqual(len(self._letters()), 1, "чернетку оновлено, а не продубльовано")

        letter.action_send()
        self.assertEqual(letter.state, "sent")
        self.assertEqual((a.ua_dunning_level_id, b.ua_dunning_level_id, c.ua_dunning_level_id),
                         (self.l3, self.l15, self.l30))
        self.assertEqual(a.ua_dunning_date, TODAY)
        message = letter.message_ids.filtered(lambda m: m.subject == letter.subject)
        self.assertIn(self.buyer, message.partner_ids, "лист пішов контрагенту")

        self.Letter._ua_generate(self.company, TODAY)
        self.assertEqual(len(self._letters()), 1, "усі рахунки вже нагадано на своїх рівнях")
        self.Letter._ua_generate(self.company, date(2026, 11, 10))
        self.assertEqual(len(self._letters()), 2, "рахунок a дійшов 15 днів, b - 30: новий лист")

    def test_paid_hold_and_excluded(self):
        paid = self._invoice(500.0, date(2026, 9, 1))
        hold = self._invoice(700.0, date(2026, 9, 1))
        hold.ua_dunning_hold = True
        self._invoice(400.0, date(2026, 9, 1), partner=self.other)
        fresh = self._invoice(900.0, date(2026, 10, 30))
        bank = self.env["account.journal"].search([("type", "=", "bank"), ("company_id", "=", self.company.id)],
                                                  limit=1)
        self.env["account.payment.register"].with_context(active_model="account.move", active_ids=paid.ids).create(
            {"payment_date": date(2026, 10, 5), "amount": 500.0, "journal_id": bank.id}).action_create_payments()
        self.assertIn(paid.payment_state, ("paid", "in_payment"))
        self.other.ua_dunning_excluded = True
        self.Letter._ua_generate(self.company, TODAY)
        self.assertFalse(self._letters(self.other), "контрагента виведено з нагадувань")
        self.assertFalse(self._letters(), "оплачений, спірний і ще не на рівні - листа немає")
        self.assertTrue(fresh)

    def test_contract_groups_and_button(self):
        Contract = self.env["ua.contract"]
        k1 = Contract.create({"name": "1/2026 (тест)", "date": date(2026, 1, 5), "partner_id": self.buyer.id,
                              "kind": "sale"})
        k2 = Contract.create({"name": "2/2026 (тест)", "date": date(2026, 2, 5), "partner_id": self.buyer.id,
                              "kind": "sale"})
        self._invoice(2000.0, date(2026, 10, 1), contract=k2)
        self._invoice(1000.0, date(2026, 10, 20), contract=k1)
        self.Letter._ua_generate(self.company, TODAY)
        letters = self._letters()
        self.assertEqual(letters.contract_id, k1 | k2, "окремий лист на кожен договір")
        self.assertIn("2/2026", letters.filtered(lambda l: l.contract_id == k2).body_html)

        k3 = Contract.create({"name": "3/2026 (тест)", "date": date(2026, 3, 5), "partner_id": self.buyer.id,
                              "kind": "sale"})
        with self.assertRaises(UserError):
            k3.action_ua_dunning_letter()
        action = k1.action_ua_dunning_letter()
        self.assertEqual(action["res_id"], letters.filtered(lambda l: l.contract_id == k1).id,
                         "кнопка договору відкриває наявну чернетку")

    def test_send_needs_email_and_cron_auto_send(self):
        self._invoice(600.0, date(2026, 10, 1))
        self._invoice(800.0, date(2026, 10, 20), partner=self.other)
        self.Letter._ua_generate(self.company, TODAY)
        self._letters().unlink()
        letter = self._letters(self.other)
        with self.assertRaises(UserError):
            letter.action_send()
        letter.action_mark_sent()
        self.assertEqual(letter.state, "sent", "передано інакше")

        self.l3.auto_send = True
        self.l15.auto_send = True
        self.l30.auto_send = True
        letters = self.Letter.with_context(tracking_disable=True)._ua_cron()
        mine = letters.filtered(lambda l: l.partner_id == self.buyer)
        self.assertEqual(mine.state, "sent", "рівень без перегляду: задача надсилає сама")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_dunning.action_report_ua_dunning_letter", mine.ids)[0].decode()
        self.assertIn(mine.name, html)
