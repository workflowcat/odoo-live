# -*- coding: utf-8 -*-
"""Річний план закупівель: предмет за класом ДК 021, процедура за порогами, редакції, факт.

Пороги плану: торги для товарів і послуг від 100 000, для робіт від 1 500 000, звіт про
договір від 50 000.

    30192000-1 офісне приладдя 60 000 + 30197000-6 канцтовари 55 000 = клас 3019, 115 000:
        «без процедури, звіт» на обидва - поділ предмета, помилка; торги - гаразд;
    72260000-5 послуги з програмного забезпечення 30 000 - каталог не можна (не товар);
    45450000-6 роботи 1 200 000 і 400 000 - роботи не складаються, кожен рядок нижче порога.

Запуск: чиста база, тег ua_proc_plan.
"""
import json

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged("post_install", "-at_install", "ua_proc_plan")
class TestUaProcurementPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.company_registry = "11112222"
        cls.Plan = cls.env["ua.procurement.plan"]
        Dk = cls.env["ua.dk021"]
        cls.code = {code: Dk.search([("code", "=", code)]) for code in (
            "30192000-1", "30197000-6", "72260000-5", "45450000-6", "34711200-6", "31430000-9")}
        cls.year = fields.Date.context_today(cls.Plan).year

    def _plan(self, rows, year=None, **values):
        values = dict({"open_goods": 100000.0, "open_works": 1500000.0,
                       "report_from": 50000.0}, **values)
        values.update({
            "year": year or self.year + 1,
            "line_ids": [(0, 0, dict({"dk021_id": self.code[code].id, "name": name,
                                      "amount": amount, "procedure": procedure, "month": "3"},
                                     **extra))
                         for code, name, amount, procedure, *rest in rows
                         for extra in [rest[0] if rest else {}]]})
        return self.Plan.create(values)

    @staticmethod
    def _checks(plan):
        return [(line.dk021_id.code, line.check_level, line.check_text) for line in plan.line_ids]

    def test_01_subject_by_class_and_procedure_checks(self):
        plan = self._plan([
            ("30192000-1", "Папір і приладдя", 60000.0, "direct_report"),
            ("30197000-6", "Канцтовари", 55000.0, "direct_report"),
            ("72260000-5", "Супровід програми", 30000.0, "catalog"),
            ("34711200-6", "Безпілотні апарати для випробувань", 900000.0, "exception"),
            ("45450000-6", "Ремонт цеху", 1200000.0, "direct_report"),
            ("45450000-6", "Ремонт складу", 400000.0, "direct_report"),
        ])
        checks = self._checks(plan)
        self.assertEqual([c[1] for c in checks], ["error", "error", "error", "error", "ok", "ok"])
        self.assertIn("Предмет 30190000-7: 115 000,00 - від 100 000,00 потрібні відкриті торги",
                      checks[0][2])
        self.assertIn("лише для товарів", checks[2][2])
        self.assertIn("підставу винятку", checks[3][2])
        self.assertEqual(plan.error_count, 4)
        rows = {row["key"]: row for row in plan.subject_rows()}
        self.assertEqual((rows["3019"]["total"], len(rows["3019"]["lines"])), (115000.0, 2))
        self.assertEqual(len([k for k in rows if k.startswith("W")]), 2, "роботи не складаються")

        office = plan.line_ids[:2]
        office[0].procedure = "open"
        self.env.invalidate_all()
        self.assertEqual(office[0].check_level, "warn", "різні процедури в одному предметі")
        self.assertEqual(office[1].check_level, "error")
        office[1].procedure = "open"
        plan.line_ids[2].procedure = "direct"
        plan.line_ids[3].exception_reason = "постанова № 1178, п. 13, пп. 6 (тест)"
        self.env.invalidate_all()
        self.assertEqual([c[1] for c in self._checks(plan)], ["ok"] * 6)
        plan.line_ids[2].amount = 60000.0
        self.env.invalidate_all()
        self.assertIn("звітом про договір", plan.line_ids[2].check_text)

    def test_02_approve_amend_and_one_live_plan(self):
        plan = self._plan([("30192000-1", "Папір", 120000.0, "direct_report")])
        with self.assertRaises(UserError):
            plan.action_approve()
        plan.line_ids.procedure = "open"
        plan.approval_doc = "Протокол № 1 (тест)"
        plan.action_approve()
        self.assertEqual((plan.state, plan.approved_by_id), ("approved", self.env.user))
        with self.assertRaises(UserError):
            plan.line_ids.amount = 1.0
        with self.assertRaises(UserError):
            plan.unlink()
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._plan([("72260000-5", "Послуги", 1000.0, "direct")])
        action = plan.action_amend()
        new = self.Plan.browse(action["res_id"])
        self.assertEqual(plan.state, "superseded")
        self.assertEqual((new.state, new.revision, new.origin_id, new.year),
                         ("draft", 2, plan, plan.year))
        self.assertEqual(new.line_ids.mapped("amount"), [120000.0])
        self.assertIn("редакція 2", new.name)
        new.line_ids.amount = 150000.0
        self.assertEqual(plan.line_ids.amount, 120000.0, "стара редакція не змінилась")

    def test_03_plan_against_orders(self):
        plan = self._plan([
            ("30192000-1", "Папір", 60000.0, "open"),
            ("30197000-6", "Канцтовари", 55000.0, "open"),
        ], year=self.year)
        vendor = self.env["res.partner"].create({"name": "Постачальник плану (тест)"})

        def product(code, name):
            template = self.env["product.template"].create({
                "name": name, "type": "consu", "ua_dk021_id": self.code[code].id,
                "supplier_taxes_id": [(5, 0, 0)]})
            return template.product_variant_id

        order = self.env["purchase.order"].create({
            "partner_id": vendor.id, "order_line": [
                (0, 0, {"product_id": product("30197000-6", "Зошити (тест)").id,
                        "product_qty": 1, "price_unit": 130000.0, "tax_ids": [(5, 0, 0)]}),
                (0, 0, {"product_id": product("31430000-9", "Акумулятори (тест)").id,
                        "product_qty": 2, "price_unit": 10000.0, "tax_ids": [(5, 0, 0)]})]})
        order.button_confirm()
        rows = {row["code"]: row for row in plan.actual_rows()}
        self.assertEqual((rows["3019"]["planned"], rows["3019"]["ordered"], rows["3019"]["level"]),
                         (115000.0, 130000.0, "warn"))
        self.assertEqual((rows["3143"]["planned"], rows["3143"]["ordered"], rows["3143"]["level"]),
                         (0.0, 20000.0, "error"))
        self.env.invalidate_all()
        self.assertIn("Замовлено 130 000,00 із запланованих 115 000,00", plan.line_ids[0].check_text)
        self.assertIn("немає в плані", plan.actual_html)
        self.assertEqual(plan.error_count, 0, "перевищення плану - попередження, не помилка")

    def test_04_print_and_prozorro_file(self):
        plan = self._plan([
            ("30192000-1", "Папір", 60000.0, "open", {"month": "4", "funding": "state",
                                                      "kekv": "2210"}),
            ("30197000-6", "Канцтовари", 55000.0, "open", {"month": "2"}),
            ("72260000-5", "Дрібний супровід", 30000.0, "direct"),
            ("45450000-6", "Ремонт цеху", 1200000.0, "direct_report"),
        ])
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_procurement_plan.report_ua_procurement_plan", plan.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("РІЧНИЙ ПЛАН ЗАКУПІВЕЛЬ НА %s РІК" % (self.year + 1), "(проєкт)",
                         "Предмет 30190000-7", "115 000,00", "Відкриті торги з особливостями",
                         "Державний бюджет, 2210", "1 345 000,00"):
            self.assertIn(expected, text)

        plans = plan.prozorro_plans()
        self.assertEqual(len(plans), 2, "договір без звіту на майданчик не йде")
        office = plans[0]
        self.assertEqual(office["classification"]["id"], "30190000-7")
        self.assertEqual(office["budget"]["amount"], 115000.0)
        self.assertEqual(office["budget"]["period"]["startDate"], "%s-02-01" % (self.year + 1))
        self.assertEqual(office["budget"]["breakdown"],
                         [{"title": "own", "amount": 55000.0}, {"title": "state", "amount": 60000.0}])
        self.assertEqual(office["tender"]["procurementMethodType"], "aboveThreshold")
        self.assertEqual(office["procuringEntity"]["identifier"], {"scheme": "UA-EDR", "id": "11112222"})
        self.assertEqual(len(office["items"]), 2)
        self.assertEqual(plans[1]["tender"]["procurementMethodType"], "reporting")
        action = plan.action_export_json()
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", plan._name), ("res_id", "=", plan.id)])
        self.assertIn(str(attachment.id), action["url"])
        self.assertEqual(json.loads(attachment.raw)["plans"], plans)

    def test_05_thresholds_carry_over(self):
        self._plan([("72260000-5", "Послуги", 1000.0, "direct")], open_goods=200000.0)
        later = self.Plan.create({"year": self.year + 2})
        self.assertEqual((later.open_goods, later.open_works, later.report_from),
                         (200000.0, 1500000.0, 50000.0))
