# -*- coding: utf-8 -*-
"""Погоджені постачальники: замовлення і приймання критичних комплектуючих.

Мікроконтролер у категорії «Електроніка / Мікроконтролери (тест)» - критичний, болт - ні.
Постачальник А погоджений на всю «Електроніку», Б - ні. Замовлення Б з мікроконтролером не
підтверджується, з болтом - так. А - підтверджується (підкатегорія входить). Погодження А
призупинили після рекламацій - приймання від А не проводиться, відновили - проводиться.
Приймання від Б без замовлення - відмова. Строки, нагадування, друк переліку.

Запуск: тег ua_supplier_approval.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_supplier_approval")
class TestUaSupplierApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["product.category"]
        cls.electronics = Category.create({"name": "Електроніка (тест)"})
        cls.mcu_categ = Category.create({"name": "Мікроконтролери (тест)", "parent_id": cls.electronics.id})
        Product = cls.env["product.product"]
        cls.mcu = Product.create({"name": "Мікроконтролер 32-біт (тест)", "type": "consu", "is_storable": True,
                                  "categ_id": cls.mcu_categ.id, "ua_approved_only": True})
        cls.bolt = Product.create({"name": "Болт М4 (тест)", "type": "consu", "is_storable": True})
        Partner = cls.env["res.partner"]
        cls.vendor_a = Partner.create({"name": "ТОВ Компоненти А (тест)", "is_company": True})
        cls.vendor_b = Partner.create({"name": "ТОВ Компоненти Б (тест)", "is_company": True})
        cls.today = fields.Date.context_today(cls.env.user)
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.env.company.id)], limit=1)

    def _order(self, vendor, rows):
        return self.env["purchase.order"].create({"partner_id": vendor.id, "order_line": [
            (0, 0, {"product_id": product.id, "product_qty": quantity, "price_unit": 100.0, "tax_ids": [(5, 0, 0)]})
            for product, quantity in rows]})

    def _approval(self, **vals):
        approval = self.env["ua.supplier.approval"].create(dict({
            "name": "ПП-1 (тест)", "partner_id": self.vendor_a.id, "scope": "categories",
            "categ_ids": [(6, 0, self.electronics.ids)], "approved_by": "Служба якості (тест)",
            "basis": "Акт аудиту № 7 (тест)", "date_approved": self.today - timedelta(days=30)}, **vals))
        approval.action_approve()
        return approval

    def _receive(self, picking):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()

    def test_01_orders_and_receipts(self):
        order_b = self._order(self.vendor_b, [(self.mcu, 10)])
        self.assertTrue(order_b.order_line.ua_supplier_unapproved)
        with self.assertRaises(UserError, msg="Б не погоджений"):
            order_b.button_confirm()
        bolts = self._order(self.vendor_b, [(self.bolt, 100)])
        bolts.button_confirm()
        self.assertEqual(bolts.state, "purchase", "некритичний товар - без погодження")

        approval = self._approval()
        order_a = self._order(self.vendor_a, [(self.mcu, 10)])
        self.assertFalse(order_a.order_line.ua_supplier_unapproved, "підкатегорія входить у погоджену")
        order_a.button_confirm()
        self.assertEqual(order_a.state, "purchase")

        approval.action_suspend("рекламації на партію (тест)")
        self.assertEqual((approval.state, approval.reason), ("suspended", "рекламації на партію (тест)"))
        receipt = order_a.picking_ids
        with self.assertRaises(UserError, msg="призупинене погодження не діє"):
            self._receive(receipt)
        approval.action_approve()
        self._receive(receipt)
        self.assertEqual(receipt.state, "done")

        direct = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.in_type_id.id, "partner_id": self.vendor_b.id,
            "location_id": self.env.ref("stock.stock_location_suppliers").id,
            "location_dest_id": self.warehouse.lot_stock_id.id,
            "move_ids": [(0, 0, {"product_id": self.mcu.id, "product_uom_qty": 5.0,
                                 "location_id": self.env.ref("stock.stock_location_suppliers").id,
                                 "location_dest_id": self.warehouse.lot_stock_id.id})]})
        direct.action_confirm()
        with self.assertRaises(UserError, msg="приймання від непогодженого"):
            self._receive(direct)

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_supplier_approval.report_ua_supplier_approval", approval.ids)[0].decode()
        for text in ("ПЕРЕЛІК ПОГОДЖЕНИХ ПОСТАЧАЛЬНИКІВ", "ТОВ Компоненти А (тест)", "Електроніка (тест)",
                     "Акт аудиту № 7 (тест)", "безстроково", "Погоджено"):
            self.assertIn(text, html)

    def test_02_terms_and_guards(self):
        approval = self._approval(scope="products", product_tmpl_ids=[(6, 0, self.mcu.product_tmpl_id.ids)],
                                  date_until=self.today + timedelta(days=10))
        old = self._approval(name="ПП-0 (тест)", partner_id=self.vendor_b.id,
                             date_approved=self.today - timedelta(days=400), date_until=self.today + timedelta(days=1))
        old.date_until = self.today - timedelta(days=1)
        Approval = self.env["ua.supplier.approval"]
        Approval._cron_reminders()
        Approval._cron_reminders()
        self.assertEqual(old.state, "expired")
        self.assertEqual(len(approval.activity_ids), 1, "нагадування одне")
        with self.assertRaises(UserError, msg="строк минув"):
            old.action_approve()
        self.assertFalse(Approval.ua_find(self.vendor_b, self.mcu, self.env.company, self.today))
        self.assertEqual(Approval.ua_find(self.vendor_a, self.mcu, self.env.company, self.today), approval)
        self.assertFalse(Approval.ua_find(self.vendor_a, self.mcu, self.env.company, self.today + timedelta(days=11)))
        approval.action_withdraw("постачальник припинив виробництво (тест)")
        self.assertEqual(approval.state, "withdrawn")
        self.assertFalse(approval.activity_ids)
        with self.assertRaises(UserError):
            approval.action_suspend()

        with self.assertRaises(ValidationError, msg="товари не обрано"):
            Approval.create({"name": "ПП-X", "partner_id": self.vendor_a.id, "scope": "products"})
        with self.assertRaises(ValidationError):
            Approval.create({"name": "ПП-Y", "partner_id": self.vendor_a.id, "scope": "all",
                             "date_approved": self.today, "date_until": self.today - timedelta(days=1)})
