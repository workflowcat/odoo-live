# -*- coding: utf-8 -*-
"""Пеня і штраф за прострочення поставки.

Контракт: пеня 0,1 % за день, штраф 7 % за прострочення понад 30 днів. Ціна дрона 100 000.
Графік: 10 шт до 2026-03-01, 5 шт до 2026-04-01, 2 шт до 2026-05-01 (останні - по 50 000).
Акти: 2026-02-25 - 6 шт (вчасно), 2026-03-11 - 4 шт (10 днів), 2026-05-11 - 5 шт (40 днів).

    4 x 100 000 = 400 000 x 0,1 % x 10 днів              пеня   4 000,00
    5 x 100 000 = 500 000 x 0,1 % x 40 днів              пеня  20 000,00, штраф 35 000,00
    2 x  50 000 = 100 000 не поставлено, на 2026-05-21:  пеня   2 000,00 (20 днів)
                                         на 2026-06-10:  пеня   4 000,00, штраф 7 000,00 (40 днів)

Запуск: чиста база, тег ua_defense.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_defense")
class TestUaDefensePenalty(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        customer = cls.env["res.partner"].create({"name": "Замовник (тест санкцій)"})
        cls.drone = cls.env["product.product"].create({"name": "Дрон (тест санкцій)", "type": "consu"})
        cls.kit = cls.env["product.product"].create({"name": "Комплект ЗІП (тест санкцій)",
                                                     "type": "consu"})
        cls.contract = cls.env["ua.contract"].create({
            "name": "ОК-9/2026 (тест)", "date": date(2026, 1, 15), "partner_id": customer.id,
            "ua_defense": True, "ua_penalty_rate": 0.1, "ua_fine_rate": 7.0, "ua_fine_days": 30,
            "ua_schedule_ids": [
                (0, 0, {"product_id": cls.drone.id, "quantity": 10.0, "date": date(2026, 3, 1),
                        "price_unit": 100000.0}),
                (0, 0, {"product_id": cls.drone.id, "quantity": 5.0, "date": date(2026, 4, 1),
                        "price_unit": 100000.0}),
                (0, 0, {"product_id": cls.kit.id, "quantity": 2.0, "date": date(2026, 5, 1),
                        "price_unit": 50000.0}),
            ]})
        for day, qty in ((date(2026, 2, 25), 6.0), (date(2026, 3, 11), 4.0), (date(2026, 5, 11), 5.0)):
            cls._act(day, cls.drone, qty).action_done()

    @classmethod
    def _act(cls, day, product, qty):
        return cls.env["ua.defense.acceptance"].create({
            "contract_id": cls.contract.id, "date": day,
            "line_ids": [(0, 0, {"product_id": product.id, "quantity": qty})]})

    def test_01_late_parts_and_totals(self):
        rows = self.contract.ua_penalty_rows(date(2026, 5, 21))
        self.assertEqual(
            [(r["product"], r["due"], r["delivered"], r["qty"], r["days"], r["penalty"], r["fine"])
             for r in rows],
            [("Дрон (тест санкцій)", date(2026, 3, 1), date(2026, 3, 11), 4.0, 10, 4000.0, 0.0),
             ("Дрон (тест санкцій)", date(2026, 4, 1), date(2026, 5, 11), 5.0, 40, 20000.0, 35000.0),
             ("Комплект ЗІП (тест санкцій)", date(2026, 5, 1), False, 2.0, 20, 2000.0, 0.0)])
        totals = self.contract.ua_penalty_totals(date(2026, 6, 10))
        self.assertEqual((totals["penalty"], totals["fine"]), (28000.0, 42000.0))

    def test_02_acts_after_the_date_do_not_count(self):
        rows = self.contract.ua_penalty_rows(date(2026, 3, 5))
        self.assertEqual([(r["qty"], r["delivered"], r["days"]) for r in rows],
                         [(4.0, False, 4)], "акт від 2026-03-11 ще не складено")
        self.assertFalse(self.contract.ua_penalty_rows(date(2026, 2, 28)))

    def test_03_rework_and_draft_acts_are_not_deliveries(self):
        act = self._act(date(2026, 5, 15), self.kit, 2.0)
        self.assertEqual(self.contract.ua_penalty_totals(date(2026, 5, 21))["penalty"], 26000.0)
        act.line_ids.result = "rework"
        act.action_done()
        self.assertEqual(self.contract.ua_penalty_totals(date(2026, 5, 21))["penalty"], 26000.0,
                         "на доопрацюванні - не поставлено")
        self._act(date(2026, 5, 16), self.kit, 2.0).action_done()
        rows = self.contract.ua_penalty_rows(date(2026, 5, 21))
        kit = [r for r in rows if r["product"].startswith("Комплект")]
        self.assertEqual([(r["delivered"], r["days"], r["penalty"]) for r in kit],
                         [(date(2026, 5, 16), 15, 1500.0)])

    def test_04_missing_price_and_print(self):
        self.contract.ua_schedule_ids.filtered(lambda s: s.product_id == self.kit).price_unit = 0.0
        totals = self.contract.ua_penalty_totals(date(2026, 5, 21))
        self.assertTrue(totals["no_price"])
        self.assertEqual(totals["penalty"], 24000.0)
        html, _kind = self.env["ir.actions.report"].with_context(
            ua_penalty_date="2026-06-10")._render_qweb_html(
            "l10n_ua_defense.report_ua_defense_penalty", self.contract.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("РОЗРАХУНОК ПЕНІ І ШТРАФУ", "ОК-9/2026", "10.06.2026", "20 000,00",
                         "35 000,00", "не поставлено", "(немає ціни)", "понад 30 днів"):
            self.assertIn(expected, text)
        plain = self.env["ua.contract"].create({
            "name": "Д-1 (тест)", "date": date(2026, 1, 1),
            "partner_id": self.contract.partner_id.id})
        with self.assertRaises(UserError):
            plain.action_print_penalty()
        self.assertEqual(plain.ua_penalty_amount, 0.0)
