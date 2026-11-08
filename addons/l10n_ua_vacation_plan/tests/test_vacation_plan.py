# -*- coding: utf-8 -*-
"""Графік відпусток на 2026 рік для підрозділу з трьох працівників.

- Іваненко: залишок 30 днів на 01.01.2026, днів є 30 + 24 = 54; відпустка 01.07-14.07 (14) і
  03.08-12.08 (10) - зауважень немає.
- Петренко: нарахувань немає, днів є 24; 01.06-10.06 (10) і 15.06-22.06 (8) - жодна частина не
  досягає 14 днів: попередження.
- Сидоренко: 01.09-30.09 (30) - більше, ніж є днів (24): попередження.
Без дат і з перетином частин графік не затвердити; без «Погоджено з» - теж.
20.06.2026 крон ставить одне завдання: повідомити Іваненко (початок 01.07, повідомити до 17.06).

Запуск: тег ua_vacation_plan.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import freeze_time


@tagged("post_install", "-at_install", "ua_vacation_plan")
class TestUaVacationPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.leave_type = cls.env.ref("l10n_ua_average.lt_vac")
        cls.dept = cls.env["hr.department"].create({"name": "Цех складання (тест графіка)"})
        Employee = cls.env["hr.employee"]
        cls.ivan = Employee.create({"name": "Іваненко Іван (тест)", "department_id": cls.dept.id,
                                    "job_title": "Складальник"})
        cls.petro = Employee.create({"name": "Петренко Петро (тест)", "department_id": cls.dept.id})
        cls.sydir = Employee.create({"name": "Сидоренко Сидір (тест)", "department_id": cls.dept.id})
        allocation = cls.env["hr.leave.allocation"].sudo().create({
            "name": "Залишок (тест графіка)", "employee_id": cls.ivan.id,
            "holiday_status_id": cls.leave_type.id, "number_of_days": 30,
            "date_from": date(2025, 1, 1)})
        allocation.action_approve()
        cls.plan = cls.env["ua.vacation.plan"].create({"year": 2026, "department_id": cls.dept.id})

    def _line(self, employee, start, end):
        return self.env["ua.vacation.plan.line"].create({
            "plan_id": self.plan.id, "employee_id": employee.id, "date_from": start, "date_to": end})

    def _fill_dates(self):
        self.plan.line_ids.unlink()
        self._line(self.ivan, date(2026, 7, 1), date(2026, 7, 14))
        self._line(self.ivan, date(2026, 8, 3), date(2026, 8, 12))
        self._line(self.petro, date(2026, 6, 1), date(2026, 6, 10))
        self._line(self.petro, date(2026, 6, 15), date(2026, 6, 22))
        self._line(self.sydir, date(2026, 9, 1), date(2026, 9, 30))
        self.plan.agreed_with = "Профспілковий комітет, протокол № 7 від 15.12.2025 (тест)"

    def _texts(self, level):
        return {c["text"]: c["fact"] for c in self.plan._checks() if c["level"] == level}

    def test_01_fill_and_checks(self):
        self.plan.action_fill()
        self.assertEqual(self.plan.line_ids.employee_id, self.ivan | self.petro | self.sydir)
        self.assertIn("Немає дат відпустки", self._texts("error"))
        self.plan.agreed_with = "Профком (тест)"
        with self.assertRaises(UserError):
            self.plan.action_approve()

        self._fill_dates()
        ivan_line = self.plan.line_ids.filtered(lambda l: l.employee_id == self.ivan)[:1]
        self.assertEqual(ivan_line.days_available, 54)
        self.assertEqual(sum(self.plan.line_ids.mapped("days")), 14 + 10 + 10 + 8 + 30)
        self.assertFalse(self._texts("error"))
        warnings = self._texts("warn")
        self.assertIn("Петренко", warnings["Немає безперервної частини щонайменше 14 днів"])
        self.assertNotIn("Іваненко", warnings["Немає безперервної частини щонайменше 14 днів"])
        self.assertIn("Сидоренко Сидір (тест) (30 з 24)", warnings["Заплановано більше, ніж є днів"])

        overlap = self._line(self.sydir, date(2026, 9, 25), date(2026, 10, 2))
        self.assertIn("Частини відпустки перетинаються", self._texts("error"))
        overlap.unlink()

    def test_02_approve_move_notice_leave(self):
        self._fill_dates()
        self.plan.agreed_with = False
        with self.assertRaises(UserError, msg="без погодження"):
            self.plan.action_approve()
        self.plan.agreed_with = "Профспілковий комітет (тест)"
        self.plan.action_approve()
        self.assertEqual(self.plan.state, "approved")

        sydir_line = self.plan.line_ids.filtered(lambda l: l.employee_id == self.sydir)
        with self.assertRaises(UserError):
            sydir_line.date_from = date(2026, 10, 1)
        with self.assertRaises(UserError):
            sydir_line.action_move(date(2026, 10, 1), date(2026, 10, 24), " ")
        sydir_line.action_move(date(2026, 10, 1), date(2026, 10, 24), "Заява працівника від 01.08.2026 (тест)")
        self.assertEqual((sydir_line.original_from, sydir_line.date_from, sydir_line.days, sydir_line.state),
                         (date(2026, 9, 1), date(2026, 10, 1), 24, "moved"))

        ivan_first = self.plan.line_ids.filtered(
            lambda l: l.employee_id == self.ivan and l.date_from == date(2026, 7, 1))
        self.assertEqual(ivan_first.notice_date, date(2026, 6, 17))
        with freeze_time("2026-06-20"):
            self.env["ua.vacation.plan"]._ua_cron_notices()
            self.env["ua.vacation.plan"]._ua_cron_notices()
        activities = self.plan.activity_ids
        self.assertEqual(len(activities), 1)
        self.assertIn("Іваненко", activities.summary)

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_vacation_plan.report_ua_vacation_notice", ivan_first.ids)[0].decode()
        self.assertIn("14 календарних днів з 01.07.2026", html)
        ivan_first.action_notified()
        self.assertEqual(ivan_first.state, "notified")

        ivan_first.action_create_leave()
        leave = ivan_first.leave_id
        self.assertEqual((leave.employee_id, leave.request_date_from, leave.request_date_to),
                         (self.ivan, date(2026, 7, 1), date(2026, 7, 14)))
        self.assertEqual(ivan_first.state, "leave")
        with self.assertRaises(UserError):
            self.plan.action_draft()

        plan_html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_vacation_plan.report_ua_vacation_plan", self.plan.ids)[0].decode()
        self.assertIn("ГРАФІК ВІДПУСТОК на 2026 рік", plan_html)
        self.assertIn("Заява працівника від 01.08.2026 (тест)", plan_html)
