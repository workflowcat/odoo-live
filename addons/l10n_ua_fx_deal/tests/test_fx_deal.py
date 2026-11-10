# -*- coding: utf-8 -*-
"""Купівля і продаж валюти: проводки через гроші в дорозі.

1 000 USD, курс НБУ 41,20, комісія банку 100 грн. Купівля за 41,50 - 300 грн понад НБУ на 942;
купівля за 41,00 - 200 грн доходу на 711; продаж за 41,00 - дохід 41 000 на 711 і собівартість
41 200 на 942. Після обох банківських ніг сальдо 333 - нуль.

Запуск: чиста база, тег ua_fx_deal.
"""
import datetime

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

DAY = datetime.date(2026, 10, 5)


@tagged("post_install", "-at_install", "ua_fx_deal")
class TestUaFxDeal(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.usd = cls.env.ref("base.USD")
        cls.usd.active = True
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.usd.id)]).unlink()
        cls.env["res.currency.rate"].create({
            "name": "2026-10-01", "currency_id": cls.usd.id, "company_id": cls.company.id, "rate": 1 / 41.2})
        cls.transit = cls._acc("333", "asset_cash")
        cls.income = cls._acc("711", "income_other")
        cls.expense = cls._acc("942", "expense")
        cls.fee = cls._acc("92", "expense")
        cls.uah_bank = cls.env["account.journal"].create({
            "name": "Банк UAH (тест)", "type": "bank", "code": "BFXU", "company_id": cls.company.id})
        cls.usd_bank = cls.env["account.journal"].create({
            "name": "Банк USD (тест)", "type": "bank", "code": "BFXD", "currency_id": cls.usd.id,
            "company_id": cls.company.id})

    @classmethod
    def _acc(cls, code, account_type):
        Account = cls.env["account.account"]
        account = Account.search([("code", "=", code), ("company_ids", "in", cls.company.id)], limit=1)
        return account or Account.create({"code": code, "name": "Рахунок %s (тест)" % code,
                                          "account_type": account_type, "company_ids": [(6, 0, cls.company.ids)]})

    def _deal(self, kind, rate, legs=True, **values):
        vals = {"kind": kind, "date": DAY, "currency_id": self.usd.id, "amount_currency": 1000.0,
                "deal_rate": rate, "commission": 100.0, "uah_journal_id": self.uah_bank.id,
                "fx_journal_id": self.usd_bank.id, "post_bank_legs": legs,
                "transit_account_id": self.transit.id, "income_account_id": self.income.id,
                "expense_account_id": self.expense.id, "fee_account_id": self.fee.id}
        vals.update(values)
        return self.env["ua.fx.deal"].create(vals)

    @staticmethod
    def _balance(move, account):
        return round(sum(move.line_ids.filtered(lambda l: l.account_id == account).mapped("balance")), 2)

    def test_buy_above_nbu(self):
        deal = self._deal("buy", 41.5)
        self.assertAlmostEqual(deal.nbu_rate, 41.2, places=4, msg="курс НБУ з курсів валют на дату")
        self.assertTrue(deal.name.startswith("ВАЛ-"))
        self.assertEqual((deal.amount_deal, deal.amount_nbu, deal.difference), (41500.0, 41200.0, 300.0))
        deal.action_post()
        move = deal.move_id
        self.assertEqual((deal.state, move.state), ("posted", "posted"))
        self.assertEqual(self._balance(move, self.transit), 0.0, "гроші в дорозі закрито")
        self.assertEqual(self._balance(move, self.expense), 300.0)
        self.assertEqual(self._balance(move, self.income), 0.0)
        self.assertEqual(self._balance(move, self.fee), 100.0)
        self.assertEqual(self._balance(move, self.uah_bank.default_account_id), -41600.0)
        usd_line = move.line_ids.filtered(lambda l: l.account_id == self.usd_bank.default_account_id)
        self.assertEqual((usd_line.balance, usd_line.amount_currency, usd_line.currency_id),
                         (41200.0, 1000.0, self.usd), "валюта приходить за курсом НБУ")

    def test_buy_below_nbu_without_bank_legs(self):
        deal = self._deal("buy", 41.0, legs=False)
        self.assertEqual(deal.difference, -200.0)
        deal.action_post()
        move = deal.move_id
        self.assertEqual(self._balance(move, self.income), -200.0, "дешевше за НБУ - дохід 711")
        self.assertEqual(self._balance(move, self.expense), 0.0)
        self.assertFalse(move.line_ids.filtered(
            lambda l: l.account_id in (self.uah_bank.default_account_id | self.usd_bank.default_account_id)),
            "без банківських ніг гроші рухають виписки")
        # виписки: гривні 41 100 у банк (Дт 333), валюта 41 200 на рахунок (Кт 333)
        self.assertEqual(self._balance(move, self.transit) + 41100.0 - 41200.0, 0.0)

    def test_sell(self):
        deal = self._deal("sell", 41.0)
        self.assertEqual(deal.difference, -200.0, "продаж дешевше за НБУ")
        deal.action_post()
        move = deal.move_id
        self.assertEqual(self._balance(move, self.transit), 0.0)
        self.assertEqual(self._balance(move, self.income), -41000.0, "дохід - за курсом угоди")
        self.assertEqual(self._balance(move, self.expense), 41200.0, "собівартість - за курсом НБУ")
        self.assertEqual(self._balance(move, self.uah_bank.default_account_id), 40900.0, "без комісії")
        usd_line = move.line_ids.filtered(lambda l: l.account_id == self.usd_bank.default_account_id)
        self.assertEqual((usd_line.balance, usd_line.amount_currency), (-41200.0, -1000.0))

    def test_cancel_reverses(self):
        deal = self._deal("buy", 41.5)
        deal.action_post()
        move = deal.move_id
        deal.action_cancel()
        self.assertEqual(deal.state, "cancel")
        reversal = self.env["account.move"].search([("reversed_entry_id", "=", move.id)])
        self.assertTrue(reversal, "проводку сторновано")
        self.assertEqual(self._balance(move, self.expense) + self._balance(reversal, self.expense), 0.0)
        deal.action_draft()
        self.assertEqual((deal.state, deal.move_id), ("draft", self.env["account.move"]))

    def test_needs_nbu_rate(self):
        deal = self._deal("buy", 41.5, date=datetime.date(2026, 9, 1))
        self.assertEqual(deal.nbu_rate, 0.0, "курсу на дату немає")
        with self.assertRaises(UserError):
            deal.action_post()
        deal.nbu_rate = 41.0
        deal.action_post()
        self.assertEqual(deal.state, "posted", "курс, вписаний вручну, діє")
        with self.assertRaises(UserError):
            deal.unlink()
