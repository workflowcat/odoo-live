# -*- coding: utf-8 -*-
"""Дата інвентаризації і дата проводки оцінки запасів.

Знайдено на збірці демо-простору. Документ `ua.stock.inventory` має свою дату -
її друкує інвентаризаційний опис і нею датується проводка лишків 947 -> 719,
яку складає сам модуль. А коригування залишків модуль віддає нативному
`action_apply_inventory()` без дати, тому нативна проводка оцінки запасів
(Дт 201 / Кт 947 на лишок, Дт 947 / Кт 201 на нестачу) датується сьогоднішнім
днем. Два боки однієї операції розʼїжджаються по періодах: у вересні висить
дебет 947 без зустрічного кредиту 201, а в жовтні - навпаки.

Обхід, яким користується `scripts/demo_business.py`: кликати `action_apply`
з `force_period_date` у контексті. Нативний `stock_account` читає цей ключ і
ставить дату документа. Обидва тести тут - про це: перший фіксує розбіжність
як вона є, другий показує, що контекст її знімає.

Модуль тестів не залежить від `l10n_ua_stock_docs`, тому без нього тести
пропускаються. Теги: ua_demo_costing.
"""
from dateutil.relativedelta import relativedelta

from odoo import fields
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
        # Дата документа - минулий місяць: у майбутньому мʼяке проведення відклало б
        # проводку в чернетку, і тест перевіряв би вже іншу історію.
        self.doc_date = fields.Date.context_today(self.env.user) - relativedelta(days=20)
        # Засів складу сам дає проводку Дт 201 / Кт 947, тому рахуємо тільки те,
        # що зʼявиться після нього.
        self.mark = self.env["account.move.line"].search([], order="id desc", limit=1).id or 0

    # --- службове -------------------------------------------------------

    def _inventory(self):
        return self.env["ua.stock.inventory"].create({
            "company_id": self.company.id,
            "date": self.doc_date,
            "location_id": self.warehouse.lot_stock_id.id,
            "basis": "Наказ № 1 (тест дат)",
            "chair": "Петренко П. П.",
            "keeper": "Коваленко К. К.",
        })

    def _surplus(self, quantity=4.0, context=None):
        """Провести інвентаризацію з лишком і віддати створені проводки."""
        inventory = self._inventory()
        inventory.action_fill()
        line = inventory.line_ids.filtered(lambda l: l.product_id == self.product)
        line.qty_fact = line.qty_book + quantity
        inventory.with_context(**(context or {})).action_apply()
        native = inventory.move_ids.account_move_id
        return inventory, native

    def _balance(self, xmlid):
        account = self.chart.ref(xmlid)
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
            ("id", ">", self.mark),
        ])
        return round(sum(lines.mapped("balance")), 2)

    # --- 1. Без контексту дати розходяться -------------------------------
    def test_01_native_entry_keeps_today_not_document_date(self):
        today = fields.Date.context_today(self.env.user)
        inventory, native = self._surplus()
        self.assertEqual(inventory.state, "done")
        self.assertTrue(native, "нативне коригування не дало проводки оцінки запасів")
        self.assertEqual(
            inventory.surplus_move_id.date, self.doc_date,
            "проводка лишків 947 -> 719 має бути датована документом")
        self.assertEqual(
            native.date, today,
            "нативна проводка оцінки запасів датується сьогоднішнім днем: "
            "документ своєї дати їй не передає")
        self.assertNotEqual(
            native.date, inventory.date,
            "якщо дати збіглися, модуль почав передавати дату - оновіть тест і "
            "заберіть force_period_date зі scripts/demo_business.py")

    # --- 2. З force_period_date обидві сторони в одному дні ---------------
    def test_02_force_period_date_puts_both_sides_in_one_day(self):
        inventory, native = self._surplus(context={"force_period_date": self.doc_date})
        self.assertEqual(native.date, self.doc_date)
        self.assertEqual(inventory.surplus_move_id.date, self.doc_date)
        # Лишок 4 одиниці по 100: нативне Дт 201 / Кт 947 на 400, далі документ
        # перекидає 947 -> 719. У підсумку 947 порожній, дохід стоїть на 719.
        self.assertAlmostEqual(self._balance("ua_psbp_947"), 0.0, delta=CENT)
        self.assertAlmostEqual(self._balance("ua_psbp_719"), -400.0, delta=CENT)
        self.assertAlmostEqual(inventory.amount_surplus, 400.0, delta=CENT)
