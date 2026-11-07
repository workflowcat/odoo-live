# -*- coding: utf-8 -*-
"""Грант: надходження на 484, використання за аналітикою, визнання доходу, перевитрата, звіт.

Грант 1 000 000 від фонду (тест). Кошторис: «Управління» 100 000 (рахунок 92), «Виробництво»
900 000 (рахунок 91).
Надійшло 500 000 (Дт 311 Кт 484, без аналітики) - «Знайти надходження» позначає рядок грантом.
Рахунки постачальників з аналітикою гранту: 120 000 на 92 і 80 000 на 91; ще 50 000 на 91
без аналітики - не грант. Використано 200 000, «Управління» перевитрачено на 20 000.
Визнання: Дт 484 Кт 718 200 000. Далі ще 400 000 на 91 - використано 600 000, але визнаємо
лише до отриманого: ще 300 000.

Запуск: тег ua_grant.
"""
from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_grant")
class TestUaGrant(TransactionCase):

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
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.acc_484 = chart.ref("ua_psbp_484")
        cls.acc_718 = chart.ref("ua_psbp_718")
        cls.acc_91 = chart.ref("ua_psbp_91")
        cls.acc_92 = chart.ref("ua_psbp_92")
        cls.acc_311 = chart.ref("ua_psbp_311")
        Journal = cls.env["account.journal"]
        cls.general = Journal.search([("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        cls.purchase = Journal.search([("type", "=", "purchase"), ("company_id", "=", cls.company.id)], limit=1)
        Partner = cls.env["res.partner"]
        cls.fund = Partner.create({"name": "Фонд підтримки (тест)", "is_company": True})
        cls.vendor = Partner.create({"name": "ТОВ Постачальник (тест)", "is_company": True})
        cls.grant = cls.env["ua.grant"].create({
            "name": "ГР-15/2026", "grantor_id": cls.fund.id, "program": "Програма (тест)", "amount": 1000000.0,
            "line_ids": [
                (0, 0, {"name": "Управління", "amount": 100000.0, "account_ids": [(6, 0, cls.acc_92.ids)]}),
                (0, 0, {"name": "Виробництво", "amount": 900000.0, "account_ids": [(6, 0, cls.acc_91.ids)]}),
            ]})
        cls.today = fields.Date.context_today(cls.env.user)

    def _receipt(self, amount):
        move = self.env["account.move"].create({
            "move_type": "entry", "journal_id": self.general.id, "date": self.today, "line_ids": [
                (0, 0, {"account_id": self.acc_311.id, "debit": amount, "partner_id": self.fund.id}),
                (0, 0, {"account_id": self.acc_484.id, "credit": amount, "partner_id": self.fund.id})]})
        move.action_post()
        return move

    def _bill(self, account, amount, grant=True):
        line = {"name": "Витрати (тест)", "quantity": 1, "price_unit": amount, "account_id": account.id,
                "tax_ids": [Command.clear()]}
        if grant:
            line["analytic_distribution"] = self.grant.ua_analytic_distribution()
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": self.vendor.id, "invoice_date": self.today,
            "journal_id": self.purchase.id, "invoice_line_ids": [Command.create(line)]})
        bill.action_post()
        return bill

    def _money(self):
        grant = self.grant.ua_fresh()
        return {"received": grant.received, "spent": grant.spent, "recognized": grant.recognized,
                "to_recognize": grant.to_recognize}

    def test_01_receive_spend_recognize(self):
        self.assertEqual(self.grant.funding_account_id, self.acc_484)
        self.assertEqual(self.grant.income_account_id, self.acc_718)
        self.assertTrue(self.grant.analytic_account_id)
        self.grant.action_activate()

        self._receipt(500000.0)
        self.assertEqual(self._money()["received"], 0.0, "без аналітики надходження ще не гранту")
        self.grant.action_find_receipts()
        self.assertEqual(self._money()["received"], 500000.0)
        with self.assertRaises(UserError, msg="нових надходжень немає"):
            self.grant.action_find_receipts()

        self._bill(self.acc_92, 120000.0)
        self._bill(self.acc_91, 80000.0)
        self._bill(self.acc_91, 50000.0, grant=False)
        self.assertEqual(self._money(), {"received": 500000.0, "spent": 200000.0, "recognized": 0.0,
                                         "to_recognize": 200000.0})
        admin, production = self.grant.line_ids.sorted("sequence")
        self.assertEqual((admin.spent, admin.remaining, admin.over_budget), (120000.0, -20000.0, True))
        self.assertEqual((production.spent, production.over_budget), (80000.0, False))
        self.assertTrue(self.grant.over_budget)

        self.grant.action_recognize()
        move = self.grant.move_ids
        self.assertEqual(len(move), 1)
        self.assertEqual(move.line_ids.filtered(lambda l: l.account_id == self.acc_718).credit, 200000.0)
        self.assertEqual(self._money()["recognized"], 200000.0)
        self.assertEqual(self._money()["to_recognize"], 0.0)
        self.assertEqual(self._money()["received"], 500000.0, "визнання не змінює отримане")
        with self.assertRaises(UserError):
            self.grant.action_recognize()

        self._bill(self.acc_91, 400000.0)
        money = self._money()
        self.assertEqual((money["spent"], money["to_recognize"]), (600000.0, 300000.0),
                         "дохід - не більше отриманого")
        self.grant.action_recognize()
        self.assertEqual(self._money()["recognized"], 500000.0)
        self.assertEqual(self.grant.remaining, -100000.0, "використано більше, ніж отримано")

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_grant.report_ua_grant", self.grant.ids)[0].decode()
        for text in ("ЗВІТ ПРО ВИКОРИСТАННЯ КОШТІВ ГРАНТУ", "ГР-15/2026", "Фонд підтримки (тест)",
                     "Управління", "(перевитрата)", "120 000,00", "600 000,00", "500 000,00"):
            self.assertIn(text, html)

    def test_02_guards(self):
        with self.assertRaises(ValidationError, msg="один рахунок у двох статтях"):
            self.grant.line_ids[:1].account_ids = [(4, self.acc_91.id)]
        with self.assertRaises(ValidationError):
            self.env["ua.grant"].create({"name": "ГР-0", "grantor_id": self.fund.id, "amount": 0.0})
        empty = self.env["ua.grant"].create({"name": "ГР-1", "grantor_id": self.fund.id, "amount": 1000.0})
        with self.assertRaises(UserError, msg="без кошторису"):
            empty.action_activate()
        empty.line_ids = [(0, 0, {"name": "Усе", "amount": 2000.0, "account_ids": [(6, 0, self.acc_92.ids)]})]
        with self.assertRaises(UserError, msg="кошторис більший за грант"):
            empty.action_activate()
        with self.assertRaises(UserError, msg="нічого визнавати"):
            self.grant.action_recognize()
