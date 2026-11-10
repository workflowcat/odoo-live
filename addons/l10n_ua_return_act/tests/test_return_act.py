# -*- coding: utf-8 -*-
"""Акт невідповідності при поверненні: документ проти фактично прийнятого.

Покупець повертає 5 моторів по 1 000 грн і камеру за 3 000 грн; кредит-нота - на все. На склад
прийшло 4 мотори і камера з розбитим об'єктивом. Акт з кредит-ноти і прийомки: мотор - нестача
1 шт., -1 000 грн; камера - кількість збігається, невідповідність «Пошкодження» ставлять рукою.

Запуск: чиста база, тег ua_return_act.
"""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_return_act")
class TestUaReturnAct(TransactionCase):

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
        cls.income = cls.env["account.account"].search(
            [("code", "=like", "70%"), ("company_ids", "in", cls.company.id)], limit=1, order="code")
        cls.buyer = cls.env["res.partner"].create({"name": "ТОВ Покупець повернення (тест)", "is_company": True})
        Product = cls.env["product.product"]
        cls.motor = Product.create({"name": "Мотор (тест повернення)", "is_storable": True})
        cls.camera = Product.create({"name": "Камера (тест повернення)", "is_storable": True, "tracking": "serial"})
        cls.lot = cls.env["stock.lot"].create({"name": "CAM-R-1", "product_id": cls.camera.id})
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)

    def _refund(self):
        refund = self.env["account.move"].create({
            "move_type": "out_refund", "partner_id": self.buyer.id, "invoice_date": "2026-11-10",
            "invoice_line_ids": [
                Command.create({"product_id": product.id, "quantity": qty, "price_unit": price,
                                "tax_ids": [Command.clear()], "account_id": self.income.id})
                for product, qty, price in ((self.motor, 5.0, 1000.0), (self.camera, 1.0, 3000.0))]})
        refund.action_post()
        return refund

    def _receipt(self):
        customers = self.env.ref("stock.stock_location_customers")
        stock = self.warehouse.lot_stock_id
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.in_type_id.id, "partner_id": self.buyer.id,
            "location_id": customers.id, "location_dest_id": stock.id,
            "move_ids": [Command.create({"product_id": product.id, "product_uom_qty": qty,
                                         "location_id": customers.id, "location_dest_id": stock.id})
                         for product, qty in ((self.motor, 5.0), (self.camera, 1.0))]})
        picking.action_confirm()
        moves = {m.product_id: m for m in picking.move_ids}
        moves[self.motor].quantity = 4.0
        moves[self.camera].quantity = 1.0
        moves[self.camera].move_line_ids.lot_id = self.lot
        return picking

    def test_01_act_from_refund_and_receipt(self):
        refund = self._refund()
        picking = self._receipt()
        action = refund.action_ua_return_act()
        act = self.env["ua.return.act"].browse(action["res_id"])
        self.assertTrue(act.name.startswith("АН-"))
        self.assertEqual((act.partner_id, act.refund_id), (self.buyer, refund))
        lines = {line.product_id: line for line in act.line_ids}
        self.assertEqual((lines[self.motor].qty_doc, lines[self.motor].price_unit), (5.0, 1000.0))
        self.assertEqual(lines[self.motor].qty_received, 5.0, "без прийомки фактично = за документом")

        act.picking_id = picking
        act.action_fill()
        lines = {line.product_id: line for line in act.line_ids}
        motor, camera = lines[self.motor], lines[self.camera]
        self.assertEqual((motor.qty_doc, motor.qty_received, motor.qty_diff), (5.0, 4.0, -1.0))
        self.assertEqual((motor.issue, motor.amount_diff), ("shortage", -1000.0))
        self.assertEqual((camera.issue, camera.lot_names), ("none", "CAM-R-1"))
        self.assertEqual((act.amount_doc, act.amount_received, act.amount_diff), (8000.0, 7000.0, -1000.0))

        camera.write({"issue": "damage", "description": "Розбитий об'єктив", "decision": "repair"})
        manual = self.env["ua.return.act.line"].create({
            "act_id": act.id, "product_id": self.motor.id, "qty_received": 1.0, "issue": "wrong",
            "description": "Мотор іншої моделі в коробці"})
        act.action_fill()
        self.assertIn(manual, act.line_ids, "«Перезаповнити» не чіпає рядки, вписані рукою")
        self.assertEqual(len(act.line_ids), 3)
        camera = act.line_ids.filtered(lambda l: l.auto and l.product_id == self.camera)
        self.assertEqual((camera.issue, camera.decision, camera.description),
                         ("damage", "repair", "Розбитий об'єктив"), "позначки рукою пережили перезаповнення")

        act.action_done()
        self.assertEqual(act.state, "done")
        with self.assertRaises(UserError):
            manual.qty_received = 2.0
        for source in (refund, picking):
            self.assertTrue(any(act.name in (m.body or "") for m in source.message_ids), "запис у документі")
        self.assertEqual((refund.ua_return_act_count, picking.ua_return_act_count), (1, 1))
        self.assertEqual(picking.action_ua_return_act()["res_id"], act.id, "наявний акт, не новий")

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_return_act.report_ua_return_act", act.ids)[0].decode()
        for text in (act.name, "Нестача", "Пошкодження", "-1000.00", "Представник покупця", "CAM-R-1"):
            self.assertIn(text, html)

    def test_02_guards(self):
        refund = self._refund()
        act = self.env["ua.return.act"].create({"partner_id": self.buyer.id})
        with self.assertRaises(UserError, msg="без джерела не заповнити"):
            act.action_fill()
        act.refund_id = refund
        act.action_fill()
        with self.assertRaises(UserError, msg="усе відповідає - акт не потрібен"):
            act.action_done()
        invoice = self.env["account.move"].create({"move_type": "out_invoice", "partner_id": self.buyer.id})
        with self.assertRaises(UserError):
            invoice.action_ua_return_act()
        delivery = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id, "partner_id": self.buyer.id})
        with self.assertRaises(UserError):
            delivery.action_ua_return_act()
