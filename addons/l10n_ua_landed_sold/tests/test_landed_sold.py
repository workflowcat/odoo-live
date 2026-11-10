# -*- coding: utf-8 -*-
"""Додаткові витрати на вже продані товари.

10 моторів отримано по 100 грн, 4 продано. Доставка 500 грн: на залишок (6 шт.) 300 грн - на
запаси, на продані 4 шт. 200 грн - на собівартість реалізації, рахунок послуги закрито на 500.

Запуск: чиста база, тег ua_landed_sold.
"""
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "ua_landed_sold")
class TestUaLandedSold(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.company.inventory_valuation = "real_time"
        cls.company.cost_method = "average"
        cls.stock_account = cls.chart.ref("ua_psbp_201")
        cls.cogs = cls.chart.ref("ua_psbp_902")
        cls.category = cls.env["product.category"].with_company(cls.company).create({
            "name": "Товари (тест)", "property_valuation": "real_time", "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.stock_account.id,
            "property_account_expense_categ_id": cls.cogs.id})
        cls.motor = cls.env["product.product"].create({"name": "Мотор (тест витрат)", "is_storable": True,
                                                       "categ_id": cls.category.id})
        cls.service_account = cls.env["account.account"].create({
            "code": "68599", "name": "Доставка до розподілу (тест)", "account_type": "liability_current",
            "company_ids": [(6, 0, cls.company.ids)]})
        cls.delivery = cls.env["product.product"].create({"name": "Доставка (тест)", "type": "service",
                                                          "landed_cost_ok": True})
        cls.vendor = cls.env["res.partner"].create({"name": "Постачальник (тест витрат)"})
        cls.customer = cls.env["res.partner"].create({"name": "Покупець (тест витрат)"})
        cls.journal = cls.env["account.journal"].search([("type", "=", "general"),
                                                         ("company_id", "=", cls.company.id)], limit=1)

    def _receive(self):
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "order_line": [(0, 0, {"product_id": self.motor.id, "product_qty": 10, "price_unit": 100.0,
                                   "tax_ids": [(5, 0, 0)]})]})
        order.button_confirm()
        picking = order.picking_ids
        picking.move_ids.write({"quantity": 10, "picked": True})
        picking.button_validate()
        return picking

    def _deliver(self, quantity):
        stock = self.warehouse.lot_stock_id
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id, "partner_id": self.customer.id,
            "location_id": stock.id, "location_dest_id": customers.id,
            "move_ids": [(0, 0, {"product_id": self.motor.id, "product_uom_qty": quantity,
                                 "location_id": stock.id, "location_dest_id": customers.id})]})
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.write({"quantity": quantity, "picked": True})
        picking.button_validate()

    def _landed(self, receipt, sold_to_cogs=True):
        cost = self.env["stock.landed.cost"].create({
            "picking_ids": [(6, 0, receipt.ids)], "account_journal_id": self.journal.id,
            "ua_sold_to_cogs": sold_to_cogs,
            "cost_lines": [(0, 0, {"name": "Доставка", "product_id": self.delivery.id, "price_unit": 500.0,
                                   "split_method": "equal", "account_id": self.service_account.id})]})
        cost.compute_landed_cost()
        cost.button_validate()
        return cost

    @staticmethod
    def _balance(move, account):
        return round(sum(move.line_ids.filtered(lambda l: l.account_id == account).mapped("balance")), 2)

    def test_sold_share_to_cogs(self):
        receipt = self._receive()
        self._deliver(4)
        cost = self._landed(receipt)
        move = cost.account_move_id
        self.assertEqual(cost.state, "done")
        self.assertEqual(self._balance(move, self.stock_account), 300.0, "на залишок 6 з 10")
        self.assertEqual(self._balance(move, self.cogs), 200.0, "на продані 4 з 10")
        self.assertEqual(self._balance(move, self.service_account), -500.0, "рахунок послуги закрито повністю")

    def test_switch_off_keeps_native(self):
        receipt = self._receive()
        self._deliver(4)
        cost = self._landed(receipt, sold_to_cogs=False)
        move = cost.account_move_id
        self.assertEqual(self._balance(move, self.cogs), 0.0)
        self.assertEqual(self._balance(move, self.service_account), -300.0, "як в Odoo: лише залишок")

    def test_all_sold(self):
        receipt = self._receive()
        self._deliver(10)
        cost = self._landed(receipt)
        self.assertEqual(self._balance(cost.account_move_id, self.cogs), 500.0, "усе продано - усе на 902")
