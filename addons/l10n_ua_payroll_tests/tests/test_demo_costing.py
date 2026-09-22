# -*- coding: utf-8 -*-
"""Дата інвентаризації і дата проводки оцінки запасів.

Знайдено на збірці демо-простору, виправлено в `l10n_ua_stock_docs`. Документ
`ua.stock.inventory` має свою дату: її друкує інвентаризаційний опис, нею
датується проводка лишків 947 -> 719, яку складає сам модуль, і нею ж тепер
датується нативна проводка оцінки запасів (Дт 201 / Кт 947 на лишок,
Дт 947 / Кт 201 на нестачу) - документ передає дату через `force_period_date`,
ключ, який читає нативний `stock_account`. Раніше нативна сторона лягала
сьогоднішнім днем, і два боки однієї операції розʼїжджалися по періодах.

Звідси ж друге правило: дата в майбутньому не приймається. Нативне мʼяке
проведення (`_post(soft=True)`) відклало б свою проводку в чернетку з
автопроведенням, а наша лягла б у книги одразу - на 947 висів би дебет без
зустрічного кредиту 201. Запаси рахують у день підрахунку, тому документ
відмовляє з UserError, а не вигадує спосіб порахувати наперед.

Модуль тестів не залежить від `l10n_ua_stock_docs`, тому без нього тести
пропускаються. Теги: ua_demo_costing.
"""
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005


@tagged("post_install", "-at_install", "ua_demo_costing")
class TestDemoInventoryDates(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)

    def setUp(self):
        super().setUp()
        if "ua.stock.inventory" not in self.env:
            self.skipTest("l10n_ua_stock_docs не встановлено в цій базі")
        self.warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company.id)], limit=1)
        if not self.warehouse:
            # тестова компанія без складу: заводимо мінімальний, щоб було де рахувати
            self.warehouse = self.env["stock.warehouse"].create({
                "name": "Склад для тесту дат", "code": "TDT",
                "company_id": self.company.id})
        # Постійна оцінка і рахунок 201 на категорії - у повному продукті це робить
        # l10n_ua_mrp; тут ставимо руками, щоб тест не залежав від виробництва.
        self.company.inventory_valuation = "real_time"
        self.company.cost_method = "average"
        self.category = self.env["product.category"].with_company(self.company).create({
            "name": "Матеріали для тесту дат",
            "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": self.chart.ref("ua_psbp_201").id,
            "property_account_expense_categ_id": self.chart.ref("ua_psbp_943").id,
        })
        self.product = self.env["product.product"].create({
            "name": "Кромка ПВХ для тесту дат",
            "is_storable": True,
            "type": "consu",
            "categ_id": self.category.id,
            "standard_price": 100.0,
        })
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "inventory_quantity": 10.0,
        }).action_apply_inventory()
        self.today = fields.Date.context_today(self.env.user)
        self.doc_date = self.today - relativedelta(days=20)
        # Засів складу сам дає проводку Дт 201 / Кт 947, тому рахуємо тільки те,
        # що зʼявиться після нього.
        self.mark = self.env["account.move.line"].search([], order="id desc", limit=1).id or 0

    # --- службове -------------------------------------------------------

    def _inventory(self, date=None):
        return self.env["ua.stock.inventory"].create({
            "company_id": self.company.id,
            "date": date or self.doc_date,
            "location_id": self.warehouse.lot_stock_id.id,
            "basis": "Наказ № 1 (тест дат)",
            "chair": "Петренко П. П.",
            "keeper": "Коваленко К. К.",
        })

    def _counted(self, quantity=4.0, date=None):
        """Опис, заповнений залишками, з однією розбіжністю. Ще не проведений."""
        inventory = self._inventory(date)
        inventory.action_fill()
        line = inventory.line_ids.filtered(lambda l: l.product_id == self.product)
        line.qty_fact = line.qty_book + quantity
        return inventory

    def _balance(self, xmlid):
        account = self.chart.ref(xmlid)
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
            ("id", ">", self.mark),
        ])
        return round(sum(lines.mapped("balance")), 2)

    # --- 1. Обидві сторони в одному дні -----------------------------------
    def test_01_both_entries_carry_the_document_date(self):
        inventory = self._counted()
        inventory.action_apply()
        native = inventory.move_ids.account_move_id
        self.assertEqual(inventory.state, "done")
        self.assertTrue(native, "нативне коригування не дало проводки оцінки запасів")
        self.assertEqual(
            native.date, self.doc_date,
            "нативна проводка оцінки запасів має йти датою документа, "
            "а не днем, коли натиснули кнопку")
        self.assertEqual(
            inventory.surplus_move_id.date, self.doc_date,
            "проводка лишків 947 -> 719 датується документом")
        self.assertNotEqual(self.doc_date, self.today,
                            "тест має порівнювати дату документа з іншим днем")
        # Лишок 4 одиниці по 100: нативне Дт 201 / Кт 947 на 400, далі документ
        # перекидає 947 -> 719. У підсумку 947 порожній, дохід стоїть на 719.
        self.assertAlmostEqual(self._balance("ua_psbp_947"), 0.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_719"), -400.0, delta=CENT)
        self.assertAlmostEqual(inventory.amount_surplus, 400.0, delta=CENT)
        self.assertEqual(native.state, "posted", "запис минулою датою проводиться одразу")

    # --- 2. Дата в майбутньому не приймається ------------------------------
    def test_02_future_date_is_refused(self):
        future = self.today + relativedelta(days=8)
        inventory = self._counted(date=future)
        with self.assertRaises(UserError):
            inventory.action_apply()
        self.assertEqual(inventory.state, "counting", "документ лишається в підрахунку")
        self.assertFalse(inventory.move_ids, "коригувань складу не сталося")
        self.assertFalse(inventory.surplus_move_id, "проводки лишків теж немає")
        self.assertAlmostEqual(self._balance("ua_psbp_947"), 0.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_719"), 0.0, delta=CENT)

    # --- 3. Сьогоднішня дата проходить -------------------------------------
    def test_03_today_is_allowed(self):
        inventory = self._counted(date=self.today)
        inventory.action_apply()
        native = inventory.move_ids.account_move_id
        self.assertEqual(inventory.state, "done")
        self.assertEqual(native.date, self.today)
        self.assertEqual(native.state, "posted")
        self.assertEqual(inventory.surplus_move_id.date, self.today)
