# -*- coding: utf-8 -*-
"""Інструктажі і медогляди: коли працівника можна допускати до роботи.

Слюсар (підвищена небезпека): повторний раз на 3 місяці, медогляд раз на 12.
Бухгалтер: повторний раз на 6 місяців, медогляду не потрібно.
- Без інструктажу - проблема; первинний 100 днів тому - слюсар прострочив, бухгалтер ні.
- Повторний, який не пройдено, строку не продовжує; пройдений - продовжує.
- Старий медогляд - прострочено; «непридатний» - не допускати; «з обмеженнями» - можна.
- Нагадування одне на строк, заповнення з посади, друк журналу, захист від порожніх записів.

Запуск: тег ua_safety.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_safety")
class TestUaSafety(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({"ua_briefing_months_hazard": 3, "ua_briefing_months_other": 6,
                           "ua_safety_notify_days": 14})
        cls.today = fields.Date.context_today(cls.env.user)
        Job = cls.env["hr.job"]
        cls.hazard = Job.create({"name": "Слюсар-складальник (тест)", "ua_hazardous": True,
                                 "ua_medical_months": 12, "ua_safety_instructions": "ІОП-07, ІОП-12 (тест)"})
        cls.office = Job.create({"name": "Бухгалтер (тест)"})
        Employee = cls.env["hr.employee"]
        cls.instructor = Employee.create({"name": "Петро Інженер (тест)", "job_title": "Інженер з охорони праці"})
        cls.ivan = Employee.create({"name": "Іван Слюсар (тест)", "job_id": cls.hazard.id})
        cls.olha = Employee.create({"name": "Ольга Бухгалтер (тест)", "job_id": cls.office.id})

    def _briefing(self, day, employees, kind="primary", passed=True, reason=False):
        briefing = self.env["ua.safety.briefing"].create({
            "date": day, "kind": kind, "reason": reason, "instructor_id": self.instructor.id,
            "instructions": "ІОП-07 (тест)",
            "line_ids": [(0, 0, {"employee_id": employee.id, "passed": passed}) for employee in employees]})
        briefing.action_done()
        return briefing

    def _exam(self, day, result="fit", restrictions=False):
        return self.env["ua.medical.exam"].create({"employee_id": self.ivan.id, "date": day, "result": result,
                                                   "restrictions": restrictions, "clinic": "Клініка (тест)"})

    def test_01_terms_by_job(self):
        self.assertEqual(self.hazard.ua_briefing_months, 3)
        self.assertEqual(self.office.ua_briefing_months, 6)
        self.assertIn("немає інструктажу на робочому місці", self.ivan.ua_safety_problems(self.today))

        start = self.today - timedelta(days=100)
        self._briefing(start, self.ivan | self.olha)
        self.assertEqual(self.ivan.ua_briefing_last, start)
        self.assertEqual(self.ivan.ua_briefing_due, start + relativedelta(months=3) - timedelta(days=1))
        problems = self.ivan.ua_safety_problems(self.today)
        self.assertTrue(any("повторний інструктаж прострочено" in p for p in problems), problems)
        self.assertIn("немає медогляду", problems)
        self.assertEqual(self.olha.ua_safety_problems(self.today), [], "бухгалтер: 6 місяців, медогляд не потрібен")
        self.assertTrue(self.ivan.ua_safety_alert)
        self.assertFalse(self.olha.ua_safety_alert)

        self._briefing(self.today, self.ivan, kind="repeat", passed=False)
        self.assertEqual(self.ivan.ua_briefing_last, start, "не пройдений повторний строку не продовжує")
        self._briefing(self.today, self.ivan, kind="introductory")
        self.assertEqual(self.ivan.ua_briefing_last, start, "вступний строку не продовжує")
        self._briefing(self.today, self.ivan, kind="repeat")
        self.assertEqual(self.ivan.ua_briefing_due, self.today + relativedelta(months=3) - timedelta(days=1))

        old = self._exam(self.today - timedelta(days=400))
        self.assertEqual(old.valid_until, old.date + relativedelta(months=12) - timedelta(days=1))
        self.assertTrue(any("медогляд прострочено" in p for p in self.ivan.ua_safety_problems(self.today)))
        self._exam(self.today, result="unfit")
        self.assertFalse(self.ivan.ua_medical_valid_until)
        self.assertIn("за медоглядом непридатний", self.ivan.ua_safety_problems(self.today))
        self._exam(self.today, result="limited", restrictions="Без робіт на висоті (тест)")
        self.assertEqual(self.ivan.ua_medical_result, "limited")
        self.assertEqual(self.ivan.ua_safety_problems(self.today), [])
        self.assertFalse(self.ivan.ua_safety_alert)

        self.hazard.ua_hazardous = False
        self.assertEqual(self.hazard.ua_briefing_months, 6)
        self.assertEqual(self.ivan.ua_briefing_due, self.today + relativedelta(months=6) - timedelta(days=1))

    def test_02_reminders_fill_and_journal(self):
        self._briefing(self.today - timedelta(days=85), self.ivan | self.olha)
        Employee = self.env["hr.employee"]
        Employee._ua_cron_safety()
        Employee._ua_cron_safety()
        reminders = self.ivan.activity_ids.filtered(lambda a: "Повторний інструктаж" in (a.summary or ""))
        self.assertEqual(len(reminders), 1, "нагадування одне")
        self.assertFalse(self.olha.activity_ids.filtered(lambda a: "Повторний інструктаж" in (a.summary or "")),
                         "до строку бухгалтера ще далеко")

        unscheduled = self.env["ua.safety.briefing"].create({
            "date": self.today, "kind": "unscheduled", "job_id": self.hazard.id, "instructor_id": self.instructor.id})
        unscheduled.action_fill_job()
        self.assertEqual(unscheduled.line_ids.employee_id, self.ivan)
        self.assertEqual(unscheduled.instructions, "ІОП-07, ІОП-12 (тест)")
        self.assertEqual(unscheduled.line_ids.job_name, "Слюсар-складальник (тест)")
        with self.assertRaises(UserError, msg="позаплановий без причини"):
            unscheduled.action_done()
        unscheduled.reason = "Нова інструкція ІОП-12 (тест)"
        unscheduled.action_done()

        briefings = self.env["ua.safety.briefing"].search([("line_ids.employee_id", "in", (self.ivan | self.olha).ids)])
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_safety.report_ua_safety_journal", briefings.ids)[0].decode()
        for text in ("ЖУРНАЛ РЕЄСТРАЦІЇ ІНСТРУКТАЖІВ", "Іван Слюсар (тест)", "Ольга Бухгалтер (тест)",
                     "Первинний", "Позаплановий (Нова інструкція ІОП-12 (тест))", "ІОП-07, ІОП-12 (тест)",
                     "Петро Інженер (тест), Інженер з охорони праці"):
            self.assertIn(text, html)
        rows = briefings.ua_journal_rows()
        self.assertEqual([row["n"] for row in rows], [1, 2, 3])

        empty = self.env["ua.safety.briefing"].create({"date": self.today, "kind": "repeat"})
        with self.assertRaises(UserError, msg="без працівників"):
            empty.action_done()
        with self.assertRaises(UserError, msg="проведений не видаляють"):
            unscheduled.unlink()
        empty.unlink()
