# -*- coding: utf-8 -*-
"""Шаблони кадрових наказів: друк за текстом компанії замість типового.

Зразки лежать в архіві, тож без них наказ друкує типовий текст. Повернений з архіву зразок
прийняття наказ бере сам; шаблон компанії важить більше за спільний; значення підставляються
екранованими, невідома підстановка лишається як є.

Запуск: чиста база, тег ua_hr_order_template.
"""
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_hr_order_template")
class TestUaHrOrderTemplate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env["hr.employee"].create({"name": "Шаблонна Анна Іванівна", "company_id": cls.company.id})
        cls.department = cls.env["hr.department"].create({"name": "Цех складання (тест)", "company_id": cls.company.id})
        cls.Template = cls.env["ua.hr.order.template"].with_context(active_test=False)
        cls.hire_sample = cls.env.ref("l10n_ua_hr_order_template.template_hire")

    def _order(self, **vals):
        values = {"order_type": "hire", "employee_id": self.employee.id, "company_id": self.company.id,
                  "date_from": date(2026, 12, 1), "job_title": "Монтажник", "kp_code": "7241",
                  "department_id": self.department.id, "wage": 25000.0, "basis": "заява від 2026-11-20"}
        values.update(vals)
        return self.env["ua.hr.order"].create(values)

    def _html(self, order):
        return self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_hr_orders.report_ua_hr_order", order.ids)[0].decode()

    def test_01_samples_archived_default_text(self):
        self.assertFalse(self.hire_sample.active, "зразок в архіві")
        self.assertEqual(len(self.Template.search([("id", "in", [
            self.env.ref("l10n_ua_hr_order_template.template_%s" % t).id for t in ("hire", "leave", "dismissal")])])), 3)
        order = self._order()
        self.assertFalse(order.template_id)
        self.assertIn("ПРИЙНЯТИ на роботу", self._html(order), "без шаблону - типовий текст")

    def test_02_template_print(self):
        self.hire_sample.active = True
        order = self._order(basis="<script>alert(1)</script>")
        self.assertEqual(order.template_id, self.hire_sample, "наказ бере шаблон свого виду сам")
        html = self._html(order)
        self.assertNotIn("ПРИЙНЯТИ на роботу", html, "типовий текст не друкується")
        for text in ("Про прийняття на роботу", "ПРИЙНЯТИ Шаблонна Анна Іванівна на посаду Монтажник",
                     "код КП 7241", "Цех складання (тест)", "з 01.12.2026", "000,00 грн"):
            self.assertIn(text, html)
        self.assertIn("&lt;script&gt;", html, "значення екрануються")
        self.assertNotIn("<script>alert", html)

        order.order_type = "wage"
        self.assertFalse(order.template_id, "для зміни окладу шаблону немає")
        order.template_id = False
        order.order_type = "hire"
        self.assertEqual(order.template_id, self.hire_sample)

    def test_03_company_template_and_unknown_keys(self):
        self.hire_sample.active = True
        own = self.Template.create({
            "name": "Прийняття (наш)", "order_type": "hire", "company_id": self.company.id, "sequence": 50,
            "title": "Про прийом працівника", "body": "<p>Прийняти {{працівник}} з {{з_дати}}. {{нема_такого}}</p>"})
        self.assertEqual(own.unknown, "{{нема_такого}}")
        order = self._order()
        self.assertEqual(order.template_id, own, "шаблон компанії важливіший за спільний")
        body = str(order.ua_template_body())
        self.assertIn("Прийняти Шаблонна Анна Іванівна з 01.12.2026.", body)
        self.assertIn("{{нема_такого}}", body, "невідома підстановка лишається як є")
        own.preview_order_id = order
        self.assertIn("Шаблонна Анна Іванівна", str(own.preview_html))
        self.assertIn("{{працівник}}", str(own.placeholders_html))
