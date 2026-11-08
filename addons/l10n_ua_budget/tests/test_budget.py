# -*- coding: utf-8 -*-
"""Бюджет руху коштів на 2026 рік і заявки на оплату під ним.

План січня: 3000 надходження від покупців 120 000, 3100 оплата товарів і послуг 50 000,
3105 зарплата 30 000. Факт січня: покупець заплатив 100 000, постачальнику - 20 000, витрати
майбутніх періодів 1 000 (статті немає - 3190, у плані немає).
Ліміт заявки без директора 50 000.
- Заявка 25 000 за статтею 3100 на 25.01: залишок 50 000 - 20 000 = 30 000 - лише фінансист.
- Заявка 10 000 там само: залишок 30 000 - 25 000 (відкрита заявка) = 5 000 - понад бюджет,
  потрібен директор.
- Заявка без статті - не подати. Лютий без плану - понад бюджет.
- Контроль «заявку не подати» - помилка.
- Платіж за першою заявкою несе статтю; після оновлення факт 3100 - 45 000.
- Бюджет 2027 з факту 2026 + 10 %: 3100 січень 49 500, 3000 січень 110 000.

Запуск: тег ua_budget.
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

GROUP = "l10n_ua_payment_request.group_ua_payment_request_"


@tagged("post_install", "-at_install", "ua_budget")
class TestUaBudget(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.sudo().ua_payment_request_limit = 50000.0
        cls.Request = cls.env["ua.payment.request"]
        cls.Budget = cls.env["ua.cashflow.budget"]
        cls.vendor = cls.env["res.partner"].create({"name": "ТОВ Постачальник (тест бюджету)"})

        def user(login, group):
            return new_test_user(cls.env, login=login, groups=GROUP + group, company_id=cls.company.id,
                                 company_ids=[(6, 0, cls.company.ids)])
        cls.initiator = user("bdds_initiator", "user")
        cls.finance = user("bdds_finance", "approver")
        cls.director = user("bdds_director", "director")
        transit = cls._acc("333")
        transit.reconcile = True
        cls.bank = cls.env["account.journal"].create({
            "name": "Банк бюджету (тест)", "type": "bank", "code": "BDD", "company_id": cls.company.id})
        (cls.bank.inbound_payment_method_line_ids
         | cls.bank.outbound_payment_method_line_ids).payment_account_id = transit
        cls.misc = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        for day, rows in [
            (date(2026, 1, 10), [("311", 100000), ("361", -100000)]),
            (date(2026, 1, 12), [("631", 20000), ("311", -20000)]),
            (date(2026, 1, 14), [("39", 1000), ("311", -1000)]),
        ]:
            cls._entry(day, rows)
        cls.budget = cls.Budget.create({"name": "БДДС 2026 (тест)", "year": 2026, "control": "director"})
        for code, plan in (("3000", 120000), ("3100", 50000), ("3105", 30000)):
            cls.env["ua.cashflow.budget.line"].create(
                {"budget_id": cls.budget.id, "item_id": cls._item(code).id, "month": "1", "plan": plan})
        cls.budget.action_approve()

    @classmethod
    def _acc(cls, code):
        Account = cls.env["account.account"].with_company(cls.company)
        domain = [("company_ids", "in", cls.company.id)]
        return Account.search(domain + [("code", "=", code)], limit=1) or \
            Account.search(domain + [("code", "=like", code + "%")], order="code", limit=1)

    @classmethod
    def _item(cls, code):
        return cls.env["ua.cashflow.item"].search([("code", "=", code)], limit=1)

    @classmethod
    def _entry(cls, day, rows):
        move = cls.env["account.move"].create({
            "move_type": "entry", "date": day, "journal_id": cls.misc.id,
            "line_ids": [(0, 0, {"account_id": cls._acc(code).id, "name": "Тест БДДС",
                                 "debit": max(amount, 0), "credit": max(-amount, 0)}) for code, amount in rows]})
        move.action_post()
        return move

    def _request(self, amount, item="3100", due="2026-01-25", **vals):
        values = {"partner_id": self.vendor.id, "amount": amount, "purpose": "Оплата (тест бюджету)",
                  "date": "2026-01-05", "date_due": due, "journal_id": self.bank.id,
                  "ua_cashflow_item_id": self._item(item).id if item else False}
        values.update(vals)
        return self.Request.with_user(self.initiator).create(values)

    def _line(self, budget, code, month="1"):
        return budget.line_ids.filtered(lambda l: l.item_id.code == code and l.month == month)

    def test_01_fact_and_unplanned_item(self):
        self.budget.action_refresh_fact()
        self.assertEqual(self._line(self.budget, "3100").fact, 20000)
        self.assertEqual(self._line(self.budget, "3000").fact, 100000)
        self.assertEqual(self._line(self.budget, "3105").fact, 0)
        unplanned = self._line(self.budget, "3190")
        self.assertEqual((unplanned.plan, unplanned.fact), (0, 1000))
        self.assertEqual(self._line(self.budget, "3100").remaining, 30000)
        self.assertEqual((self.budget.plan_in, self.budget.fact_in), (120000, 100000))

    def test_02_requests_against_budget(self):
        first = self._request(25000.0)
        self.assertEqual(first.ua_budget_remaining, 30000)
        first.with_user(self.initiator).action_submit()
        self.assertFalse(first.ua_budget_over)
        self.assertEqual(first.steps_required, "Фінансист")

        second = self._request(10000.0, due="2026-01-28")
        self.assertEqual(second.ua_budget_remaining, 5000)
        second.with_user(self.initiator).action_submit()
        self.assertTrue(second.ua_budget_over)
        self.assertEqual(second.steps_required, "Фінансист, Директор")
        second.with_user(self.finance).action_approve()
        self.assertEqual(second.state, "submitted", "понад бюджет фінансиста замало")
        second.with_user(self.director).action_approve()
        self.assertEqual(second.state, "approved")

        no_item = self._request(1000.0, item=False)
        with self.assertRaises(UserError):
            no_item.with_user(self.initiator).action_submit()

        february = self._request(1000.0, due="2026-02-10")
        february.with_user(self.initiator).action_submit()
        self.assertTrue(february.ua_budget_over, "на лютий плану немає")

        self.budget.control = "block"
        third = self._request(10000.0, due="2026-01-29")
        with self.assertRaises(UserError):
            third.with_user(self.initiator).action_submit()
        self.assertEqual(third.state, "draft")

        self.budget.action_refresh_fact()
        self.assertEqual(self._line(self.budget, "3100").committed, 35000)

    def test_03_payment_carries_item_into_fact(self):
        request = self._request(25000.0)
        request.with_user(self.initiator).action_submit()
        request.with_user(self.finance).action_approve()
        request = request.with_env(self.env)  # платіж робить бухгалтер
        request.action_create_payment()
        payment = request.payment_ids
        self.assertEqual(payment.ua_cashflow_item_id, self._item("3100"))
        self.budget.action_refresh_fact()
        line = self._line(self.budget, "3100")
        self.assertEqual((line.fact, line.committed, line.remaining), (45000, 0, 5000))

        nxt = self.Budget.create({"name": "БДДС 2027 (тест)", "year": 2027, "fill_year": 2026,
                                  "fill_percent": 10})
        nxt.action_fill_from_fact()
        self.assertEqual(self._line(nxt, "3100").plan, 49500)
        self.assertEqual(self._line(nxt, "3000").plan, 110000)

    def test_04_rules(self):
        twin = self.Budget.create({"name": "Ще один (тест)", "year": 2026})
        self.env["ua.cashflow.budget.line"].create(
            {"budget_id": twin.id, "item_id": self._item("3100").id, "month": "2", "plan": 1})
        with self.assertRaises(ValidationError):
            twin.action_approve()
        with self.assertRaises(UserError):
            self._line(self.budget, "3100").plan = 1
        with self.assertRaises(ValidationError):
            self.env["ua.cashflow.budget.line"].create(
                {"budget_id": twin.id, "item_id": self._item("3105").id, "month": "3", "plan": -5})
        self.budget.action_refresh_fact()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_budget.report_ua_budget", self.budget.ids)[0].decode()
        self.assertIn("Виконання бюджету руху грошових коштів", html)
        self.assertIn("50000.00", html)
