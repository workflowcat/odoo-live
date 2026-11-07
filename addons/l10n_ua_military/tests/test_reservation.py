# -*- coding: utf-8 -*-
"""Бронювання: статус критично важливого, квота, строки, оклад, звільнення.

Окрема компанія, дати від сьогодні (С). Статус: С-100 ... С+200, квота 50 %.
Військовозобов'язаних за трудовим договором шість (призовник і ЦПХ у базу не входять):
квота 3. Заброньовано двоє з чинним строком і один із простроченим -> 2 з 3.
Ще двоє -> 4 з 3: помилка «більше, ніж дозволяє квота».

Запуск: чиста база, тег ua_military.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_military")
class TestUaReservation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env["ua.military.critical"])
        cls.company = cls.env["res.company"].create({"name": "ТОВ Бронювання (тест)"})
        cls.status = cls.env["ua.military.critical"].create({
            "company_id": cls.company.id, "authority": "Міністерство (тест)",
            "decision_number": "77-К", "criterion": "defense",
            "date_from": cls.today - timedelta(days=100), "date_to": cls.today + timedelta(days=200),
            "quota_percent": 50.0, "notify_days": 30, "dismissal_days": 5,
            "user_id": cls.env.ref("base.user_admin").id})
        Employee = cls.env["hr.employee"]

        def person(name, status="liable", kind="employment"):
            return Employee.create({"name": name, "company_id": cls.company.id,
                                    "ua_mil_status": status, "ua_contract_kind": kind})

        cls.liable = [person("Працівник %s (тест)" % n) for n in range(1, 7)]
        person("Призовник (тест)", status="conscript")
        person("Виконавець ЦПХ (тест)", kind="gph")
        cls._reserve(cls.liable[0], 100)
        cls._reserve(cls.liable[1], 100)
        cls._reserve(cls.liable[2], -5)  # бронювання скінчилось

    @classmethod
    def _reserve(cls, employee, days):
        employee.write({"ua_mil_reserved": True, "ua_mil_reserve_order": "Наказ 1-Б (тест)",
                        "ua_mil_reserve_until": cls.today + timedelta(days=days)})

    def _list(self, days=0):
        doc = self.env["ua.military.reserved"].create({
            "company_id": self.company.id, "date": self.today + timedelta(days=days)})
        doc.action_refill()
        return doc

    @staticmethod
    def _rows(doc, level):
        return {row["text"]: row["fact"] for row in doc._checks() if row["level"] == level}

    def test_01_quota(self):
        self.assertEqual(self.status.quota_counts(self.today),
                         {"liable": 6, "reserved": 2, "quota": 3, "free": 1})
        doc = self._list()
        self.assertEqual((doc.critical_id, doc.liable_count, doc.quota, doc.reserved_count),
                         (self.status, 6, 3, 2))
        self.assertIn("Квота бронювання", self._rows(doc, "ok"))
        self.assertIn("Бронювання прострочене", self._rows(doc, "error"))

        self._reserve(self.liable[3], 100)
        self._reserve(self.liable[4], 100)
        doc = self._list()
        errors = self._rows(doc, "error")
        self.assertEqual(errors["Заброньовано більше, ніж дозволяє квота"], "4 з 3 (база 6)")
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_military.report_ua_military_reserved", doc.ids)
        text = html.decode() if isinstance(html, bytes) else html
        self.assertIn("рішення № 77-К", text)
        self.assertIn("квота 3, заброньовано 4", text)

    def test_02_no_status_and_status_ending(self):
        doc = self._list(days=250)  # статус уже скінчився
        self.assertFalse(doc.critical_id)
        self.assertIn("Немає чинного статусу критично важливого підприємства на дату списку",
                      self._rows(doc, "error"))
        doc = self._list(days=180)  # 20 днів до кінця статусу
        self.assertIn("Статус критично важливого закінчується", self._rows(doc, "warn"))
        self._reserve(self.liable[5], 300)
        doc = self._list()
        self.assertEqual(self._rows(doc, "warn")["Бронювання довше за статус критично важливого"],
                         "1")

    def test_03_wage_floor(self):
        self.env["ua.payroll.param"].create({
            "key": "min_wage", "name": "Мінімальна зарплата (тест)", "value": 10000.0,
            "valid_from": self.today - timedelta(days=100), "company_id": self.company.id})
        self.status.wage_multiplier = 2.0
        self.assertEqual(self.status.wage_floor(self.today), 20000.0)
        self.liable[0].version_id.write({"wage": 18000.0})
        self.liable[1].version_id.write({"wage": 25000.0})
        doc = self._list()
        self.assertEqual(doc.wage_floor, 20000.0)
        self.assertEqual(self._rows(doc, "warn")["Оклад заброньованого нижчий за межу статусу"],
                         "2, межа 20000.00")  # 18 000 і прострочений без окладу

    def test_04_status_rules(self):
        values = {"company_id": self.company.id, "authority": "ОВА (тест)",
                  "date_from": self.today + timedelta(days=150),
                  "date_to": self.today + timedelta(days=400)}
        with self.assertRaises(ValidationError):
            self.env["ua.military.critical"].create(values)  # перетинається з чинним
        with self.assertRaises(ValidationError):
            self.env["ua.military.critical"].create(dict(
                values, date_from=self.today + timedelta(days=300),
                date_to=self.today + timedelta(days=250)))
        with self.assertRaises(ValidationError):
            self.env["ua.military.critical"].create(dict(
                values, date_from=self.today + timedelta(days=201), quota_percent=0.0))
        following = self.env["ua.military.critical"].create(dict(
            values, date_from=self.today + timedelta(days=201)))
        self.assertTrue(self.status.is_current)
        self.assertFalse(following.is_current)
        Status = self.env["ua.military.critical"]
        self.assertEqual(Status._current(self.company, self.today + timedelta(days=250)), following)

    def test_05_reminders(self):
        self.status.date_to = self.today + timedelta(days=10)
        self._reserve(self.liable[3], 20)
        Status = self.env["ua.military.critical"]
        Status._cron_reminders()
        Status._cron_reminders()  # повтор нагадування не ставить
        status_todo = self.status.activity_ids
        self.assertEqual(len(status_todo), 1)
        self.assertIn("Продовжити статус критично важливого", status_todo.summary)
        self.assertEqual(status_todo.date_deadline, self.status.date_to)
        employee_todo = self.liable[3].activity_ids
        self.assertEqual(len(employee_todo), 1)
        self.assertIn("Продовжити бронювання", employee_todo.summary)
        self.assertEqual(employee_todo.user_id, self.status.user_id)
        self.assertFalse(self.liable[0].activity_ids, "до кінця бронювання ще 100 днів")

    def test_06_dismissed_reserved_employee(self):
        leaving = self.liable[0]
        leaving.write({"active": False})
        event = leaving.ua_mil_event_ids.filtered(lambda e: e.kind == "reserve")
        self.assertEqual(len(event), 1)
        todo = self.status.activity_ids
        self.assertEqual(len(todo), 1)
        self.assertIn(leaving.name, todo.summary)
        self.assertEqual(todo.date_deadline, self.today + timedelta(days=5))
        self.assertEqual(self.status.quota_counts(self.today)["liable"], 5)
        self.liable[5].write({"active": False})  # не заброньований - нагадування немає
        self.assertEqual(len(self.status.activity_ids), 1)
