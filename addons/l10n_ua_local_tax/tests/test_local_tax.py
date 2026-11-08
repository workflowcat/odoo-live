# -*- coding: utf-8 -*-
"""Місцеві податки за 2025 рік на вигаданих об'єктах.

Нерухомість, мінімальна зарплата 8000:
- адмінбудівля 1000 кв. м, ставка 1 % - 80 000 за рік, по 20 000 за квартал;
- склад 300 кв. м, 1,5 %, куплено 10.05.2025 - травень-грудень, 8 місяців: 24 000
  (II кв. 6 000, III і IV по 9 000);
- виробничий корпус 5000 кв. м не є об'єктом (пп. 266.2.2) - нуль, але в розрахунку.
Земля: ділянка з оцінкою 2 400 000 і ставкою 1 %, продана 15.10.2025 - січень-вересень,
по 2 000 на місяць; оренда 36 000 за рік - по 3 000. Січень 5 000, грудень 3 000.
Екологічний податок I кв.: CO2 1000 т x 30 + оксиди азоту 2,5 т x 2500 = 36 250.

Запуск: тег ua_local_tax.
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_local_tax")
class TestUaLocalTax(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        Object = cls.env["ua.local.tax.object"]
        common = {"territory": "Тестова громада", "date_from": date(2019, 3, 1)}
        cls.office = Object.create({**common, "name": "Адмінбудівля (тест)", "kind": "property", "area": 1000,
                                    "rate_percent": 1.0, "cadastral_number": "РН-1 (тест)"})
        cls.store = Object.create({**common, "name": "Склад (тест)", "kind": "property", "area": 300,
                                   "rate_percent": 1.5, "date_from": date(2025, 5, 10)})
        cls.plant = Object.create({**common, "name": "Виробничий корпус (тест)", "kind": "property", "area": 5000,
                                   "rate_percent": 1.0, "exempt": True,
                                   "exempt_reason": "пп. 266.2.2 ПКУ, виробничий корпус (тест)"})
        cls.plot = Object.create({**common, "name": "Ділянка під цехом (тест)", "kind": "land", "area": 1.2,
                                  "valuation": 2400000, "rate_percent": 1.0, "date_to": date(2025, 10, 15)})
        cls.rent = Object.create({**common, "name": "Оренда ділянки (тест)", "kind": "rent", "area": 0.5,
                                  "annual_rent": 36000})
        cls.Return = cls.env["ua.local.tax.return"]

    def _moves_by_date(self, record):
        return {move.date: sum(move.line_ids.mapped("debit")) for move in record.move_ids}

    def test_01_property_by_quarters(self):
        self.assertEqual(self.office.ua_months(2025), list(range(1, 13)))
        self.assertEqual(self.store.ua_months(2025), list(range(5, 13)))
        record = self.Return.create({"kind": "property", "year": 2025, "min_wage": 8000})
        record.action_fill()
        amounts = {line.object_id: line.amount for line in record.line_ids}
        self.assertEqual(amounts, {self.office: 80000.0, self.store: 24000.0, self.plant: 0.0})
        self.assertEqual(record.amount_total, 104000.0)
        self.assertEqual(record.due_date, date(2025, 2, 20))
        self.assertEqual(record.ua_schedule(), [(date(2025, 3, 31), 20000.0), (date(2025, 6, 30), 26000.0),
                                                (date(2025, 9, 30), 29000.0), (date(2025, 12, 31), 29000.0)])
        record.action_post()
        self.assertEqual(record.state, "posted")
        self.assertEqual(self._moves_by_date(record), {date(2025, 3, 31): 20000.0, date(2025, 6, 30): 26000.0,
                                                       date(2025, 9, 30): 29000.0, date(2025, 12, 31): 29000.0})
        credit = record.move_ids.line_ids.filtered("credit")
        self.assertTrue(all(code.startswith("64") for code in credit.account_id.mapped("code")))
        self.assertTrue(all(line.account_id.code.startswith("92") for line in record.move_ids.line_ids.filtered("debit")))
        with self.assertRaises(UserError):
            record.action_post()
        with self.assertRaises(UserError):
            record.unlink()

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_local_tax.report_ua_local_tax_return", record.ids)[0].decode()
        for text in ("ПОДАТОК НА НЕРУХОМЕ МАЙНО", "Адмінбудівля (тест)", "РН-1 (тест)", "пп. 266.2.2 ПКУ",
                     "104000.00", "31.03.2025", "20.02.2025"):
            self.assertIn(text, html)

        moves = record.move_ids
        record.action_draft()
        self.assertEqual(record.state, "draft")
        self.assertFalse(record.move_ids)
        self.assertEqual(self.env["account.move"].search_count([("reversed_entry_id", "in", moves.ids)]), 4,
                         "проводки сторновано")
        with self.assertRaises(ValidationError):
            self.Return.create({"kind": "property", "year": 2025})

    def test_02_land_by_months(self):
        record = self.Return.create({"kind": "land", "year": 2025})
        record.action_fill()
        amounts = {line.object_id: line.amount for line in record.line_ids}
        self.assertEqual(amounts, {self.plot: 18000.0, self.rent: 36000.0})
        record.action_post()
        by_date = self._moves_by_date(record)
        self.assertEqual(len(by_date), 12)
        self.assertEqual(by_date[date(2025, 1, 31)], 5000.0)
        self.assertEqual(by_date[date(2025, 9, 30)], 5000.0)
        self.assertEqual(by_date[date(2025, 10, 31)], 3000.0)
        self.assertEqual(by_date[date(2025, 12, 31)], 3000.0)

        later = self.Return.create({"kind": "land", "year": 2026})
        later.action_fill()
        self.assertEqual(later.line_ids.object_id, self.rent, "продану ділянку в 2026 не рахуємо")

    def test_03_environmental_quarter(self):
        first = self.Return.create({"kind": "env", "year": 2025, "quarter": "1", "line_ids": [
            (0, 0, {"name": "Двоокис вуглецю (тест)", "env_kind": "co2", "quantity": 1000, "rate": 30}),
            (0, 0, {"name": "Оксиди азоту (тест)", "env_kind": "air", "quantity": 2.5, "rate": 2500})]})
        self.assertEqual(first.amount_total, 36250.0)
        self.assertEqual(first.due_date, date(2025, 5, 10))
        first.action_post()
        self.assertEqual(self._moves_by_date(first), {date(2025, 3, 31): 36250.0})

        second = self.Return.create({"kind": "env", "year": 2025, "quarter": "2"})
        second.action_copy_previous()
        self.assertEqual(sorted(second.line_ids.mapped("name")), ["Двоокис вуглецю (тест)", "Оксиди азоту (тест)"])
        self.assertEqual(second.amount_total, 0.0)
        self.assertEqual(sorted(second.line_ids.mapped("rate")), [30.0, 2500.0])
        with self.assertRaises(UserError, msg="у екологічного немає об'єктів"):
            second.action_fill()
        with self.assertRaises(ValidationError):
            self.Return.create({"kind": "env", "year": 2025})
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_local_tax.report_ua_local_tax_return", first.ids)[0].decode()
        self.assertIn("Викиди двоокису вуглецю", html)
        self.assertIn("36250.00", html)

    def test_04_object_guards(self):
        with self.assertRaises(ValidationError):
            self.env["ua.local.tax.object"].create({"name": "Без підстави (тест)", "kind": "property",
                                                    "date_from": date(2025, 1, 1), "exempt": True})
        with self.assertRaises(ValidationError):
            self.env["ua.local.tax.object"].create({"name": "Дати навпаки (тест)", "kind": "land",
                                                    "date_from": date(2025, 5, 1), "date_to": date(2025, 1, 1)})
