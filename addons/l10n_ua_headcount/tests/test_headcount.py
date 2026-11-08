# -*- coding: utf-8 -*-
"""Середньооблікова кількість за I квартал 2026 року, окрема компанія, табелі з кроном.

Працівники (трудові договори):
- Андрієнко (повна ставка, з 2025 року) - на обліку весь квартал;
- Борисенко (повна ставка) - прийнято в понеділок 16.02.2026;
- Василенко (повна ставка) - звільнено в п'ятницю 13.02.2026: облікова за 14 і 15 лютого (субота,
  неділя) дорівнює п'ятниці, тож 15 людино-днів, а не 13;
- Гнатенко (0,5 ставки) - пропорційно годинам: 4 години x робочі дні / 8 / робочі дні = 0,5;
- Дмитренко (повна ставка) - у лютому відпустка у зв'язку з вагітністю та пологами (ВП): в обліковій
  є, у середньообліковій ні.
Січень (31 день, 22 робочих): 3 x 31 / 31 + 0,5 = 3,5. Лютий (28 днів, 20 робочих): (28 + 15 + 13) / 28
+ 0,5 = 2,5. Березень: 3,5. Квартал: (3,5 + 2,5 + 3,5) / 3 = 3,17, цілих 3.

Запуск: тег ua_headcount.
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_headcount")
class TestUaHeadcount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "ТОВ Чисельність (тест)"})
        cls.env.user.company_ids |= cls.company
        Employee = cls.env["hr.employee"].with_company(cls.company)
        calendar = cls.company.resource_calendar_id

        def hire(name, start, end=False, fte="1"):
            employee = Employee.create({"name": name, "company_id": cls.company.id, "ua_fte": fte,
                                        "ua_contract_kind": "employment", "resource_calendar_id": calendar.id})
            employee.version_id.with_context(sync_contract_dates=True).write({
                "contract_date_start": start, "contract_date_end": end, "resource_calendar_id": calendar.id})
            return employee

        cls.andriienko = hire("Андрієнко Андрій (тест)", "2025-01-01")
        cls.borysenko = hire("Борисенко Борис (тест)", "2026-02-16")
        cls.vasylenko = hire("Василенко Василь (тест)", "2025-01-01", "2026-02-13")
        cls.hnatenko = hire("Гнатенко Галина (тест)", "2025-01-01", fte="0.5")
        cls.dmytrenko = hire("Дмитренко Дарина (тест)", "2025-01-01")

        Sheet = cls.env["ua.timesheet.sheet"]
        cls.february = Sheet._ua_ensure_for(cls.company, 2026, 2)
        line = cls.february.line_ids.filtered(lambda l: l.employee_id == cls.dmytrenko)
        line.write({"d%02d" % day: "ВП" for day in range(1, 29)})
        cls.report = cls.env["ua.headcount.report"].create({
            "company_id": cls.company.id, "date_from": date(2026, 1, 1), "date_to": date(2026, 3, 31)})
        cls.report.action_compute()

    def _month(self, month):
        return self.report.month_ids.filtered(lambda m: m.month_start.month == month)

    def test_01_months(self):
        jan, feb, mar = self._month(1), self._month(2), self._month(3)
        self.assertEqual((jan.days, jan.working_days, jan.person_days, jan.part_equiv, jan.average),
                         (31, 22, 93, 0.5, 3.5))
        self.assertEqual((feb.days, feb.working_days, feb.person_days, feb.part_equiv, feb.average),
                         (28, 20, 56, 0.5, 2.5))
        self.assertEqual(mar.average, 3.5)
        self.assertEqual((feb.on_books_end, feb.excluded_end, feb.hired, feb.dismissed), (4, 1, 1, 1))
        self.assertEqual((jan.on_books_end, jan.hired, jan.dismissed), (4, 0, 0))
        self.assertEqual((jan.hours, feb.hours, mar.hours), (616, 400, 616))
        self.assertEqual(feb.timesheet_id, self.february)

    def test_02_period_and_checks(self):
        rep = self.report
        self.assertEqual((rep.months, rep.average, rep.average_int), (3, 3.17, 3))
        self.assertEqual((rep.on_books_end, rep.hired, rep.dismissed, rep.hours), (4, 1, 1, 1632))
        self.assertIn("Табель 02.2026 не затверджено", rep.check_text)
        self.assertEqual(len(self.env["ua.timesheet.sheet"].search([("company_id", "=", self.company.id)])), 3)

        rep.excluded_codes = "ДД"
        rep.action_compute()
        self.assertEqual(self._month(2).average, 3.5, "без ВП у виключеннях Дмитренко рахується")

        with self.assertRaises(ValidationError):
            rep.date_from = date(2026, 1, 2)

    def test_03_done_and_print(self):
        self.report.action_done()
        with self.assertRaises(UserError):
            self.report.action_compute()
        with self.assertRaises(UserError):
            self.report.unlink()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_headcount.report_ua_headcount", self.report.ids)[0].decode()
        self.assertIn("Розрахунок середньооблікової кількості штатних працівників", html)
        self.assertIn("3,17", html)
        self.assertIn("2,50", html)
