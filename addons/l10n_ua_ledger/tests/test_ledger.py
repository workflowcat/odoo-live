"""Регістри головної книги на шести проводках, порахованих вручну.

Набір (компанія з планом ua_psbo, журнал інших операцій):

  червень 2026 - формує сальдо на початок липня
    1) 10.06  Дт 311 20 000 / Кт 401 20 000   внесок до статутного капіталу
    2) 20.06  Дт 201  5 000 / Кт 631  5 000   надійшли матеріали

  липень 2026 - обороти періоду
    3) 05.07  Дт 361 12 000 / Кт 701 12 000   реалізація
    4) 10.07  Дт 311  9 000 / Кт 361  9 000   оплата від покупця
    5) 15.07  Дт 631  5 000 / Кт 311  5 000   оплата постачальникові
    6) 20.07  Дт  92  3 000 / Кт 661 1 800 і Кт 651 1 200   адмінвитрати

Сальдо на початок липня: Дт 311 20 000 + Дт 201 5 000 = 25 000;
                         Кт 401 20 000 + Кт 631 5 000 = 25 000.
Обороти липня: Дт 12 000 + 9 000 + 5 000 + 3 000 = 29 000;
               Кт  9 000 + 12 000 + 5 000 + 1 800 + 1 200 = 29 000.
Сальдо на кінець липня:
  311  20 000 + 9 000 - 5 000 = 24 000 Дт
  201                           5 000 Дт
  361  12 000 - 9 000         =  3 000 Дт
  92                            3 000 Дт     разом Дт 35 000
  401                          20 000 Кт
  701                          12 000 Кт
  661                           1 800 Кт
  651                           1 200 Кт     разом Кт 35 000
  631  -5 000 + 5 000         =      0
"""
import io
from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

TOLERANCE = 0.005
JULY_FROM = date(2026, 7, 1)
JULY_TO = date(2026, 7, 31)


