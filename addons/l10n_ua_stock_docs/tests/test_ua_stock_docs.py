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
        # Друга категорія потрібна для звуження опису: комірник рахує по одній.
        cls.category_goods = cls.env["product.category"].with_company(cls.company).create({
            "name": "Фурнітура",
            "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": cls.chart.ref("ua_psbp_201").id,
            "property_account_expense_categ_id": cls.chart.ref("ua_psbp_943").id,
        })
        cls.handle = cls.env["product.product"].create({
            "name": "Ручка меблева",
            "is_storable": True,
            "type": "consu",
            "categ_id": cls.category_goods.id,
            "standard_price": 30.0,
            "list_price": 60.0,
        })

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

    # --- 12. Звуження опису категорією і полицею --------------------------
    def test_12_fill_narrowed(self):
        """Опис за однією категорією не бачить чужої, за полицею - чужої полиці."""
        self._seed(self.board, 10)     # Сировина і матеріали
        self._seed(self.varnish, 4)    # Сировина і матеріали
        self._seed(self.handle, 6)     # Фурнітура
        inventory = self._inventory()
        inventory.action_fill(category_ids=[self.category_goods.id])
        self.assertEqual(inventory.line_ids.product_id, self.handle)
        self.assertAlmostEqual(self._line(inventory, self.handle).qty_book, 6.0, delta=CENT)

        # без звуження - усі три товари
        inventory.action_fill()
        self.assertEqual(len(inventory.line_ids), 3)

        # звуження полицею: окрема полиця з власним залишком
        shelf = self.env["stock.location"].sudo().create({
            "name": "Полиця А1",
            "location_id": self.stock_location.id,
            "usage": "internal",
            "company_id": self.company.id,
            "ua_capacity": 10,
        })
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.varnish.id,
            "location_id": shelf.id,
            "inventory_quantity": 2.0,
        }).action_apply_inventory()
        inventory.action_fill(location_ids=[shelf.id])
        self.assertEqual(inventory.line_ids.product_id, self.varnish)
        # на полиці лежать рівно 2, а не 4 + 2 усього складу
        self.assertAlmostEqual(self._line(inventory, self.varnish).qty_book, 2.0, delta=CENT)

    # --- 13. План збігається з тим, що проведення справді проведе ----------
    def test_13_plan_matches_apply(self):
        self._seed(self.board, 10)
        self._seed(self.varnish, 4)
        inventory = self._inventory()
        inventory.action_fill()
        self._line(inventory, self.board).qty_fact = 12   # лишок 2 × 150 = 300
        self._line(inventory, self.varnish).qty_fact = 1  # нестача 3 × 80 = 240

        rows = inventory.plan()
        self.assertTrue(all(set(row) <= {"text", "level", "target"} for row in rows))
        self.assertTrue(all(row["level"] in ("info", "warn", "crit") for row in rows))
        self.assertFalse([row for row in rows if row["level"] == "crit"])
        text = "\n".join(row["text"] for row in rows)
        self.assertIn("Розбіжностей: 2 рядків із 2", text)
        self.assertIn("Лишок 300.00", text)
        self.assertIn("Нестача 240.00", text)
        self.assertIn("947", text)
        self.assertIn("719", text)
        self.assertIn(inventory.date.strftime("%d.%m.%Y"), text)

        mark = self._last_line_id()
        inventory.action_apply()
        # план обіцяв 300 лишку і 240 нестачі - стільки й лягло
        self.assertAlmostEqual(self._balance("ua_psbp_719", mark), -300.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_947", mark), 240.0, delta=CENT)
        self.assertTrue(all(row["level"] == "info" for row in inventory.plan()))

    # --- 14. План показує перешкоди: майбутня дата і порожній опис ---------
    def test_14_plan_blockers(self):
        self._seed(self.board, 10)
        inventory = self._inventory()
        crit = [row for row in inventory.plan() if row["level"] == "crit"]
        self.assertTrue(crit, "чернетка без рядків має бути перешкодою")

        inventory.action_fill()
        self._line(inventory, self.board).qty_fact = 11
        inventory.date = fields.Date.add(fields.Date.context_today(self.env.user), days=3)
        crit = [row for row in inventory.plan() if row["level"] == "crit"]
        self.assertTrue(any("не настав" in row["text"] for row in crit))
        with self.assertRaises(Exception):
            inventory.action_apply()

    # --- 15. Мітка клієнта: другий виклик віддає той самий документ --------
    def test_15_get_or_create_is_idempotent(self):
        values = {
            "company_id": self.company.id,
            "location_id": self.stock_location.id,
            "basis": "Наказ № 13",
        }
        first = self.env["ua.stock.inventory"].ua_get_or_create("wh-2026-09-22-01", values)
        second = self.env["ua.stock.inventory"].ua_get_or_create("wh-2026-09-22-01", values)
        self.assertEqual(first, second)
        self.assertEqual(self.env["ua.stock.inventory"].search_count(
            [("ua_client_ref", "=", "wh-2026-09-22-01")]), 1)
        # інша мітка - інший документ
        third = self.env["ua.stock.inventory"].ua_get_or_create("wh-2026-09-22-02", values)
        self.assertNotEqual(first, third)

    # --- 16. Стан міняє кнопка, а не запис поля ззовні ---------------------
    def test_16_start_count(self):
        inventory = self.env["ua.stock.inventory"].ua_get_or_create("wh-2026-09-22-03", {
            "company_id": self.company.id,
            "location_id": self.stock_location.id,
            "line_ids": [(0, 0, {
                "product_id": self.board.id,
                "qty_book": 10.0,
                "qty_fact": 10.0,
                "cost": 150.0,
            })],
        })
        self.assertEqual(inventory.state, "draft")
        inventory.action_start_count()
        self.assertEqual(inventory.state, "counting")
        empty = self._inventory()
        with self.assertRaises(Exception):
            empty.action_start_count()

    # --- 17. Зайнято місць: кількість × габарит ---------------------------
    def test_17_capacity_used(self):
        shelf = self.env["stock.location"].sudo().create({
            "name": "Полиця Б2",
            "location_id": self.stock_location.id,
            "usage": "internal",
            "company_id": self.company.id,
            "ua_capacity": 20,
        })
        self.board.product_tmpl_id.ua_size = "l"    # 16 місць за штуку
        self.varnish.product_tmpl_id.ua_size = "s"  # 1 місце за штуку
        for product, quantity in ((self.board, 1.0), (self.varnish, 5.0)):
            self.env["stock.quant"].with_context(inventory_mode=True).create({
                "product_id": product.id,
                "location_id": shelf.id,
                "inventory_quantity": quantity,
            }).action_apply_inventory()
        shelf.invalidate_recordset()
        # 1 × 16 + 5 × 1 = 21 місце на полиці з 20 - переповнення видно
        self.assertEqual(shelf.ua_capacity_used, 21)
        self.assertGreater(shelf.ua_capacity_used, shelf.ua_capacity)
        # батьківська локація бачить залишки дітей
        self.stock_location.invalidate_recordset()
        self.assertGreaterEqual(self.stock_location.ua_capacity_used, 21)
        # товар без габариту - одне місце за штуку
        self.varnish.product_tmpl_id.ua_size = False
        shelf.invalidate_recordset()
        self.assertEqual(shelf.ua_capacity_used, 21)
