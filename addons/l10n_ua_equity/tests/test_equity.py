# -*- coding: utf-8 -*-
"""Звіт про власний капітал за 2026 рік з попереднім 2025 роком, нова компанія з планом ПСБО.

2025:
- 01.03 Дт 46 Кт 401 100 000 - учасники підписалися на статутний капітал (4240: гр. 3 +, гр. 8 -);
- 10.03 Дт 311 Кт 46 60 000 - внесли частину (4245);
- продаж Дт 361 Кт 702 50 000, зарплата Дт 92 Кт 661 30 000 - прибуток 20 000;
- 31.12 закриття: Дт 702 Кт 791 50 000, Дт 791 Кт 92 30 000, Дт 791 Кт 441 20 000 - у 4100 той
  самий прибуток 20 000, а не 40 000.
На кінець 2025: зареєстрований 100 000, неоплачений (40 000), нерозподілений 20 000, разом 80 000.

2026:
- 15.01 Дт 311 Кт 46 40 000 - решта внеску (4245);
- 01.03 Дт 443 Кт 671 5 000 - дивіденди (4200);
- 15.03 Дт 443 Кт 43 1 000 - до резервного капіталу (4210, графа 10 - нуль);
- 01.04 Дт 103 Кт 411 12 000 - дооцінка будівлі (4111, у 4110);
- 01.05 Дт 441 Кт 631 2 000 - виправлення помилки 2025 року, проводка позначена 4010;
- 01.06 Дт 451 Кт 311 3 000 - викуп частки (4260);
- 30.06 Дт 442 Кт 3771 500 - правила немає: 4290 і зауваження, потім рядок 4090;
- продаж Дт 361 Кт 703 40 000, зарплата Дт 92 Кт 661 25 000 - прибуток 15 000, не закрито.
4095: 100 000, -, -, -, 18 000, (40 000), -, 78 000.
4295: -, 12 000, -, 1 000, 8 500, 40 000, (3 000), 58 500.
4300: 100 000, 12 000, -, 1 000, 26 500, -, (3 000), 136 500 - як сальдо рахунків 40-46 і
незакритий прибуток.

Запуск: тег ua_equity.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

KEYS = ["registered", "revaluation", "additional", "reserve", "retained", "unpaid", "withdrawn", "total"]


@tagged("post_install", "-at_install", "ua_equity")
class TestUaEquity(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.misc = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        for day, rows in [
            (date(2025, 3, 1), [("46", 100000), ("401", -100000)]),
            (date(2025, 3, 10), [("311", 60000), ("46", -60000)]),
            (date(2025, 6, 1), [("361", 50000), ("702", -50000)]),
            (date(2025, 6, 30), [("92", 30000), ("661", -30000)]),
            (date(2025, 12, 31), [("702", 50000), ("791", -50000)]),
            (date(2025, 12, 31), [("791", 30000), ("92", -30000)]),
            (date(2025, 12, 31), [("791", 20000), ("441", -20000)]),
            (date(2026, 1, 15), [("311", 40000), ("46", -40000)]),
            (date(2026, 3, 1), [("443", 5000), ("671", -5000)]),
            (date(2026, 3, 15), [("443", 1000), ("43", -1000)]),
            (date(2026, 4, 1), [("103", 12000), ("411", -12000)]),
            (date(2026, 6, 1), [("451", 3000), ("311", -3000)]),
            (date(2026, 6, 30), [("442", 500), ("3771", -500)]),
            (date(2026, 7, 1), [("361", 40000), ("703", -40000)]),
            (date(2026, 7, 31), [("92", 25000), ("661", -25000)]),
        ]:
            cls._entry(day, rows)
        cls.correction = cls._entry(date(2026, 5, 1), [("441", 2000), ("631", -2000)], row="4010")
        cls.Statement = cls.env["ua.equity.statement"]

    @classmethod
    def _acc(cls, code):
        Account = cls.env["account.account"].with_company(cls.company)
        domain = [("company_ids", "in", cls.company.id)]
        return Account.search(domain + [("code", "=", code)], limit=1) or \
            Account.search(domain + [("code", "=like", code + "%")], order="code", limit=1)

    @classmethod
    def _entry(cls, day, rows, row=False):
        move = cls.env["account.move"].create({
            "move_type": "entry", "date": day, "journal_id": cls.misc.id, "ua_equity_row": row,
            "line_ids": [(0, 0, {"account_id": cls._acc(code).id, "name": "Тест форми № 4",
                                 "debit": max(amount, 0), "credit": max(-amount, 0)}) for code, amount in rows]})
        move.action_post()
        return move

    def _statement(self):
        statement = self.Statement.create({"date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31)})
        statement.action_compute()
        return statement

    def _row(self, statement, code, period="current"):
        lines = statement.line_ids if period == "current" else statement.line_prev_ids
        line = lines.filtered(lambda l: l.code == code)
        self.assertEqual(len(line), 1, code)
        return [line["amount_" + key] for key in KEYS]

    def test_01_current_year(self):
        st = self._statement()
        self.assertEqual(self._row(st, "4000"), [100000, 0, 0, 0, 20000, -40000, 0, 80000])
        self.assertEqual(self._row(st, "4010"), [0, 0, 0, 0, -2000, 0, 0, -2000])
        self.assertEqual(self._row(st, "4095"), [100000, 0, 0, 0, 18000, -40000, 0, 78000])
        self.assertEqual(self._row(st, "4100"), [0, 0, 0, 0, 15000, 0, 0, 15000])
        self.assertEqual(self._row(st, "4110"), [0, 12000, 0, 0, 0, 0, 0, 12000])
        self.assertEqual(self._row(st, "4111"), [0, 12000, 0, 0, 0, 0, 0, 12000])
        self.assertEqual(self._row(st, "4200"), [0, 0, 0, 0, -5000, 0, 0, -5000])
        self.assertEqual(self._row(st, "4210"), [0, 0, 0, 1000, -1000, 0, 0, 0])
        self.assertEqual(self._row(st, "4245"), [0, 0, 0, 0, 0, 40000, 0, 40000])
        self.assertEqual(self._row(st, "4260"), [0, 0, 0, 0, 0, 0, -3000, -3000])
        self.assertEqual(self._row(st, "4290"), [0, 0, 0, 0, -500, 0, 0, -500])
        self.assertEqual(self._row(st, "4295"), [0, 12000, 0, 1000, 8500, 40000, -3000, 58500])
        self.assertEqual(self._row(st, "4300"), [100000, 12000, 0, 1000, 26500, 0, -3000, 136500])
        self.assertEqual((st.opening, st.profit, st.closing, st.book_closing), (80000, 15000, 136500, 136500))
        self.assertEqual(st.fallback_count, 1)
        self.assertFalse(st.check_text)
        sources = {(e.row, e.source) for e in st.entry_ids if e.period == "current"}
        self.assertIn(("4010", "move"), sources)
        self.assertIn(("4100", "result"), sources)

    def test_02_previous_year_and_closing(self):
        st = self._statement()
        self.assertEqual(self._row(st, "4000", "previous"), [0] * 8)
        self.assertEqual(self._row(st, "4100", "previous"), [0, 0, 0, 0, 20000, 0, 0, 20000],
                         "закриття 79 на 441 не двоїть прибуток")
        self.assertEqual(self._row(st, "4240", "previous"), [100000, 0, 0, 0, 0, -100000, 0, 0])
        self.assertEqual(self._row(st, "4245", "previous"), [0, 0, 0, 0, 0, 60000, 0, 60000])
        self.assertEqual(self._row(st, "4300", "previous"), self._row(st, "4000"))

    def test_03_fallback_set_row_and_company_rule(self):
        st = self._statement()
        fallback = st.entry_ids.filtered(lambda e: e.source == "fallback")
        self.assertEqual(fallback.account_id.code, "442")
        line = fallback.move_line_id
        fallback.action_set_row("4090")
        with self.assertRaises(UserError):
            st.entry_ids.filtered(lambda e: e.source == "result")[:1].action_set_row("4090")
        st.action_compute()
        self.assertEqual(st.fallback_count, 0)
        self.assertEqual(self._row(st, "4090"), [0, 0, 0, 0, -500, 0, 0, -500])
        self.assertEqual(self._row(st, "4095"), [100000, 0, 0, 0, 17500, -40000, 0, 77500])
        self.assertEqual(self._row(st, "4300")[-1], 136500)

        line.sudo().ua_equity_row = False
        self.env["ua.equity.rule"].sudo().create({"company_id": self.company.id, "account_prefix": "44",
                                           "counter_prefix": "377", "row": "4225"})
        st.action_compute()
        self.assertEqual(self._row(st, "4225"), [0, 0, 0, 0, -500, 0, 0, -500])
        self.assertEqual(st.entry_ids.filtered(lambda e: e.row == "4225").source, "rule")

    def test_04_checks_done_and_print(self):
        st = self._statement()
        st.action_done()
        self.assertEqual(st.state, "done")
        with self.assertRaises(UserError):
            st.action_compute()
        st.action_draft()

        self._entry(date(2026, 9, 1), [("311", 1000), ("401", -1000)], row="4205")
        st.action_compute()
        self.assertIn("4205", st.check_text)

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_equity.report_ua_equity", st.ids)[0].decode()
        self.assertIn("Звіт про власний капітал", html)
        self.assertIn("137 500.00", html)
        self.assertIn("(3 000.00)", html)
        self.assertIn("За попередній рік", html)
