"""Інвентаризація каси: залишок за обліком, перерахунок за номіналами, проводка різниці.

Числа пораховані вручну, арифметика в коментарях. Окремий журнал каси дає свій новий рахунок
групи 30 (код Odoo бере наступний вільний, наприклад 303), тож на залишок не впливають проводки
інших тестів.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

TOLERANCE = 0.005


@tagged("post_install", "-at_install", "ua_cash_count")
class TestUaCashCount(TransactionCase):
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

        cls.journal = cls.env["account.journal"].create({
            "name": "Каса інвентаризації", "type": "cash", "code": "CCNT", "company_id": cls.company.id})
        cls.cash = cls.journal.default_account_id
        assert cls.cash.account_type == "asset_cash" and cls.cash.code.startswith("30"), cls.cash.code
        cls.misc = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        cls.acc_311 = cls._account("311")
        cls.acc_372 = cls._account("372")
        cls.acc_375 = cls._account("375")
        cls.acc_947 = cls._account("947")
        cls.acc_719 = cls._account("719")
        cls.cashier = cls.env["res.partner"].create({"name": "Касир Коваленко"})
        # Залишок каси: +10000 (1 листопада) - 1500 (2 листопада) = 8500 на 3 листопада.
        cls._entry(date(2026, 11, 1), cls.cash, cls.acc_311, 10000.0)
        cls._entry(date(2026, 11, 2), cls.acc_372, cls.cash, 1500.0)
        # Після дати акта - не входить у залишок на 3 листопада.
        cls._entry(date(2026, 11, 5), cls.cash, cls.acc_311, 700.0)

    @classmethod
    def _account(cls, prefix):
        account = cls.env["account.account"].search(
            [("code", "=like", prefix + "%"), ("company_ids", "in", cls.company.id)], order="code", limit=1)
        assert account, "у плані немає рахунку %s" % prefix
        return account

    @classmethod
    def _entry(cls, on_date, debit, credit, amount):
        move = cls.env["account.move"].create({
            "move_type": "entry", "date": on_date, "journal_id": cls.misc.id,
            "line_ids": [(0, 0, {"account_id": debit.id, "name": "тест", "debit": amount}),
                         (0, 0, {"account_id": credit.id, "name": "тест", "credit": amount})]})
        move.action_post()
        return move

    def _count(self, **vals):
        return self.env["ua.cash.count"].create(dict({
            "journal_id": self.journal.id, "date": date(2026, 11, 3), "cashier_id": self.cashier.id,
            "commission": "Голова: Директор Іваненко\nБухгалтер Петренко",
            "last_receipt": "ПКО № 12 від 01.11.2026", "last_payment": "ВКО № 7 від 02.11.2026",
        }, **vals))

    def _move_lines(self, move, account):
        return move.line_ids.filtered(lambda l: l.account_id == account)

    def _book(self, on_date):
        lines = self.env["account.move.line"].search([
            ("account_id", "=", self.cash.id), ("parent_state", "=", "posted"), ("date", "<=", on_date)])
        return sum(lines.mapped("balance"))

    def test_01_book_balance_on_date(self):
        doc = self._count()
        self.assertAlmostEqual(doc.book_balance, 8500.0, delta=TOLERANCE)
        doc.date = date(2026, 11, 6)
        doc.action_refresh()
        self.assertAlmostEqual(doc.book_balance, 9200.0, delta=TOLERANCE)  # 8500 + 700

    def test_02_nominals_and_shortage_to_cashier(self):
        doc = self._count()
        doc.action_nominals()
        self.assertEqual(len(doc.line_ids), 12)
        doc.action_nominals()
        self.assertEqual(len(doc.line_ids), 12, "повторне натискання не дублює номінали")
        counts = {500: 10, 200: 10, 100: 12, 50: 4}
        for line in doc.line_ids:
            line.quantity = counts.get(line.nominal, 0)
        # 5000 + 2000 + 1200 + 200 = 8400; нестача 8400 - 8500 = -100.
        self.assertAlmostEqual(doc.counted, 8400.0, delta=TOLERANCE)
        self.assertAlmostEqual(doc.difference, -100.0, delta=TOLERANCE)
        doc.action_done()
        self.assertEqual(doc.state, "done")
        debit = self._move_lines(doc.move_id, self.acc_375)
        self.assertAlmostEqual(debit.debit, 100.0, delta=TOLERANCE)
        self.assertEqual(debit.partner_id, self.cashier)
        self.assertAlmostEqual(self._move_lines(doc.move_id, self.cash).credit, 100.0, delta=TOLERANCE)
        self.assertEqual(doc.move_id.state, "posted")
        self.assertAlmostEqual(self._book(date(2026, 11, 3)), 8400.0, delta=TOLERANCE)
        with self.assertRaises(UserError):
            doc.action_done()
        with self.assertRaises(UserError):
            doc.unlink()

    def test_03_coins(self):
        doc = self._count(line_ids=[(0, 0, {"nominal": 0.5, "quantity": 7}),
                                    (0, 0, {"nominal": 0.1, "quantity": 3})])
        self.assertAlmostEqual(doc.counted, 3.8, delta=TOLERANCE)  # 3.5 + 0.3
        self.assertEqual(doc.ua_nominal(doc.line_ids[0]), "50 коп.")

    def test_04_shortage_to_expense_and_culprit(self):
        doc = self._count(counted_manual=8450.0, shortage_to="expense")
        doc.action_done()
        self.assertAlmostEqual(self._move_lines(doc.move_id, self.acc_947).debit, 50.0, delta=TOLERANCE)

        culprit = self.env["res.partner"].create({"name": "Винна особа"})
        doc = self._count(counted_manual=8420.0, culprit_id=culprit.id)
        doc.action_done()  # після першого акта за обліком 8450, нестача 30
        line = self._move_lines(doc.move_id, self.acc_375)
        self.assertAlmostEqual(line.debit, 30.0, delta=TOLERANCE)
        self.assertEqual(line.partner_id, culprit)

    def test_05_surplus(self):
        doc = self._count(counted_manual=8620.0)
        self.assertAlmostEqual(doc.difference, 120.0, delta=TOLERANCE)
        doc.action_done()
        self.assertAlmostEqual(self._move_lines(doc.move_id, self.cash).debit, 120.0, delta=TOLERANCE)
        self.assertAlmostEqual(self._move_lines(doc.move_id, self.acc_719).credit, 120.0, delta=TOLERANCE)

    def test_06_no_difference_no_move(self):
        doc = self._count(counted_manual=8500.0)
        doc.action_done()
        self.assertEqual(doc.state, "done")
        self.assertFalse(doc.move_id)

    def test_07_shortage_needs_person(self):
        doc = self._count(counted_manual=8000.0, cashier_id=False)
        with self.assertRaises(UserError):
            doc.action_done()
        self.assertEqual(doc.state, "draft")

    def test_08_print(self):
        doc = self._count(line_ids=[(0, 0, {"nominal": 1000, "quantity": 8}),
                                    (0, 0, {"nominal": 200, "quantity": 2})])
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_cash_count.report_ua_cash_count", doc.ids)[0]
        self.assertIn("Акт інвентаризації наявних коштів".encode(), html)
        self.assertIn("Нестача".encode(), html)  # 8400 - 8500
        self.assertIn("1000 грн".encode(), html)
        self.assertIn("Касир Коваленко".encode(), html)
