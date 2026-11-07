# -*- coding: utf-8 -*-
"""Погоджені аналоги: заміна відсутніх компонентів і завершення замовлення без зауважень.

Дрон = камера А ×1 + мотор ×4 + довгий кабель ×1.
Аналоги: камера А -> камера Б (погоджено), камера В (не погоджено);
довгий кабель -> два коротких (коефіцієнт 2, погоджено).
Залишки: камера А 3, камера Б 2, камера В 10, мотори 100, довгих кабелів 0, коротких 20.

Замовлення на 6 дронів: камер бракує 3 - дві покриває камера Б, камера В не йде (не погоджена),
одна лишається в нестачі; довгі кабелі повністю замінено 12 короткими.

Запуск: чиста база, тег ua_mrp_substitute.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install", "ua_mrp_substitute")
class TestUaMrpSubstitute(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.stock = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1).lot_stock_id
        Product = cls.env["product.product"]

        def product(name):
            return Product.create({"name": name, "type": "consu", "is_storable": True})

        cls.drone = product("Дрон з аналогами (тест)")
        cls.camera_a = product("Камера А (тест)")
        cls.camera_b = product("Камера Б (тест)")
        cls.camera_c = product("Камера В (тест)")
        cls.motor = product("Мотор аналоги (тест)")
        cls.cable_long = product("Кабель довгий (тест)")
        cls.cable_short = product("Кабель короткий (тест)")
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "consumption": "warning",
            "bom_line_ids": [(0, 0, {"product_id": p.id, "product_qty": q}) for p, q in (
                (cls.camera_a, 1.0), (cls.motor, 4.0), (cls.cable_long, 1.0))]})
        line = {l.product_id: l for l in cls.bom.bom_line_ids}
        Sub = cls.env["ua.bom.substitute"]
        cls.sub_b = Sub.create({"bom_line_id": line[cls.camera_a].id, "product_id": cls.camera_b.id,
                                "sequence": 1, "approval_ref": "ПЗ-7/2026"})
        cls.sub_c = Sub.create({"bom_line_id": line[cls.camera_a].id, "product_id": cls.camera_c.id,
                                "sequence": 2})
        cls.sub_cable = Sub.create({"bom_line_id": line[cls.cable_long].id,
                                    "product_id": cls.cable_short.id, "factor": 2.0,
                                    "approval_ref": "ПЗ-8/2026"})
        cls.manager = new_test_user(cls.env, login="sub_manager", groups="mrp.group_mrp_manager",
                                    company_id=cls.company.id, company_ids=[(6, 0, cls.company.ids)])
        cls.worker = new_test_user(cls.env, login="sub_worker", groups="mrp.group_mrp_user",
                                   company_id=cls.company.id, company_ids=[(6, 0, cls.company.ids)])
        (cls.sub_b | cls.sub_cable).with_user(cls.manager).action_approve()
        Quant = cls.env["stock.quant"]
        for prod, qty in ((cls.camera_a, 3), (cls.camera_b, 2), (cls.camera_c, 10),
                          (cls.motor, 100), (cls.cable_short, 20)):
            Quant._update_available_quantity(prod, cls.stock, qty)

    def _mo(self, qty):
        production = self.env["mrp.production"].create({
            "product_id": self.drone.id, "product_qty": qty, "bom_id": self.bom.id})
        production.action_confirm()
        production.action_assign()
        return production

    @staticmethod
    def _raw(production, product):
        return production.move_raw_ids.filtered(lambda m: m.product_id == product)

    def test_01_substitute_and_finish(self):
        production = self._mo(6.0)
        self.assertEqual(self._raw(production, self.camera_a).quantity, 3.0)

        production.action_ua_substitute()
        camera_a, camera_b = self._raw(production, self.camera_a), self._raw(production, self.camera_b)
        self.assertEqual(camera_a.product_uom_qty, 4.0, "потреба в камері А зменшилась на покрите")
        self.assertEqual((camera_b.product_uom_qty, camera_b.quantity), (2.0, 2.0))
        self.assertEqual(camera_b.ua_substitute_of_id, self.camera_a)
        self.assertEqual(camera_b.ua_substitute_id, self.sub_b)
        self.assertFalse(self._raw(production, self.camera_c), "непогоджений аналог не йде")
        self.assertEqual(self._raw(production, self.cable_long).state, "cancel",
                         "довгий кабель повністю замінено")
        cable_short = self._raw(production, self.cable_short)
        self.assertEqual((cable_short.product_uom_qty, cable_short.quantity), (12.0, 12.0))
        self.assertEqual(self._raw(production, self.motor).product_uom_qty, 24.0, "мотори не чіпаємо")
        self.assertIn("ПЗ-7/2026", production.message_ids[:1].body)

        with self.assertRaises(UserError, msg="аналогів на складі більше немає"):
            production.action_ua_substitute()

        self.env["stock.quant"]._update_available_quantity(self.camera_a, self.stock, 1)
        production.action_assign()
        result = production.button_mark_done()
        self.assertEqual(production.state, "done",
                         "погоджена заміна не дає зауважень щодо споживання: %s" % (result,))
        consumed = {m.product_id: m.quantity for m in production.move_raw_ids if m.state == "done"}
        self.assertEqual(consumed.get(self.camera_a), 4.0)
        self.assertEqual(consumed.get(self.camera_b), 2.0)
        self.assertEqual(consumed.get(self.cable_short), 12.0)

    def test_02_approval_rules(self):
        with self.assertRaises(UserError):
            self.sub_c.with_user(self.worker).action_approve()
        with self.assertRaises(UserError, msg="без підстави не погоджують"):
            self.sub_c.with_user(self.manager).action_approve()
        with self.assertRaises(UserError):
            self.sub_c.write({"approved_by": self.manager.id})
        self.assertTrue(self.sub_b.approved)
        self.sub_b.factor = 1.5
        self.assertFalse(self.sub_b.approved, "зміна коефіцієнта знімає погодження")
        with self.assertRaises(ValidationError):
            self.sub_b.factor = 0.0
        with self.assertRaises(ValidationError):
            self.sub_b.product_id = self.camera_a
        copy = self.bom.copy()
        self.assertEqual(copy.ua_substitute_count, 3)
        self.assertFalse(copy.bom_line_ids.ua_substitute_ids.filtered("approved"),
                         "нова редакція специфікації погоджується заново")
        self.sub_cable.with_user(self.manager).action_revoke()
        self.assertFalse(self.sub_cable.approved)

    def test_03_nothing_to_replace(self):
        self.env["stock.quant"]._update_available_quantity(self.camera_a, self.stock, 10)
        self.env["stock.quant"]._update_available_quantity(self.cable_long, self.stock, 10)
        production = self._mo(2.0)
        with self.assertRaises(UserError):
            production.action_ua_substitute()
