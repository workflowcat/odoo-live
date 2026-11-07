# -*- coding: utf-8 -*-
"""Багаторівневе планування від графіка оборонного контракту.

Дрон = рама (купуємо) + камера (купуємо) + 4 мотори (купуємо). Залишків немає.
Графік контракту: 10 дронів через 30 днів, 5 - через 60. За контрактом уже є
підтверджене замовлення на 4 дрони (відкрите відвантаження).

MRP бачить попит: 4 із замовлення (як завжди) + 6 і 5 з графіка (10 - 4 покрито, 5).
Разом 15 дронів до виготовлення, 60 моторів, 15 камер і 15 рам до закупівлі.
Закритий контракт попиту не дає.

Запуск: чиста база, тег ua_mrp_plan.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_mrp_plan")
class TestUaMrpPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.area = cls.env["mrp.area"].create({
            "name": "Склад виробництва (тест)", "warehouse_id": cls.warehouse.id,
            "location_id": cls.warehouse.lot_stock_id.id, "ua_defense_demand": True})
        cls.vendor = cls.env["res.partner"].create({"name": "Постачальник комплектуючих (тест)"})
        manufacture = cls.env.ref("mrp.route_warehouse0_manufacture")
        buy = cls.env.ref("purchase_stock.route_warehouse0_buy")
        cls.drone = cls._product("Дрон-розвідник MRP (тест)", manufacture)
        cls.frame = cls._product("Рама MRP (тест)", buy)
        cls.camera = cls._product("Камера MRP (тест)", buy)
        cls.motor = cls._product("Мотор MRP (тест)", buy)
        cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "bom_line_ids": [(0, 0, {"product_id": p.id, "product_qty": q})
                             for p, q in ((cls.frame, 1.0), (cls.camera, 1.0), (cls.motor, 4.0))]})
        cls.customer = cls.env["res.partner"].create({"name": "Державний замовник MRP (тест)",
                                                      "is_company": True})
        today = fields.Date.context_today(cls.env["mrp.area"])
        cls.contract = cls.env["ua.contract"].create({
            "name": "ОК-MRP/2026", "date": today, "partner_id": cls.customer.id,
            "ua_defense": True, "ua_customer_kind": "dot",
            "ua_schedule_ids": [
                (0, 0, {"product_id": cls.drone.id, "quantity": 10.0, "date": today + timedelta(days=30)}),
                (0, 0, {"product_id": cls.drone.id, "quantity": 5.0, "date": today + timedelta(days=60)}),
            ]})
        order = cls.env["sale.order"].create({
            "partner_id": cls.customer.id, "ua_contract_id": cls.contract.id,
            "order_line": [(0, 0, {"product_id": cls.drone.id, "product_uom_qty": 4.0,
                                   "price_unit": 100000.0, "tax_ids": [(5, 0, 0)]})]})
        order.action_confirm()
        cls.order = order

    @classmethod
    def _product(cls, name, route):
        product = cls.env["product.product"].create({
            "name": name, "type": "consu", "is_storable": True,
            "route_ids": [(6, 0, route.ids)]})
        if route == cls.env.ref("purchase_stock.route_warehouse0_buy"):
            cls.env["product.supplierinfo"].create({
                "partner_id": cls.vendor.id, "product_tmpl_id": product.product_tmpl_id.id,
                "price": 100.0, "delay": 5})
        cls.env["product.mrp.area"].create({"product_id": product.id, "mrp_area_id": cls.area.id})
        return product

    def _run(self):
        self.env["mrp.multi.level"].create({"mrp_area_ids": [(6, 0, self.area.ids)]}).run_mrp_multi_level()

    def _planned(self, product):
        return sum(self.env["mrp.planned.order"].search([
            ("product_mrp_area_id.product_id", "=", product.id),
            ("product_mrp_area_id.mrp_area_id", "=", self.area.id)]).mapped("mrp_qty"))

    def test_01_schedule_drives_all_levels(self):
        self.assertEqual(self.order.ua_contract_id, self.contract)
        rows = self.env["ua.defense.schedule"].ua_open_demand(self.drone, self.company)
        self.assertEqual([qty for _date, qty, _contract in rows], [6.0, 5.0])

        self._run()
        forecast = self.env["mrp.move"].search([
            ("product_id", "=", self.drone.id), ("mrp_area_id", "=", self.area.id),
            ("mrp_origin", "=", "fc")], order="mrp_date")
        self.assertEqual(forecast.mapped("mrp_qty"), [-6.0, -5.0])
        self.assertEqual(set(forecast.mapped("mrp_order_number")), {"ОК-MRP/2026"})
        self.assertEqual(self._planned(self.drone), 15.0)
        self.assertEqual(self._planned(self.motor), 60.0)
        self.assertEqual((self._planned(self.camera), self._planned(self.frame)), (15.0, 15.0))

    def test_02_closed_contract_and_other_area(self):
        other = self.env["mrp.area"].create({
            "name": "Інша зона (тест)", "warehouse_id": self.warehouse.id,
            "location_id": self.warehouse.lot_stock_id.id})
        self.env["product.mrp.area"].create({"product_id": self.drone.id, "mrp_area_id": other.id})
        self.env["mrp.multi.level"].create({"mrp_area_ids": [(6, 0, other.ids)]}).run_mrp_multi_level()
        self.assertFalse(self.env["mrp.move"].search([
            ("mrp_area_id", "=", other.id), ("mrp_origin", "=", "fc")]),
            "графік планується лише в одній зоні компанії")

        self.contract.state = "closed"
        self._run()
        self.assertFalse(self.env["mrp.move"].search([
            ("product_id", "=", self.drone.id), ("mrp_area_id", "=", self.area.id),
            ("mrp_origin", "=", "fc")]))
        self.assertEqual(self._planned(self.drone), 4.0, "лишилось тільки замовлення")
