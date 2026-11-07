# -*- coding: utf-8 -*-
"""Комісійна торгівля в обидва боки. Без ПДВ, щоб суми були круглі.

1. Компанія комісіонер, 10 %: комітент дає 10 павербанків; покупцю продано 4 по 1 500.
   Звіт: 6 000, винагорода 600; рахунок від комітента 6 000, рахунок комітенту 600,
   взаємозалік 600 - комітенту лишається 5 400. Скасування повертає все; 6 штук - назад.
2. Компанія комітент, 5 %: 6 тепловізорів передано дилеру; він продав 4 по 2 000.
   Звіт: 8 000, винагорода 400; рахунок дилеру 8 000, рахунок від дилера 400, залік 400 -
   дилер винен 7 600. У дилера лишилось 2; продати 5 не можна.
3. Компанія комісіонер, ціна комітента 1 000: продано 2 по 1 500. Рахунок від комітента
   2 000, без винагороди і заліку; виручка 3 000 видна у звіті.

Запуск: чиста база, тег ua_commission.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_commission")
class TestUaCommission(TransactionCase):

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
        cls.company.write({"account_sale_tax_id": False, "account_purchase_tax_id": False})
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        Partner = cls.env["res.partner"]
        cls.consignor = Partner.create({"name": "ФОП Комітент (тест)", "company_registry": "1234567890"})
        cls.dealer = Partner.create({"name": "ТОВ Дилер (тест)", "is_company": True,
                                     "company_registry": "55556666"})
        cls.buyer = Partner.create({"name": "Покупець (тест)"})
        cls.powerbank = cls._product("Павербанк 20000 (тест)", 1500.0)
        cls.imager = cls._product("Тепловізійний монокуляр (тест)", 2000.0)
        quant = cls.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": cls.imager.id, "location_id": cls.stock.id, "inventory_quantity": 10.0})
        quant.action_apply_inventory()
        cls.Agreement = cls.env["ua.commission.agreement"]

    @classmethod
    def _product(cls, name, price):
        return cls.env["product.product"].create({
            "name": name, "type": "consu", "is_storable": True, "list_price": price,
            "taxes_id": [(5, 0, 0)], "supplier_taxes_id": [(5, 0, 0)]})

    def _validate(self, picking):
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        return picking

    def _on_hand(self, product, location, owner=None):
        quants = self.env["stock.quant"].search([("product_id", "=", product.id),
                                                 ("location_id", "=", location.id)])
        if owner is not None:
            quants = quants.filtered(lambda q: q.owner_id == owner)
        return sum(quants.mapped("quantity"))

    def _agreement(self, role, partner, product, price, qty, **values):
        agreement = self.Agreement.create(dict({
            "role": role, "partner_id": partner.id, "warehouse_id": self.warehouse.id,
            "line_ids": [(0, 0, {"product_id": product.id, "price_unit": price, "product_qty": qty})],
        }, **values))
        agreement.action_open()
        self._validate(self.env["stock.picking"].browse(agreement.action_transfer()["res_id"]))
        return agreement

    def _sell(self, product, qty, price):
        order = self.env["sale.order"].create({
            "partner_id": self.buyer.id,
            "order_line": [(0, 0, {"product_id": product.id, "product_uom_qty": qty,
                                   "price_unit": price, "tax_ids": [(5, 0, 0)]})]})
        order.action_confirm()
        picking = order.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        return picking

    def _render(self, report):
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_commission.report_ua_commission", report.ids)
        return html.decode() if isinstance(html, bytes) else html

    def test_01_company_sells_consigned_goods(self):
        agreement = self._agreement("in", self.consignor, self.powerbank, 1000.0, 10.0,
                                    pricing="percent", commission_percent=10.0)
        self.assertEqual(self._on_hand(self.powerbank, self.stock, self.consignor), 10.0)
        self.assertEqual(agreement.balance_rows()[0]["quantity"], 10.0)

        picking = self._sell(self.powerbank, 4.0, 1500.0)
        self.assertEqual(picking.move_line_ids.owner_id, self.consignor, "продано чужий товар")
        report = self.env["ua.commission.report"].browse(agreement.action_new_report()["res_id"])
        line = report.line_ids
        self.assertEqual((line.product_id, line.quantity, line.price_unit, line.amount, line.commission),
                         (self.powerbank, 4.0, 1500.0, 6000.0, 600.0))
        self.assertEqual((report.amount_due, report.sale_total), (5400.0, 6000.0))

        report.action_done()
        bill = report.invoice_ids.filtered(lambda m: m.move_type == "in_invoice")
        fee = report.invoice_ids.filtered(lambda m: m.move_type == "out_invoice")
        self.assertEqual((bill.partner_id, bill.amount_total, bill.state),
                         (self.consignor, 6000.0, "posted"))
        income = self.powerbank.product_tmpl_id.get_product_accounts()["income"]
        if income:
            self.assertEqual(bill.invoice_line_ids.account_id, income,
                             "виручка комітента згортає дохід від чужого товару")
        self.assertEqual((fee.amount_total, fee.amount_residual), (600.0, 0.0))
        self.assertEqual(bill.amount_residual, 5400.0, "комітенту - виручка мінус винагорода")
        self.assertEqual(report.offset_id.amount, 600.0)
        self.assertEqual(picking.move_line_ids.ua_commission_report_id, report)

        text = self._render(report)
        for expected in ("ЗВІТ КОМІСІОНЕРА", report.name, "ФОП Комітент (тест)", "6 000,00",
                         "600,00", "5 400,00", "10%"):
            self.assertIn(expected, text)

        again = self.env["ua.commission.report"].browse(agreement.action_new_report()["res_id"])
        self.assertFalse(again.line_ids, "продане вже у звіті")
        with self.assertRaises(UserError):
            again.action_fill()
        with self.assertRaises(UserError):
            agreement.action_close()  # ще лежить 6 штук і є чернетка

        report.action_cancel()
        self.assertEqual((report.state, bill.state, fee.state), ("cancel", "cancel", "cancel"))
        self.assertFalse(picking.move_line_ids.ua_commission_report_id)
        again.action_fill()
        self.assertEqual(again.line_ids.quantity, 4.0)
        again.unlink()

        back = self.env["stock.picking"].browse(agreement.action_return()["res_id"])
        self.assertEqual(back.move_ids.product_uom_qty, 6.0)
        self._validate(back)
        self.assertEqual(self._on_hand(self.powerbank, self.stock, self.consignor), 0.0)
        report.unlink()
        agreement.action_close()
        self.assertEqual(agreement.state, "closed")

    def test_02_company_goods_at_dealer(self):
        agreement = self._agreement("out", self.dealer, self.imager, 2000.0, 6.0,
                                    pricing="percent", commission_percent=5.0)
        location = agreement.location_id
        self.assertEqual(location.ua_commission_partner_id, self.dealer)
        self.assertEqual((self._on_hand(self.imager, location), self._on_hand(self.imager, self.stock)),
                         (6.0, 4.0))

        Report = self.env["ua.commission.report"]
        report = Report.create({
            "agreement_id": agreement.id, "date_from": agreement.date, "date_to": agreement.date,
            "partner_ref": "17", "line_ids": [(0, 0, {
                "product_id": self.imager.id, "quantity": 4.0, "price_unit": 2000.0})]})
        report.action_done()
        self.assertEqual(report.picking_id.state, "done")
        self.assertEqual(self._on_hand(self.imager, location), 2.0)
        invoice = report.invoice_ids.filtered(lambda m: m.move_type == "out_invoice")
        fee = report.invoice_ids.filtered(lambda m: m.move_type == "in_invoice")
        self.assertEqual((invoice.partner_id, invoice.amount_total), (self.dealer, 8000.0))
        self.assertEqual((fee.amount_total, fee.ref), (400.0, "17"))
        self.assertEqual((invoice.amount_residual, fee.amount_residual), (7600.0, 0.0))
        text = self._render(report)
        for expected in ("ЗВІТ КОМІСІОНЕРА № 17", "ТОВ Дилер (тест)", "8 000,00", "400,00"):
            self.assertIn(expected, text)

        too_much = Report.create({
            "agreement_id": agreement.id, "date_from": agreement.date, "date_to": agreement.date,
            "line_ids": [(0, 0, {"product_id": self.imager.id, "quantity": 5.0, "price_unit": 2000.0})]})
        with self.assertRaises(UserError):
            too_much.action_done()  # у дилера лише 2

        report.action_cancel()
        self.assertEqual(self._on_hand(self.imager, location), 6.0, "скасоване повернулось дилеру")
        self.assertEqual(invoice.state, "cancel")
        self._validate(self.env["stock.picking"].browse(agreement.action_return()["res_id"]))
        self.assertEqual((self._on_hand(self.imager, location), self._on_hand(self.imager, self.stock)),
                         (0.0, 10.0))

    def test_03_consignor_price(self):
        agreement = self._agreement("in", self.consignor, self.powerbank, 1000.0, 5.0, pricing="price")
        self._sell(self.powerbank, 2.0, 1500.0)
        report = self.env["ua.commission.report"].browse(agreement.action_new_report()["res_id"])
        line = report.line_ids
        self.assertEqual((line.quantity, line.price_unit, line.amount, line.commission, line.sale_amount),
                         (2.0, 1000.0, 2000.0, 0.0, 3000.0))
        report.action_done()
        self.assertEqual(report.invoice_ids.mapped("move_type"), ["in_invoice"])
        self.assertEqual(report.invoice_ids.amount_total, 2000.0)
        self.assertFalse(report.offset_id)
        self.assertNotIn("Винагорода комісіонера", self._render(report))