@tagged("post_install", "-at_install", "ua_ledger")
class TestUaLedger(TransactionCase):
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

        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1
        )
        assert cls.journal, "у компанії немає журналу інших операцій"

        cls.acc_311 = cls._account("311")
        cls.acc_401 = cls._account("401")
        cls.acc_201 = cls._account("201")
        cls.acc_631 = cls._account("631")
        cls.acc_361 = cls._account("361")
        cls.acc_701 = cls._account("701")
        cls.acc_92 = cls._account("92")
        cls.acc_661 = cls._account("661")
        cls.acc_651 = cls._account("651")
        cls.buyer = cls.env["res.partner"].create({"name": "ТОВ Покупець"})
        cls.supplier = cls.env["res.partner"].create({"name": "ТОВ Постачальник"})
        cls._build_entries()

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

    @classmethod
    def _move(cls, on_date, ref, lines):
        """lines: [(рахунок, дебет, кредит, партнер)]"""
        move = cls.env["account.move"].create({
            "journal_id": cls.journal.id,
            "company_id": cls.company.id,
            "date": on_date,
            "ref": ref,
            "line_ids": [
                (0, 0, {
                    "account_id": account.id,
                    "name": ref,
                    "debit": debit,
                    "credit": credit,
                    "partner_id": partner.id if partner else False,
                })
                for account, debit, credit, partner in lines
            ],
        })
        move.action_post()
        return move

    @classmethod
    def _build_entries(cls):
        cls._move(date(2026, 6, 10), "Внесок до статутного капіталу", [
            (cls.acc_311, 20000.0, 0.0, None),
            (cls.acc_401, 0.0, 20000.0, None),
        ])
        cls._move(date(2026, 6, 20), "Матеріали від постачальника", [
            (cls.acc_201, 5000.0, 0.0, None),
            (cls.acc_631, 0.0, 5000.0, cls.supplier),
        ])
        cls._move(date(2026, 7, 5), "Реалізація продукції", [
            (cls.acc_361, 12000.0, 0.0, cls.buyer),
            (cls.acc_701, 0.0, 12000.0, None),
        ])
        cls._move(date(2026, 7, 10), "Оплата від покупця", [
            (cls.acc_311, 9000.0, 0.0, None),
            (cls.acc_361, 0.0, 9000.0, cls.buyer),
        ])
        cls._move(date(2026, 7, 15), "Оплата постачальникові", [
            (cls.acc_631, 5000.0, 0.0, cls.supplier),
            (cls.acc_311, 0.0, 5000.0, None),
        ])
        cls._move(date(2026, 7, 20), "Адміністративні витрати", [
            (cls.acc_92, 3000.0, 0.0, None),
            (cls.acc_661, 0.0, 1800.0, None),
            (cls.acc_651, 0.0, 1200.0, None),
        ])

    def _osv(self, detail="account", skip_zero=True):
        osv = self.env["ua.osv.report"].create({
            "company_id": self.company.id,
            "date_from": JULY_FROM,
            "date_to": JULY_TO,
            "detail": detail,
            "skip_zero": skip_zero,
        })
        osv.action_compute()
        return osv

    def _osv_row(self, osv, account):
        rows = osv.line_ids.filtered(lambda line: line.account_id == account)
        self.assertEqual(len(rows), 1, "у відомості немає рядка рахунку %s" % account.code)
        return rows

    def _card(self, account, partner=None, date_from=JULY_FROM, date_to=JULY_TO):
        card = self.env["ua.account.card"].create({
            "company_id": self.company.id,
            "account_id": account.id,
            "partner_id": partner.id if partner else False,
            "date_from": date_from,
            "date_to": date_to,
        })
        card.action_compute()
        return card

    def _analysis(self, account):
        analysis = self.env["ua.account.analysis"].create({
            "company_id": self.company.id,
            "account_id": account.id,
            "date_from": JULY_FROM,
            "date_to": JULY_TO,
        })
        analysis.action_compute()
        return analysis

    # ------------------------------------------------------------------
    # ОСВ
    # ------------------------------------------------------------------
    def test_01_osv_double_entry_control(self):
        """Оборот Дт = оборот Кт = 29 000,00."""
        osv = self._osv()
        self.assertTrue(osv.control_ok)
        self.assertAlmostEqual(osv.total_debit, 29000.0, delta=TOLERANCE)
        self.assertAlmostEqual(osv.total_credit, 29000.0, delta=TOLERANCE)

    def test_02_osv_opening_plus_turnover_equals_closing(self):
        """Для кожного рядка: сальдо поч. + оборот Дт - оборот Кт = сальдо кін."""
        osv = self._osv()
        self.assertTrue(osv.line_ids)
        for line in osv.line_ids:
            opening = line.open_debit - line.open_credit
            closing = line.close_debit - line.close_credit
            self.assertAlmostEqual(
                opening + line.debit - line.credit, closing, delta=TOLERANCE,
                msg="рахунок %s: %s + %s - %s != %s"
                    % (line.code, opening, line.debit, line.credit, closing),
            )
            # Розгорнуте сальдо: одночасно Дт і Кт по рядку бути не може.
            self.assertFalse(line.open_debit and line.open_credit)
            self.assertFalse(line.close_debit and line.close_credit)

    def test_03_osv_totals_by_hand(self):
        """Сальдо поч. 25 000 = 25 000; сальдо кін. 35 000 = 35 000."""
        osv = self._osv()
        self.assertAlmostEqual(osv.total_open_debit, 25000.0, delta=TOLERANCE)
        self.assertAlmostEqual(osv.total_open_credit, 25000.0, delta=TOLERANCE)
        self.assertAlmostEqual(osv.total_close_debit, 35000.0, delta=TOLERANCE)
        self.assertAlmostEqual(osv.total_close_credit, 35000.0, delta=TOLERANCE)

    def test_04_osv_rows_by_hand(self):
        """311: 20 000 + 9 000 - 5 000 = 24 000; 631 закривається в нуль."""
        osv = self._osv()
        row = self._osv_row(osv, self.acc_311)
        self.assertAlmostEqual(row.open_debit, 20000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.debit, 9000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.credit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.close_debit, 24000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.close_credit, 0.0, delta=TOLERANCE)

        row = self._osv_row(osv, self.acc_631)
        self.assertAlmostEqual(row.open_credit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.debit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.close_debit, 0.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.close_credit, 0.0, delta=TOLERANCE)

        row = self._osv_row(osv, self.acc_92)
        self.assertAlmostEqual(row.open_debit + row.open_credit, 0.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.debit, 3000.0, delta=TOLERANCE)
        self.assertAlmostEqual(row.close_debit, 3000.0, delta=TOLERANCE)

    def test_05_osv_grouping_by_class_keeps_totals(self):
        """Групування за класами не міняє підсумків; клас 3 має свій рядок."""
        by_class = self._osv(detail="c1")
        self.assertAlmostEqual(by_class.total_debit, 29000.0, delta=TOLERANCE)
        self.assertAlmostEqual(by_class.total_credit, 29000.0, delta=TOLERANCE)
        self.assertAlmostEqual(by_class.total_close_debit, 35000.0, delta=TOLERANCE)
        codes = by_class.line_ids.mapped("code")
        self.assertEqual(codes, sorted(codes))
        self.assertIn("3", codes)
        # Клас 3: 311 (24 000) + 361 (3 000) = 27 000 Дт, кредитового сальдо немає.
        class_three = by_class.line_ids.filtered(lambda line: line.code == "3")
        self.assertAlmostEqual(class_three.close_debit, 27000.0, delta=TOLERANCE)
        self.assertAlmostEqual(class_three.close_credit, 0.0, delta=TOLERANCE)

    def test_06_osv_skips_untouched_accounts(self):
        """Порожні рахунки плану у відомість не потрапляють."""
        osv = self._osv(skip_zero=True)
        touched = {
            self.acc_311, self.acc_401, self.acc_201, self.acc_631,
            self.acc_361, self.acc_701, self.acc_92, self.acc_661, self.acc_651,
        }
        self.assertEqual(set(osv.line_ids.mapped("account_id")), touched)

    # ------------------------------------------------------------------
    # Картка рахунку
    # ------------------------------------------------------------------
    def test_07_card_lists_only_own_entries(self):
        """Картка 311 за липень: два рядки, сальдо 20 000 -> 29 000 -> 24 000."""
        card = self._card(self.acc_311)
        self.assertEqual(len(card.line_ids), 2)
        self.assertAlmostEqual(card.opening_balance, 20000.0, delta=TOLERANCE)
        first, second = card.line_ids
        self.assertAlmostEqual(first.debit, 9000.0, delta=TOLERANCE)
        self.assertAlmostEqual(first.balance, 29000.0, delta=TOLERANCE)
        self.assertAlmostEqual(second.credit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(second.balance, 24000.0, delta=TOLERANCE)
        self.assertAlmostEqual(card.total_debit, 9000.0, delta=TOLERANCE)
        self.assertAlmostEqual(card.total_credit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(card.closing_balance, 24000.0, delta=TOLERANCE)
        # Усі рядки - саме цього рахунку.
        self.assertEqual(
            set(card.line_ids.mapped("move_id.line_ids.account_id")) & {self.acc_401},
            set(),
        )

    def test_08_card_shows_counterpart_codes(self):
        """Кор. рахунок береться з протилежного боку проводки: 361, потім 631."""
        card = self._card(self.acc_311)
        first, second = card.line_ids
        self.assertEqual(first.counterpart, self.acc_361.with_company(self.company).code)
        self.assertEqual(second.counterpart, self.acc_631.with_company(self.company).code)
        # Тристороння проводка: у картці 92 кор. рахунок - обидва кредити через кому.
        expense_card = self._card(self.acc_92)
        self.assertEqual(len(expense_card.line_ids), 1)
        expected = ", ".join(sorted([
            self.acc_651.with_company(self.company).code,
            self.acc_661.with_company(self.company).code,
        ]))
        self.assertEqual(expense_card.line_ids.counterpart, expected)

    def test_09_card_partner_filter(self):
        """Фільтр партнера: покупець бачить свої два рядки, постачальник - жодного."""
        card = self._card(self.acc_361, partner=self.buyer)
        self.assertEqual(len(card.line_ids), 2)
        self.assertAlmostEqual(card.closing_balance, 3000.0, delta=TOLERANCE)  # 12000 - 9000
        empty = self._card(self.acc_361, partner=self.supplier)
        self.assertEqual(len(empty.line_ids), 0)
        self.assertAlmostEqual(empty.closing_balance, 0.0, delta=TOLERANCE)

    # ------------------------------------------------------------------
    # Аналіз рахунку
    # ------------------------------------------------------------------
    def test_10_analysis_splits_multiline_entry(self):
        """92: Дт 3 000 розкладається 661 = 3000*1800/3000 = 1800, 651 = 1200."""
        analysis = self._analysis(self.acc_92)
        self.assertTrue(analysis.control_ok)
        rows = {line.corr_account_id: line for line in analysis.line_ids}
        self.assertEqual(set(rows), {self.acc_651, self.acc_661})
        self.assertAlmostEqual(rows[self.acc_661].debit, 1800.0, delta=TOLERANCE)
        self.assertAlmostEqual(rows[self.acc_651].debit, 1200.0, delta=TOLERANCE)
        self.assertAlmostEqual(analysis.total_debit, 3000.0, delta=TOLERANCE)
        self.assertAlmostEqual(analysis.total_credit, 0.0, delta=TOLERANCE)

    def test_11_analysis_matches_account_turnover(self):
        """311: Дт 9 000 проти 361, Кт 5 000 проти 631; сальдо кін. 24 000."""
        analysis = self._analysis(self.acc_311)
        self.assertTrue(analysis.control_ok)
        rows = {line.corr_account_id: line for line in analysis.line_ids}
        self.assertAlmostEqual(rows[self.acc_361].debit, 9000.0, delta=TOLERANCE)
        self.assertAlmostEqual(rows[self.acc_631].credit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(analysis.total_debit, 9000.0, delta=TOLERANCE)
        self.assertAlmostEqual(analysis.total_credit, 5000.0, delta=TOLERANCE)
        self.assertAlmostEqual(analysis.opening_balance, 20000.0, delta=TOLERANCE)
        self.assertAlmostEqual(analysis.closing_balance, 24000.0, delta=TOLERANCE)

    # ------------------------------------------------------------------
    # Вивантаження
    # ------------------------------------------------------------------
    def test_12_xlsx_opens(self):
        """Усі три файли xlsx відкриваються і містять пораховані числа."""
        import openpyxl

        osv = self._osv()
        card = self._card(self.acc_311)
        analysis = self._analysis(self.acc_92)
        cases = [
            ("l10n_ua_ledger.action_report_ua_osv_xlsx", osv, 29000.0),
            ("l10n_ua_ledger.action_report_ua_account_card_xlsx", card, 24000.0),
            ("l10n_ua_ledger.action_report_ua_account_analysis_xlsx", analysis, 1800.0),
        ]
        for report_ref, record, expected in cases:
            content, extension = self.env["ir.actions.report"]._render_xlsx(
                report_ref, record.ids, None
            )
            self.assertEqual(extension, "xlsx")
            book = openpyxl.load_workbook(io.BytesIO(content))
            numbers = [
                cell.value
                for row in book.active.iter_rows()
                for cell in row
                if isinstance(cell.value, int | float)
            ]
            self.assertIn(expected, numbers, "у %s немає числа %s" % (report_ref, expected))
