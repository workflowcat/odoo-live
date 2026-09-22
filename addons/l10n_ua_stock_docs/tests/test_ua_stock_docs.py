# -*- coding: utf-8 -*-
"""Інваріанти складських документів.

Числа в очікуваннях пораховані руками, арифметика показана в коментарі поруч.
Перевіряємо те, що додано поверх нативного коригування залишків: рахунок втрат
на локації списання, перекидання лишків на 719, дві друковані форми
інвентаризації, акт приймання-передачі і протокол якості.

Повне налаштування оцінки запасів (постійна оцінка, рахунки категорій) робить
l10n_ua_mrp. Тут воно ставиться руками в setUpClass - рівно як його поставив би
бухгалтер у компанії без виробництва.

Запуск: чиста база через docker compose run, теги ua_stock_docs.
"""
from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005


@tagged("post_install", "-at_install", "ua_stock_docs")
class TestUaStockDocs(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

        # Постійна оцінка запасів і рахунок 201 на категорії - те, що в повному
        # продукті приходить з l10n_ua_mrp.
        cls.company.inventory_valuation = "real_time"
        cls.company.cost_method = "average"
        cls.category = cls.env["product.category"].with_company(cls.company).create({
            "name": "Сировина і матеріали",
            "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.chart.ref("ua_psbp_201").id,
            "property_account_expense_categ_id": cls.chart.ref("ua_psbp_943").id,
        })
        cls.board = cls._product("Плита ДСП", 150.0)
        cls.varnish = cls._product("Лак меблевий", 80.0)

    # --- службове -------------------------------------------------------

    @classmethod
    def _product(cls, name, price):
        return cls.env["product.product"].create({
            "name": name,
            "is_storable": True,
            "type": "consu",
            "categ_id": cls.category.id,
            "standard_price": price,
            "list_price": price * 2,
        })

    def _seed(self, product, quantity):
        """Покласти кількість на склад, не чіпаючи документ інвентаризації."""
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": quantity,
        }).action_apply_inventory()

    def _inventory(self):
        return self.env["ua.stock.inventory"].create({
            "company_id": self.company.id,
            "location_id": self.stock_location.id,
            "basis": "Наказ № 12 від 01.09.2026",
            "chair": "Петренко П. П.",
            "members": "Іваненко І. І., Сидоренко С. С.",
            "keeper": "Коваленко К. К.",
        })

    def _line(self, inventory, product):
        return inventory.line_ids.filtered(lambda line: line.product_id == product)

    def _balance(self, xmlid, since=None):
        account = self.chart.ref(xmlid)
        domain = [
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
        ]
        if since:
            domain.append(("id", ">", since))
        lines = self.env["account.move.line"].search(domain)
        return round(sum(lines.mapped("balance")), 2)

    def _last_line_id(self):
        line = self.env["account.move.line"].search([], order="id desc", limit=1)
        return line.id or 0

    # --- 1. Рахунок втрат прийшов разом із планом рахунків ----------------
    def test_01_loss_account_on_locations(self):
        locations = self.env["stock.location"].search(
            [("usage", "=", "inventory"), ("company_id", "=", self.company.id)])
        self.assertTrue(locations)
        for location in locations:
            self.assertEqual(location.valuation_account_id, self.chart.ref("ua_psbp_947"))

    # --- 2. Опис заповнюється залишками складу ----------------------------
    def test_02_fill_from_stock(self):
        self._seed(self.board, 10)
        self._seed(self.varnish, 4)
        inventory = self._inventory()
        inventory.action_fill()
        self.assertEqual(inventory.state, "counting")
        self.assertEqual(len(inventory.line_ids), 2)
        self.assertAlmostEqual(self._line(inventory, self.board).qty_book, 10.0, delta=CENT)
        self.assertAlmostEqual(self._line(inventory, self.board).qty_fact, 10.0, delta=CENT)
        self.assertAlmostEqual(self._line(inventory, self.board).cost, 150.0, delta=CENT)

    # --- 3. Лишок 2 одиниці: Кт 719 --------------------------------------
    def test_03_surplus_goes_to_719(self):
        self._seed(self.board, 10)
        inventory = self._inventory()
        inventory.action_fill()
        mark = self._last_line_id()
        self._line(inventory, self.board).qty_fact = 12  # лишок 2 × 150 = 300
        inventory.action_apply()
        self.assertEqual(inventory.state, "done")
        self.assertAlmostEqual(inventory.amount_surplus, 300.0, delta=CENT)
        # запас виріс: Дт 201 на 300
        self.assertAlmostEqual(self._balance("ua_psbp_201", mark), 300.0, delta=CENT)
        # дохід: Кт 719 на 300 (сальдо доходу відʼємне)
        self.assertAlmostEqual(self._balance("ua_psbp_719", mark), -300.0, delta=CENT)
        # 947 нативний Odoo кредитує, ми його закриваємо: разом нуль
        self.assertAlmostEqual(self._balance("ua_psbp_947", mark), 0.0, delta=CENT)
        self.assertTrue(inventory.surplus_move_id)
        self.assertEqual(inventory.surplus_move_id.state, "posted")

    # --- 4. Нестача 3 одиниці: Дт 947 -------------------------------------
    def test_04_shortage_goes_to_947(self):
        self._seed(self.board, 10)
        inventory = self._inventory()
        inventory.action_fill()
        mark = self._last_line_id()
        self._line(inventory, self.board).qty_fact = 7  # нестача 3 × 150 = 450
        inventory.action_apply()
        self.assertAlmostEqual(inventory.amount_shortage, 450.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_201", mark), -450.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_947", mark), 450.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_719", mark), 0.0, delta=CENT)
        self.assertFalse(inventory.surplus_move_id)

    # --- 5. Лишок і нестача в одному документі ----------------------------
    def test_05_surplus_and_shortage(self):
        self._seed(self.board, 10)
        self._seed(self.varnish, 4)
        inventory = self._inventory()
        inventory.action_fill()
        mark = self._last_line_id()
        self._line(inventory, self.board).qty_fact = 12   # лишок 2 × 150 = 300
        self._line(inventory, self.varnish).qty_fact = 1  # нестача 3 × 80 = 240
        inventory.action_apply()
        self.assertAlmostEqual(inventory.amount_surplus, 300.0, delta=CENT)
        self.assertAlmostEqual(inventory.amount_shortage, 240.0, delta=CENT)
        # 201: +300 − 240 = +60
        self.assertAlmostEqual(self._balance("ua_psbp_201", mark), 60.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_719", mark), -300.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_947", mark), 240.0, delta=CENT)

    # --- 6. Склад після проведення дорівнює факту -------------------------
    def test_06_stock_matches_count(self):
        self._seed(self.board, 10)
        inventory = self._inventory()
        inventory.action_fill()
        self._line(inventory, self.board).qty_fact = 12
        inventory.action_apply()
        self.board.invalidate_recordset()
        self.assertAlmostEqual(
            self.board.with_company(self.company).qty_available, 12.0, delta=CENT)
        self.assertTrue(inventory.move_ids)

    # --- 7. Нумерація за роком -------------------------------------------
    def test_07_numbering(self):
        year = fields.Date.context_today(self.env.user).year
        first = self._inventory()
        second = self._inventory()
        self.assertTrue(first.name.startswith("ІНВ/%s/" % year), first.name)
        self.assertTrue(second.name.startswith("ІНВ/%s/" % year), second.name)
        self.assertNotEqual(first.name, second.name)
        protocol = self.env["ua.quality.protocol"].create({
            "company_id": self.company.id,
            "product_id": self.board.id,
        })
        self.assertTrue(protocol.name.startswith("ЯК/%s/" % year), protocol.name)

    # --- 8. Проведений документ не проводять двічі ------------------------
    def test_08_apply_once(self):
        self._seed(self.board, 10)
        inventory = self._inventory()
        inventory.action_fill()
        self._line(inventory, self.board).qty_fact = 11
        inventory.action_apply()
        with self.assertRaises(Exception):
            inventory.action_apply()

    # --- 9. Обидві форми інвентаризації будуються -------------------------
    def test_09_inventory_forms(self):
        self._seed(self.board, 10)
        self._seed(self.varnish, 4)
        inventory = self._inventory()
        inventory.action_fill()
        self._line(inventory, self.board).qty_fact = 12
        inventory.action_apply()
        for xmlid in ("l10n_ua_stock_docs.action_report_ua_inventory_list",
                      "l10n_ua_stock_docs.action_report_ua_inventory_sheet"):
            html = self.env["ir.actions.report"]._render_qweb_html(xmlid, inventory.ids)[0]
            text = html.decode() if isinstance(html, bytes) else html
            self.assertIn("Плита ДСП", text)
            self.assertIn("Петренко П. П.", text)
        sheet = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_stock_docs.action_report_ua_inventory_sheet", inventory.ids)[0]
        sheet = sheet.decode() if isinstance(sheet, bytes) else sheet
        # у звіряльну відомість потрапляє лише розбіжність
        self.assertNotIn("Лак меблевий", sheet)

    # --- 10. Акт приймання-передачі з готової доставки --------------------
    def test_10_acceptance_act(self):
        self._seed(self.board, 10)
        self.company.partner_id.company_registry = "12345678"
        self.partner_a.company_registry = "87654321"
        picking = self.env["stock.picking"].create({
            "partner_id": self.partner_a.id,
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "company_id": self.company.id,
            "ua_act_handover": "Комірник Литвин Л. Л.",
            "ua_act_receiver": "Водій Мороз М. М.",
            "move_ids": [(0, 0, {
                "product_id": self.board.id,
                "product_uom_qty": 3.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            })],
        })
        picking.action_confirm()
        picking.move_ids.quantity = 3.0
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_stock_docs.action_report_ua_acceptance_act", picking.ids)[0]
        text = html.decode() if isinstance(html, bytes) else html
        self.assertIn("Акт приймання-передачі", text)
        self.assertIn("12345678", text)
        self.assertIn("87654321", text)
        self.assertIn("Плита ДСП", text)
        self.assertIn("3.000", text)
        self.assertIn("Комірник Литвин Л. Л.", text)

    # --- 11. Протокол якості: перелік, висновок, форма ---------------------
    def test_11_quality_protocol(self):
        protocol = self.env["ua.quality.protocol"].create({
            "company_id": self.company.id,
            "product_id": self.board.id,
            "quantity": 5.0,
            "inspector": "Контролер Бондар Б. Б.",
        })
        protocol.action_fill_checklist()
        self.assertEqual(len(protocol.line_ids), 5)
        protocol.action_fill_checklist()
        self.assertEqual(len(protocol.line_ids), 5, "повторний виклик подвоїв перелік")
        protocol.line_ids[0].value = "без пошкоджень"
        protocol.action_pass()
        self.assertEqual(protocol.state, "passed")
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_stock_docs.action_report_ua_quality_protocol", protocol.ids)[0]
        text = html.decode() if isinstance(html, bytes) else html
        self.assertIn("Протокол перевірки якості", text)
        self.assertIn("Зовнішній огляд", text)
        self.assertIn("Придатний", text)
        self.assertIn("Контролер Бондар Б. Б.", text)
