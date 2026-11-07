# -*- coding: utf-8 -*-
"""Переробка давальницької сировини.

Сценарій: давалець передає 5 тепловізійних камер на 4 дрони (одна про запас). Рама - наша.
У нас на складі є ще 5 власних камер і 10 рам.

    прийом 5 камер давальця     -> місце давальця 5, наш склад камер 5, вартість запасів та сама
    виробництво 4 дронів         -> 4 камери з місця давальця, 4 рами зі складу; наші камери 5
    відвантаження 4 дронів       -> передано 4
    повернення залишку           -> 1 камера давальцю; залишок 0, замовлення можна завершити
    рахунок за переробку         -> 4 x 2 500 = 10 000 без ПДВ

Запуск: чиста база, теги ua_tolling.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005


@tagged("post_install", "-at_install", "ua_tolling")
class TestUaTolling(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.company.inventory_valuation = "real_time"
        cls.category = cls.env["product.category"].with_company(cls.company).create({
            "name": "Виробництво (тест)",
            "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.chart.ref("ua_psbp_201").id,
        })
        cls.drone = cls._product("Дрон-розвідник Т (тест)", 0.0)
        cls.camera = cls._product("Камера тепловізійна (тест)", 9000.0)
        cls.frame = cls._product("Рама 7 дюймів (тест)", 800.0)
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "company_id": cls.company.id,
            "bom_line_ids": [(0, 0, {"product_id": cls.camera.id, "product_qty": 1.0}),
                             (0, 0, {"product_id": cls.frame.id, "product_qty": 1.0})],
        })
        cls.customer = cls.env["res.partner"].create({"name": "Військова частина А0000 (тест)",
                                                      "company_registry": "00000000"})
        for product, quantity in ((cls.camera, 5.0), (cls.frame, 10.0)):
            quant = cls.env["stock.quant"].with_context(inventory_mode=True).create({
                "product_id": product.id, "location_id": cls.stock.id,
                "inventory_quantity": quantity})
            quant.action_apply_inventory()

    @classmethod
    def _product(cls, name, cost):
        return cls.env["product.product"].create({
            "name": name, "type": "consu", "is_storable": True,
            "categ_id": cls.category.id, "standard_price": cost})

    # --- службове -------------------------------------------------------

    def _order(self, quantity=4.0, cameras=5.0):
        order = self.env["ua.tolling.order"].create({
            "partner_id": self.customer.id, "product_id": self.drone.id,
            "product_qty": quantity, "price_unit": 2500.0, "warehouse_id": self.warehouse.id})
        order.action_fill_from_bom()
        order.line_ids.filtered(lambda l: l.product_id == self.frame).unlink()
        order.line_ids.product_qty = cameras
        order.action_confirm()
        return order

    def _validate(self, picking):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")

    def _on_hand(self, product, location, owner=None):
        quants = self.env["stock.quant"].search([("product_id", "=", product.id),
                                                 ("location_id", "=", location.id)])
        if owner is not None:
            quants = quants.filtered(lambda q: q.owner_id == owner)
        return sum(quants.mapped("quantity"))

    def _valuation(self):
        account = self.chart.ref("ua_psbp_201")
        return sum(self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("parent_state", "=", "posted")]).mapped("balance"))

    def _receive(self, order):
        picking = self.env["stock.picking"].browse(order.action_receive()["res_id"])
        self._validate(picking)
        return picking

    def _produce(self, order):
        production = self.env["mrp.production"].browse(order.action_produce()["res_id"])
        production.button_mark_done()
        self.assertEqual(production.state, "done")
        return production

    # --- 1. Повний цикл ---------------------------------------------------

    def test_01_full_cycle(self):
        order = self._order()
        self.assertEqual(order.line_ids.product_id, self.camera)
        location = order.location_id
        self.assertEqual(location.ua_tolling_partner_id, self.customer)
        self.assertFalse(location.parent_path.startswith(self.stock.parent_path),
                         "місце давальця не всередині складу")

        valuation = self._valuation()
        picking = self._receive(order)
        self.assertEqual(picking.owner_id, self.customer)
        self.assertAlmostEqual(self._on_hand(self.camera, location, self.customer), 5.0)
        self.assertAlmostEqual(self._on_hand(self.camera, self.stock), 5.0, msg="наші камери ті самі")
        self.assertAlmostEqual(self._valuation(), valuation, delta=CENT,
                               msg="сировина давальця не потрапляє у вартість запасів")

        production = self._produce(order)
        camera_moves = production.move_raw_ids.filtered(lambda m: m.product_id == self.camera)
        self.assertEqual(camera_moves.location_id, location)
        self.assertEqual(camera_moves.move_line_ids.owner_id, self.customer)
        self.assertEqual(production.move_raw_ids.filtered(
            lambda m: m.product_id == self.frame).location_id, self.stock)
        self.assertAlmostEqual(self._on_hand(self.camera, location), 1.0)
        self.assertAlmostEqual(self._on_hand(self.camera, self.stock), 5.0)
        self.assertAlmostEqual(self._on_hand(self.frame, self.stock), 6.0)
        order.invalidate_recordset()
        self.assertAlmostEqual(order.qty_produced, 4.0)

        rows = {row["product"]: row for row in order.material_rows()}
        camera = rows[self.camera]
        self.assertAlmostEqual(camera["received"], 5.0)
        self.assertAlmostEqual(camera["consumed"], 4.0)
        self.assertAlmostEqual(camera["norm"], 4.0)
        self.assertAlmostEqual(camera["deviation"], 0.0)
        self.assertAlmostEqual(camera["balance"], 1.0)

        with self.assertRaises(UserError):
            order.action_done()  # камера давальця ще в нас

        delivery = self.env["stock.picking"].browse(order.action_deliver()["res_id"])
        self._validate(delivery)
        back = self.env["stock.picking"].browse(order.action_return_materials()["res_id"])
        self.assertEqual(back.location_id, location)
        self._validate(back)
        order.invalidate_recordset()
        self.assertAlmostEqual(order.qty_delivered, 4.0)
        camera = {row["product"]: row for row in order.material_rows()}[self.camera]
        self.assertAlmostEqual(camera["returned"], 1.0)
        self.assertAlmostEqual(camera["balance"], 0.0)
        self.assertAlmostEqual(self._on_hand(self.camera, location), 0.0)

        invoice = self.env["account.move"].browse(order.action_invoice()["res_id"])
        self.assertEqual(invoice.partner_id, self.customer)
        self.assertAlmostEqual(invoice.amount_untaxed, 10000.0, delta=CENT)
        invoice.action_post()
        order.invalidate_recordset()
        self.assertAlmostEqual(order.qty_invoiced, 4.0)
        with self.assertRaises(UserError):
            order.action_invoice()

        order.action_done()
        self.assertEqual(order.state, "done")

        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_tolling.report_ua_tolling", order.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("ЗВІТ ПРО ПЕРЕРОБКУ ДАВАЛЬНИЦЬКОЇ СИРОВИНИ", "Камера тепловізійна (тест)",
                         self.customer.name, order.name):
            self.assertIn(expected, text)

    # --- 2. Своє виробництво не бере сировину давальця ----------------------

    def test_02_own_production_does_not_touch_customer_material(self):
        order = self._order()
        self._receive(order)
        production = self.env["mrp.production"].create({
            "product_id": self.drone.id, "product_qty": 5.0, "bom_id": self.bom.id,
            "company_id": self.company.id})
        production.action_confirm()
        production.action_assign()
        camera = production.move_raw_ids.filtered(lambda m: m.product_id == self.camera)
        self.assertEqual(camera.move_line_ids.location_id, self.stock)
        self.assertFalse(camera.move_line_ids.owner_id)
        self.assertAlmostEqual(sum(camera.move_line_ids.mapped("quantity")), 5.0)

    def test_03_overconsumption_shows_as_deviation(self):
        order = self._order(quantity=2.0, cameras=3.0)
        self._receive(order)
        production = self.env["mrp.production"].browse(order.action_produce()["res_id"])
        production.qty_producing = 2.0
        production._set_qty_producing()
        camera = production.move_raw_ids.filtered(lambda m: m.product_id == self.camera)
        camera.quantity = 3.0
        camera.picked = True
        result = production.button_mark_done()
        if production.state != "done":
            # Перевитрата відкриває майстер - підтверджуємо її.
            wizard = self.env[result["res_model"]].with_context(result["context"]).create({})
            wizard.action_confirm()
        self.assertEqual(production.state, "done")
        row = {r["product"]: r for r in order.material_rows()}[self.camera]
        self.assertAlmostEqual(row["norm"], 2.0)
        self.assertAlmostEqual(row["consumed"], 3.0)
        self.assertAlmostEqual(row["deviation"], 1.0)
        self.assertAlmostEqual(row["balance"], 0.0)

    # --- 3. Межі ----------------------------------------------------------

    def test_04_nothing_to_receive_twice(self):
        order = self._order()
        order.action_receive()
        with self.assertRaises(UserError):
            order.action_receive()  # перший прихід ще чекає

    def test_05_cancel_only_without_movement(self):
        order = self._order()
        order.action_receive()
        order.action_cancel()
        self.assertEqual(order.state, "cancel")
        self.assertEqual(order.picking_ids.state, "cancel")
        other = self._order()
        self._receive(other)
        with self.assertRaises(UserError):
            other.action_cancel()

    def test_06_one_location_per_customer(self):
        first, second = self._order(), self._order()
        self.assertEqual(first.location_id, second.location_id)
        other = self.env["res.partner"].create({"name": "Інший давалець (тест)"})
        third = self.env["ua.tolling.order"].create({
            "partner_id": other.id, "product_id": self.drone.id, "product_qty": 1.0,
            "warehouse_id": self.warehouse.id,
            "line_ids": [(0, 0, {"product_id": self.camera.id, "product_qty": 1.0})]})
        third.action_confirm()
        self.assertNotEqual(third.location_id, first.location_id)

    def test_07_draft_needs_materials(self):
        order = self.env["ua.tolling.order"].create({
            "partner_id": self.customer.id, "product_id": self.drone.id, "product_qty": 1.0,
            "warehouse_id": self.warehouse.id})
        self.assertTrue(order.name.startswith("ДС/"))
        self.assertEqual(order.bom_id, self.bom)
        with self.assertRaises(UserError):
            order.action_confirm()
