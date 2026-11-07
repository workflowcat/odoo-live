# -*- coding: utf-8 -*-
"""Передача виробів військовій частині: благодійник оплатив, частина отримала; безоплатно.

Дрон-розвідник з камерою, серійний облік, ціна 100 000, собівартість 60 000. На складі
три номери UT-001...UT-003. Фонд купує два, відвантаження - на військову частину А0000
(умовна, тестова). Акт із відвантаження бере номери і ціну з замовлення.

Запуск: чиста база, тег ua_unit_transfer.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_unit_transfer")
class TestUaUnitTransfer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Partner = cls.env["res.partner"]
        cls.fund = Partner.create({"name": "БФ Крила (тест)", "is_company": True,
                                   "company_registry": "44445555"})
        cls.unit = Partner.create({"name": "Військова частина (тест)", "is_company": True,
                                   "ua_unit": True, "ua_unit_number": "А0000"})
        cls.drone = cls.env["product.product"].create({
            "name": "Дрон-розвідник з камерою (тест)", "is_storable": True, "tracking": "serial",
            "list_price": 100000.0, "standard_price": 60000.0})
        cls.stock = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1).lot_stock_id
        cls.lots = cls.env["stock.lot"].create([
            {"name": "UT-00%s" % n, "product_id": cls.drone.id, "company_id": cls.company.id}
            for n in (1, 2, 3)])
        for lot in cls.lots:
            cls.env["stock.quant"]._update_available_quantity(cls.drone, cls.stock, 1.0, lot_id=lot)

    def _sale_delivery(self, qty=2.0):
        order = self.env["sale.order"].create({
            "partner_id": self.fund.id, "partner_shipping_id": self.unit.id,
            "order_line": [(0, 0, {"product_id": self.drone.id, "product_uom_qty": qty,
                                   "price_unit": 100000.0, "tax_ids": [(5, 0, 0)]})]})
        order.action_confirm()
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        return order, picking

    def test_01_fund_pays_unit_receives(self):
        order, picking = self._sale_delivery()
        action = picking.action_ua_unit_transfer()
        transfer = self.env["ua.unit.transfer"].browse(action["res_id"])
        self.assertEqual((transfer.kind, transfer.donor_id, transfer.unit_id, transfer.sale_id),
                         ("fund", self.fund, self.unit, order))
        line = transfer.line_ids
        self.assertEqual((line.product_id, line.quantity, line.price_unit, transfer.amount_total),
                         (self.drone, 2.0, 100000.0, 200000.0))
        self.assertEqual(len(line.lot_ids), 2)
        self.assertEqual(picking.action_ua_unit_transfer()["res_id"], transfer.id,
                         "друге натискання відкриває той самий акт")
        transfer.receiver = "командир взводу, лейтенант Тестовий Т. Т."
        transfer.action_done()
        self.assertEqual(line.lot_ids.ua_unit_id, self.unit)
        self.assertEqual(self.unit.ua_unit_transfer_count, 1)

        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_unit_transfer.report_ua_unit_transfer", transfer.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("АКТ ПРИЙМАННЯ-ПЕРЕДАЧІ", transfer.name, "БФ Крила (тест)", "А0000",
                         "200 000,00", "Благодійник", line.lot_names()):
            self.assertIn(expected, text)
        if transfer.currency_id.name == "UAH":
            self.assertIn("Двісті тисяч гривень", text)
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_defense.report_ua_product_passport", line.lot_ids[:1].ids)
        passport = html.decode() if isinstance(html, bytes) else html
        self.assertIn("Передано військовій частині", passport)
        self.assertIn(transfer.name, passport)

    def test_02_donation_and_serial_guards(self):
        transfer = self.env["ua.unit.transfer"].create({
            "kind": "donation", "unit_id": self.unit.id,
            "line_ids": [(0, 0, {"product_id": self.drone.id, "quantity": 2.0,
                                 "price_unit": self.drone.standard_price,
                                 "lot_ids": [(6, 0, self.lots[:1].ids)]})]})
        with self.assertRaises(UserError):
            transfer.action_done()  # два вироби, один номер
        transfer.line_ids.lot_ids = [(6, 0, self.lots[:2].ids)]
        transfer.action_done()
        self.assertEqual(transfer.amount_total, 120000.0)

        again = self.env["ua.unit.transfer"].create({
            "kind": "donation", "unit_id": self.unit.id,
            "line_ids": [(0, 0, {"product_id": self.drone.id, "quantity": 1.0,
                                 "lot_ids": [(6, 0, self.lots[1:2].ids)]})]})
        with self.assertRaises(UserError):
            again.action_done()  # UT-002 уже передано
        transfer.action_cancel()
        self.assertFalse(self.lots[1].ua_unit_transfer_id)
        again.action_done()
        self.assertEqual(self.lots[1].ua_unit_transfer_id, again)
        with self.assertRaises(UserError):
            again.unlink()

    def test_03_parties(self):
        civil = self.env["res.partner"].create({"name": "Звичайна компанія (тест)", "is_company": True})
        with self.assertRaises(ValidationError):
            self.env["ua.unit.transfer"].create({"kind": "donation", "unit_id": civil.id})
        with self.assertRaises(ValidationError):
            self.env["ua.unit.transfer"].create({"kind": "donation", "unit_id": self.unit.id,
                                                 "donor_id": self.fund.id})
        transfer = self.env["ua.unit.transfer"].create({
            "kind": "fund", "unit_id": self.unit.id,
            "line_ids": [(0, 0, {"product_id": self.drone.id, "quantity": 1.0,
                                 "lot_ids": [(6, 0, self.lots[2:].ids)]})]})
        with self.assertRaises(UserError):
            transfer.action_done()  # немає благодійника
        transfer.donor_id = self.fund
        transfer.action_done()
        self.assertEqual(transfer.state, "done")
