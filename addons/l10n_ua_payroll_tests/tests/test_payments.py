# -*- coding: utf-8 -*-
"""Відомість на перерахування на платіжному дорученні OCA. Тег `ua_payments`.

Перевіряємо рівно те, заради чого відомість переїхала з власної моделі на
`account.payment.order`: суми ті самі, що й були; затвердження й оплата створюють
справжні `account.payment`, які закривають 661 кожному працівникові і 6411 / 6415 / 651
бюджету; файл для банку байт у байт той самий, що давав старий код; без IBAN відомість
не збирається.

Зразок старого файлу лежить у tests/fixtures/payment_batch_salary_2026_08.csv - його
згенерував старий `ua.payment.batch.action_export` на тих самих рядках.
"""
import os

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PERIOD = ("2026-08-01", "2026-08-31")
PAY_DATE = "2026-09-04"


@tagged("post_install", "-at_install", "ua_payments")
class TestUaPayments(TransactionCase):

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
        from odoo.addons.l10n_ua_chart.hooks import _short_codes
        _short_codes(cls.env)
        cls.env["account.account"].invalidate_model(["code"])
        cls.company.write({
            "ua_iban_pdfo": "UA908999980313080000000010101",
            "ua_iban_vz": "UA908999980313080000000011011",
            "ua_iban_esv": "UA908999980313080000000012121",
        })
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        assert cls.structure, "немає структури UA_SALARY"
        cls.calendar = cls.company.resource_calendar_id
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)
        assert cls.journal, "у компанії немає банківського журналу"

    # ------------------------------------------------------------------ побудова даних
    def _employee(self, name, rnokpp, iban, wage=20000.0, kind="employment"):
        partner = self.env["res.partner"].create({"name": name, "company_id": self.company.id})
        employee = self.env["hr.employee"].create({
            "name": name, "company_id": self.company.id, "work_contact_id": partner.id,
            "ua_rnokpp": rnokpp, "ua_contract_kind": kind, "ua_fte": "1",
            "resource_calendar_id": self.calendar.id,
        })
        if iban:
            bank = self.env["res.partner.bank"].create({
                "acc_number": iban, "partner_id": partner.id, "company_id": self.company.id})
            employee.bank_account_ids = [(6, 0, bank.ids)]
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": wage, "date_version": "2026-01-01", "contract_date_start": "2026-01-01",
            "struct_id": self.structure.id, "resource_calendar_id": self.calendar.id,
        })
        return employee

    def _payslip(self, employee, done=True):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id, "date_from": PERIOD[0], "date_to": PERIOD[1],
            "struct_id": self.structure.id, "name": employee.name, "company_id": self.company.id,
        })
        slip.onchange_employee()
        slip.compute_sheet()
        if done:
            slip.action_payslip_done()
        return slip

    def _order(self, kind="salary"):
        return self.env["account.payment.order"].ua_compose(self.company, 2026, 8, kind)

    @staticmethod
    def _net(slip):
        return round(sum(slip.line_ids.filtered(lambda l: l.code == "NET").mapped("total")), 2)

    def _account(self, code):
        return self.env["account.account"].with_company(self.company).search(
            [("code", "=like", "%s%%" % code), ("company_ids", "in", self.company.id)],
            order="code", limit=1)

    def _open_balance(self, account, partner):
        """Незакритий залишок рахунку за контрагентом у серпні."""
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("partner_id", "=", partner.id),
            ("parent_state", "=", "posted"), ("reconciled", "=", False),
            ("date", ">=", PERIOD[0]), ("date", "<=", PERIOD[1]),
        ])
        return round(sum(lines.mapped("amount_residual")), 2)

    # ------------------------------------------------------------------ 1. суми
    def test_01_order_totals_match_payslips(self):
        """Доручення збирає ті самі суми, що давала стара відомість: NET кожного листка."""
        first = self._employee("Тест Перший", "3000000001", "UA763052990000026207000110332")
        second = self._employee("Тест Другий", "3000000002", "UA373220010000026207001119625", wage=15000.0)
        slips = self._payslip(first) + self._payslip(second)
        order = self._order()

        self.assertEqual(order.ua_kind, "salary")
        self.assertEqual(order.ua_label, "Заробітна плата 08.2026")
        self.assertEqual(order.payment_type, "outbound")
        self.assertEqual(order.payment_mode_id.name, "Зарплата")
        self.assertEqual(len(order.payment_line_ids), 2)
        by_employee = {line.ua_employee_id: line for line in order.payment_line_ids}
        for slip in slips:
            line = by_employee[slip.employee_id]
            self.assertAlmostEqual(line.amount_currency, self._net(slip), 2,
                                   "сума рядка - це «до виплати» листка")
            self.assertEqual(line.partner_id, slip.employee_id.work_contact_id)
            self.assertEqual(line.partner_bank_id, slip.employee_id._ua_payment_bank())
            self.assertEqual(line.communication,
                             "Заробітна плата за серпень 2026, остаточний розрахунок")
            self.assertEqual(line.ua_account_id, self._account("661"))
        self.assertAlmostEqual(order.total_company_currency,
                               sum(self._net(s) for s in slips), 2)

    # ------------------------------------------------------------------ 2. проведення
    def test_02_payment_clears_661_for_each_employee(self):
        """Оплата дебетує 661 кожного працівника і закриває його рядки листка."""
        first = self._employee("Тест Третій", "3000000003", "UA763052990000026207000110333")
        second = self._employee("Тест Четвертий", "3000000004", "UA373220010000026207001119626", wage=18000.0)
        slips = self._payslip(first) + self._payslip(second)
        account = self._account("661")
        for slip in slips:
            self.assertLess(self._open_balance(account, slip.employee_id.work_contact_id), 0,
                            "до виплати 661 стоїть у кредиті")

        order = self._order()
        order.ua_pay_date = PAY_DATE
        order.action_confirm()
        self.assertEqual(order.state, "open")
        self.assertEqual(len(order.payment_ids), 2, "на кожного працівника - свій платіж")

        order.action_paid()
        self.assertEqual(order.state, "uploaded")
        for payment in order.payment_ids:
            self.assertIn(payment.state, ("posted", "paid", "in_process"))
            self.assertEqual(payment.destination_account_id, account)
            self.assertEqual(str(payment.date), PAY_DATE)
        for slip in slips:
            partner = slip.employee_id.work_contact_id
            self.assertEqual(self._open_balance(account, partner), 0.0,
                             "661 працівника %s закрито повністю" % slip.employee_id.name)

    # ------------------------------------------------------------------ 3. файл банку
    def test_03_bank_file_matches_old_sample_byte_for_byte(self):
        """Файл для банку байт у байт такий самий, як давав старий ua.payment.batch."""
        rows = [
            ("Гаврилюк Богдан Тарасович", "3312205412", "UA763052990000026207000110332", 16200.00),
            ("Бойчук Соломія Андріївна", "3480053480", "UA373220010000026207001119625", 3796.41),
            ("Коваль Остап Ігорович", "2911107777", "UA903052990000026208000120001", 12163.32),
        ]
        order = self.env["account.payment.order"].create({
            "payment_mode_id": self.company._ua_payment_mode("salary").id,
            "journal_id": self.journal.id, "date_prefered": "now",
            "ua_kind": "salary", "ua_year": 2026, "ua_month": 8, "ua_pay_date": PAY_DATE,
        })
        purpose = order._ua_purpose()
        for name, rnokpp, iban, amount in rows:
            employee = self._employee(name, rnokpp, iban)
            self.env["account.payment.line"].create({
                "order_id": order.id, "partner_id": employee.work_contact_id.id,
                "partner_bank_id": employee._ua_payment_bank().id,
                "amount_currency": amount, "currency_id": self.company.currency_id.id,
                "communication": purpose, "ua_employee_id": employee.id,
                "ua_account_id": self._account("661").id,
            })
        with open(os.path.join(FIXTURES, "payment_batch_salary_2026_08.csv"), "rb") as fh:
            expected = fh.read()
        self.assertEqual(order._ua_bank_file(), expected)
        # той самий файл віддає і гак OCA generate_payment_file
        content, filename = order.generate_payment_file()
        self.assertEqual(content, expected)
        self.assertEqual(filename, "Заробітна плата 08.2026.csv")

    # ------------------------------------------------------------------ 4. без IBAN
    def test_04_missing_iban_is_refused_by_name(self):
        """Без банківського рахунку відомість не збирається і називає людину."""
        good = self._employee("Тест Пʼятий", "3000000005", "UA763052990000026207000110335")
        bad = self._employee("Тест Без Рахунку", "3000000006", False)
        self._payslip(good)
        self._payslip(bad)
        with self.assertRaises(UserError) as caught:
            self._order()
        self.assertIn("Немає IBAN", str(caught.exception))
        self.assertIn("Тест Без Рахунку", str(caught.exception))

    # ------------------------------------------------------------------ 5. бюджет
    def test_05_tax_lines_go_to_dps_partner_and_accounts(self):
        """Рядки бюджету йдуть контрагентові ДПС і закривають 6411, 6415 і 651."""
        employee = self._employee("Тест Шостий", "3000000007", "UA763052990000026207000110336")
        slip = self._payslip(employee)
        order = self._order("tax")
        order.ua_pay_date = "2026-09-20"

        dps = self.company._ua_partner("dps")
        self.assertEqual(len(order.payment_line_ids), 3)
        self.assertEqual(order.payment_mode_id.name, "Податки")
        by_label = {line.ua_label: line for line in order.payment_line_ids}
        expected = {"ПДФО": ("PDFO", "6411", self.company.ua_iban_pdfo),
                    "Військовий збір": ("VZ", "6415", self.company.ua_iban_vz),
                    "Єдиний внесок (ЄСВ)": ("ESV", "651", self.company.ua_iban_esv)}
        for label, (code, account_code, iban) in expected.items():
            line = by_label[label]
            rule_total = round(abs(sum(slip.line_ids.filtered(lambda l, c=code: l.code == c)
                                       .mapped("total"))), 2)
            self.assertAlmostEqual(line.amount_currency, rule_total, 2)
            self.assertEqual(line.partner_id, dps)
            self.assertEqual(line.partner_bank_id.acc_number, iban)
            self.assertEqual(line.ua_account_id, self._account(account_code))

        order.action_confirm()
        order.action_paid()
        accounts = {payment.destination_account_id for payment in order.payment_ids}
        self.assertEqual(accounts, {self._account("6411"), self._account("6415"),
                                    self._account("651")},
                         "три податки - три платежі на свої рахунки, не один злитий")
        for account in accounts:
            self.assertEqual(self._open_balance(account, dps), 0.0)

    # ------------------------------------------------------------------ 6. аванс
    def test_06_advance_order_reads_the_advance_sheet(self):
        """Аванс збирається з авансової відомості, а не з листків."""
        employee = self._employee("Тест Сьомий", "3000000008", "UA763052990000026207000110337")
        self._payslip(employee, done=False)
        sheet = self.env["ua.advance.sheet"].create({
            "company_id": self.company.id, "year": 2026, "month": 8, "percent": 50.0,
            "pay_date": "2026-08-20"})
        sheet.action_refill()
        self.assertTrue(sheet.line_ids, "авансова відомість наповнилася з чернеток листків")

        order = self._order("advance")
        self.assertEqual(order.ua_label, "Аванс 08.2026")
        self.assertEqual(len(order.payment_line_ids), len(sheet.line_ids.filtered(lambda l: l.amount > 0)))
        self.assertAlmostEqual(order.total_company_currency, round(sheet.total, 2), 2)
        self.assertEqual(order.payment_line_ids[0].communication, "Аванс за серпень 2026")
        levels = {row["text"]: row["level"] for row in order._checks()}
        self.assertEqual(levels.get("Сума відомості збігається з авансовою відомістю"), "ok")

    # ------------------------------------------------------------------ 7. ФОП
    def test_07_contractor_line_closes_6851_not_661(self):
        """Оплата ФОП-підряднику дебетує 6851 - той самий рахунок, що його кредитує листок."""
        fop = self._employee("Тест ФОП", "3000000009", "UA763052990000026207000110338", kind="fop")
        slip = self._payslip(fop)
        order = self._order()
        line = order.payment_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.ua_account_id, self._account("6851"))

        order.action_confirm()
        order.action_paid()
        self.assertEqual(order.payment_ids.destination_account_id, self._account("6851"))
        self.assertEqual(self._open_balance(self._account("6851"), fop.work_contact_id), 0.0)
        self.assertAlmostEqual(order.total_company_currency, self._net(slip), 2)

    # ------------------------------------------------------------------ 8. скасування
    def test_08_cancel_unwinds_payments_and_reopens_661(self):
        """Скасована відомість не лишає за собою проведених платежів і закритого 661."""
        employee = self._employee("Тест Восьмий", "3000000010", "UA763052990000026207000110339")
        slip = self._payslip(employee)
        account = self._account("661")
        partner = employee.work_contact_id
        before = self._open_balance(account, partner)

        order = self._order()
        order.ua_pay_date = PAY_DATE
        order.action_confirm()
        order.action_paid()
        self.assertEqual(self._open_balance(account, partner), 0.0)

        order.action_cancel()
        self.assertEqual(order.state, "cancel")
        self.assertTrue(all(p.state == "canceled" for p in order.payment_ids),
                        "платежі скасовані, а не лишені «в обробці»")
        self.assertAlmostEqual(self._open_balance(account, partner), before, 2,
                               "661 знову відкрито на ту саму суму")
        self.assertAlmostEqual(before, -self._net(slip), 2,
                               "до виплати на 661 висить рівно «до виплати» листка")

    # ------------------------------------------------------------------ 9. довідники
    def test_09_payment_mode_is_created_once_and_carries_the_file_format(self):
        """Способи оплати заводяться самі, по одному на компанію, і несуть формат файлу."""
        salary = self.company._ua_payment_mode("salary")
        again = self.company._ua_payment_mode("salary")
        tax = self.company._ua_payment_mode("tax")
        self.assertEqual(salary, again, "другий виклик не створює дубля")
        self.assertNotEqual(salary, tax)
        for mode in (salary, tax):
            self.assertEqual(mode.payment_type, "outbound")
            self.assertEqual(mode.ua_file_format, "csv1251")
            self.assertEqual(mode.company_id, self.company)
            self.assertFalse(mode.group_lines, "рядки не зливаємо: один працівник - один платіж")
        setup = self.company.ua_payment_setup()
        self.assertEqual(setup["salary"], salary.id)
        self.assertEqual(setup["tax"], tax.id)
        self.assertEqual(setup["journal"], self.journal.id)

    # ------------------------------------------------------------------ 10. перевірки
    def test_10_checks_report_the_payment_state(self):
        """Перевірки документа кажуть, на якому кроці відомість і чи стоять за нею платежі."""
        employee = self._employee("Тест Девʼятий", "3000000011", "UA763052990000026207000110340")
        self._payslip(employee)
        order = self._order()

        levels = {row["text"]: row["level"] for row in order._checks()}
        self.assertEqual(levels.get("Усі рядки мають IBAN"), "ok")
        self.assertEqual(levels.get("Сума відомості збігається з листками місяця"), "ok")
        self.assertEqual(levels.get("Платежі ще не складені"), "ok")

        order.action_confirm()
        self.assertIn("Платежі складені, чекають на оплату",
                      {row["text"] for row in order._checks()})
        order.action_paid()
        texts = {row["text"]: row for row in order._checks()}
        self.assertEqual(texts["Платежі проведені"]["level"], "ok")
        self.assertEqual(texts["Стан документа"]["fact"], "Оплачено")

    # ------------------------------------------------------------------ 11. чужі доручення
    def test_11_plain_oca_order_is_untouched(self):
        """Звичайне доручення OCA без виду виплати лишається звичайним дорученням."""
        order = self.env["account.payment.order"].create({
            "payment_mode_id": self.company._ua_payment_mode("salary").id,
            "journal_id": self.journal.id, "date_prefered": "now",
        })
        self.assertFalse(order.ua_kind)
        self.assertFalse(order.ua_label)
        self.assertEqual(order._checks(), [], "українських перевірок у чужого доручення немає")
        with self.assertRaises(UserError):
            order.action_fill()


    def test_12_refund_nets_to_zero_by_account_and_partner(self):
        """Оригінал і повернення разом обнуляють кожен рахунок і контрагента."""
        from collections import defaultdict
        employee = self._employee("Повернення Перевірка", "3000000012", "")
        slip = self._payslip(employee)
        self.assertEqual(slip.move_id.state, "posted")
        original_move = slip.move_id
        slip.refund_sheet()
        refund = slip.refunded_id
        self.assertTrue(refund.credit_note)
        self.assertEqual(refund.state, "done")
        self.assertEqual(refund.move_id.state, "posted")
        self.assertNotEqual(refund.move_id, original_move)
        totals = defaultdict(float)
        for line in (original_move | refund.move_id).line_ids:
            totals[(line.account_id.code, line.partner_id.id)] += line.balance
        remaining = {key: round(value, 2) for key, value in totals.items() if abs(value) > 0.004}
        self.assertFalse(remaining, "Оригінал і повернення не обнулили рахунки: %s" % remaining)
