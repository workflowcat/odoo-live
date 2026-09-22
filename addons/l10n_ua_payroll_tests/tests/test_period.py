# -*- coding: utf-8 -*-
"""Місяць: підготовка, перешкоди, план і закриття. Тег `ua_period`.

Раніше це перевіряв scripts/period_check.py на живому стенді через сторінку «Період».
Сторінки більше немає - робота йде стандартним списком «Зарплата > Місяці» і формою
ua.period.close. Перевірки, які були про логіку (підготовка місяця, одне джерело
перешкод, план, закриття і відкриття), переїхали сюди й рахуються в транзакції.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

YEAR, MONTH = 2026, 3
FIRST, LAST = date(YEAR, MONTH, 1), date(YEAR, MONTH, 31)


@tagged("post_install", "-at_install", "ua_period")
class TestUaPeriod(TransactionCase):

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
        cls.Close = cls.env["ua.period.close"]
        cls.Run = cls.env["hr.payslip.run"]
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.employee = cls._employee("Періодова Ніна", "3111111111")

    @classmethod
    def _employee(cls, name, rnokpp):
        employee = cls.env["hr.employee"].create({
            "name": name, "company_id": cls.company.id, "ua_rnokpp": rnokpp,
            "ua_main_job": True, "ua_psp": "none", "ua_esv_category": "standard",
            "ua_contract_kind": "employment", "ua_fte": "1", "ua_index_off": True,
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 20000.0, "contract_date_start": "2025-01-01",
            "struct_id": cls.structure.id,
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })
        return employee

    def _record(self, kind="month", month=MONTH):
        return self.Close.create({"company_id": self.company.id, "year": YEAR,
                                  "month": month, "kind": kind})

    def _slips(self):
        return self.env["hr.payslip"].search([
            ("company_id", "=", self.company.id),
            ("date_from", ">=", FIRST), ("date_from", "<=", LAST)])

    # ------------------------------------------------------------------ підготовка місяця
    def test_01_prepare_month_builds_the_month(self):
        """Порожній місяць справді готується: табель, пакет листків, листки."""
        self.assertFalse(self._slips(), "місяць починається порожнім")
        result = self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        self.assertTrue(result.get("message"), "процедура каже, що зробила")
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company.id), ("year", "=", YEAR), ("month", "=", MONTH)])
        self.assertEqual(len(sheet), 1, "табель місяця один")
        run = self.Run.search([("company_id", "=", self.company.id),
                               ("date_start", ">=", FIRST), ("date_start", "<=", LAST)])
        self.assertEqual(len(run), 1, "пакет листків місяця один")
        self.assertIn(self.employee, self._slips().mapped("employee_id"),
                      "працівник місяця дістав листок")

    def test_02_prepare_month_is_idempotent(self):
        """Друга підготовка того самого місяця не плодить дублів."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        first = sorted(self._slips().mapped("employee_id").ids)
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        second = sorted(self._slips().mapped("employee_id").ids)
        self.assertEqual(first, second, "набір листків той самий")
        self.assertEqual(len(self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company.id), ("year", "=", YEAR), ("month", "=", MONTH)])), 1)

    def test_03_button_prepare_month_calls_the_same_logic(self):
        """Кнопка форми і процедура дають той самий набір листків."""
        record = self._record()
        record.action_prepare_month()
        by_button = sorted(self._slips().mapped("employee_id").ids)
        self.assertTrue(by_button, "кнопка створила листки")
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        self.assertEqual(sorted(self._slips().mapped("employee_id").ids), by_button,
                         "логіка напряму дає те саме")

    # ------------------------------------------------------------------ перешкоди
    def test_04_blockers_have_one_source(self):
        """blockers() - це тексти рядків blocker_rows(), не другий перелік."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        rows = self.Close.blocker_rows(self.company, YEAR, MONTH)
        self.assertEqual([row["text"] for row in rows],
                         self.Close.blockers(self.company, YEAR, MONTH))
        for row in rows:
            self.assertIn(row["key"], ("changes", "moves", "payslips", "timesheet"))
            self.assertTrue(row["short"] and row["plan"] and row["target"],
                            "кожна перешкода знає своє коротке слово, речення плану і ціль")

    def test_05_unposted_payslips_block_the_month(self):
        """Непроведені листки - перешкода, і вона називає саме їх."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        rows = self.Close.blocker_rows(self.company, YEAR, MONTH)
        payslip_rows = [row for row in rows if row["key"] == "payslips"]
        self.assertTrue(payslip_rows, "чернетки листків заважають закрити місяць")
        target = payslip_rows[0]["target"]
        self.assertEqual(target["model"], "hr.payslip")
        found = self.env["hr.payslip"].search(target["domain"])
        self.assertTrue(found, "ціль перешкоди знаходить реальні листки")

    # ------------------------------------------------------------------ план
    def test_06_plan_rows_have_text_and_level(self):
        """План закриття - рядки з текстом і рівнем; перешкоди в ньому - crit."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        plan = self.Close.plan(self.company, YEAR, MONTH)
        self.assertTrue(plan)
        for row in plan:
            self.assertTrue(row.get("text"))
            self.assertIn(row.get("level"), ("info", "warn", "crit"))
        if any(row["level"] == "crit" for row in plan):
            self.assertTrue(any(row["level"] == "warn" for row in plan),
                            "коли є перешкоди, план прямо каже, що кнопка нічого не змінить")

    def test_07_plan_html_renders_with_links(self):
        """Поле плану на формі малює перелік, а перешкоди ведуть на записи."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        record = self._record()
        html = record.plan_html or ""
        self.assertIn("<ul", html)
        self.assertIn("<li", html)
        quarter = self._record(kind="quarter", month=3)
        self.assertIn("<li", quarter.plan_html or "", "у кварталу свій план")
        year = self._record(kind="year", month=12)
        self.assertIn("<li", year.plan_html or "", "у року свій план")

    def test_08_counts_match_the_records(self):
        """Лічильники на формі рахують те саме, що й самі записи."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        record = self._record()
        record.invalidate_recordset()
        self.assertEqual(record.payslip_count, len(self._slips()))
        self.assertEqual(record.draft_move_count, self.env["account.move"].search_count([
            ("company_id", "=", self.company.id), ("date", ">=", FIRST),
            ("date", "<=", LAST), ("state", "=", "draft")]))
        self.assertEqual(record.new_change_count,
                         self.env["ua.change.log"].count_new(self.company, YEAR, MONTH))
        action = record.action_open_payslips()
        self.assertEqual(action["res_model"], "hr.payslip")
        self.assertEqual(self.env["hr.payslip"].search_count(action["domain"]), record.payslip_count)

    # ------------------------------------------------------------------ закриття
    def test_09_close_refuses_while_blockers_stand(self):
        """Поки перешкоди на місці, місяць не закривається."""
        self.Run.ua_prepare_month(self.company, YEAR, MONTH)
        self.assertTrue(self.Close.blockers(self.company, YEAR, MONTH))
        with self.assertRaises(UserError):
            self.Close.close_period(YEAR, MONTH)

    def test_10_clean_month_closes_and_sets_the_lock_date(self):
        """Чистий місяць закривається і ставить дату блокування на його останній день."""
        self.assertFalse(self.Close.blockers(self.company, YEAR, MONTH),
                         "порожній місяць нічим не заблокований")
        record_id = self.Close.close_period(YEAR, MONTH)
        record = self.Close.browse(record_id)
        self.assertEqual(record.state, "closed")
        self.assertEqual(record.lock_date, LAST)
        self.assertEqual(self.company.sudo().fiscalyear_lock_date, LAST)
        with self.assertRaises(UserError):
            self.Close.close_period(YEAR, MONTH)

    def test_11_reopen_needs_a_reason(self):
        """Відкрити місяць можна лише з причиною, і остаточне закриття не знімається."""
        record = self.Close.browse(self.Close.close_period(YEAR, MONTH))
        self.env.user.group_ids |= self.env.ref("account.group_account_manager")
        with self.assertRaises(UserError):
            record.action_reopen()
        record.reopen_reason = "Бухгалтер знайшов помилку в табелі"
        record.action_reopen()
        self.assertEqual(record.state, "open")
        self.assertTrue(record.reopened_user_id)
        self.assertTrue(self.env["ua.change.log"].search_count([
            ("model_name", "=", "ua.period.close"), ("res_id", "=", record.id)]),
            "відкриття періоду лишає слід у журналі змін")
        record.write({"state": "closed", "hard": True})
        with self.assertRaises(UserError):
            record.action_reopen()

    def test_12_quarter_and_year_blockers(self):
        """Квартал не закрити з відкритими місяцями, рік - з відкритими кварталами."""
        reasons = self.Close.quarter_blockers(self.company, YEAR, 1)
        self.assertTrue(reasons, "місяці кварталу ще відкриті")
        with self.assertRaises(UserError):
            self.Close.close_quarter(YEAR, 1)
        self.assertTrue(self.Close.year_blockers(self.company, YEAR))
        with self.assertRaises(UserError):
            self.Close.close_year(YEAR)

    def test_13_state_of_reports_the_month(self):
        """state_of() каже стан місяця тими самими словами, що й запис."""
        self.assertEqual(self.Close.state_of(self.company, YEAR, MONTH)["state"], "open")
        self.Close.close_period(YEAR, MONTH)
        state = self.Close.state_of(self.company, YEAR, MONTH)
        self.assertEqual(state["state"], "closed")
        self.assertTrue(state["closed_by"])
        self.assertTrue(state["closed_date"])

    def test_14_accept_changes_button(self):
        """Кнопка «Прийняти зміни» приймає непереглянуті рядки місяця."""
        log = self.env["ua.change.log"].sudo().with_context(ua_no_log=True).create({
            "user_id": self.env.uid, "company_id": self.company.id, "area": "hr",
            "operation": "write", "model_name": "hr.employee", "res_id": self.employee.id,
            "res_name": self.employee.name, "what": "Оклад", "old_value": "1", "new_value": "2",
            "year": YEAR, "month": MONTH,
        })
        record = self._record()
        record.invalidate_recordset()
        self.assertEqual(record.new_change_count, 1)
        record.action_accept_changes()
        self.assertEqual(log.state, "accepted")
        record.invalidate_recordset()
        self.assertEqual(record.new_change_count, 0)

    # ------------------------------------------------------------------ подання
    def test_15_views_load(self):
        """Список, форма і пошук місяців будуються."""
        views = self.env["ua.period.close"].get_views(
            [(False, "list"), (False, "form"), (False, "search")])
        self.assertEqual(set(views["views"]), {"list", "form", "search"})
        arch = views["views"]["form"]["arch"]
        for method in ("action_prepare_month", "action_accept_changes", "action_close",
                       "action_close_quarter", "action_close_year", "action_reopen"):
            self.assertIn(method, arch, "кнопка %s стоїть на формі" % method)
            self.assertTrue(hasattr(self.Close, method))
