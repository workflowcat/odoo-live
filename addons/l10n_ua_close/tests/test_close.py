# -*- coding: utf-8 -*-
"""Регламентні операції закриття місяця.

Числа, пораховані руками (жовтень 2026, курс долара 40 до 31.10, на 31.10 - 42):

    рахунок покупцю 1 000 $ від 05.10  -> борг 40 000; на 31.10 42 000: різниця +2 000
    рахунок постачальника 500 $ від 06.10 -> борг 20 000; на 31.10 21 000: різниця -1 000
    надходження 200 $ на валютний рахунок 10.10 -> 8 000; на 31.10 8 400: різниця +400
    разом: Кт 714 2 400, Дт 945 1 000; 01.11 сторно

Гривневий місяць: продаж 10 000 (701), витрати 3 000 на 91 і 1 000 на 92.
    91 -> 901: 3 000
    79: Дт 701 10 000, Кт 901 3 000, Кт 92 1 000, Кт 791 6 000
    Ф2 до і після закриття однакова: дохід 10 000, чистий прибуток 6 000

Запуск: чиста база, теги ua_close.
"""
import datetime

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005
OCT_FIRST, OCT_LAST = datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)


@tagged("post_install", "-at_install", "ua_close")
class TestUaClose(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.Close = cls.env["ua.period.close"]
        cls.usd = cls.env.ref("base.USD")
        cls.usd.active = True
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.usd.id)]).unlink()
        for day, rate in (("2026-10-01", 40.0), ("2026-10-31", 42.0)):
            cls.env["res.currency.rate"].create({
                "name": day, "currency_id": cls.usd.id, "company_id": cls.company.id,
                "rate": 1 / rate})
        cls.customer = cls.env["res.partner"].create({"name": "Покупець (тест)"})
        cls.vendor = cls.env["res.partner"].create({"name": "Постачальник (тест)"})
        cls.usd_bank = cls.env["account.journal"].create({
            "name": "Банк USD", "type": "bank", "code": "BUSD", "currency_id": cls.usd.id,
            "company_id": cls.company.id})

    # --- службове -------------------------------------------------------

    def _account(self, xmlid):
        return self.chart.ref(xmlid)

    def _invoice(self, move_type, partner, day, lines, currency=None):
        move = self.env["account.move"].create({
            "move_type": move_type,
            "partner_id": partner.id,
            "invoice_date": day,
            "date": day,
            "currency_id": (currency or self.company.currency_id).id,
            "invoice_line_ids": [(0, 0, {
                "name": "Рядок (тест)", "quantity": 1, "price_unit": amount,
                "account_id": self._account(xmlid).id, "tax_ids": [(6, 0, [])],
            }) for xmlid, amount in lines],
        })
        move.action_post()
        return move

    def _uah_month(self, day="2026-10-15"):
        self._invoice("out_invoice", self.customer, day, [("ua_psbp_701", 10000.0)])
        self._invoice("in_invoice", self.vendor, day, [("ua_psbp_91", 3000.0),
                                                        ("ua_psbp_92", 1000.0)])

    def _usd_month(self):
        self._invoice("out_invoice", self.customer, "2026-10-05", [("ua_psbp_701", 1000.0)],
                      self.usd)
        self._invoice("in_invoice", self.vendor, "2026-10-06", [("ua_psbp_91", 500.0)], self.usd)
        line = self.env["account.bank.statement.line"].create({
            "journal_id": self.usd_bank.id, "date": "2026-10-10", "amount": 200.0,
            "payment_ref": "Надходження (тест)"})
        return line

    def _balance(self, prefix, day):
        groups = self.env["account.move.line"]._read_group(
            [("company_id", "=", self.company.id), ("parent_state", "=", "posted"),
             ("account_id.code", "=like", prefix + "%"), ("date", "<=", day)],
            [], ["balance:sum"])
        return groups[0][0] or 0.0

    def _month(self, year=2026, month=10):
        return self.Close.ensure_for(self.company, year, month)

    def _run(self, record):
        """run_operations; якщо проводка не зійшлась - показати рядки переоцінки."""
        try:
            record.run_operations()
        except UserError as error:
            items = record._ua_fx_items(self.company, OCT_LAST)
            self.fail("%s; переоцінка: %s; сьогодні: %s" % (error, [
                (i["account"].code, i["partner"].name, i["currency"].name, i["diff"])
                for i in items], fields.Date.context_today(record)))

    def _kind(self, record, kind):
        return record.ua_close_move_ids.filtered(lambda m: m.ua_close_kind == kind)

    def _f2(self, date_from, date_to):
        report = self.env.ref("l10n_ua_finrep.report_f2", raise_if_not_found=False)
        if not report:
            self.skipTest("l10n_ua_finrep не встановлено")
        instance = self.env["mis.report.instance"].create({
            "name": "Ф2 (тест)", "report_id": report.id, "target_move": "posted",
            "company_id": self.company.id, "temporary": True,
            "period_ids": [(0, 0, {"name": "Місяць", "mode": "fix", "sequence": 1,
                                   "manual_date_from": date_from,
                                   "manual_date_to": date_to})],
        })
        return instance.with_company(self.company)._ua_finrep_values()

    # --- 1. Переоцінка і сторно -------------------------------------------

    def test_01_fx_revaluation_and_reversal(self):
        self._usd_month()
        record = self._month()
        rows = {row["key"]: row for row in record.operation_rows(self.company, 2026, 10)}
        self.assertEqual(rows["fx"]["state"], "todo")
        self.assertAlmostEqual(rows["fx"]["amount"], 3400.0, delta=CENT)
        self._run(record)

        fx = self._kind(record, "fx")
        self.assertEqual(len(fx), 1)
        self.assertEqual(fx.date, OCT_LAST)
        receivable = fx.line_ids.filtered(lambda l: l.partner_id == self.customer)
        payable = fx.line_ids.filtered(lambda l: l.partner_id == self.vendor)
        bank = fx.line_ids.filtered(lambda l: l.account_id == self.usd_bank.default_account_id)
        self.assertAlmostEqual(receivable.balance, 2000.0, delta=CENT)
        self.assertAlmostEqual(payable.balance, -1000.0, delta=CENT)
        self.assertAlmostEqual(bank.balance, 400.0, delta=CENT)
        self.assertEqual(receivable.amount_currency, 0.0, "валютна сума боргу не змінюється")
        gain_account = (self.company.income_currency_exchange_account_id
                        or self._account("ua_psbp_714"))
        loss_account = (self.company.expense_currency_exchange_account_id
                        or self._account("ua_psbp_945"))
        gain = fx.line_ids.filtered(lambda l: l.account_id == gain_account)
        loss = fx.line_ids.filtered(lambda l: l.account_id == loss_account)
        self.assertAlmostEqual(sum(gain.mapped("balance")), -2400.0, delta=CENT)
        self.assertAlmostEqual(sum(loss.mapped("balance")), 1000.0, delta=CENT)

        reverse = self._kind(record, "fx_reverse")
        self.assertEqual(reverse.date, datetime.date(2026, 11, 1))
        self.assertEqual(reverse.state, "posted")
        self.assertTrue(receivable.reconciled, "сторно закрило рядок переоцінки")
        receivable_account = receivable.account_id
        on_day = lambda day: sum(self.env["account.move.line"].search([
            ("account_id", "=", receivable_account.id), ("partner_id", "=", self.customer.id),
            ("parent_state", "=", "posted"), ("date", "<=", day)]).mapped("balance"))
        self.assertAlmostEqual(on_day(OCT_LAST), 42000.0, delta=CENT)
        self.assertAlmostEqual(on_day(datetime.date(2026, 11, 1)), 40000.0, delta=CENT)

    def test_02_advance_is_not_revalued(self):
        """Оплата без рахунку - аванс, немонетарна стаття: її не переоцінюють."""
        other = self.env["res.partner"].create({"name": "Покупець з авансом (тест)"})
        payment = self.env["account.payment"].create({
            "payment_type": "inbound", "partner_type": "customer", "partner_id": other.id,
            "amount": 300.0, "currency_id": self.usd.id, "journal_id": self.usd_bank.id,
            "date": "2026-10-12"})
        payment.action_post()
        items = self.Close._ua_fx_items(self.company, OCT_LAST)
        self.assertFalse([item for item in items if item["partner"] == other])

    # --- 2. 91, 79 і Ф2 ---------------------------------------------------

    def test_03_overhead_and_result(self):
        self._uah_month()
        record = self._month()
        before = self._f2(OCT_FIRST, OCT_LAST)
        self.assertIn("warn", [row["level"] for row in
                               self.Close.plan(self.company, 2026, 10)
                               if "Регламентні операції" in row["text"]])
        record.run_operations()

        self.assertAlmostEqual(self._balance("91", OCT_LAST), 0.0, delta=CENT)
        for prefix in ("70", "90", "92"):
            self.assertAlmostEqual(self._balance(prefix, OCT_LAST), 0.0, delta=CENT, msg=prefix)
        self.assertAlmostEqual(self._balance("791", OCT_LAST), -6000.0, delta=CENT)
        result = self._kind(record, "result")
        self.assertEqual(result.journal_id.code, "CLS")
        self.assertNotEqual(self._kind(record, "overhead").journal_id.code, "CLS",
                            "91 на 901 - собівартість, Ф2 її бачить")
        self.assertFalse(record.ua_operations_pending)
        self.assertFalse([row for row in self.Close.plan(self.company, 2026, 10)
                          if "Регламентні операції" in row["text"]])

        after = self._f2(OCT_FIRST, OCT_LAST)
        self.assertAlmostEqual(before["2000"], 10000.0, delta=CENT)
        self.assertAlmostEqual(after["2000"], 10000.0, delta=CENT, msg="CLS не чіпає дохід у Ф2")
        self.assertAlmostEqual(after["2050"], 3000.0, delta=CENT, msg="ЗВВ у собівартості")
        self.assertAlmostEqual(before["2350"], 6000.0, delta=CENT)
        self.assertAlmostEqual(after["2350"], 6000.0, delta=CENT)

    def test_04_stale_result_after_new_entry(self):
        self._uah_month()
        record = self._month()
        record.run_operations()
        self._invoice("out_invoice", self.customer, "2026-10-20", [("ua_psbp_701", 500.0)])
        rows = {row["key"]: row for row in record.operation_rows(self.company, 2026, 10)}
        self.assertEqual(rows["result"]["state"], "stale")
        record.invalidate_recordset()
        self.assertTrue(record.ua_operations_pending)

    # --- 3. Рік ---------------------------------------------------------

    def test_05_year_profit_to_441(self):
        self._invoice("out_invoice", self.customer, "2026-12-10", [("ua_psbp_701", 5000.0)])
        self._invoice("in_invoice", self.vendor, "2026-12-10", [("ua_psbp_92", 2000.0)])
        record = self._month(2026, 12)
        record.run_operations()
        last = datetime.date(2026, 12, 31)
        self.assertAlmostEqual(self._balance("79", last), 0.0, delta=CENT)
        self.assertAlmostEqual(self._balance("441", last), -3000.0, delta=CENT)
        self.assertEqual(self._kind(record, "year").journal_id.code, "CLS")

    def test_06_year_loss_to_442(self):
        self._invoice("out_invoice", self.customer, "2026-12-10", [("ua_psbp_701", 1000.0)])
        self._invoice("in_invoice", self.vendor, "2026-12-10", [("ua_psbp_92", 4000.0)])
        self._month(2026, 12).run_operations()
        last = datetime.date(2026, 12, 31)
        self.assertAlmostEqual(self._balance("79", last), 0.0, delta=CENT)
        self.assertAlmostEqual(self._balance("442", last), 3000.0, delta=CENT)

    def test_07_no_year_step_mid_year(self):
        self._uah_month()
        record = self._month()
        self.assertNotIn("year", [row["key"] for row in
                                  record.operation_rows(self.company, 2026, 10)])
        record.run_operations()
        self.assertFalse(self._kind(record, "year"))

    # --- 4. Скасування і порядок ------------------------------------------

    def test_08_undo_restores_and_rerun_works(self):
        self._uah_month()
        self._usd_month()
        record = self._month()
        self._run(record)
        self.assertTrue(record.ua_close_move_ids)
        record.undo_operations()
        record.invalidate_recordset()
        self.assertFalse(record.ua_close_move_ids)
        self.assertAlmostEqual(self._balance("70", OCT_LAST), -10000.0 - 40000.0, delta=CENT)
        self.assertAlmostEqual(self._balance("91", OCT_LAST), 3000.0 + 20000.0, delta=CENT)
        if "ua.zvv.allocation" in self.env:
            self.assertFalse(self.env["ua.zvv.allocation"].search(
                [("company_id", "=", self.company.id)]))
        record.run_operations()
        self.assertAlmostEqual(self._balance("70", OCT_LAST), 0.0, delta=CENT)

    def test_09_later_month_first_blocks(self):
        self._uah_month()
        self._invoice("out_invoice", self.customer, "2026-11-10", [("ua_psbp_701", 700.0)])
        self._month(2026, 11).run_operations()
        with self.assertRaises(UserError):
            self._month().run_operations()

    def test_10_locked_month_refuses(self):
        self._uah_month()
        self.company.sudo().fiscalyear_lock_date = OCT_LAST
        with self.assertRaises(UserError):
            self._month().run_operations()

    def test_11_only_months(self):
        quarter = self.Close.create({"company_id": self.company.id, "year": 2026, "month": 12,
                                     "kind": "quarter"})
        with self.assertRaises(UserError):
            quarter.run_operations()

    # --- 5. Амортизація -----------------------------------------------------

    def test_12_depreciation_posted_and_undone(self):
        if "account.asset" not in self.env or "ua_tax_group" not in self.env[
                "account.asset.profile"]._fields:
            self.skipTest("модуль основних засобів не встановлено")
        profile = self.env["account.asset.profile"].search([
            ("company_id", "=", self.company.id), ("ua_tax_group", "=", "oz_04")], limit=1)
        asset = self.env["account.asset"].create({
            "name": "Верстат (тест)", "code": "ОЗ-777", "profile_id": profile.id,
            "purchase_value": 120000.0, "date_start": "2026-09-15", "method_number": 60})
        asset.validate()
        line = asset.depreciation_line_ids.filtered(
            lambda l: l.type == "depreciate" and l.line_date == OCT_LAST)
        self.assertEqual(len(line), 1)
        record = self._month()
        rows = {row["key"]: row for row in record.operation_rows(self.company, 2026, 10)}
        self.assertEqual(rows["depreciation"]["state"], "todo")
        record.run_operations()
        self.assertTrue(line.move_check)
        self.assertEqual(line.move_id.ua_close_kind, "depreciation")
        self.assertEqual(line.move_id.ua_close_id, record)
        record.undo_operations()
        self.assertFalse(line.move_check)
        self.assertFalse(line.move_id)

    def test_13_operations_html(self):
        self._uah_month()
        record = self._month()
        self.assertIn("<ol", record.ua_operations_html)
        self.assertIn("Фінансовий результат", record.ua_operations_html)
        self.assertTrue(record.ua_operations_pending)
