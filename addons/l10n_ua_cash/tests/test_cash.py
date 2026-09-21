"""Каса: перевірки проводок, нумерації, касової книги і підзвіту.

Усі очікувані числа порахровані вручну, арифметика записана в коментарі поруч.
База будується з нуля в транзакції тесту: країна Україна, план рахунків ua_psbo,
партнер, журнал каси з плану.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Копійка: усі очікувані суми заокруглені до двох знаків.
TOLERANCE = 0.005


@tagged("post_install", "-at_install", "ua_cash")
class TestUaCash(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading(
                "ua_psbo", cls.company, install_demo=False
            )
        cls.company.invalidate_recordset()

        # План ua_psbo створює журнали продажу, придбання і банку, але не касу:
        # касовий журнал заводить сама компанія. Рахунок каси Odoo створює за
        # префіксом плану (301), тому він гарантовано з класу 301.
        cls.cash_journal = cls.env["account.journal"].search(
            [("type", "=", "cash"), ("company_id", "=", cls.company.id)], limit=1
        ) or cls.env["account.journal"].create({
            "name": "Каса",
            "type": "cash",
            "code": "CASH",
            "company_id": cls.company.id,
        })
        cls.cash_account = cls.cash_journal.default_account_id
        assert cls.cash_account.code.startswith("301"), (
            "рахунок журналу каси не з класу 301: %s" % cls.cash_account.code
        )

        cls.acc_361 = cls._account("361")      # розрахунки з покупцями
        cls.acc_372 = cls._account("372")      # підзвіт (у плані ПСБО це 3721)
        cls.acc_92 = cls._account("92")        # адміністративні витрати
        cls.acc_93 = cls._account("93")        # витрати на збут
        cls.partner = cls.env["res.partner"].create({"name": "Підзвітний Петренко"})
        cls.buyer = cls.env["res.partner"].create({"name": "ТОВ Покупець"})

    # ------------------------------------------------------------------
    # Допоміжне
    # ------------------------------------------------------------------
    @classmethod
    def _account(cls, prefix):
        account = cls.env["account.account"].search(
            [("code", "=like", prefix + "%"), ("company_ids", "in", cls.company.id)],
            limit=1,
            order="code",
        )
        assert account, "у плані немає рахунку %s" % prefix
        return account

    def _order(self, kind, amount, account, on_date, partner=None, post=True, person=None):
        """Створити касовий ордер: kind='in' - ПКО, kind='out' - ВКО."""
        payment = self.env["account.payment"].create({
            "payment_type": "inbound" if kind == "in" else "outbound",
            "partner_type": "customer" if kind == "in" else "supplier",
            "partner_id": (partner or self.partner).id,
            "journal_id": self.cash_journal.id,
            "company_id": self.company.id,
            "date": on_date,
            "amount": amount,
            "destination_account_id": account.id,
            "memo": "Тест %s %s" % (kind, amount),
            "ua_person": person or (partner or self.partner).name,
        })
        if post:
            payment.action_post()
        return payment

    def _side(self, payment, account):
        """Дебет і кредит проводки платежу по конкретному рахунку."""
        lines = payment.move_id.line_ids.filtered(lambda line: line.account_id == account)
        return sum(lines.mapped("debit")), sum(lines.mapped("credit"))

    def _gl_balance(self, account):
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
        ])
        return round(sum(lines.mapped("debit")) - sum(lines.mapped("credit")), 2)

    def _cash_book(self, date_from, date_to, limit=None):
        book = self.env["ua.cash.book"].create({
            "company_id": self.company.id,
            "journal_id": self.cash_journal.id,
            "date_from": date_from,
            "date_to": date_to,
            "limit_amount": self.company.ua_cash_limit if limit is None else limit,
        })
        book.action_compute()
        return book

    # ------------------------------------------------------------------
    # 1-2. Проводки ордерів
    # ------------------------------------------------------------------
    def test_01_pko_debits_cash_account(self):
        """ПКО на 5 000,00 від покупця: Дт 301 5000,00 / Кт 361 5000,00."""
        order = self._order("in", 5000.0, self.acc_361, date(2026, 7, 1), partner=self.buyer)
        self.assertEqual(order.ua_order_kind, "in")
        self.assertTrue(order.move_id, "ПКО не створив проводки")
        self.assertEqual(order.move_id.state, "posted")
        debit, credit = self._side(order, self.cash_account)
        self.assertAlmostEqual(debit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(credit, 0.0, delta=TOLERANCE)
        debit, credit = self._side(order, self.acc_361)
        self.assertAlmostEqual(debit, 0.0, delta=TOLERANCE)
        self.assertAlmostEqual(credit, 5000.0, delta=TOLERANCE)

    def test_02_vko_credits_cash_account(self):
        """ВКО на 1 200,00 під звіт: Дт 372 1200,00 / Кт 301 1200,00."""
        order = self._order("out", 1200.0, self.acc_372, date(2026, 7, 2))
        self.assertEqual(order.ua_order_kind, "out")
        debit, credit = self._side(order, self.cash_account)
        self.assertAlmostEqual(debit, 0.0, delta=TOLERANCE)
        self.assertAlmostEqual(credit, 1200.0, delta=TOLERANCE)
        debit, credit = self._side(order, self.acc_372)
        self.assertAlmostEqual(debit, 1200.0, delta=TOLERANCE)
        self.assertAlmostEqual(credit, 0.0, delta=TOLERANCE)

    # ------------------------------------------------------------------
    # 3-4. Нумерація
    # ------------------------------------------------------------------
    def test_03_numbering_per_register(self):
        """Реєстри ПКО і ВКО нумеруються незалежно: 0001, 0002 у кожному."""
        first_in = self._order("in", 100.0, self.acc_361, date(2026, 7, 1), partner=self.buyer)
        second_in = self._order("in", 200.0, self.acc_361, date(2026, 7, 2), partner=self.buyer)
        first_out = self._order("out", 300.0, self.acc_372, date(2026, 7, 3))
        self.assertEqual(first_in.ua_order_number, "ПКО-2026-0001")
        self.assertEqual(second_in.ua_order_number, "ПКО-2026-0002")
        self.assertEqual(first_out.ua_order_number, "ВКО-2026-0001")

    def test_04_numbering_restarts_each_year(self):
        """Новий рік - нумерація з 0001; номер проводки при цьому свій."""
        self._order("in", 100.0, self.acc_361, date(2026, 12, 31), partner=self.buyer)
        next_year = self._order("in", 150.0, self.acc_361, date(2027, 1, 5), partner=self.buyer)
        self.assertEqual(next_year.ua_order_number, "ПКО-2027-0001")
        self.assertNotEqual(next_year.ua_order_number, next_year.name)

    # ------------------------------------------------------------------
    # 5. Кореспондуючий рахунок
    # ------------------------------------------------------------------
    def test_05_counterpart_account_is_kept(self):
        """Вибір бухгалтера (372) не затирається дебіторкою партнера при зміні особи."""
        order = self._order("out", 500.0, self.acc_372, date(2026, 7, 4), post=False)
        self.assertEqual(order.destination_account_id, self.acc_372)
        order.partner_id = self.buyer
        self.assertEqual(
            order.destination_account_id, self.acc_372,
            "нативний розрахунок підставив рахунок партнера замість обраного 372",
        )
        order.action_post()
        debit, _credit = self._side(order, self.acc_372)
        self.assertAlmostEqual(debit, 500.0, delta=TOLERANCE)

    # ------------------------------------------------------------------
    # 6-7. Касова книга
    # ------------------------------------------------------------------
    def _three_days(self):
        """01.07 ПКО 5000; 02.07 ВКО 1200; 03.07 ПКО 700 і ВКО 2500."""
        self._order("in", 5000.0, self.acc_361, date(2026, 7, 1), partner=self.buyer)
        self._order("out", 1200.0, self.acc_372, date(2026, 7, 2))
        self._order("in", 700.0, self.acc_361, date(2026, 7, 3), partner=self.buyer)
        self._order("out", 2500.0, self.acc_372, date(2026, 7, 3))

    def test_06_cash_book_three_days(self):
        """Залишки: 0+5000=5000; 5000-1200=3800; 3800+700-2500=2000."""
        self._three_days()
        book = self._cash_book(date(2026, 7, 1), date(2026, 7, 3), limit=0.0)
        self.assertEqual(len(book.line_ids), 3)
        day1, day2, day3 = book.line_ids
        self.assertAlmostEqual(day1.opening_balance, 0.0, delta=TOLERANCE)
        self.assertAlmostEqual(day1.total_in, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(day1.closing_balance, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(day2.opening_balance, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(day2.total_out, 1200.0, delta=TOLERANCE)
        self.assertAlmostEqual(day2.closing_balance, 3800.0, delta=TOLERANCE)
        self.assertAlmostEqual(day3.opening_balance, 3800.0, delta=TOLERANCE)
        self.assertAlmostEqual(day3.total_in, 700.0, delta=TOLERANCE)
        self.assertAlmostEqual(day3.total_out, 2500.0, delta=TOLERANCE)
        self.assertAlmostEqual(day3.closing_balance, 2000.0, delta=TOLERANCE)
        # Підсумки книги: надійшло 5000+700=5700, видано 1200+2500=3700.
        self.assertAlmostEqual(book.total_in, 5700.0, delta=TOLERANCE)
        self.assertAlmostEqual(book.total_out, 3700.0, delta=TOLERANCE)
        self.assertAlmostEqual(book.closing_balance, 2000.0, delta=TOLERANCE)
        # У третьому дні два ордери, у перших двох по одному.
        self.assertEqual([len(line.entry_ids) for line in book.line_ids], [1, 1, 2])

    def test_07_cash_book_flags_limit_breach(self):
        """Ліміт 2 000: 5000 і 3800 - перевищення, 2000 - ні (рівно ліміт)."""
        self._three_days()
        self.company.ua_cash_limit = 2000.0
        book = self._cash_book(date(2026, 7, 1), date(2026, 7, 3))
        self.assertEqual([line.over_limit for line in book.line_ids], [True, True, False])
        self.assertTrue(book.over_limit)
        self.assertEqual(book.over_limit_days, 2)
        # Без ліміту (нуль) попереджень немає.
        free = self._cash_book(date(2026, 7, 1), date(2026, 7, 3), limit=0.0)
        self.assertFalse(free.over_limit)

    def test_08_cash_book_matches_gl(self):
        """Залишок на кінець = сальдо рахунку каси; початок періоду - з попередніх днів."""
        self._three_days()
        book = self._cash_book(date(2026, 7, 1), date(2026, 7, 3), limit=0.0)
        self.assertAlmostEqual(
            book.closing_balance, self._gl_balance(self.cash_account), delta=TOLERANCE
        )
        # Книга з другого дня: залишок на початок = 5000 з першого дня.
        later = self._cash_book(date(2026, 7, 2), date(2026, 7, 3), limit=0.0)
        self.assertAlmostEqual(later.opening_balance, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(later.closing_balance, 2000.0, delta=TOLERANCE)

    # ------------------------------------------------------------------
    # 9-11. Авансовий звіт
    # ------------------------------------------------------------------
    def _advance(self, given, expenses, on_date=date(2026, 7, 10)):
        payment = self._order("out", given, self.acc_372, on_date)
        report = self.env["ua.advance.report"].create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date": on_date,
            "payment_id": payment.id,
            "line_ids": [
                (0, 0, {"name": name, "amount": amount, "expense_account_id": account.id})
                for name, amount, account in expenses
            ],
        })
        return payment, report

    def test_09_advance_report_returns_balance(self):
        """Видано 3000, витрачено 1800+650=2450, залишок 550 -> ПКО; 372 = 0."""
        _payment, report = self._advance(
            3000.0, [("Канцтовари", 1800.0, self.acc_92), ("Доставка", 650.0, self.acc_93)]
        )
        self.assertAlmostEqual(report.amount_total, 2450.0, delta=TOLERANCE)
        self.assertAlmostEqual(report.amount_given, 3000.0, delta=TOLERANCE)
        self.assertAlmostEqual(report.amount_balance, 550.0, delta=TOLERANCE)
        report.action_confirm()
        self.assertEqual(report.state, "done")
        # Проводка звіту: Дт 92 1800 + Дт 93 650 / Кт 372 2450.
        lines = report.move_id.line_ids
        self.assertAlmostEqual(
            sum(lines.filtered(lambda l: l.account_id == self.acc_92).mapped("debit")),
            1800.0, delta=TOLERANCE,
        )
        self.assertAlmostEqual(
            sum(lines.filtered(lambda l: l.account_id == self.acc_93).mapped("debit")),
            650.0, delta=TOLERANCE,
        )
        self.assertAlmostEqual(
            sum(lines.filtered(lambda l: l.account_id == self.acc_372).mapped("credit")),
            2450.0, delta=TOLERANCE,
        )
        settle = report.action_settle_balance()
        self.assertEqual(settle.ua_order_kind, "in", "залишок повертають у касу (ПКО)")
        self.assertAlmostEqual(settle.amount, 550.0, delta=TOLERANCE)
        # 372 по цьому підзвіту: 3000 - 2450 - 550 = 0.
        self.assertAlmostEqual(self._gl_balance(self.acc_372), 0.0, delta=TOLERANCE)

    def test_10_advance_report_overspend(self):
        """Видано 3000, витрачено 1800+1400=3200, перевитрата 200 -> ВКО; 372 = 0."""
        _payment, report = self._advance(
            3000.0, [("Готель", 1800.0, self.acc_92), ("Квитки", 1400.0, self.acc_92)]
        )
        self.assertAlmostEqual(report.amount_balance, -200.0, delta=TOLERANCE)
        report.action_confirm()
        settle = report.action_settle_balance()
        self.assertEqual(settle.ua_order_kind, "out", "перевитрату доплачують з каси (ВКО)")
        self.assertAlmostEqual(settle.amount, 200.0, delta=TOLERANCE)
        # 372: 3000 - 3200 + 200 = 0.
        self.assertAlmostEqual(self._gl_balance(self.acc_372), 0.0, delta=TOLERANCE)

    def test_11_advance_report_guards(self):
        """Порожній звіт не проводиться; залишок закривається лише раз."""
        payment = self._order("out", 1000.0, self.acc_372, date(2026, 7, 12))
        empty = self.env["ua.advance.report"].create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date": date(2026, 7, 12),
            "payment_id": payment.id,
        })
        with self.assertRaises(UserError):
            empty.action_confirm()
        with self.assertRaises(UserError):
            empty.action_settle_balance()

        _given, report = self._advance(
            1000.0, [("Папір", 400.0, self.acc_92)], on_date=date(2026, 7, 13)
        )
        report.action_confirm()
        first = report.action_settle_balance()
        second = report.action_settle_balance()
        self.assertEqual(first, second, "повторне закриття створило другий ордер")
        self.assertAlmostEqual(first.amount, 600.0, delta=TOLERANCE)  # 1000 - 400

    def test_12_report_renders(self):
        """Друковані форми КО-1, КО-2, КО-4 і авансового звіту будуються."""
        pko = self._order("in", 1234.56, self.acc_361, date(2026, 7, 1), partner=self.buyer)
        vko = self._order("out", 765.44, self.acc_372, date(2026, 7, 1))
        vko.ua_document = "паспорт АА 123456, виданий 01.01.2015"
        for payment in (pko, vko):
            html = self.env["ir.actions.report"]._render_qweb_html(
                "l10n_ua_cash.report_ua_cash_order", payment.ids
            )[0]
            self.assertIn(payment.ua_order_number.encode(), html)
        book = self._cash_book(date(2026, 7, 1), date(2026, 7, 1), limit=0.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_cash.report_ua_cash_book", book.ids
        )[0]
        self.assertIn("КО-4".encode(), html)

        _payment, report = self._advance(
            500.0, [("Вода", 120.0, self.acc_92)], on_date=date(2026, 7, 14)
        )
        report.action_confirm()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_cash.report_ua_advance_report", report.ids
        )[0]
        self.assertIn(report.name.encode(), html)
