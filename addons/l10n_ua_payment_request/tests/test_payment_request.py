# -*- coding: utf-8 -*-
"""Заявки на оплату з погодженням.

Ліміт компанії 50 000 грн: до ліміту погоджує фінансист, понад - ще й директор.

    10 000 грн постачальнику            -> фінансист -> погоджено
    80 000 грн                          -> фінансист -> директор -> погоджено
    1 000 USD за курсом 42 = 42 000     -> лише фінансист
    1 500 USD = 63 000                  -> фінансист і директор
    рахунок 12 000, заявка 12 000       -> платіж закриває рахунок
    рахунок 12 000, заявка 5 000        -> рахунок оплачено частково
    аванс 3 000 без рахунку             -> вихідний платіж 3 000

Запуск: чиста база, тег ua_payment_request.
"""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

GROUP = "l10n_ua_payment_request.group_ua_payment_request_"


@tagged("post_install", "-at_install", "ua_payment_request")
class TestUaPaymentRequest(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.sudo().ua_payment_request_limit = 50000.0
        cls.Request = cls.env["ua.payment.request"]
        cls.vendor = cls.env["res.partner"].create({"name": "ТОВ Постачальник (тест)"})
        cls.other = cls.env["res.partner"].create({"name": "Інший постачальник (тест)"})

        def user(login, group):
            return new_test_user(cls.env, login=login, groups=GROUP + group,
                                 company_id=cls.company.id,
                                 company_ids=[(6, 0, cls.company.ids)])

        cls.initiator = user("pr_initiator", "user")
        cls.finance = user("pr_finance", "approver")
        cls.finance2 = user("pr_finance2", "approver")
        cls.director = user("pr_director", "director")

        # Свій банківський журнал, що платить через 333: платіж має проводку і закриває рахунок.
        transit = cls.env["account.account"].search([
            ("code", "=", "333"), ("company_ids", "in", cls.company.id)], limit=1)
        cls.bank = cls.env["account.journal"].create({
            "name": "Банк заявок (тест)", "type": "bank", "code": "BPR",
            "company_id": cls.company.id})
        (cls.bank.inbound_payment_method_line_ids
         | cls.bank.outbound_payment_method_line_ids).payment_account_id = transit

        cls.usd = cls.env.ref("base.USD")
        cls.usd.active = True
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.usd.id)]).unlink()
        cls.env["res.currency.rate"].create({
            "name": "2026-11-01", "currency_id": cls.usd.id, "company_id": cls.company.id,
            "rate": 1 / 42.0})

    # --- службове -------------------------------------------------------

    def _request(self, amount, user=None, **vals):
        values = {"partner_id": self.vendor.id, "amount": amount, "purpose": "Оплата (тест)",
                  "date": "2026-11-05", "date_due": "2026-11-10"}
        values.update(vals)
        return self.Request.with_user(user or self.initiator).create(values)

    def _approve(self, request, *users):
        for approver in users:
            request.with_user(approver).action_approve()
        return request

    def _bill(self, amount, partner=None):
        return self.init_invoice("in_invoice", partner=partner or self.vendor,
                                 invoice_date=fields.Date.from_string("2026-11-01"),
                                 amounts=[amount], taxes=[], post=True)

    # --- 1. Кроки погодження -------------------------------------------------

    def test_01_small_request_needs_finance_only(self):
        request = self._request(10000.0)
        self.assertTrue(request.name.startswith("ЗО/"))
        self.assertEqual(request.user_id, self.initiator)
        self.assertEqual(request.steps_required, "Фінансист")
        request.with_user(self.initiator).action_submit()
        self.assertEqual(request.state, "submitted")
        self.assertEqual(request.approval_round, 1)
        self.assertEqual(request.with_user(self.finance).next_step, "finance")
        self.assertTrue(request.with_user(self.finance).can_approve)
        self.assertFalse(request.with_user(self.initiator).can_approve)

        self._approve(request, self.finance)
        self.assertEqual(request.state, "approved")
        approval = request.approval_ids
        self.assertEqual(len(approval), 1)
        self.assertEqual((approval.step, approval.decision, approval.user_id, approval.submission),
                         ("finance", "approve", self.finance, 1))

    def test_02_over_limit_needs_director(self):
        request = self._request(80000.0)
        self.assertEqual(request.steps_required, "Фінансист, Директор")
        request.with_user(self.initiator).action_submit()
        self._approve(request, self.finance)
        self.assertEqual(request.state, "submitted", "понад ліміт фінансиста замало")
        self.assertEqual(request.next_step, "director")
        self.assertFalse(request.with_user(self.finance2).can_approve)
        with self.assertRaises(UserError):
            request.with_user(self.finance2).action_approve()
        self.assertTrue(request.with_user(self.director).can_approve)
        self._approve(request, self.director)
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_ids.mapped("step"), ["finance", "director"])

    def test_03_initiator_never_approves_own_request(self):
        request = self._request(10000.0, user=self.finance2)
        request.with_user(self.finance2).action_submit()
        self.assertFalse(request.with_user(self.finance2).can_approve)
        with self.assertRaises(UserError):
            request.with_user(self.finance2).action_approve()
        self._approve(request, self.finance)
        self.assertEqual(request.state, "approved")

    def test_04_foreign_currency_counts_in_hryvnia(self):
        small = self._request(1000.0, currency_id=self.usd.id)
        self.assertAlmostEqual(small.amount_company, 42000.0, places=2)
        self.assertEqual(small.steps_required, "Фінансист")
        large = self._request(1500.0, currency_id=self.usd.id)
        self.assertAlmostEqual(large.amount_company, 63000.0, places=2)
        self.assertEqual(large.steps_required, "Фінансист, Директор")

    def test_05_no_limit_means_director_always(self):
        self.company.sudo().ua_payment_request_limit = 0.0
        request = self._request(100.0)
        self.assertEqual(request.steps_required, "Фінансист, Директор")

    # --- 2. Відхилення й повторне подання -------------------------------------

    def test_06_reject_needs_reason_and_resubmit_starts_new_round(self):
        request = self._request(10000.0)
        request.with_user(self.initiator).action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.finance).action_reject()
        request.with_user(self.finance).reject_reason = "Немає рахунку"
        request.with_user(self.finance).action_reject()
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.approval_ids.decision, "reject")
        self.assertEqual(request.approval_ids.note, "Немає рахунку")

        request.with_user(self.initiator).amount = 9000.0
        request.with_user(self.initiator).action_submit()
        self.assertEqual(request.approval_round, 2)
        self.assertFalse(request.reject_reason)
        self.assertEqual(request.next_step, "finance", "нове подання починається з першого кроку")
        self._approve(request, self.finance)
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_ids.mapped("submission"), [1, 2])
        self.assertEqual(request.approval_ids.mapped("decision"), ["reject", "approve"])

    def test_07_approval_in_old_round_does_not_count(self):
        request = self._request(80000.0)
        request.with_user(self.initiator).action_submit()
        self._approve(request, self.finance)
        request.with_user(self.director).reject_reason = "Дорого"
        request.with_user(self.director).action_reject()
        request.with_user(self.initiator).action_submit()
        self.assertEqual(request.next_step, "finance",
                         "погодження фінансиста з першого подання не переходить у друге")

    # --- 3. Платіж ------------------------------------------------------

    def test_08_payment_from_bill_closes_it(self):
        bill = self._bill(12000.0)
        request = self._request(12000.0, user=self.env.user, bill_ids=[(6, 0, bill.ids)],
                                journal_id=self.bank.id)
        request.action_submit()
        with self.assertRaises(UserError):
            request.action_create_payment()  # ще не погоджено
        self._approve(request, self.finance)
        action = request.action_create_payment()
        payment = self.env["account.payment"].browse(action["res_id"])
        self.assertEqual(request.state, "payment")
        self.assertEqual(request.payment_ids, payment)
        self.assertAlmostEqual(payment.amount, 12000.0, places=2)
        self.assertEqual(payment.partner_id, self.vendor)
        self.assertEqual(payment.payment_type, "outbound")
        self.assertEqual(payment.journal_id, self.bank)
        self.assertTrue(payment.move_id, "платіж має проводку")
        self.assertIn(bill.payment_state, ("in_payment", "paid"))
        self.assertAlmostEqual(bill.amount_residual, 0.0, places=2)
        with self.assertRaises(UserError):
            request.action_cancel()  # платіж уже є

    def test_09_partial_payment_and_too_much(self):
        bill = self._bill(12000.0)
        request = self._request(5000.0, user=self.env.user, bill_ids=[(6, 0, bill.ids)],
                                journal_id=self.bank.id)
        request.action_submit()
        self._approve(request, self.finance)
        request.action_create_payment()
        self.assertEqual(bill.payment_state, "partial")
        self.assertAlmostEqual(bill.amount_residual, 7000.0, places=2)

        too_much = self._request(8000.0, user=self.env.user, bill_ids=[(6, 0, bill.ids)],
                                 journal_id=self.bank.id)
        too_much.action_submit()
        self._approve(too_much, self.finance)
        with self.assertRaises(UserError):
            too_much.action_create_payment()  # на рахунку лишилось 7 000

    def test_10_advance_without_bill(self):
        request = self._request(3000.0, purpose="Аванс за датчики (тест)")
        request.with_user(self.initiator).action_submit()
        self._approve(request, self.finance)
        request = request.with_user(self.env.user)  # далі працює бухгалтер
        request.journal_id = self.bank  # рахунок оплати обирає бухгалтер
        request.action_create_payment()
        payment = request.payment_ids
        self.assertEqual(len(payment), 1)
        self.assertAlmostEqual(payment.amount, 3000.0, places=2)
        self.assertEqual(payment.memo, "Аванс за датчики (тест)")
        self.assertIn(payment.state, ("in_process", "paid"))
        self.assertEqual(payment.date, fields.Date.from_string("2026-11-10"))

    def test_11_bills_must_belong_to_recipient(self):
        bill = self._bill(1000.0, partner=self.other)
        with self.assertRaises(ValidationError):
            self._request(1000.0, user=self.env.user, bill_ids=[(6, 0, bill.ids)])

    # --- 4. Календар, друк, межі -----------------------------------------------

    def test_12_payment_calendar(self):
        submitted = self._request(1000.0, date_due="2026-11-20")
        submitted.with_user(self.initiator).action_submit()
        approved = self._request(2000.0, date_due="2026-11-20")
        approved.with_user(self.initiator).action_submit()
        self._approve(approved, self.finance)
        later = self._request(500.0, date_due="2026-11-23")
        later.with_user(self.initiator).action_submit()
        self._approve(later, self.finance)
        self._request(700.0, date_due="2026-11-20")  # чернетка - не в календарі
        rows = self.Request.calendar_rows("2026-11-20", "2026-11-30", self.company)
        self.assertEqual([(str(r["date"]), r["requests"], r["amount"], r["approved"]) for r in rows],
                         [("2026-11-20", 2, 3000.0, 2000.0), ("2026-11-23", 1, 500.0, 500.0)])

    def test_13_print_and_guards(self):
        request = self._request(10000.0)
        request.with_user(self.initiator).action_submit()
        self._approve(request, self.finance)
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_payment_request.report_ua_payment_request", request.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("ЗАЯВКА НА ОПЛАТУ", request.name, self.vendor.name, "Оплата (тест)",
                         self.finance.name):
            self.assertIn(expected, text)
        with self.assertRaises(UserError):
            request.unlink()  # погоджену не видаляють
        with self.assertRaises(UserError):
            request.with_user(self.initiator).action_submit()  # уже погоджено
        draft = self._request(100.0)
        draft.with_user(self.initiator).unlink()
        self.assertFalse(draft.exists())
