# -*- coding: utf-8 -*-
"""Лімітно-забірна картка: відпуск у межах ліміту, понад ліміт, повернення, ліміт із замовлень, друк.

Пластина алюмінієва, на складі 500 кг. Цех 1 - окреме місце зберігання. Ліміт 120 кг на місяць.
Відпуск 50 і 60 - залишок ліміту 10. Ще 20 без причини - відмова; комірник без прав керівника -
відмова; керівник з причиною - відпущено, понад ліміт 20. Повернення 5 - відпущено 125.
У цеху 125, на складі 375. Ліміт із замовлень: корпус потребує 2 кг, замовлення на 30 - ліміт 60.

Запуск: тег ua_limit_card.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install", "ua_limit_card")
class TestUaLimitCard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.plate = cls.env["product.product"].create({
            "name": "Пластина алюмінієва (тест)", "type": "consu", "is_storable": True, "default_code": "АЛ-3",
            "uom_id": cls.kg.id})
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.shop = cls.env["stock.location"].create({"name": "Цех 1 (тест)", "usage": "internal",
                                                     "location_id": cls.warehouse.view_location_id.id})
        cls.env["stock.quant"]._update_available_quantity(cls.plate, cls.stock, 500)
        cls.today = fields.Date.context_today(cls.env.user)

    def _card(self, **vals):
        return self.env["ua.limit.card"].create(dict({
            "product_id": self.plate.id, "location_id": self.stock.id, "location_dest_id": self.shop.id,
            "department": "Механічний цех (тест)", "purpose": "Рами виробів (тест)"}, **vals))

    def _qty(self, location):
        return self.plate.with_context(location=location.id).qty_available

    def test_01_issue_within_and_over_limit(self):
        card = self._card(limit_qty=120.0)
        self.assertTrue(card.name.startswith("ЛЗК/"))
        with self.assertRaises(UserError, msg="чернетка не відпускає"):
            card.action_issue(10.0)
        card.action_open()
        card.action_issue(50.0, receiver="Петренко (тест)")
        card.action_issue(60.0)
        self.assertEqual((card.issued_qty, card.remaining_qty, card.over_qty), (110.0, 10.0, 0.0))

        with self.assertRaises(UserError, msg="понад ліміт без причини"):
            card.action_issue(20.0)
        keeper = new_test_user(self.env, login="keeper_test", groups="stock.group_stock_user")
        with self.assertRaises(UserError, msg="комірник не дозволяє понад ліміт"):
            card.with_user(keeper).action_issue(20.0, reason="брак партії (тест)")
        line = card.action_issue(20.0, reason="брак партії (тест)")
        self.assertTrue(line.over_limit)
        self.assertEqual((card.issued_qty, card.remaining_qty, card.over_qty), (130.0, -10.0, 20.0))

        card.action_return(5.0)
        self.assertEqual(card.issued_qty, 125.0)
        with self.assertRaises(UserError, msg="повернути більше відпущеного"):
            card.action_return(500.0)
        self.assertEqual(self._qty(self.shop), 125.0)
        self.assertEqual(self._qty(self.stock), 375.0)
        self.assertEqual(set(card.line_ids.move_id.mapped("reference")), {card.name})

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_limit_card.report_ua_limit_card", card.ids)[0].decode()
        for text in ("ЛІМІТНО-ЗАБІРНА КАРТКА", "Типова форма № М-8", card.name, "Пластина алюмінієва (тест)",
                     "АЛ-3", "120", "брак партії (тест)", "Петренко (тест)", "125"):
            self.assertIn(text, html)

        card.action_close()
        with self.assertRaises(UserError, msg="закрита картка не відпускає"):
            card.action_issue(1.0)
        with self.assertRaises(UserError):
            card.unlink()

    def test_02_limit_from_productions_and_guards(self):
        body = self.env["product.product"].create({"name": "Корпус (тест)", "type": "consu"})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": body.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": self.plate.id, "product_qty": 2.0})]})
        production = self.env["mrp.production"].create({"product_id": body.id, "product_qty": 30.0,
                                                          "bom_id": bom.id})
        production.action_confirm()
        card = self._card(production_ids=[(6, 0, production.ids)])
        card.action_fill_from_productions()
        self.assertEqual(card.limit_qty, 60.0)

        empty = self._card()
        with self.assertRaises(UserError, msg="ліміт не задано"):
            empty.action_open()
        with self.assertRaises(UserError, msg="замовлень не обрано"):
            empty.action_fill_from_productions()
        with self.assertRaises(ValidationError):
            self._card(location_dest_id=self.stock.id)
        with self.assertRaises(ValidationError):
            self._card(limit_qty=-1.0)
        card.action_open()
        with self.assertRaises(UserError, msg="поза місяцем картки"):
            card.action_issue(1.0, day=card.date_from - timedelta(days=1))
        with self.assertRaises(UserError, msg="на складі менше"):
            card.action_issue(1000.0, reason="тест", day=self.today)
