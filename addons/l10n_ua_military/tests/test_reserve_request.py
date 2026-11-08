# -*- coding: utf-8 -*-
"""Заявка на бронювання: кандидати, дані, квота, CSV, рішення на картки.

Окрема компанія, статус С-100 ... С+200, квота 50 % від шести військовозобов'язаних = 3.
Заброньовані до С+100 (двоє) лишаються чинними. Кандидати: бронювання скінчилось (П3),
закінчується за 10 днів (П4, продовження), не заброньовані (П5, П6; у П6 немає номера документа).
- 2 чинних + 4 у заявці > 3: подати не можна; без П5 і П6 - все ще 4; без П3 - 3, можна.
- CSV - лише включені рядки; рішення без дати не вноситься; з датою - на картці і в подіях.

Запуск: тег ua_military.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_military")
class TestUaReserveRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env["ua.military.critical"])
        cls.company = cls.env["res.company"].create({"name": "ТОВ Заявка на бронювання (тест)"})
        cls.status = cls.env["ua.military.critical"].create({
            "company_id": cls.company.id, "authority": "Міністерство (тест)", "decision_number": "88-К",
            "criterion": "defense", "date_from": cls.today - timedelta(days=100),
            "date_to": cls.today + timedelta(days=200), "quota_percent": 50.0,
            "user_id": cls.env.ref("base.user_admin").id})
        Employee = cls.env["hr.employee"]
        cls.people = []
        for n in range(1, 7):
            cls.people.append(Employee.create({
                "name": "Працівник%s Тестовий Іванович" % n, "company_id": cls.company.id,
                "ua_mil_status": "liable", "ua_contract_kind": "employment", "ua_rnokpp": "30000000%02d" % n,
                "birthday": date(1990, 1, n), "ua_mil_doc_type": "ticket", "ua_mil_doc_series": "АА",
                "ua_mil_doc_number": "" if n == 6 else "10000%s" % n, "job_title": "Складальник (тест)"}))
        for person, days in zip(cls.people[:4], (100, 100, -5, 10)):
            person.write({"ua_mil_reserved": True, "ua_mil_reserve_order": "Рішення 1 (тест)",
                          "ua_mil_reserve_until": cls.today + timedelta(days=days)})

    def _errors(self, doc):
        return {row["text"]: row["fact"] for row in doc._checks() if row["level"] == "error"}

    def test_01_candidates_quota_and_decision(self):
        doc = self.env["ua.military.reserve.request"].create({"company_id": self.company.id, "date": self.today})
        doc.action_fill()
        lines = {line.employee_id: line for line in doc.line_ids}
        p = self.people
        self.assertEqual(set(lines), {p[2], p[3], p[4], p[5]})
        self.assertEqual((doc.critical_id, doc.liable_count, doc.quota, doc.kept_count), (self.status, 6, 3, 2))
        self.assertEqual(lines[p[3]].purpose, "prolong")
        self.assertEqual(lines[p[3]].current_until, self.today + timedelta(days=10))
        self.assertEqual(lines[p[2]].purpose, "new")
        self.assertEqual(lines[p[2]].last_name, "Працівник3")
        self.assertTrue(lines[p[5]].blocking)
        self.assertIn("номер військового документа", lines[p[5]].problems)
        self.assertEqual(doc.blocked_count, 1)

        errors = self._errors(doc)
        self.assertEqual(errors["Заявка більша, ніж дозволяє квота"], "6 з 3 (чинних 2, у заявці 4)")
        self.assertIn("Не вистачає даних для заявки", errors)
        with self.assertRaises(UserError):
            doc.action_submit()
        (lines[p[4]] | lines[p[5]]).write({"include": False})
        self.assertEqual(self._errors(doc), {"Заявка більша, ніж дозволяє квота": "4 з 3 (чинних 2, у заявці 2)"})
        lines[p[2]].include = False
        self.assertFalse(self._errors(doc))

        csv_text = doc.ua_csv()
        rows = csv_text.strip().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith("№;РНОКПП;Прізвище"))
        self.assertIn("3000000004;Працівник4;Тестовий;Іванович;04.01.1990;Військовий квиток;АА;100004", rows[1])
        self.assertIn("Продовження", rows[1])
        action = doc.action_export_csv()
        self.assertTrue(action["url"].startswith("/web/content/"))

        doc.action_submit()
        self.assertEqual(doc.state, "submitted")
        self.assertEqual(doc.submitted_date, self.today)
        doc.decision_ref = "Рішення 2-К від сьогодні (тест)"
        with self.assertRaises(UserError, msg="рішення не внесено"):
            doc.action_apply()
        lines[p[3]].result = "approved"
        with self.assertRaises(UserError, msg="без дати"):
            doc.action_apply()
        until = self.today + timedelta(days=180)
        lines[p[3]].decision_until = until
        doc.action_apply()
        self.assertEqual(doc.state, "done")
        self.assertEqual(p[3].ua_mil_reserve_until, until)
        self.assertEqual(p[3].ua_mil_reserve_order, "Рішення 2-К від сьогодні (тест)")
        self.assertFalse(p[2].ua_mil_reserve_until > self.today, "не включений рядок не чіпаємо")
        events = self.env["ua.military.event"].search([("employee_id", "=", p[3].id), ("kind", "=", "reserve")])
        self.assertTrue(any("Заброньовано до" in (e.note or "") for e in events))
        with self.assertRaises(UserError):
            doc.action_draft()
        with self.assertRaises(UserError):
            doc.unlink()

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_military.report_ua_military_reserve_request", doc.ids)[0].decode()
        for text in ("ПЕРЕЛІК ВІЙСЬКОВОЗОБОВ'ЯЗАНИХ ДЛЯ БРОНЮВАННЯ", "рішення № 88-К", "Працівник4 Тестовий Іванович",
                     "3000000004", "заброньовано до"):
            self.assertIn(text, html)
        self.assertNotIn("Працівник5", html)

    def test_02_refusal_and_no_status(self):
        doc = self.env["ua.military.reserve.request"].create({"company_id": self.company.id, "date": self.today})
        doc.action_fill()
        doc.line_ids.filtered(lambda l: l.employee_id != self.people[4]).write({"include": False})
        doc.action_submit()
        doc.line_ids.filtered("include").result = "refused"
        doc.action_apply()
        self.assertFalse(self.people[4].ua_mil_reserved)
        events = self.env["ua.military.event"].search([("employee_id", "=", self.people[4].id)])
        self.assertTrue(any("Відмовлено" in (e.note or "") for e in events))

        later = self.env["ua.military.reserve.request"].create({
            "company_id": self.company.id, "date": self.today + timedelta(days=300)})
        later.action_fill()
        self.assertIn("Немає чинного статусу критично важливого підприємства на дату заявки", self._errors(later))
