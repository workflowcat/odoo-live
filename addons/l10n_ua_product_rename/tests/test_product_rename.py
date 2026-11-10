# -*- coding: utf-8 -*-
"""Акт зміни найменування: назва, одиниця без руху, переведення запасу на нову картку.

Дріт у метрах: 100 м на складі по 5 грн. Облік переходить у кілограми, 0,2 кг в метрі: нова картка
«Дріт (кг)», 20 кг по 25 грн, на старій картці нуль, вона в архіві.

Запуск: чиста база, тег ua_product_rename.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_product_rename")
class TestUaProductRename(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.stock = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1).lot_stock_id
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.meter = cls.env.ref("uom.product_uom_meter")
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        Product = cls.env["product.product"]
        cls.bolt = Product.create({"name": "Болт М8 (тест)", "is_storable": True})
        cls.tape = Product.create({"name": "Стрічка (тест)", "is_storable": True, "uom_id": cls.unit.id})
        cls.wire = Product.create({"name": "Дріт (тест)", "is_storable": True, "uom_id": cls.meter.id,
                                   "standard_price": 5.0})
        cls.env["stock.quant"]._update_available_quantity(cls.wire, cls.stock, 100.0)
        cls.Act = cls.env["ua.product.rename"]

    def _act(self, *rows):
        return self.Act.create({"reason": "Тест", "line_ids": [(0, 0, row) for row in rows]})

    def test_rename_and_uom_without_moves(self):
        act = self._act({"product_id": self.bolt.id, "new_name": "Болт М8х40 оцинкований (тест)"},
                        {"product_id": self.tape.id, "new_uom_id": self.meter.id})
        self.assertTrue(act.name.startswith("АЗН-"))
        act.action_done()
        bolt, tape = act.line_ids
        self.assertEqual(self.bolt.name, "Болт М8х40 оцинкований (тест)")
        self.assertEqual((bolt.mode, bolt.old_name), ("rename", "Болт М8 (тест)"))
        self.assertEqual((tape.mode, self.tape.uom_id), ("uom", self.meter), "руху не було - одиниця в картці")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_product_rename.action_report_ua_product_rename", act.ids)[0].decode()
        self.assertIn("Болт М8 (тест)", html)

    def test_convert_stock_to_new_uom(self):
        act = self._act({"product_id": self.wire.id, "new_name": "Дріт (кг) (тест)", "new_uom_id": self.kg.id,
                         "factor": 0.2})
        act.action_done()
        line = act.line_ids
        new = line.new_product_id
        self.assertEqual(line.mode, "convert")
        self.assertEqual((new.name, new.uom_id), ("Дріт (кг) (тест)", self.kg))
        self.assertEqual((line.quantity_old, line.quantity_new), (100.0, 20.0))
        self.assertAlmostEqual(new.standard_price, 25.0, places=4, msg="вартість запасу та сама: 100 × 5 = 20 × 25")
        Quant = self.env["stock.quant"]
        self.assertEqual(Quant._get_available_quantity(new, self.stock), 20.0)
        self.assertEqual(Quant._get_available_quantity(self.wire, self.stock), 0.0)
        self.assertFalse(self.wire.product_tmpl_id.active, "стара картка в архіві")

    def test_guards(self):
        with self.assertRaises(UserError):
            self._act({"product_id": self.bolt.id}).action_done()
        act = self._act({"product_id": self.wire.id, "new_uom_id": self.kg.id, "factor": 0.2})
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env["stock.warehouse"].search([], limit=1).out_type_id.id,
            "location_id": self.stock.id, "location_dest_id": customers.id,
            "move_ids": [(0, 0, {"product_id": self.wire.id, "product_uom_qty": 10.0, "location_id": self.stock.id,
                                 "location_dest_id": customers.id})]})
        picking.action_confirm()
        picking.action_assign()
        with self.assertRaises(UserError, msg="резерв у відвантаженні"):
            act.action_done()
