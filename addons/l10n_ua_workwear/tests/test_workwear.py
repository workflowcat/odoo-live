# -*- coding: utf-8 -*-
"""Спецодяг: норми посади, видача зі списанням на витрати, повернення, списання, друк.

Посада «Складальник (тест)»: куртка 1 шт. на 24 міс., рукавиці 12 пар на 12 міс.
Склад: курток 5 по 1 500, рукавиць 100 пар по 40. Рахунок витрат - 91.
Відомість для двох складальників за нормами: 2 куртки + 24 пари = 3 000 + 960 = 3 960 на 91,
з 22 стільки ж зменшилось. Повернення однієї куртки сторнує 1 500 з 91.

Запуск: тег ua_workwear.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_workwear")
class TestUaWorkwear(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.company.inventory_valuation = "real_time"
        cls.account_22 = cls.chart.ref("ua_psbp_22")
        cls.account_91 = cls.chart.ref("ua_psbp_91")
        category = cls.env["product.category"].with_company(cls.company).create({
            "name": "МШП (тест)", "property_valuation": "real_time", "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.account_22.id})

        def product(name, price):
            return cls.env["product.product"].create({
                "name": name, "type": "consu", "is_storable": True, "categ_id": category.id,
                "standard_price": price})

        cls.jacket = product("Куртка утеплена (тест)", 1500.0)
        cls.gloves = product("Рукавиці трикотажні (тест)", 40.0)
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.jacket, cls.stock, 5)
        Quant._update_available_quantity(cls.gloves, cls.stock, 100)

        cls.job = cls.env["hr.job"].create({"name": "Складальник (тест)", "ua_workwear_norm_ids": [
            (0, 0, {"product_id": cls.jacket.id, "quantity": 1, "wear_months": 24, "reference": "п. 12"}),
            (0, 0, {"product_id": cls.gloves.id, "quantity": 12, "wear_months": 12, "reference": "п. 12"}),
        ]})
        Employee = cls.env["hr.employee"]
        cls.ivan = Employee.create({"name": "Іван Складальник", "job_id": cls.job.id})
        cls.olha = Employee.create({"name": "Ольга Складальниця", "job_id": cls.job.id})
        cls.today = fields.Date.context_today(cls.env.user)

    def _balance(self, account):
        return round(sum(self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("parent_state", "=", "posted")]).mapped("balance")), 2)

    def _issue(self, employees):
        issue = self.env["ua.workwear.issue"].create({
            "location_id": self.stock.id, "expense_account_id": self.account_91.id,
            "employee_ids": [(6, 0, employees.ids)]})
        issue.action_fill()
        return issue

    def test_01_issue_by_norms_return_and_write_off(self):
        start_91, start_22 = self._balance(self.account_91), self._balance(self.account_22)
        issue = self._issue(self.ivan | self.olha)
        self.assertTrue(issue.name.startswith("ВЕ/"))
        rows = {(l.employee_id, l.product_id): l for l in issue.line_ids}
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[(self.ivan, self.gloves)].quantity, 12.0)
        self.assertEqual(rows[(self.ivan, self.jacket)].wear_months, 24)

        issue.action_done()
        self.assertEqual(issue.state, "done")
        self.assertEqual(issue.amount_total, 3960.0)
        jacket = rows[(self.ivan, self.jacket)]
        self.assertEqual((jacket.state, jacket.price_unit, jacket.amount), ("in_use", 1500.0, 1500.0))
        self.assertEqual(jacket.date_until, self.today + relativedelta(months=24))
        self.assertEqual(self._balance(self.account_91) - start_91, 3960.0, "вартість - у витрати 91")
        self.assertEqual(self._balance(self.account_22) - start_22, -3960.0)
        self.assertEqual(self.jacket.with_context(location=self.stock.id).qty_available, 3.0)
        self.assertEqual(self.ivan.ua_workwear_count, 2)

        due = {row["product"]: row["due"] for row in self.ivan.ua_workwear_due()}
        self.assertEqual(due, {self.jacket: 0.0, self.gloves: 0.0}, "за нормами видано все")
        with self.assertRaises(UserError, msg="за нормами видавати нічого"):
            self._issue(self.ivan)

        later = self.today + relativedelta(months=13)
        due = {row["product"]: row["due"] for row in self.ivan.ua_workwear_due(later)}
        self.assertEqual(due[self.gloves], 12.0, "рукавиці зносились - належить нова пара")
        self.assertEqual(due[self.jacket], 0.0)

        with self.assertRaises(UserError):
            jacket.quantity = 2.0
        with self.assertRaises(UserError):
            issue.unlink()

        rows[(self.olha, self.jacket)].action_return()
        self.assertEqual(rows[(self.olha, self.jacket)].state, "returned")
        self.assertEqual(self._balance(self.account_91) - start_91, 2460.0, "повернення сторнує 1 500")
        self.assertEqual(self.jacket.with_context(location=self.stock.id).qty_available, 4.0)
        with self.assertRaises(UserError):
            rows[(self.olha, self.jacket)].action_return()

        gloves = rows[(self.ivan, self.gloves)]
        gloves.action_write_off("знос до строку")
        self.assertEqual((gloves.state, gloves.close_reason), ("written_off", "знос до строку"))
        self.assertEqual(self._balance(self.account_91) - start_91, 2460.0, "списання проводок не дає")

        Report = self.env["ir.actions.report"]
        html = Report._render_qweb_html("l10n_ua_workwear.report_ua_workwear_issue", issue.ids)[0].decode()
        for text in ("ВІДОМІСТЬ ВИДАЧІ", issue.name, "Іван Складальник", "Куртка утеплена (тест)",
                     "24 міс.", "3 960,00"):
            self.assertIn(text, html)
        html = Report._render_qweb_html("l10n_ua_workwear.report_ua_workwear_card", self.ivan.ids)[0].decode()
        for text in ("ОСОБОВА КАРТКА", "Складальник (тест)", "п. 12", "Рукавиці трикотажні (тест)",
                     "списано", "знос до строку"):
            self.assertIn(text, html)
        html = Report._render_qweb_html("l10n_ua_workwear.report_ua_workwear_write_off", gloves.ids)[0].decode()
        self.assertIn("АКТ СПИСАННЯ", html)
        self.assertIn("знос до строку", html)

    def test_02_guards(self):
        with self.assertRaises(ValidationError):
            self.job.ua_workwear_norm_ids[:1].quantity = 0.0
        issue = self.env["ua.workwear.issue"].create({
            "location_id": self.stock.id, "expense_account_id": self.account_91.id,
            "line_ids": [(0, 0, {"employee_id": self.ivan.id, "product_id": self.jacket.id, "quantity": 9})]})
        with self.assertRaises(UserError, msg="курток на складі 5"):
            issue.action_done()
        empty = self.env["ua.workwear.issue"].create({
            "location_id": self.stock.id, "expense_account_id": self.account_91.id})
        with self.assertRaises(UserError):
            empty.action_fill()
        with self.assertRaises(UserError):
            empty.action_done()
        empty.action_cancel()
        self.assertEqual(empty.state, "cancel")
        empty.action_draft()
        self.assertEqual(empty.state, "draft")

    def test_03_auto_write_off_after_term(self):
        self.gloves.ua_wear_auto_write_off = True
        issue = self._issue(self.ivan)
        issue.date = date(2025, 11, 3)
        issue.action_done()
        gloves = issue.line_ids.filtered(lambda l: l.product_id == self.gloves)
        jacket = issue.line_ids.filtered(lambda l: l.product_id == self.jacket)
        self.assertEqual((gloves.date_until, jacket.date_until), (date(2026, 11, 3), date(2027, 11, 3)))
        Line = self.env["ua.workwear.line"]
        self.assertFalse(Line._ua_auto_write_off(date(2026, 10, 31)), "строк ще не минув")
        done = Line._ua_auto_write_off(date(2026, 11, 30))
        self.assertEqual(done, gloves, "куртка без позначки автосписання лишається")
        self.assertEqual((gloves.state, gloves.date_closed), ("written_off", date(2026, 11, 30)))
        self.assertEqual(jacket.state, "in_use")
        self.assertIn("строк", gloves.close_reason)

