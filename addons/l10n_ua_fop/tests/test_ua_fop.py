"""ФОП 3 групи: книга доходів і квартальний розрахунок.

Усі очікувані числа пораховані руками, арифметика написана в коментарі поруч.
Параметри беруться з даних модуля: МЗП 2025 - 8 000 грн, 2026 - 8 647 грн.

Запуск: docker compose run ... --test-tags=ua_fop
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

# Копійка.
CENT = 0.005


@tagged("post_install", "-at_install", "ua_fop")
class TestUaFop(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({"ua_fop": True, "ua_fop_group": "3", "ua_fop_vat_payer": False})
        cls.uah = cls.company.currency_id
        cls.usd = cls.env.ref("base.USD")
        cls.usd.active = True
        cls.bank_journal = cls.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)
        cls.cash_journal = cls.env["account.journal"].search([
            ("type", "=", "cash"), ("company_id", "=", cls.company.id)], limit=1
        ) or cls.env["account.journal"].create({
            "name": "Каса", "type": "cash", "code": "CSHF", "company_id": cls.company.id,
        })
        cls.customer = cls.env["res.partner"].create({"name": "ТОВ Замовник"})
        # Базовий набір тестів account заводить свої курси - прибираємо, щоб
        # арифметика нижче була рівно за нашим курсом.
        cls.env["res.currency.rate"].search([
            ("currency_id", "=", cls.usd.id)]).unlink()
        # Курс НБУ 15.02.2026: 41,50 грн за долар. Odoo тримає обернений курс.
        cls.env["res.currency.rate"].create({
            "name": "2026-02-15",
            "currency_id": cls.usd.id,
            "company_id": cls.company.id,
            "rate": 1 / 41.50,
        })

    # ------------------------------------------------------------------
    # Допоміжне
    # ------------------------------------------------------------------
    @classmethod
    def _pay(cls, amount, on_date, currency=None, kind="inbound", cash=False, not_income=False):
        payment = cls.env["account.payment"].create({
            "payment_type": kind,
            "partner_type": "customer",
            "partner_id": cls.customer.id,
            "journal_id": (cls.cash_journal if cash else cls.bank_journal).id,
            "company_id": cls.company.id,
            "date": on_date,
            "amount": amount,
            "currency_id": (currency or cls.uah).id,
            "memo": "Оплата за послуги",
            "ua_fop_not_income": not_income,
        })
        payment.action_post()
        return payment

    def _quarter(self, year, quarter):
        rec = self.env["ua.fop.quarter"].create({
            "company_id": self.company.id, "year": year, "quarter": str(quarter),
        })
        rec.action_compute()
        return rec

    def _manual(self, amount, on_date, kind="money"):
        return self.env["ua.fop.income"].create({
            "name": "Готівковий виторг",
            "date": on_date,
            "company_id": self.company.id,
            "kind": kind,
            "amount": amount,
            "source": "cash",
        })

    # ------------------------------------------------------------------
    # 1. Гривневий квартал: ЄП 5 % від касового доходу.
    # ------------------------------------------------------------------
    def test_01_uah_quarter_ep_5(self):
        self._pay(100000.0, date(2026, 1, 20))
        self._pay(50000.0, date(2026, 3, 5))
        self.env["ua.fop.income"]._ua_fop_sync()
        q1 = self._quarter(2026, 1)
        # 100 000 + 50 000 = 150 000; ЄП 5 % = 7 500
        self.assertAlmostEqual(q1.income_quarter, 150000.0, delta=CENT)
        self.assertAlmostEqual(q1.ep_rate, 5.0, delta=CENT)
        self.assertAlmostEqual(q1.ep_quarter, 7500.0, delta=CENT)

    # ------------------------------------------------------------------
    # 2. Валютне надходження - у гривню за курсом дати отримання (п. 292.5 ПКУ).
    # ------------------------------------------------------------------
    def test_02_usd_receipt_at_rate(self):
        self._pay(1000.0, date(2026, 2, 15), currency=self.usd)
        self.env["ua.fop.income"]._ua_fop_sync()
        row = self.env["ua.fop.income"].search([("company_id", "=", self.company.id)])
        self.assertEqual(len(row), 1)
        # 1 000 USD × 41,50 = 41 500 грн
        self.assertAlmostEqual(row.amount, 41500.0, delta=0.05)
        self.assertEqual(row.currency_foreign_id, self.usd)
        self.assertAlmostEqual(row.amount_foreign, 1000.0, delta=CENT)
        self.assertAlmostEqual(row.rate, 41.50, delta=0.001)
        q1 = self._quarter(2026, 1)
        # ЄП 5 % від 41 500 = 2 075
        self.assertAlmostEqual(q1.ep_quarter, 2075.0, delta=0.05)

    # ------------------------------------------------------------------
    # 3. Декларація наростаючим підсумком: Q1..Q4.
    # ------------------------------------------------------------------
    def test_03_cumulative_q1_q4(self):
        for month, amount in ((2, 100000.0), (5, 200000.0), (8, 50000.0), (11, 150000.0)):
            self._pay(amount, date(2026, month, 10))
        self.env["ua.fop.income"]._ua_fop_sync()
        q1, q2, q3, q4 = (self._quarter(2026, n) for n in (1, 2, 3, 4))
        # дохід наростаючим: 100 000 / 300 000 / 350 000 / 500 000
        self.assertAlmostEqual(q1.income_ytd, 100000.0, delta=CENT)
        self.assertAlmostEqual(q2.income_ytd, 300000.0, delta=CENT)
        self.assertAlmostEqual(q3.income_ytd, 350000.0, delta=CENT)
        self.assertAlmostEqual(q4.income_ytd, 500000.0, delta=CENT)
        # ЄП наростаючим 5 %: 5 000 / 15 000 / 17 500 / 25 000
        self.assertAlmostEqual(q2.ep_ytd, 15000.0, delta=CENT)
        self.assertAlmostEqual(q4.ep_ytd, 25000.0, delta=CENT)
        # ЄП за квартал = різниця наростаючих: 5 000 / 10 000 / 2 500 / 7 500
        self.assertAlmostEqual(q1.ep_quarter, 5000.0, delta=CENT)
        self.assertAlmostEqual(q2.ep_quarter, 10000.0, delta=CENT)
        self.assertAlmostEqual(q3.ep_quarter, 2500.0, delta=CENT)
        self.assertAlmostEqual(q4.ep_quarter, 7500.0, delta=CENT)
        rows = {r["key"]: r["value"] for r in q3.declaration_rows()}
        self.assertAlmostEqual(rows["income_ytd"], 350000.0, delta=CENT)
        self.assertAlmostEqual(rows["ep_prev"], 15000.0, delta=CENT)
        self.assertAlmostEqual(rows["ep_quarter"], 2500.0, delta=CENT)

    # ------------------------------------------------------------------
    # 4. Військовий збір 1 % з доходу (з 2025 року), у 2024 - нуль.
    # ------------------------------------------------------------------
    def test_04_military_levy(self):
        self._pay(120000.0, date(2026, 3, 1))
        self.env["ua.fop.income"]._ua_fop_sync()
        q1 = self._quarter(2026, 1)
        # 120 000 × 1 % = 1 200
        self.assertAlmostEqual(q1.vz_rate, 1.0, delta=CENT)
        self.assertAlmostEqual(q1.vz_quarter, 1200.0, delta=CENT)
        # 2024 рік: військового збору з доходу ФОП на ЄП ще не було
        q2024 = self._quarter(2024, 1)
        self.assertAlmostEqual(q2024.vz_rate, 0.0, delta=CENT)
        self.assertAlmostEqual(q2024.vz_quarter, 0.0, delta=CENT)

    # ------------------------------------------------------------------
    # 5. ЄСВ «за себе» - три місяці кварталу, незалежно від доходу.
    # ------------------------------------------------------------------
    def test_05_esv_three_months(self):
        q2026 = self._quarter(2026, 2)
        # 8 647 × 22 % = 1 902,34; × 3 = 5 707,02
        self.assertAlmostEqual(q2026.esv_quarter, 5707.02, delta=CENT)
        q2025 = self._quarter(2025, 2)
        # 8 000 × 22 % = 1 760,00; × 3 = 5 280,00
        self.assertAlmostEqual(q2025.esv_quarter, 5280.0, delta=CENT)
        # ЄСВ нараховується і при нульовому доході
        self.assertAlmostEqual(q2026.income_quarter, 0.0, delta=CENT)
        self.assertAlmostEqual(q2026.total_due, 5707.02, delta=CENT)

    # ------------------------------------------------------------------
    # 6. Ліміт 3 групи: стан і ЄП 15 % з перевищення.
    # ------------------------------------------------------------------
    def test_06_limit_breach(self):
        # ліміт 2026 = 1167 × 8 647 = 10 091 049 грн
        q_probe = self.env["ua.fop.quarter"].new({
            "company_id": self.company.id, "year": 2026, "quarter": "1"})
        self.assertAlmostEqual(q_probe._limit_amount(), 10091049.0, delta=CENT)
        self._pay(10000000.0, date(2026, 1, 10))
        self._pay(200000.0, date(2026, 2, 10))
        self.env["ua.fop.income"]._ua_fop_sync()
        q1 = self._quarter(2026, 1)
        self.assertEqual(q1.limit_state, "crit")
        # 10 200 000 - 10 091 049 = 108 951 перевищення
        self.assertAlmostEqual(q1.excess_amount, 108951.0, delta=CENT)
        # 108 951 × 15 % = 16 342,65
        self.assertAlmostEqual(q1.excess_tax, 16342.65, delta=CENT)
        # ЄП: 10 091 049 × 5 % = 504 552,45 плюс 16 342,65 = 520 895,10
        self.assertAlmostEqual(q1.ep_quarter, 520895.10, delta=CENT)

    def test_07_limit_warning(self):
        # 85 % ліміту 2026: 10 091 049 × 0,85 = 8 577 391,65
        self._pay(8577391.65, date(2026, 1, 10))
        self.env["ua.fop.income"]._ua_fop_sync()
        q1 = self._quarter(2026, 1)
        self.assertEqual(q1.limit_state, "warn")
        self.assertAlmostEqual(q1.limit_pct, 85.0, delta=0.05)
        self.assertAlmostEqual(q1.excess_amount, 0.0, delta=CENT)

    # ------------------------------------------------------------------
    # 8. Повернення коштів покупцю зменшує дохід (п. 292.11 ПКУ).
    # ------------------------------------------------------------------
    def test_08_refund_reduces_income(self):
        self._pay(100000.0, date(2026, 1, 15))
        self._pay(30000.0, date(2026, 2, 20), kind="outbound")
        self.env["ua.fop.income"]._ua_fop_sync()
        refund = self.env["ua.fop.income"].search([("kind", "=", "refund")])
        self.assertEqual(len(refund), 1)
        self.assertAlmostEqual(refund.amount, -30000.0, delta=CENT)
        q1 = self._quarter(2026, 1)
        # 100 000 - 30 000 = 70 000; ЄП 5 % = 3 500
        self.assertAlmostEqual(q1.income_quarter, 70000.0, delta=CENT)
        self.assertAlmostEqual(q1.ep_quarter, 3500.0, delta=CENT)

    # ------------------------------------------------------------------
    # 9. Не дохід: кредит і власні кошти на рахунок - рядок є, податку немає.
    # ------------------------------------------------------------------
    def test_09_not_income_excluded(self):
        self._pay(80000.0, date(2026, 1, 12))
        loan = self._pay(500000.0, date(2026, 1, 13), not_income=True)
        self.env["ua.fop.income"]._ua_fop_sync()
        rows = self.env["ua.fop.income"].search([("company_id", "=", self.company.id)])
        self.assertEqual(len(rows), 2)  # у книзі видно обидва надходження
        self.assertEqual(rows.filtered(lambda r: r.payment_id == loan).kind, "not_income")
        q1 = self._quarter(2026, 1)
        # у розрахунок іде лише 80 000; ЄП 5 % = 4 000
        self.assertAlmostEqual(q1.income_quarter, 80000.0, delta=CENT)
        self.assertAlmostEqual(q1.ep_quarter, 4000.0, delta=CENT)
        # прапорець зняли - рядок повертається в дохід
        loan.ua_fop_not_income = False
        self.assertEqual(rows.filtered(lambda r: r.payment_id == loan).kind, "money")
        q1.action_compute()
        self.assertAlmostEqual(q1.income_quarter, 580000.0, delta=CENT)

    # ------------------------------------------------------------------
    # 10. Синхронізація ідемпотентна, готівка потрапляє з касового журналу.
    # ------------------------------------------------------------------
    def test_10_sync_idempotent_and_cash(self):
        self._pay(10000.0, date(2026, 1, 5))
        self._pay(2500.0, date(2026, 1, 6), cash=True)
        first = self.env["ua.fop.income"]._ua_fop_sync()
        self.assertEqual(len(first), 2)
        second = self.env["ua.fop.income"]._ua_fop_sync()
        self.assertEqual(len(second), 0)
        rows = self.env["ua.fop.income"].search([("company_id", "=", self.company.id)])
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows.mapped("source")), ["bank", "cash"])

    # ------------------------------------------------------------------
    # 11. Платник ПДВ: ставка ЄП 3 % замість 5 %.
    # ------------------------------------------------------------------
    def test_11_vat_payer_rate_3(self):
        self.company.ua_fop_vat_payer = True
        self._pay(200000.0, date(2026, 2, 2))
        self.env["ua.fop.income"]._ua_fop_sync()
        q1 = self._quarter(2026, 1)
        # 200 000 × 3 % = 6 000
        self.assertAlmostEqual(q1.ep_rate, 3.0, delta=CENT)
        self.assertAlmostEqual(q1.ep_quarter, 6000.0, delta=CENT)

    # ------------------------------------------------------------------
    # 12. Книга доходів: ручний рядок, наростаючий підсумок, знак повернення.
    # ------------------------------------------------------------------
    def test_12_book_rows(self):
        self._manual(5000.0, date(2026, 1, 3))
        self._manual(7000.0, date(2026, 1, 10))
        self._manual(-2000.0, date(2026, 1, 20), kind="refund")
        self._manual(90000.0, date(2026, 1, 25), kind="not_income")
        book = self.env["ua.fop.income"]._book_rows(
            self.company, date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(len(book), 4)
        # наростаючий підсумок: 5 000 / 12 000 / 10 000 / 10 000 (не дохід не рахується)
        self.assertEqual([r["running"] for r in book], [5000.0, 12000.0, 10000.0, 10000.0])
        with self.assertRaises(ValidationError):
            self._manual(-500.0, date(2026, 1, 28))

    # ------------------------------------------------------------------
    # 13. Компанія без ознаки ФОП і рік без параметрів - зрозуміла помилка.
    # ------------------------------------------------------------------
    def test_13_guards(self):
        other = self.env["res.company"].create({"name": "ТОВ Звичайне", "currency_id": self.uah.id})
        rec = self.env["ua.fop.quarter"].create({
            "company_id": other.id, "year": 2026, "quarter": "1"})
        with self.assertRaises(UserError):
            rec.action_compute()
        old = self.env["ua.fop.quarter"].create({
            "company_id": self.company.id, "year": 2015, "quarter": "1"})
        with self.assertRaises(UserError):
            old.action_compute()

    def test_14_company_value_beats_common(self):
        """Параметр компанії перемагає загальний, навіть коли загальний новіший; інша компанія бере загальний.

        Загальна МЗП з 2026-01-01 - 8 647 грн (дані модуля). Компанія має свій запис з 2025-06-01 -
        9 000 грн: на 2026-03-01 для неї 9 000, для іншої компанії 8 647.
        """
        Param = self.env["ua.fop.param"].sudo()
        Param.create({"key": "fop_mzp", "name": "Мінімальна зарплата, грн/міс", "valid_from": date(2025, 6, 1),
                      "value": 9000.0, "company_id": self.company.id, "source": "уявне значення для перевірки"})
        other = self.env["res.company"].sudo().create({"name": "ТОВ Інше", "currency_id": self.uah.id})
        self.assertEqual(Param.get("fop_mzp", date(2026, 3, 1), self.company), 9000.0)
        self.assertEqual(Param.get("fop_mzp", date(2026, 3, 1), other), 8647.0)
