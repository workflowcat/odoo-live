# -*- coding: utf-8 -*-
"""Розрахункова відомість з сальдо: розрахунки з працівником за місяць на рахунку 661.

Вересень: листок проведено, виплачено 10 000. Жовтень: листок проведено, виплачено борг за
вересень. Відомість за жовтень: сальдо на початок - решта вересневої зарплати, нараховано і
утримано - з жовтневого листка, виплачено - жовтнева виплата, сальдо на кінець - жовтнева
зарплата до виплати. Суми листка тримають еталонні сценарії; тут - що відомість бере їх з
проводок і правильно ділить.

Запуск: чиста база, тег ua_payments.
"""
import calendar
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

YEAR = 2026


@tagged("post_install", "-at_install", "ua_payments")
class TestUaPayrollStatement(TransactionCase):

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
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.calendar = cls.company.resource_calendar_id
        cls.employee = cls.env["hr.employee"].create({
            "name": "Відомість з сальдо (тест)", "company_id": cls.company.id, "ua_contract_kind": "employment",
            "ua_main_job": True, "ua_rnokpp": "3000000777", "resource_calendar_id": cls.calendar.id})
        cls.employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 20000.0, "date_version": date(YEAR, 1, 1), "contract_date_start": date(YEAR, 1, 1),
            "struct_id": cls.structure.id, "resource_calendar_id": cls.calendar.id})

    def _slip(self, month):
        start, end = date(YEAR, month, 1), date(YEAR, month, calendar.monthrange(YEAR, month)[1])
        slip = self.env["hr.payslip"].create({
            "employee_id": self.employee.id, "date_from": start, "date_to": end,
            "struct_id": self.structure.id, "name": self.employee.name, "company_id": self.company.id})
        slip.onchange_employee()
        slip.compute_sheet()
        slip.action_payslip_done()
        self.assertTrue(slip.move_id, "проведений листок має проводку")
        return slip

    def _pay(self, slip, amount, day):
        """Виплата з банку: Дт 661 Кт 311, партнер - працівник."""
        move = self.env["account.move"].create({
            "journal_id": slip._ua_journal().id, "date": day, "move_type": "entry", "ref": "Виплата зарплати",
            "line_ids": [
                (0, 0, {"account_id": slip._ua_code_account("661").id, "debit": amount, "credit": 0.0,
                        "partner_id": self.employee.work_contact_id.id, "name": "Виплата"}),
                (0, 0, {"account_id": slip._ua_account("311").id, "debit": 0.0, "credit": amount, "name": "Виплата"}),
            ]})
        move.action_post()
        return move

    @staticmethod
    def _total(slip, code):
        return round(sum(slip.line_ids.filtered(lambda line: line.code == code).mapped("total")), 2)

    def test_statement_balances(self):
        september = self._slip(9)
        self._pay(september, 10000.0, date(YEAR, 9, 30))
        october = self._slip(10)
        owed_september = round(self._total(september, "NET") - 10000.0, 2)
        self._pay(october, owed_september, date(YEAR, 10, 15))

        statement = self.env["ua.payroll.statement"].create({"company_id": self.company.id, "year": YEAR, "month": "10"})
        statement.action_compute()
        line = statement.line_ids.filtered(lambda r: r.employee_id == self.employee)
        self.assertEqual(len(line), 1)
        gross, net = self._total(october, "GROSS"), self._total(october, "NET")
        self.assertAlmostEqual(line.opening, owed_september, places=2, msg="сальдо на початок - борг за вересень")
        self.assertAlmostEqual(line.accrued, gross, places=2, msg="нараховано - кредит 661 з листка")
        self.assertAlmostEqual(line.withheld, round(gross - net, 2), places=2, msg="утримано - дебет 661 з листка")
        self.assertAlmostEqual(line.paid, owed_september, places=2, msg="виплачено - дебет 661 з банку")
        self.assertAlmostEqual(line.closing, net, places=2, msg="на кінець - жовтнева зарплата до виплати")

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_payroll_account.action_report_ua_payroll_statement", statement.ids)[0].decode()
        self.assertIn("Розрахункова відомість з сальдо", html)
        self.assertIn(self.employee.name, html)
        self.assertIn("Головний бухгалтер", html)

    def test_empty_month_has_nothing_to_print(self):
        statement = self.env["ua.payroll.statement"].create({"company_id": self.company.id, "year": YEAR, "month": "3"})
        with self.assertRaises(UserError):
            statement.action_print()
