# -*- coding: utf-8 -*-
"""Митна декларація на імпорт: мито в собівартість, ПДВ у кредит, 3771 на повну суму.

Приклад, порахований руками (курс 40 грн за долар):

    двигуни: 10 шт по 25 $  = 250 $  -> митна вартість 10 000, мито 10 %   = 1 000
    камери:   5 шт по 100 $ = 500 $  -> митна вартість 20 000, мито 0 %    =     0
    збори 1 500 за митною вартістю: двигуни 10 000 / 30 000 * 1 500 = 500, камери 1 000
    ПДВ: двигуни (10 000 + 1 000) * 20 % = 2 200, камери 20 000 * 20 % = 4 000, разом 6 200
    у собівартість: 1 000 + 1 500 = 2 500 (двигуни 1 500, камери 1 000)
    3771 кредит: 2 500 + 6 200 = 8 700

Запуск: чиста база, теги ua_customs.
"""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tools import mute_logger

CENT = 0.005


@tagged("post_install", "-at_install", "ua_customs")
class TestUaCustoms(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.company.inventory_valuation = "real_time"
        cls.company.cost_method = "average"
        cls.category = cls.env["product.category"].with_company(cls.company).create({
            "name": "Комплектуючі імпорт",
            "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.chart.ref("ua_psbp_201").id,
            "property_account_expense_categ_id": cls.chart.ref("ua_psbp_943").id,
        })
        cls.motor = cls._product("Двигун безколекторний 2807", "8501310000", 10.0)
        cls.camera = cls._product("Камера тепловізійна 640", "8525890000", 0.0)
        cls.spare = cls._product("Пропелер 7 дюймів", "8803900000", 5.0)

        cls.usd = cls.env.ref("base.USD")
        cls.usd.active = True
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.usd.id)]).unlink()
        cls.env["res.currency.rate"].create({
            "name": fields.Date.context_today(cls.env.user),
            "currency_id": cls.usd.id,
            "company_id": cls.company.id,
            "rate": 1 / 40.0,
        })
        cls.vendor = cls.env["res.partner"].create({"name": "Shenzhen Parts Ltd (тест)"})
        cls.customs = cls.env["res.partner"].create({"name": "Митниця (тест)"})
        cls.receipt = cls._receive([(cls.motor, 10, 25.0), (cls.camera, 5, 100.0)])

    # --- службове -------------------------------------------------------

    @classmethod
    def _product(cls, name, uktzed, duty):
        return cls.env["product.product"].create({
            "name": name,
            "is_storable": True,
            "type": "consu",
            "categ_id": cls.category.id,
            "ua_uktzed": uktzed,
            "ua_customs_duty_rate": duty,
        })

    @classmethod
    def _receive(cls, rows):
        order = cls.env["purchase.order"].create({
            "partner_id": cls.vendor.id,
            "currency_id": cls.usd.id,
            "order_line": [(0, 0, {
                "product_id": product.id,
                "product_qty": quantity,
                "price_unit": price,
                "tax_ids": [(5, 0, 0)],
            }) for product, quantity, price in rows],
        })
        order.button_confirm()
        picking = order.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.button_validate()
        return picking

    def _declaration(self, name="UA100010/2026/000101", fee=1500.0, pickings=None):
        declaration = self.env["ua.customs.declaration"].create({
            "name": name,
            "partner_id": self.vendor.id,
            "customs_partner_id": self.customs.id,
            "currency_id": self.usd.id,
            "picking_ids": [(6, 0, (pickings or self.receipt).ids)],
            "fee_amount": fee,
        })
        declaration.action_fill_from_pickings()
        return declaration

    def _line(self, declaration, product):
        return declaration.line_ids.filtered(lambda line: line.product_id == product)

    def _balance(self, xmlid, since, partner=None):
        domain = [
            ("account_id", "=", self.chart.ref(xmlid).id),
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
            ("id", ">", since),
        ]
        if partner:
            domain.append(("partner_id", "=", partner.id))
        return round(sum(self.env["account.move.line"].search(domain).mapped("balance")), 2)

    def _mark(self):
        line = self.env["account.move.line"].search([], order="id desc", limit=1)
        return line.id or 0

    # --- 1. розрахунок ---------------------------------------------------

    def test_01_fill_and_compute(self):
        declaration = self._declaration()
        self.assertAlmostEqual(declaration.rate, 40.0, places=4)
        motor, camera = self._line(declaration, self.motor), self._line(declaration, self.camera)
        self.assertEqual((motor.quantity, camera.quantity), (10.0, 5.0))
        self.assertAlmostEqual(motor.invoice_value, 250.0, delta=CENT)
        self.assertAlmostEqual(camera.invoice_value, 500.0, delta=CENT)
        self.assertEqual(motor.uktzed, "8501310000")
        self.assertEqual((motor.duty_rate, motor.vat_rate), (10.0, 20.0))

        declaration.action_compute()
        self.assertAlmostEqual(motor.customs_value, 10000.0, delta=CENT)
        self.assertAlmostEqual(camera.customs_value, 20000.0, delta=CENT)
        self.assertAlmostEqual(motor.duty, 1000.0, delta=CENT)
        self.assertAlmostEqual(camera.duty, 0.0, delta=CENT)
        self.assertAlmostEqual(motor.fee_share, 500.0, delta=CENT)
        self.assertAlmostEqual(camera.fee_share, 1000.0, delta=CENT)
        self.assertAlmostEqual(motor.vat_base, 11000.0, delta=CENT)
        self.assertAlmostEqual(motor.vat, 2200.0, delta=CENT)
        self.assertAlmostEqual(camera.vat, 4000.0, delta=CENT)
        self.assertAlmostEqual(motor.landed_cost, 1500.0, delta=CENT)
        self.assertAlmostEqual(declaration.customs_value_total, 30000.0, delta=CENT)
        self.assertAlmostEqual(declaration.landed_total, 2500.0, delta=CENT)
        self.assertAlmostEqual(declaration.vat_total, 6200.0, delta=CENT)
        self.assertAlmostEqual(declaration.payable_total, 8700.0, delta=CENT)

    def test_02_fee_remainder_goes_to_last_line(self):
        """100 за митною вартістю 10 000 / 20 000: 33,33 і 66,67, разом рівно 100."""
        declaration = self._declaration(fee=100.0)
        declaration.action_compute()
        shares = declaration.line_ids.sorted("id").mapped("fee_share")
        self.assertAlmostEqual(sum(shares), 100.0, delta=CENT)
        self.assertAlmostEqual(shares[0], 33.33, delta=CENT)
        self.assertAlmostEqual(shares[1], 66.67, delta=CENT)

    # --- 2. проведення ---------------------------------------------------

    def test_03_post_spreads_duty_and_takes_vat(self):
        mark = self._mark()
        declaration = self._declaration()
        declaration.action_post()
        self.assertEqual(declaration.state, "posted")

        cost = declaration.landed_cost_id
        self.assertEqual(cost.state, "done")
        self.assertEqual(cost.ua_customs_declaration_id, declaration)
        by_product = {}
        for adjustment in cost.valuation_adjustment_lines:
            by_product[adjustment.product_id] = (
                by_product.get(adjustment.product_id, 0.0) + adjustment.additional_landed_cost)
        # кожен товар отримав своє мито, а не частку за ціною
        self.assertAlmostEqual(by_product[self.motor], 1500.0, delta=CENT)
        self.assertAlmostEqual(by_product[self.camera], 1000.0, delta=CENT)

        # Дт 201 на 2 500, Дт 6412 на 6 200, Кт 3771 на 8 700 - усе з контрагентом «митниця»
        self.assertAlmostEqual(self._balance("ua_psbp_201", mark), 2500.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_6412", mark), 6200.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_3771", mark), -8700.0, delta=CENT)
        self.assertAlmostEqual(
            self._balance("ua_psbp_3771", mark, partner=self.customs), -8700.0, delta=CENT)

        vat = declaration.vat_move_id
        self.assertEqual(vat.state, "posted")
        self.assertTrue(vat.ua_customs_entry)
        self.assertFalse(declaration.rest_move_id)

        # середня собівартість: (10 000 + 1 500) / 10 і (20 000 + 1 000) / 5
        self.motor.invalidate_recordset()
        self.camera.invalidate_recordset()
        self.assertAlmostEqual(self.motor.standard_price, 1150.0, delta=CENT)
        self.assertAlmostEqual(self.camera.standard_price, 4200.0, delta=CENT)

    def test_04_used_goods_still_close_3771(self):
        """4 двигуни з 10 уже видано до проведення декларації. 3771 все одно отримує 8 700,
        а мито на видане не губиться: 201 + 943 разом отримують 2 500."""
        out = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "move_ids": [(0, 0, {
                "product_id": self.motor.id,
                "product_uom_qty": 4.0,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            })],
        })
        out.action_confirm()
        out.move_ids.quantity = 4.0
        out.move_ids.picked = True
        out.button_validate()

        mark = self._mark()
        declaration = self._declaration(name="UA100010/2026/000102")
        declaration.action_post()
        self.assertAlmostEqual(self._balance("ua_psbp_3771", mark), -8700.0, delta=CENT)
        self.assertAlmostEqual(
            self._balance("ua_psbp_201", mark) + self._balance("ua_psbp_943", mark),
            2500.0, delta=0.02)

    def test_05_product_not_received(self):
        declaration = self._declaration(name="UA100010/2026/000103")
        declaration.line_ids = [(0, 0, {"product_id": self.spare.id, "quantity": 20,
                                        "invoice_value": 40.0})]
        with self.assertRaises(UserError):
            declaration.action_post()

    def test_06_zero_vat_needs_basis(self):
        declaration = self._declaration(name="UA100010/2026/000104")
        line = self._line(declaration, self.camera)
        line.vat_rate = 0.0
        line.vat_exempt_basis = False
        with self.assertRaises(UserError):
            declaration.action_compute()
        line.vat_exempt_basis = "п. 197.11 ст. 197 ПКУ (тестова підстава)"
        declaration.action_compute()
        self.assertAlmostEqual(line.vat, 0.0, delta=CENT)
        self.assertAlmostEqual(declaration.vat_total, 2200.0, delta=CENT)

    def test_07_manual_customs_value_and_rate(self):
        """Брокер додав до митної вартості доставку до кордону: значення з декларації лишається."""
        declaration = self._declaration(name="UA100010/2026/000105", fee=0.0)
        declaration.rate = 41.0
        motor = self._line(declaration, self.motor)
        declaration.action_compute()
        self.assertAlmostEqual(motor.customs_value, 10250.0, delta=CENT)
        motor.invoice_value = 0.0
        motor.customs_value = 11000.0
        declaration.action_compute()
        self.assertAlmostEqual(motor.customs_value, 11000.0, delta=CENT)
        self.assertAlmostEqual(motor.duty, 1100.0, delta=CENT)

    # --- 3. правила документа --------------------------------------------

    def test_08_state_rules(self):
        declaration = self._declaration(name="UA100010/2026/000106")
        declaration.action_post()
        with self.assertRaises(UserError):
            declaration.action_post()
        with self.assertRaises(UserError):
            declaration.action_reset_draft()
        with self.assertRaises(UserError):
            declaration.unlink()

        draft = self._declaration(name="UA100010/2026/000107")
        draft.action_cancel()
        draft.action_reset_draft()
        self.assertEqual(draft.state, "draft")
        with self.assertRaises(ValidationError):
            draft.fee_amount = -1.0

    def test_08b_vat_already_taken_on_bill(self):
        """Бухгалтер уже взяв митний ПДВ кнопкою на рахунку: декларація не задвоює кредит."""
        bill = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.vendor.id,
            "invoice_date": fields.Date.context_today(self.env.user),
            "ua_customs_decl_number": "UA100010/2026/000110",
            "ua_customs_vat": 6200.0,
        })
        bill.action_ua_post_customs_vat()
        self.assertTrue(bill.ua_customs_move_id)
        declaration = self._declaration(name="UA100010/2026/000110")
        with self.assertRaises(UserError):
            declaration.action_post()

    @mute_logger("odoo.sql_db")
    def test_09_number_unique_per_company(self):
        self._declaration(name="UA100010/2026/000108")
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._declaration(name="UA100010/2026/000108")

    def test_10_print(self):
        declaration = self._declaration(name="UA100010/2026/000109")
        declaration.action_compute()
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_customs.report_ua_customs_declaration", declaration.ids)
        text = html.decode()
        self.assertIn("РОЗРАХУНОК МИТНИХ ПЛАТЕЖІВ", text)
        self.assertIn("UA100010/2026/000109", text)
        self.assertIn("8501310000", text)
        action = declaration.action_print()
        self.assertEqual(action["type"], "ir.actions.report")
