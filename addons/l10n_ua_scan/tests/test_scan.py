# -*- coding: utf-8 -*-
"""Сканер на складі і у виробництві: що додає кожен скан.

Відвантаження 4 моторів і 2 камер із серійними номерами: перший скан мотора скидає резерв і
рахує з одиниці, серійний номер ставиться в рядок один раз. Замовлення на 2 дрони (4 мотори і
рама на дрон): скан дрона - +1 до випуску і компоненти за специфікацією, скан рами - +1 до її
витрати. Вікно «Сканування» знаходить документ за номером.

Запуск: чиста база, тег ua_scan.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_scan")
class TestUaScan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")
        Product = cls.env["product.product"]
        cls.motor = Product.create({"name": "Мотор (тест скану)", "is_storable": True, "barcode": "4829900000011"})
        cls.frame = Product.create({"name": "Рама (тест скану)", "is_storable": True, "default_code": "RAMA-T1"})
        cls.camera = Product.create({"name": "Камера (тест скану)", "is_storable": True, "tracking": "serial"})
        cls.drone = Product.create({"name": "Дрон (тест скану)", "is_storable": True, "barcode": "4829900000028"})
        cls.lots = cls.env["stock.lot"].create([{"name": "CAM-T-%s" % n, "product_id": cls.camera.id}
                                                for n in (1, 2, 3)])
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.motor, cls.stock, 20.0)
        Quant._update_available_quantity(cls.frame, cls.stock, 5.0)
        for lot in cls.lots:
            Quant._update_available_quantity(cls.camera, cls.stock, 1.0, lot_id=lot)

    def _delivery(self):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id, "location_id": self.stock.id,
            "location_dest_id": self.customers.id,
            "move_ids": [(0, 0, {"product_id": product.id, "product_uom_qty": qty, "location_id": self.stock.id,
                                 "location_dest_id": self.customers.id})
                         for product, qty in ((self.motor, 4.0), (self.camera, 2.0))]})
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _move(self, picking, product):
        return picking.move_ids.filtered(lambda m: m.product_id == product)

    def test_picking_scan(self):
        picking = self._delivery()
        motor = self._move(picking, self.motor)
        self.assertEqual(motor.quantity, 4.0, "резерв")
        self.assertIsNone(picking._ua_scan("4829900000011"))
        self.assertEqual((motor.quantity, motor.picked), (1.0, True), "перший скан рахує з одиниці, не з резерву")
        picking._ua_scan("4829900000011")
        self.assertEqual(motor.quantity, 2.0)

        self.assertIn("warning", picking._ua_scan("RAMA-T1"), "рами немає в документі")
        self.assertIn("warning", picking.on_barcode_scanned("NO-SUCH-CODE"), "невідомий код - попередження")

        camera = self._move(picking, self.camera)
        self.assertIsNone(picking._ua_scan("CAM-T-3"))
        self.assertEqual(camera.move_line_ids.lot_id, self.lots[2], "резерв інших номерів знято")
        self.assertIn("warning", picking._ua_scan("CAM-T-3"), "серійний номер - один раз")
        picking._ua_scan("CAM-T-1")
        self.assertEqual(camera.move_line_ids.lot_id, self.lots[0] | self.lots[2])
        self.assertEqual(camera.quantity, 2.0)

        for _ in range(2):
            picking._ua_scan("4829900000011")
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(motor.quantity, 4.0)
        self.assertIn("warning", picking._ua_scan("4829900000011"), "закритий документ")

    def test_tracked_product_needs_lot(self):
        picking = self._delivery()
        self.assertIsNone(picking._ua_scan("  "), "порожній скан нічого не робить")
        self.camera.barcode = "4829900000035"
        warning = picking._ua_scan("4829900000035")
        self.assertIn("серійний номер", warning["warning"]["message"])

    def test_production_scan(self):
        self.env["mrp.bom"].create({
            "product_tmpl_id": self.drone.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": self.motor.id, "product_qty": 4.0}),
                             (0, 0, {"product_id": self.frame.id, "product_qty": 1.0})]})
        production = self.env["mrp.production"].create({"product_id": self.drone.id, "product_qty": 2.0})
        self.assertIn("warning", production._ua_scan("4829900000028"), "чернетка")
        production.action_confirm()
        self.assertIsNone(production._ua_scan("4829900000028"))
        self.assertEqual(production.qty_producing, 1.0)
        raw = {m.product_id: m for m in production.move_raw_ids}
        self.assertEqual((raw[self.motor].quantity, raw[self.frame].quantity), (4.0, 1.0),
                         "компоненти за специфікацією на один дрон")
        self.assertIsNone(production._ua_scan("RAMA-T1"))
        self.assertEqual(raw[self.frame].quantity, 2.0, "скан компонента - +1 до витрати")
        self.assertTrue(raw[self.frame].manual_consumption)
        self.assertIn("warning", production._ua_scan("CAM-T-1"), "камери немає у специфікації")

    def test_find_document_by_number(self):
        picking = self._delivery()
        wizard = self.env["ua.scan.start"].create({})
        wizard._ua_find(picking.name)
        self.assertEqual(wizard.picking_id, picking)
        action = wizard.action_open()
        self.assertEqual((action["res_model"], action["res_id"]), ("stock.picking", picking.id))
        wizard._ua_find("4829900000011")
        self.assertFalse(wizard.picking_id)
        self.assertIn("Мотор", wizard.message)
