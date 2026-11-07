# -*- coding: utf-8 -*-
"""Подорожні листи і списання ПММ.

Фургон AA0000AA, дизель за 50 грн/л (на складі 100 л), базова норма 10 л/100 км,
списання в межах норми - 92, понад норму - 949. Зимова надбавка 10 % (обирається вручну).

Лист 1: спідометр 1000 -> 1250 (250 км), зима. Норма 10 * 2,5 * 1,1 = 27,5 л.
    Бак порожній, заправлено зі складу 40 л, при поверненні 10 л: фактично 30 л,
    понад норму 2,5 л. Дт 92 - 27,5 * 50 = 1 375, Дт 949 - 2,5 * 50 = 125.
Лист 2: 1250 -> 1350, норма 10 л; при виїзді 10 л, при поверненні 2 л - фактично 8, економія 2.

Запуск: чиста база, тег ua_fleet.
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_fleet")
class TestUaWaybill(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        cls.company.invalidate_recordset()
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.company.inventory_valuation = "real_time"
        category = cls.env["product.category"].with_company(cls.company).create({
            "name": "ПММ (тест)", "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.chart.ref("ua_psbp_201").id})
        cls.diesel = cls.env["product.product"].create({
            "name": "Дизельне паливо (тест)", "type": "consu", "is_storable": True,
            "categ_id": category.id, "standard_price": 50.0,
            "uom_id": cls.env.ref("uom.product_uom_litre").id})
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        quant = cls.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": cls.diesel.id, "location_id": cls.stock.id, "inventory_quantity": 100.0})
        quant.action_apply_inventory()

        cls.expense = cls.chart.ref("ua_psbp_92")
        cls.overnorm = cls.chart.ref("ua_psbp_949")
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Марка (тест)"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Фургон (тест)", "brand_id": brand.id})
        cls.driver = cls.env["res.partner"].create({"name": "Водій Тестовий"})
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": model.id, "license_plate": "AA0000AA", "driver_id": cls.driver.id,
            "ua_fuel_product_id": cls.diesel.id, "ua_norm_base": 10.0,
            "ua_warehouse_id": cls.warehouse.id, "ua_expense_account_id": cls.expense.id,
            "ua_overnorm_account_id": cls.overnorm.id})
        Adjustment = cls.env["ua.fuel.norm.adjustment"]
        cls.winter = Adjustment.create({"name": "Зима (тест)", "percent": 10.0})
        cls.Waybill = cls.env["ua.waybill"]

    def _balance(self, account):
        return sum(self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("parent_state", "=", "posted")]).mapped("balance"))

    def _on_hand(self, location):
        return sum(self.env["stock.quant"].search([
            ("product_id", "=", self.diesel.id), ("location_id", "=", location.id)]).mapped("quantity"))

    def _first_trip(self):
        waybill = self.Waybill.create({
            "vehicle_id": self.vehicle.id, "odometer_start": 1000.0,
            "route": "Київ - Житомир - Київ", "purpose": "доставка комплектуючих",
            "adjustment_ids": [(6, 0, self.winter.ids)],
            "refuel_ids": [(0, 0, {"source": "stock", "quantity": 40.0})]})
        waybill.action_open()
        waybill.write({"odometer_end": 1250.0, "fuel_end": 10.0})
        return waybill

    def test_01_norm_overrun_economy_and_cancel(self):
        expense, overnorm = self._balance(self.expense), self._balance(self.overnorm)
        first = self._first_trip()
        self.assertEqual(first.driver_id, self.driver)
        self.assertEqual((first.fuel_start, first.distance, first.adjustment_pct), (0.0, 250.0, 10.0))
        self.assertEqual((first.fuel_norm, first.fuel_actual, first.fuel_over, first.fuel_saved),
                         (27.5, 30.0, 2.5, 0.0))
        first.action_done()
        tank = self.vehicle.ua_tank_location_id
        self.assertEqual((self._on_hand(tank), self._on_hand(self.stock)), (10.0, 60.0))
        self.assertEqual(self.vehicle.odometer, 1250.0)
        self.assertAlmostEqual(self._balance(self.expense) - expense, 1375.0, places=2)
        self.assertAlmostEqual(self._balance(self.overnorm) - overnorm, 125.0, places=2)

        second = self.Waybill.create({"vehicle_id": self.vehicle.id})
        self.assertEqual(second.odometer_start, 1250.0, "спідометр з попереднього листа")
        second.action_open()
        self.assertEqual(second.fuel_start, 10.0, "залишок у баку з попереднього листа")
        second.write({"odometer_end": 1350.0, "fuel_end": 2.0})
        self.assertEqual((second.fuel_norm, second.fuel_actual, second.fuel_saved, second.fuel_over),
                         (10.0, 8.0, 2.0, 0.0))
        second.action_done()
        self.assertEqual(self._on_hand(tank), 2.0)
        self.assertAlmostEqual(self._balance(self.expense) - expense, 1775.0, places=2)

        with self.assertRaises(UserError):
            first.action_cancel()  # спершу скасовують пізніший лист
        second.action_cancel()
        self.assertEqual(self._on_hand(tank), 10.0)
        self.assertEqual(self.vehicle.odometer, 1250.0)
        self.assertAlmostEqual(self._balance(self.expense) - expense, 1375.0, places=2)
        first.action_cancel()
        self.assertEqual((self._on_hand(tank), self._on_hand(self.stock)), (0.0, 100.0))
        self.assertAlmostEqual(self._balance(self.overnorm) - overnorm, 0.0, places=2)
        first.action_reset_draft()
        self.assertEqual(first.state, "draft")

    def test_02_adjustments_work_and_guards(self):
        Adjustment = self.env["ua.fuel.norm.adjustment"]
        month = fields.Date.context_today(self.Waybill).month
        city = Adjustment.create({"name": "Місто (тест)", "percent": 5.0,
                                  "month_from": "1", "month_to": "12"})
        other = str(month % 12 + 1)
        Adjustment.create({"name": "Не цей місяць (тест)", "percent": 50.0,
                           "month_from": other, "month_to": other})
        self.vehicle.write({"ua_norm_cargo": 2.0, "ua_norm_hour": 3.0})
        waybill = self.Waybill.create({"vehicle_id": self.vehicle.id, "odometer_start": 2000.0})
        self.assertEqual(waybill.adjustment_ids, city, "діє само лише коригування цього місяця")
        waybill.adjustment_ids = [(4, self.winter.id)]
        waybill.write({"cargo_tkm": 500.0, "engine_hours": 2.0, "refuel_ids": [(0, 0, {
            "source": "vendor", "quantity": 30.0, "price_unit": 52.0, "reference": "чек 15"})]})
        waybill.action_open()
        busy = self.Waybill.create({"vehicle_id": self.vehicle.id, "odometer_start": 2000.0})
        with self.assertRaises(UserError):
            busy.action_open()  # авто вже в рейсі
        with self.assertRaises(UserError):
            waybill.unlink()

        waybill.write({"odometer_end": 1990.0, "fuel_end": 0.1})
        with self.assertRaises(UserError):
            waybill.action_done()  # спідометр назад
        waybill.write({"odometer_end": 2100.0, "fuel_end": 50.0})
        with self.assertRaises(UserError):
            waybill.action_done()  # у баку більше, ніж було і заправлено
        waybill.fuel_end = 0.1
        # (10 * 100 / 100 + 2 * 500 / 100 + 3 * 2) * 1,15 = 29,9
        self.assertEqual((waybill.fuel_norm, waybill.fuel_actual, waybill.fuel_over), (29.9, 29.9, 0.0))
        waybill.action_done()
        self.assertAlmostEqual(self.vehicle.ua_fuel_in_tank, 0.1, places=2)
        self.assertEqual(self._on_hand(self.stock), 100.0, "заправка на АЗС склад не чіпає")

        low = self.Waybill.create({"vehicle_id": self.vehicle.id, "odometer_start": 1500.0})
        with self.assertRaises(UserError):
            low.action_open()  # спідометр менший за останній відомий

    def test_03_print(self):
        waybill = self._first_trip()
        waybill.action_done()
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_fleet.report_ua_waybill", waybill.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("ПОДОРОЖНІЙ ЛИСТ", waybill.name, "AA0000AA", "Водій Тестовий",
                         "Київ - Житомир - Київ", "27,50", "30,00", "2,50", "Зима (тест) 10%"):
            self.assertIn(expected, text)
