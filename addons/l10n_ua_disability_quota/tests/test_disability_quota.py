# -*- coding: utf-8 -*-
"""Норматив для осіб з інвалідністю за III квартал 2026 року, окрема компанія з 10 штатними.

Середньооблікова 10 щомісяця - норматив одне місце. Ольга (III група, основне місце роботи) нараховано:
липень 12 000, серпень 8 000 (не більше мінімальної 8 647 - не зараховується), вересень 12 000. Зараховано
(1 + 0 + 1) / 3 = 0,67, цілих 1 - норматив виконано.
Фонд: 9 x 20 000 x 3 + 32 000 Ольги - 1 000 лікарняних = 571 000; середня зарплата 571 000 / 10 / 3 =
19 033,33. Якщо Ольга - не основне місце роботи: незайняте одне місце, внесок 40 % x 19 033,33 x 3 x 1 x
0,5 = 11 420,00.

Запуск: тег ua_disability_quota.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_disability_quota")
class TestUaDisabilityQuota(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "ТОВ Норматив (тест)"})
        cls.env.user.company_ids |= cls.company
        calendar = cls.company.resource_calendar_id
        Employee = cls.env["hr.employee"].with_company(cls.company)
        gross_rule = cls.env.ref("l10n_ua_payroll_rules.rule_gross")
        sick_rule = cls.env.ref("l10n_ua_average.rule_sick_emp")
        cls.staff = Employee.browse()
        for i in range(10):
            employee = Employee.create({
                "name": "Працівник %02d (тест нормативу)" % i, "company_id": cls.company.id, "ua_fte": "1",
                "ua_contract_kind": "employment", "ua_main_job": True, "resource_calendar_id": calendar.id})
            employee.version_id.with_context(sync_contract_dates=True).write({
                "contract_date_start": "2025-01-01", "resource_calendar_id": calendar.id})
            cls.staff |= employee
        cls.olha = cls.staff[0]
        cls.olha.write({"name": "Ольга (тест нормативу)", "ua_disability_group": "3"})
        wages = {cls.olha.id: {7: 12000.0, 8: 8000.0, 9: 12000.0}}
        Payslip = cls.env["hr.payslip"]
        for employee in cls.staff:
            for month in (7, 8, 9):
                d1 = date(2026, month, 1)
                slip = Payslip.create({
                    "employee_id": employee.id, "date_from": d1, "date_to": d1 + relativedelta(months=1, days=-1),
                    "name": employee.name, "company_id": cls.company.id, "contract_id": employee.version_id.id})
                amount = wages.get(employee.id, {}).get(month, 20000.0)
                lines = [(gross_rule, amount)]
                if employee == cls.staff[1] and month == 9:
                    lines.append((sick_rule, 1000.0))
                for rule, value in lines:
                    cls.env["hr.payslip.line"].create({
                        "slip_id": slip.id, "salary_rule_id": rule.id, "name": rule.name, "code": rule.code,
                        "category_id": rule.category_id.id, "amount": value, "quantity": 1, "rate": 100,
                        "employee_id": employee.id, "contract_id": employee.version_id.id})
                slip.write({"state": "done"})
        cls.quota = cls.env["ua.disability.quota"].create(
            {"company_id": cls.company.id, "year": 2026, "quarter": "3"})
        cls.quota.action_compute()

    def test_01_norm_met(self):
        q = self.quota
        self.assertEqual((q.date_from, q.date_to), (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual((q.headcount, q.headcount_int, q.norm), (10, 10, 1))
        self.assertEqual((q.disabled, q.disabled_int, q.shortfall, q.contribution), (0.67, 1, 0, 0))
        self.assertEqual((q.min_wage, q.wage_fund, q.average_wage), (8647, 571000, 19033.33))
        august = q.line_ids.filtered(lambda l: l.month_start.month == 8)
        self.assertFalse(august.counted)
        self.assertIn("не більше мінімальної", august.reason)
        self.assertIn("Ольга (тест нормативу) (08.2026)", q.check_text)
        self.assertEqual(q.name, "Норматив для осіб з інвалідністю, III квартал 2026")

    def test_02_contribution(self):
        self.olha.ua_main_job = False
        self.quota.action_compute()
        q = self.quota
        self.assertEqual((q.disabled_int, q.shortfall, q.contribution), (0, 1, 11420.0))
        self.assertTrue(all("не основне місце роботи" in l.reason for l in q.line_ids))
        q.martial_factor = 1.0
        q.action_compute()
        self.assertEqual(q.contribution, 22840.0)

    def test_03_group_one_counts_twice_and_norm_rule(self):
        self.olha.ua_disability_group = "1"
        self.quota.action_compute()
        self.assertEqual((self.quota.disabled, self.quota.disabled_int), (1.33, 1))
        self.assertEqual(set(self.quota.line_ids.mapped("weight")), {2})
        norms = {n: self.quota.ua_norm(n) for n in (7, 8, 25, 26, 38, 60, 63)}
        self.assertEqual(norms, {7: 0, 8: 1, 25: 1, 26: 1, 38: 2, 60: 2, 63: 3})

    def test_04_done_and_print(self):
        self.quota.action_done()
        with self.assertRaises(UserError):
            self.quota.action_compute()
        with self.assertRaises(UserError):
            self.quota.unlink()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_disability_quota.report_ua_disability_quota", self.quota.ids)[0].decode()
        self.assertIn("Розрахунок виконання нормативу робочих місць для осіб з інвалідністю", html)
        self.assertIn("19 033,33", html)
        self.assertIn("571 000,00", html)
