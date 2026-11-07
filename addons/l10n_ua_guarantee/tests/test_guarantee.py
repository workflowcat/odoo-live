# -*- coding: utf-8 -*-
"""Аванси і гарантії за договорами.

Постачальник «Оптика» (договір П-7/2026): підприємство платить аванс 30 000.
  Гарантія повернення авансу Г-1 на 20 000 - без забезпечення лишається 10 000.
  Рахунок постачальника на 12 000 - аванс 18 000, покрито повністю.
  Г-1 повернути не можна: аванс 18 000 лишився б без гарантії.
  Нова гарантія Г-2 на 18 000 - тепер Г-1 повертається.
  Рахунок на 18 000 - аванс 0, повертається і Г-2.

Покупець «Замовник» (договір 21/2026, аванс відпрацювати до вчора): платить аванс 50 000.
  Надана гарантія повернення авансу на 30 000 - без забезпечення 20 000, аванс прострочено.
  Гарантія виконання діє ще 10 днів (нагадати за 30) - нагадування; тендерна гарантія
  закінчилась учора - «строк минув».

Рахунки без ПДВ, щоб сума рахунку дорівнювала сумі рядка. Запуск: тег ua_guarantee.
"""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_guarantee")
class TestUaGuarantee(TransactionCase):

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
        cls.today = fields.Date.context_today(cls.env.user)

        Account = cls.env["account.account"]
        cls.expense = Account.search([("account_type", "=", "expense"),
                                      ("company_ids", "in", cls.company.id)], limit=1, order="code")
        cls.income = Account.search([("code", "=like", "70%"),
                                     ("company_ids", "in", cls.company.id)], limit=1, order="code")
        Journal = cls.env["account.journal"]
        cls.bank = Journal.search([("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)
        cls.purchase_journal = Journal.search([("type", "=", "purchase"),
                                               ("company_id", "=", cls.company.id)], limit=1)

        Partner = cls.env["res.partner"]
        cls.supplier = Partner.create({"name": "ТОВ Оптика (тест)", "is_company": True})
        cls.customer = Partner.create({"name": "ДП Замовник (тест)", "is_company": True})
        cls.bank_partner = Partner.create({"name": "АТ Банк гарант (тест)", "is_company": True})
        Contract = cls.env["ua.contract"]
        cls.supply = Contract.create({"name": "П-7/2026", "partner_id": cls.supplier.id,
                                      "kind": "purchase", "is_main": True})
        cls.sale = Contract.create({"name": "21/2026", "partner_id": cls.customer.id, "kind": "sale",
                                    "is_main": True, "amount": 150000.0,
                                    "date_end": cls.today + timedelta(days=100),
                                    "ua_advance_due": cls.today - timedelta(days=1)})

    # ------------------------------------------------------------------
    def _payment(self, contract, amount):
        inbound = contract.kind == "sale"
        payment = self.env["account.payment"].create({
            "payment_type": "inbound" if inbound else "outbound",
            "partner_type": "customer" if inbound else "supplier",
            "partner_id": contract.partner_id.id, "amount": amount, "journal_id": self.bank.id,
            "date": self.today, "ua_contract_id": contract.id})
        payment.action_post()
        return payment

    def _bill(self, amount):
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": self.supplier.id, "invoice_date": self.today,
            "journal_id": self.purchase_journal.id, "ua_contract_id": self.supply.id,
            "invoice_line_ids": [Command.create({
                "name": "Об'єктиви", "quantity": 1, "price_unit": amount,
                "tax_ids": [Command.clear()], "account_id": self.expense.id})]})
        bill.action_post()
        return bill

    def _guarantee(self, contract, name, amount, kind="advance", days=60, **extra):
        values = {"name": name, "partner_id": contract.partner_id.id, "contract_id": contract.id,
                  "direction": "received" if contract.kind == "purchase" else "given",
                  "kind": kind, "issuer_id": self.bank_partner.id, "amount": amount,
                  "date_issue": self.today - timedelta(days=5),
                  "date_expiry": self.today + timedelta(days=days)}
        values.update(extra)
        return self.env["ua.guarantee"].create(values)

    @staticmethod
    def _advance(contract):
        contract._ua_advance_fresh()
        return (contract.ua_advance_balance, contract.ua_advance_cover, contract.ua_advance_uncovered)

    # ------------------------------------------------------------------
    def test_01_supplier_advance_and_release_rule(self):
        self._payment(self.supply, 30000.0)
        self.assertEqual(self._advance(self.supply), (30000.0, 0.0, 30000.0))
        self.assertTrue(self.supply.ua_advance_unsecured)
        self.assertFalse(self.supply.ua_advance_overdue, "строку відпрацювання немає")

        g1 = self._guarantee(self.supply, "Г-1", 20000.0)
        self.assertEqual(g1.off_balance_code, "06")
        self.assertEqual(self._advance(self.supply), (30000.0, 0.0, 30000.0), "чернетка не покриває")
        g1.action_activate()
        self.assertEqual(self._advance(self.supply), (30000.0, 20000.0, 10000.0))

        self._bill(12000.0)
        self.assertEqual(self._advance(self.supply), (18000.0, 20000.0, 0.0))
        self.assertFalse(self.supply.ua_advance_unsecured)
        with self.assertRaises(UserError, msg="аванс 18 000 лишився б без гарантії"):
            g1.action_release()

        g2 = self._guarantee(self.supply, "Г-2", 18000.0)
        g2.action_activate()
        g1.action_release()
        self.assertEqual((g1.state, g1.release_date), ("released", self.today))
        self.assertEqual(self._advance(self.supply), (18000.0, 18000.0, 0.0))

        self._bill(18000.0)
        self.assertEqual(self._advance(self.supply)[0], 0.0)
        g2.action_release()
        self.assertEqual(g2.state, "released")

        Contract = self.env["ua.contract"]
        self.assertNotIn(self.supply, Contract.search([("ua_advance_open", "=", True)]))

    def test_02_customer_advance_reminders(self):
        self._payment(self.sale, 50000.0)
        guarantee = self._guarantee(self.sale, "НГ-5", 30000.0)
        guarantee.action_activate()
        self.assertEqual(guarantee.off_balance_code, "05")
        self.assertAlmostEqual(guarantee.contract_percent, 20.0, 2)
        self.assertEqual(self._advance(self.sale), (50000.0, 30000.0, 20000.0))
        self.assertTrue(self.sale.ua_advance_overdue)

        Contract = self.env["ua.contract"]
        self.assertIn(self.sale, Contract.search([("ua_advance_overdue", "=", True)]))
        self.assertIn(self.sale, Contract.search([("ua_advance_unsecured", "=", True)]))
        self.assertNotIn(self.supply, Contract.search([("ua_advance_open", "=", True)]))
        self.assertIn(self.supply, Contract.search([("ua_advance_open", "!=", True)]))

        performance = self._guarantee(self.sale, "НГ-6", 15000.0, kind="performance", days=10)
        performance.action_activate()
        self.assertTrue(performance.shorter_than_contract, "договір діє 100 днів, гарантія 10")
        bid = self._guarantee(self.sale, "ТЗ-1", 5000.0, kind="bid", days=3)
        bid.action_activate()
        bid.date_expiry = self.today - timedelta(days=1)

        Guarantee = self.env["ua.guarantee"]
        Guarantee._cron_reminders()
        self.assertEqual(bid.state, "expired")
        self.assertEqual(len(performance.activity_ids), 1, "кінець строку за 10 днів")
        self.assertFalse(guarantee.activity_ids, "до кінця 60 днів, нагадування за 30")
        self.assertEqual(len(self.sale.activity_ids), 1, "аванс прострочено")
        Guarantee._cron_reminders()
        self.assertEqual(len(performance.activity_ids), 1, "повтор не ставимо")
        self.assertEqual(len(self.sale.activity_ids), 1)

        performance.claim_amount = 15000.0
        performance.action_claim()
        self.assertEqual((performance.state, performance.claim_date), ("claimed", self.today))
        bid.action_release()
        self.assertEqual(bid.state, "released")

    def test_03_guards(self):
        with self.assertRaises(ValidationError):
            self._guarantee(self.sale, "Н-0", 0.0)
        with self.assertRaises(ValidationError):
            self._guarantee(self.sale, "Н-1", 100.0, date_expiry=self.today - timedelta(days=10))
        with self.assertRaises(ValidationError, msg="договір іншого контрагента"):
            self._guarantee(self.sale, "Н-2", 100.0, partner_id=self.supplier.id)
        late = self._guarantee(self.sale, "Н-3", 100.0, days=1)
        late.date_expiry = self.today - timedelta(days=1)
        with self.assertRaises(UserError, msg="строк уже минув"):
            late.action_activate()
        guarantee = self._guarantee(self.sale, "Н-4", 100.0)
        with self.assertRaises(UserError, msg="чернетку не повертають"):
            guarantee.action_release()
        guarantee.action_activate()
        with self.assertRaises(UserError, msg="вимога без суми"):
            guarantee.action_claim()
        with self.assertRaises(ValidationError):
            guarantee.claim_amount = 200.0
        action = self.sale.action_ua_guarantees()
        self.assertEqual(action["context"]["default_direction"], "given")
        self.assertEqual(self.sale.ua_guarantee_count, 2)
