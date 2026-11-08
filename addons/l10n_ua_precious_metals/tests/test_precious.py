# -*- coding: utf-8 -*-
"""Дорогоцінні метали: вміст за специфікаціями, паспорт, відомість руху.

Резистор - Ag 0,0005 г, роз'єм - Au 0,012 г (довідкові дані). Плата: специфікація на 2 шт. -
40 резисторів і 8 роз'ємів, плюс власний паладій 0,002 г (покриття). На одну плату:
Ag 0,01, Au 0,048, Pd 0,002. Виріб: 2 плати і рама без металів - Ag 0,02, Au 0,096, Pd 0,004.

Рухи: надійшло 100 роз'ємів (Au 1,2), відвантажено 1 виріб (Au 0,096), списано 1 плату
(Au 0,048). На складі: 100 роз'ємів, 2 вироби, 4 плати - Au 1,2 + 0,192 + 0,192 = 1,584.

Запуск: тег ua_precious.
"""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_precious")
class TestUaPrecious(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.au = cls.env.ref("l10n_ua_precious_metals.metal_au")
        cls.ag = cls.env.ref("l10n_ua_precious_metals.metal_ag")
        cls.pd = cls.env.ref("l10n_ua_precious_metals.metal_pd")
        Product = cls.env["product.product"]

        def product(name, metals=(), **vals):
            return Product.create(dict({
                "name": name, "type": "consu", "is_storable": True,
                "ua_precious_ids": [(0, 0, {"metal_id": metal.id, "grams": grams, "source": "довідкові дані (тест)"})
                                    for metal, grams in metals]}, **vals))

        cls.resistor = product("Резистор 0603 (тест)", [(cls.ag, 0.0005)])
        cls.connector = product("Роз'єм позолочений (тест)", [(cls.au, 0.012)])
        cls.board = product("Плата керування (тест)", [(cls.pd, 0.002)])
        cls.frame = product("Рама (тест)")
        cls.drone = product("БпЛА розвідувальний (тест)")
        Bom = cls.env["mrp.bom"]
        Bom.create({"product_tmpl_id": cls.board.product_tmpl_id.id, "product_qty": 2.0, "bom_line_ids": [
            (0, 0, {"product_id": cls.resistor.id, "product_qty": 40.0}),
            (0, 0, {"product_id": cls.connector.id, "product_qty": 8.0})]})
        Bom.create({"product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "bom_line_ids": [
            (0, 0, {"product_id": cls.board.id, "product_qty": 2.0}),
            (0, 0, {"product_id": cls.frame.id, "product_qty": 1.0})]})
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.today = fields.Date.context_today(cls.env.user)

    def _rounded(self, content):
        return {metal.code: round(grams, 6) for metal, grams in content.items()}

    def _transfer(self, picking_type, source, dest, rows, partner=None):
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id, "location_id": source.id, "location_dest_id": dest.id,
            "partner_id": partner.id if partner else False,
            "move_ids": [(0, 0, {"product_id": product.id, "product_uom_qty": quantity,
                                 "location_id": source.id, "location_dest_id": dest.id})
                         for product, quantity in rows]})
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        return picking

    def test_01_content_through_boms(self):
        self.assertEqual(self._rounded(self.board.ua_precious_content()), {"Ag": 0.01, "Au": 0.048, "Pd": 0.002})
        self.assertEqual(self._rounded(self.drone.ua_precious_content()), {"Ag": 0.02, "Au": 0.096, "Pd": 0.004})
        self.assertEqual(self._rounded(self.drone.ua_precious_content(5)), {"Ag": 0.1, "Au": 0.48, "Pd": 0.02})
        self.assertEqual(self.frame.ua_precious_content(), {})
        self.drone.product_tmpl_id.invalidate_recordset(["ua_precious_summary"])
        self.assertEqual(self.drone.product_tmpl_id.ua_precious_summary, "Au 0,096 г; Ag 0,02 г; Pd 0,004 г")
        rows = self.drone.ua_precious_rows()
        self.assertEqual([(row["code"], row["grams"]) for row in rows], [("Au", "0,096"), ("Ag", "0,02"), ("Pd", "0,004")])

        lot = self.env["stock.lot"].create({"name": "SN-0001 (тест)", "product_id": self.drone.id})
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_defense.report_ua_product_passport", lot.ids)[0].decode()
        for text in ("ПАСПОРТ ВИРОБУ", "Відомості про вміст дорогоцінних металів", "Золото", "0,096", "Паладій"):
            self.assertIn(text, html)
        plain = self.env["stock.lot"].create({"name": "SN-R (тест)", "product_id": self.frame.id})
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_defense.report_ua_product_passport", plain.ids)[0].decode()
        self.assertNotIn("дорогоцінних металів", html, "без металів розділу немає")

    def test_02_movement_report(self):
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(self.board, self.stock, 5)
        Quant._update_available_quantity(self.drone, self.stock, 3)
        vendor = self.env["res.partner"].create({"name": "ТОВ Компоненти (тест)"})
        customer = self.env["res.partner"].create({"name": "Замовник (тест)"})
        self._transfer(self.warehouse.in_type_id, self.env.ref("stock.stock_location_suppliers"), self.stock,
                       [(self.connector, 100)], vendor)
        self._transfer(self.warehouse.out_type_id, self.stock, self.env.ref("stock.stock_location_customers"),
                       [(self.drone, 1)], customer)
        scrap = self.env["stock.scrap"].create({"product_id": self.board.id, "scrap_qty": 1.0,
                                                "location_id": self.stock.id})
        scrap.action_validate()
        self.assertEqual(scrap.state, "done")

        report = self.env["ua.precious.report"].create({"date_from": self.today, "date_to": self.today})
        rows = {row["code"]: row for row in report.ua_rows()}
        self.assertEqual(list(rows), ["Au", "Ag", "Pd"])
        gold = rows["Au"]
        self.assertEqual((gold["received"], gold["shipped"], gold["written_off"], gold["on_hand"]),
                         ("1,2", "0,096", "0,048", "1,584"))
        self.assertEqual((gold["consumed"], gold["produced"]), ("0", "0"))
        self.assertEqual(rows["Pd"]["on_hand"], "0,016", "4 плати і 2 вироби: 0,008 + 0,008")

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_precious_metals.report_ua_precious", report.ids)[0].decode()
        for text in ("ВІДОМІСТЬ НАДХОДЖЕННЯ І ВИКОРИСТАННЯ ДОРОГОЦІННИХ МЕТАЛІВ", "Золото (Au)", "1,584",
                     "Надійшло від постачальників"):
            self.assertIn(text, html)

    def test_03_guards(self):
        with self.assertRaises(ValidationError):
            self.frame.product_tmpl_id.ua_precious_ids = [(0, 0, {"metal_id": self.au.id, "grams": 0.0})]
        with self.assertRaises(ValidationError):
            self.env["ua.precious.report"].create({"date_from": self.today, "date_to": self.today.replace(year=2000)})
        with self.assertRaises(UserError):
            self.drone.ua_precious_content(_path=(self.drone.id,))
