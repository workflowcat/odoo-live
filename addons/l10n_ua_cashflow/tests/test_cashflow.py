# -*- coding: utf-8 -*-
"""Форма № 3 на наборі проводок, порахованому руками.

До звітного періоду: 10.02.2025 оплата покупця 20 000 (попередній рік, 3000), 15.12.2025 внесок до
капіталу 50 000. Залишок на 01.01.2026 - 70 000, на 01.01.2025 - 0.

Звітний період 01.01-31.03.2026:
- 10.01 оплата покупця 100 000 (Дт 311 Кт 361) - 3000;
- 12.01 оплата постачальнику 30 000 (Дт 631 Кт 311) - 3100;
- 15.01 оплата постачальнику за верстат 40 000, на проводці стаття 3260;
- 20.01 зарплата 25 000 (661) - 3105; ПДВ 8 000 (6412) - 3117; ПДФО 5 000 (6411) - 3118, разом 3115 - 13 000;
- 01.02 з банку в касу 2 000 - переміщення, у звіт не йде;
- 05.02 короткостроковий кредит 10 000 (601) - 3305;
- 10.02 витрати майбутніх періодів 3 000 (39) - правила немає, 3190 «без статті»;
- 11.02 комісія банку 200 (92) - 3100;
- 05.03 оплата рахунку покупця 12 000 через платіж банку (Дт 333 Кт 361) - 3000;
- 06.03 платіж постачальнику 6 000 зі статтею 3260 на платежі;
- 31.03 курсова різниця на валютному рахунку 500 (Дт 312 Кт 714) - 3410.
3195 = 112 000 - 30 200 - 25 000 - 13 000 - 3 000 = 40 800; 3295 = -46 000; 3395 = 10 000;
3400 = 4 800; 3415 = 70 000 + 4 800 + 500 = 75 300 = сальдо 30, 31, 33 на 31.03.2026.

Запуск: тег ua_cashflow.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "ua_cashflow")
class TestUaCashflow(AccountTestInvoicingCommon):
    """Своя компанія з планом ua_psbo: у звіт не потрапляють чужі гроші."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Item = cls.env["ua.cashflow.item"]
        cls.misc = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        cls.bank = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)
        lines = cls.bank.inbound_payment_method_line_ids | cls.bank.outbound_payment_method_line_ids
        cls._acc("333").reconcile = True
        lines.write({"payment_account_id": cls._acc("333").id})
        cls.buyer = cls.env["res.partner"].create({"name": "ТОВ Покупець (тест Ф3)", "is_company": True})
        cls.vendor = cls.env["res.partner"].create({"name": "ТОВ Постачальник (тест Ф3)", "is_company": True})
        entries = [
            (date(2025, 2, 10), [("311", 20000), ("361", -20000)], None),
            (date(2025, 12, 15), [("311", 50000), ("401", -50000)], None),
            (date(2026, 1, 10), [("311", 100000), ("361", -100000)], None),
            (date(2026, 1, 12), [("631", 30000), ("311", -30000)], None),
            (date(2026, 1, 15), [("631", 40000), ("311", -40000)], "3260"),
            (date(2026, 1, 20), [("661", 25000), ("311", -25000)], None),
            (date(2026, 1, 20), [("6412", 8000), ("6411", 5000), ("311", -13000)], None),
            (date(2026, 2, 1), [("301", 2000), ("311", -2000)], None),
            (date(2026, 2, 5), [("311", 10000), ("601", -10000)], None),
            (date(2026, 2, 10), [("39", 3000), ("311", -3000)], None),
            (date(2026, 2, 11), [("92", 200), ("311", -200)], None),
            (date(2026, 3, 31), [("312", 500), ("714", -500)], None),
        ]
        cls.moves = [cls._entry(day, rows, item) for day, rows, item in entries]
        invoice = cls.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": cls.buyer.id, "invoice_date": date(2026, 3, 1),
            "invoice_line_ids": [(0, 0, {"name": "Виріб (тест)", "quantity": 1, "price_unit": 12000,
                                         "tax_ids": [(6, 0, [])]})]})
        invoice.action_post()
        cls.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids).create(
            {"payment_date": date(2026, 3, 5), "amount": 12000, "journal_id": cls.bank.id}).action_create_payments()
        cls.vendor_payment = cls.env["account.payment"].create({
            "payment_type": "outbound", "partner_type": "supplier", "partner_id": cls.vendor.id,
            "amount": 6000, "date": date(2026, 3, 6), "journal_id": cls.bank.id,
            "ua_cashflow_item_id": cls._item("3260").id})
        cls.vendor_payment.action_post()

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
    def _entry(cls, day, rows, item_code):
        move = cls.env["account.move"].create({
            "move_type": "entry", "date": day, "journal_id": cls.misc.id,
            "ua_cashflow_item_id": cls._item(item_code).id if item_code else False,
            "line_ids": [(0, 0, {"account_id": cls._acc(code).id, "name": "Тест Ф3",
                                 "debit": max(amount, 0), "credit": max(-amount, 0)}) for code, amount in rows]})
        move.action_post()
        return move

    def _statement(self, **values):
        data = {"date_from": date(2026, 1, 1), "date_to": date(2026, 3, 31), "company_id": self.company.id}
        data.update(values)
        statement = self.env["ua.cashflow.statement"].create(data)
        statement.action_compute()
        return statement

    def _row(self, statement, code):
        row = statement.line_ids.filtered(lambda l: l.code == code)
        self.assertEqual(len(row), 1, code)
        return row

    def test_01_form_rows(self):
        st = self._statement()
        expected = {
            "3000": 112000, "3100": -30200, "3105": -25000, "3115": -13000, "3116": 0, "3117": -8000,
            "3118": -5000, "3190": -3000, "3195": 40800, "3260": -46000, "3295": -46000,
            "3305": 10000, "3395": 10000, "3400": 4800, "3405": 70000, "3410": 500, "3415": 75300,
        }
        for code, amount in expected.items():
            self.assertAlmostEqual(self._row(st, code).amount, amount, places=2, msg=code)
        self.assertEqual(self._row(st, "3117").row_kind, "sub")
        self.assertAlmostEqual(st.closing, 75300, places=2)
        self.assertAlmostEqual(st.book_closing, 75300, places=2)
        self.assertAlmostEqual(st.opening, 70000, places=2)
        # Попередній рік: лише оплата покупця 10.02.2025.
        self.assertAlmostEqual(self._row(st, "3000").amount_prev, 20000, places=2)
        self.assertAlmostEqual(self._row(st, "3405").amount_prev, 0, places=2)
        self.assertAlmostEqual(self._row(st, "3415").amount_prev, 20000, places=2)

    def test_02_sources_and_internal_transfer(self):
        st = self._statement()
        current = st.entry_ids.filtered(lambda e: e.period == "current")
        by_move = {e.move_id: e for e in current}
        self.assertNotIn(self.moves[7], by_move, "переміщення з банку в касу не рух")
        self.assertEqual(by_move[self.moves[4]].source, "move")
        self.assertEqual(by_move[self.moves[3]].source, "rule")
        payment_entry = by_move[self.vendor_payment.move_id]
        self.assertEqual((payment_entry.source, payment_entry.item_id.code), ("payment", "3260"))
        self.assertEqual(st.unassigned_count, 1)
        self.assertAlmostEqual(st.unassigned_amount, 3000, places=2)
        self.assertEqual(by_move[self.moves[9]].source, "fallback")

    def test_03_choose_item_and_recompute(self):
        st = self._statement()
        fallback = st.entry_ids.filtered(lambda e: e.period == "current" and e.source == "fallback")
        fallback.action_set_item(self._item("3100"))
        st.action_compute()
        self.assertEqual(st.unassigned_count, 0)
        self.assertAlmostEqual(self._row(st, "3100").amount, -33200, places=2)
        self.assertAlmostEqual(self._row(st, "3190").amount, 0, places=2)
        self.assertAlmostEqual(self._row(st, "3195").amount, 40800, places=2)
        line_entry = st.entry_ids.filtered(lambda e: e.move_id == self.moves[9] and e.period == "current")
        self.assertEqual(line_entry.source, "line")

    def test_04_company_rule_beats_shared(self):
        self.env["ua.cashflow.rule"].create({
            "account_prefix": "39", "company_id": self.company.id,
            "item_out_id": self._item("3100").id, "note": "Передплата послуг (тест)"})
        self.env["ua.cashflow.rule"].create({
            "account_prefix": "631", "company_id": self.company.id, "item_out_id": self._item("3135").id})
        st = self._statement()
        self.assertEqual(st.unassigned_count, 0)
        self.assertAlmostEqual(self._row(st, "3100").amount, -3200, places=2)
        self.assertAlmostEqual(self._row(st, "3135").amount, -30000, places=2)
        self.assertAlmostEqual(self._row(st, "3195").amount, 40800, places=2)

    def test_05_done_locks_and_print(self):
        st = self._statement()
        st.action_done()
        self.assertEqual(st.state, "done")
        with self.assertRaises(UserError):
            st.action_compute()
        st.action_draft()
        self.assertEqual(st.ua_money(-13000), "(13 000.00)")
        self.assertEqual(st.ua_money(0), "-")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_cashflow.report_ua_cashflow", st.ids)[0].decode()
        self.assertIn("1801004", html)
        self.assertIn("Чистий рух коштів від операційної діяльності", html)
        self.assertIn("40 800.00", html)

    def test_06_drilldown(self):
        st = self._statement()
        action = self._row(st, "3115").action_open_entries()
        entries = self.env["ua.cashflow.statement.entry"].search(action["domain"])
        self.assertEqual(sorted(entries.mapped("item_id.code")), ["3117", "3118"])
        self.assertAlmostEqual(sum(entries.mapped("amount")), -13000, places=2)

    def test_07_flow_totals_for_other_reports(self):
        totals = self.env["ua.cashflow.statement"].ua_flow_totals(
            self.company, date(2026, 1, 1), date(2026, 1, 31))
        by_code = {self.env["ua.cashflow.item"].browse(k).code: v for k, v in totals.items()}
        self.assertEqual(by_code, {"3000": 100000.0, "3100": -30000.0, "3260": -40000.0, "3105": -25000.0,
                                   "3117": -8000.0, "3118": -5000.0})
