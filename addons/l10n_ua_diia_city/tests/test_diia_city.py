# -*- coding: utf-8 -*-
"""Дія Сіті: акт гіг-спеціаліста у валюті -> гривні за курсом -> листок за ставками Дія Сіті.

Гіг-спеціаліст з винагородою 1 000 одиниць валюти на місяць. Курс на дату акта - 50 грн,
тож винагорода 50 000 грн, премія 100 одиниць - 5 000 грн. Компанія - резидент з 2025 року:
ПДФО 5 % і військовий збір 5 % з 55 000 грн (по 2 750 грн), ЄСВ - мінімальний внесок 1 902,34 грн.
Ставки на кожен випадок перевіряють еталонні сценарії 32-36 (l10n_ua_payroll_tests); тут - що
акт дійшов до листка, що місяць невідповідності вимикає пільгу і що звітність бере коди гіга.

Запуск: чиста база, тег ua_diia_city.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

YEAR = 2026
MONTH_START, MONTH_END, ACT_DATE = date(YEAR, 8, 1), date(YEAR, 8, 31), date(YEAR, 8, 31)
RATE = 50.0


@tagged("post_install", "-at_install", "ua_diia_city")
class TestUaDiiaCity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({"ua_dc_resident": True, "ua_dc_since": date(2025, 6, 10)})
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.calendar = cls.company.resource_calendar_id
        eur = cls.env.ref("base.EUR")
        cls.foreign = eur if cls.company.currency_id != eur else cls.env.ref("base.USD")
        cls.foreign.active = True
        cls.env["res.currency.rate"].create({
            "currency_id": cls.foreign.id, "name": date(YEAR, 8, 1), "company_id": cls.company.id,
            "inverse_company_rate": RATE})
        cls.gig = cls._employee("Гіг-спеціаліст (тест)", "gig", 0.0)
        cls.gig.write({"ua_gig_currency_id": cls.foreign.id, "ua_gig_fee": 1000.0})

    @classmethod
    def _employee(cls, name, kind, wage):
        employee = cls.env["hr.employee"].create({
            "name": name, "company_id": cls.company.id, "ua_contract_kind": kind,
            "ua_main_job": kind == "employment", "ua_rnokpp": "3000000999",
            "resource_calendar_id": cls.calendar.id})
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": wage, "date_version": date(YEAR, 1, 1), "contract_date_start": date(YEAR, 1, 1),
            "struct_id": cls.structure.id, "resource_calendar_id": cls.calendar.id})
        return employee

    def _slip(self, employee):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id, "date_from": MONTH_START, "date_to": MONTH_END,
            "struct_id": self.structure.id, "name": employee.name, "company_id": self.company.id})
        slip.onchange_employee()
        return slip

    def _act(self, **values):
        vals = {"employee_id": self.gig.id, "date": ACT_DATE, "date_from": MONTH_START, "date_to": MONTH_END,
                "bonus_currency": 100.0}
        vals.update(values)
        return self.env["ua.gig.act"].create(vals)

    @staticmethod
    def _lines(slip):
        return {line.code: round(line.total, 2) for line in slip.line_ids}

    def test_act_in_currency_goes_to_slip(self):
        act = self._act()
        self.assertEqual(act.currency_id, self.foreign, "валюта акта - з картки гіг-спеціаліста")
        self.assertEqual(act.amount_currency, 1000.0, "винагорода - з картки")
        self.assertAlmostEqual(act.rate, RATE, places=4)
        self.assertEqual((act.amount, act.bonus, act.total), (50000.0, 5000.0, 55000.0))
        slip = self._slip(self.gig)
        act.action_confirm()
        slip.compute_sheet()
        lines = self._lines(slip)
        self.assertTrue(slip.ua_diia_city, "резидент, що відповідає вимогам: ставки Дія Сіті")
        self.assertEqual(lines.get("GIG"), 50000.0)
        self.assertEqual(lines.get("GIG_BONUS"), 5000.0)
        self.assertEqual(lines.get("PDFO"), -2750.0)
        self.assertEqual(lines.get("VZ"), -2750.0)
        self.assertEqual(lines.get("ESV"), 1902.34)
        self.assertEqual(act.payslip_id, slip)
        auto = slip.input_line_ids.filtered("ua_gig_auto")
        self.assertEqual(set(auto.mapped("code")), {"GIG", "GIG_BONUS"})

        act.action_cancel()
        slip.invalidate_recordset()
        self.assertFalse(slip.input_line_ids.filtered("ua_gig_auto"), "скасований акт прибирає суми з листка")

    def test_print_shows_both_currencies(self):
        act = self._act()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_diia_city.action_report_ua_gig_act", act.ids)[0].decode()
        self.assertIn("1 000,00", html)
        self.assertIn("50 000,00", html)
        self.assertIn(self.foreign.name, html)

    def test_noncompliant_month_uses_general_rates(self):
        self.env["ua.diia.city.month"].create({"company_id": self.company.id, "month": MONTH_START,
                                               "compliant": False})
        act = self._act(bonus_currency=0.0)
        act.action_confirm()
        slip = self._slip(self.gig)
        slip.compute_sheet()
        lines = self._lines(slip)
        self.assertFalse(slip.ua_diia_city)
        self.assertEqual(lines.get("PDFO"), -9000.0, "18 % з 50 000")
        self.assertEqual(lines.get("ESV"), 11000.0, "22 % з усієї винагороди, без мінімуму")

    def test_rate_needed_to_confirm(self):
        other = self.env.ref("base.GBP")
        other.active = True
        act = self._act(currency_id=other.id)
        self.env["res.currency.rate"].search([("currency_id", "=", other.id)]).unlink()
        act.action_refresh_rate()
        self.assertEqual(act.rate, 0.0)
        with self.assertRaises(UserError):
            act.action_confirm()
        act.rate = 60.0
        act.action_confirm()
        self.assertEqual(act.amount, 60000.0, "курс, вписаний руками, рахує гривні")

    def test_manual_input_and_act_do_not_double(self):
        slip = self._slip(self.gig)
        self.env["hr.payslip.input"].create({"payslip_id": slip.id, "contract_id": slip.contract_id.id,
                                             "code": "GIG", "name": "GIG", "amount": 1000.0})
        act = self._act()
        with self.assertRaises(UserError):
            act.action_confirm()

    def test_month_document_counts_and_checks(self):
        act = self._act()
        act.action_confirm()
        slip = self._slip(self.gig)
        slip.compute_sheet()
        slip.write({"state": "done"})   # без проводки: тут потрібен лише стан листка
        month = self.env["ua.diia.city.month"].create({"company_id": self.company.id, "month": date(YEAR, 8, 15)})
        self.assertEqual(month.month, MONTH_START, "місяць документа - перше число")
        month.action_fill()
        self.assertEqual(month.headcount, 1)
        self.assertEqual(month.reward_total, 55000.0)
        self.assertGreater(month.eur_rate, 0.0, "курс євро - з параметра dc_eur_rate")
        texts = " ".join(check["text"] for check in month._checks())
        self.assertIn("Людей менше", texts, "одна людина - менше за вимогу закону")
        self.assertIn("позначено «відповідає»", texts, "суперечність цифр і позначки видно")

    def test_esv_minimum_once_per_month(self):
        first = self._slip(self.gig)
        self._act().action_confirm()
        first.compute_sheet()
        first.write({"state": "done"})
        second = self._slip(self.gig)
        second.compute_sheet()
        self.assertEqual(self._lines(second).get("ESV", 0.0), 0.0,
                         "мінімальний внесок уже взято першим листком місяця")

    def test_report_codes_for_gig(self):
        if "ua.payroll.report.wizard" not in self.env:
            self.skipTest("модуль звітності не встановлено")
        self._act().action_confirm()
        slip = self._slip(self.gig)
        slip.compute_sheet()
        wizard = self.env["ua.payroll.report.wizard"].create({"year": YEAR, "month": 8})
        params = self.env["ua.payroll.param"].get_all(MONTH_END, self.company)
        rows, person = wizard._person_rows(slip, params)
        self.assertEqual(len(rows), 1, "Дія Сіті: один рядок Д1")
        self.assertEqual(rows[0]["G8"], "83", "категорія застрахованої особи гіг-спеціаліста")
        self.assertEqual(rows[0]["G17"], params["min_wage"], "база ЄСВ - мінімальна зарплата")
        self.assertEqual(rows[0]["G20"], 1902.34)
        df = wizard._4df_rows([person])
        self.assertEqual(df[0]["G05"], "102", "ознака доходу гіг-контракту")
        self.assertEqual(person["gph"], 55000.0, "винагорода - у рядку цивільно-правових договорів")
