# -*- coding: utf-8 -*-
"""Інваріанти собівартості виробництва.

Числа в очікуваннях пораховані руками, арифметика показана в коментарі поруч.
Перевіряємо дві різні речі. Перша - що нативна оцінка запасів після нашого
налаштування справді кладе суми на 231, 26 і 901: якщо Odoo колись змінить
механіку, тест упаде тут, а не в бухгалтерії. Друга - те, що додали ми:
розподіл ЗВВ за нормальною потужністю, калькуляція, вартість специфікації.

Запуск: чиста база через docker compose run, теги ua_mrp.
"""
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005


@tagged("post_install", "-at_install", "ua_mrp")
class TestUaMrp(AccountTestInvoicingCommon):

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
        cls.categ_raw = cls._categ("Сировина і матеріали")
        cls.categ_finished = cls._categ("Готова продукція")

        # Меблевий набір: стільниця 3 шт по 100, ніжка 12 шт по 25, гвинт 20 по 5.
        cls.top = cls._product("Стільниця", cls.categ_raw, 100.0)
        cls.leg = cls._product("Ніжка", cls.categ_raw, 25.0)
        cls.screw = cls._product("Гвинт", cls.categ_raw, 5.0)
        cls.table = cls._product("Стіл обідній", cls.categ_finished, 0.0)

        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.table.product_tmpl_id.id,
            "product_qty": 1.0,
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {"product_id": cls.top.id, "product_qty": 1.0}),
                (0, 0, {"product_id": cls.leg.id, "product_qty": 4.0}),
                (0, 0, {"product_id": cls.screw.id, "product_qty": 8.0}),
            ],
        })

    # --- службове -------------------------------------------------------

    @classmethod
    def _categ(cls, name):
        return cls.env["product.category"].with_company(cls.company).search(
            [("name", "=", name)], limit=1)

    @classmethod
    def _product(cls, name, category, price):
        return cls.env["product.product"].create({
            "name": name,
            "is_storable": True,
            "type": "consu",
            "categ_id": category.id,
            "standard_price": price,
            "list_price": price * 2 or 1.0,
        })

    @classmethod
    def _account(cls, xmlid):
        return cls.chart.ref(xmlid)

    def _receive(self, product, quantity):
        """Поставити кількість на склад інвентаризацією (Дт 20x / Кт 947)."""
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()
        return quant

    def _produce(self, quantity=1.0, date_finished=None):
        """Виробниче замовлення від створення до «Готово»."""
        production = self.env["mrp.production"].create({
            "product_id": self.table.id,
            "bom_id": self.bom.id,
            "product_qty": quantity,
            "company_id": self.company.id,
        })
        production.action_confirm()
        production.qty_producing = quantity
        production.move_raw_ids.picked = True
        production.button_mark_done()
        if date_finished:
            production.date_finished = date_finished
        return production

    def _balance(self, account, domain=None):
        """Сальдо рахунку за проведеними записами."""
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
        ] + (domain or []))
        return round(sum(lines.mapped("balance")), 2)

    def _move_lines(self, move, account):
        return move.line_ids.filtered(lambda line: line.account_id == account)

    def _zvv_entry(self, amount, date):
        """Записати ЗВВ на 91 однією проводкою: Дт 91 / Кт 631."""
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.company.id)], limit=1)
        entry = self.env["account.move"].create({
            "journal_id": journal.id,
            "company_id": self.company.id,
            "date": date,
            "ref": "Витрати цеху",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {"account_id": self._account("ua_psbp_91").id,
                        "name": "Витрати цеху", "balance": amount}),
                (0, 0, {"account_id": self._account("ua_psbp_631").id,
                        "name": "Витрати цеху", "balance": -amount}),
            ],
        })
        entry.action_post()
        return entry

    # --- 1. Налаштування прийшло разом із планом рахунків ----------------
    def test_01_company_and_locations(self):
        self.assertEqual(self.company.inventory_valuation, "real_time")
        self.assertTrue(self.company.account_stock_journal_id)
        production = self.env["stock.location"].search(
            [("usage", "=", "production"), ("company_id", "=", self.company.id)], limit=1)
        self.assertEqual(production.valuation_account_id, self._account("ua_psbp_231"))
        losses = self.env["stock.location"].search(
            [("usage", "=", "inventory"), ("company_id", "=", self.company.id)])
        self.assertTrue(losses)
        for location in losses:
            self.assertEqual(location.valuation_account_id, self._account("ua_psbp_947"))

    # --- 2. Рахунки категорій --------------------------------------------
    def test_02_category_accounts(self):
        raw = self.categ_raw.with_company(self.company)
        finished = self.categ_finished.with_company(self.company)
        goods = self._categ("Товари").with_company(self.company)
        self.assertEqual(raw.property_stock_valuation_account_id, self._account("ua_psbp_201"))
        self.assertEqual(finished.property_stock_valuation_account_id, self._account("ua_psbp_26"))
        self.assertEqual(goods.property_stock_valuation_account_id, self._account("ua_psbp_281"))
        self.assertEqual(finished.property_account_expense_categ_id, self._account("ua_psbp_901"))
        self.assertEqual(goods.property_account_expense_categ_id, self._account("ua_psbp_902"))
        self.assertEqual(raw.property_account_expense_categ_id, self._account("ua_psbp_943"))
        for category in (raw, finished, goods):
            self.assertEqual(category.property_valuation, "real_time")
            self.assertEqual(category.property_cost_method, "average")
        self.assertEqual(
            finished.property_stock_account_production_cost_id, self._account("ua_psbp_231"))

    # --- 3. Списання комплектуючих: Дт 231 / Кт 201 -----------------------
    def test_03_consume_posts_wip(self):
        self._receive(self.top, 2)
        self._receive(self.leg, 8)
        self._receive(self.screw, 16)
        acc_201 = self._account("ua_psbp_201")
        acc_231 = self._account("ua_psbp_231")
        production = self._produce(1)
        # 1×100 + 4×25 + 8×5 = 100 + 100 + 40 = 240
        raw_moves = production.move_raw_ids
        self.assertEqual(round(sum(raw_moves.mapped("value")), 2), 240.0)
        entries = raw_moves.mapped("account_move_id")
        self.assertTrue(entries, "нативна оцінка не створила проводки списання")
        debit_231 = sum(self._move_lines(entries, acc_231).mapped("debit"))
        credit_201 = sum(self._move_lines(entries, acc_201).mapped("credit"))
        self.assertAlmostEqual(debit_231, 240.0, delta=CENT)
        self.assertAlmostEqual(credit_201, 240.0, delta=CENT)

    # --- 4. Випуск продукції: Дт 26 / Кт 231 ------------------------------
    def test_04_finished_posts_26(self):
        self._receive(self.top, 2)
        self._receive(self.leg, 8)
        self._receive(self.screw, 16)
        acc_26 = self._account("ua_psbp_26")
        acc_231 = self._account("ua_psbp_231")
        production = self._produce(1)
        finished_moves = production.move_finished_ids.filtered(
            lambda move: move.product_id == self.table)
        entries = finished_moves.mapped("account_move_id")
        self.assertTrue(entries, "нативна оцінка не створила проводки випуску")
        debit_26 = sum(self._move_lines(entries, acc_26).mapped("debit"))
        credit_231 = sum(self._move_lines(entries, acc_231).mapped("credit"))
        self.assertAlmostEqual(debit_26, 240.0, delta=CENT)
        self.assertAlmostEqual(credit_231, 240.0, delta=CENT)
        # 231 - транзитний рахунок: після закриття замовлення на ньому нуль.
        self.assertAlmostEqual(self._balance(acc_231), 0.0, delta=CENT)

    # --- 5. Два вироби: собівартість множиться на кількість ---------------
    def test_05_two_units(self):
        self._receive(self.top, 4)
        self._receive(self.leg, 16)
        self._receive(self.screw, 32)
        production = self._produce(2)
        # 2 × 240 = 480
        self.assertAlmostEqual(
            round(sum(production.move_raw_ids.mapped("value")), 2), 480.0, delta=CENT)
        self.assertAlmostEqual(self._balance(self._account("ua_psbp_26")), 480.0, delta=CENT)
        self.assertAlmostEqual(self._balance(self._account("ua_psbp_231")), 0.0, delta=CENT)

    # --- 6. Продаж: Дт 901 / Кт 26 ----------------------------------------
    def test_06_cogs_on_sale(self):
        self._receive(self.top, 2)
        self._receive(self.leg, 8)
        self._receive(self.screw, 16)
        self._produce(1)
        acc_26 = self._account("ua_psbp_26")
        acc_901 = self._account("ua_psbp_901")
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": fields.Date.context_today(self.env.user),
            "company_id": self.company.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": self.table.id,
                "quantity": 1.0,
                "price_unit": 900.0,
                "tax_ids": [(6, 0, [])],
            })],
        })
        invoice.action_post()
        cogs = invoice.line_ids.filtered(lambda line: line.display_type == "cogs")
        self.assertTrue(cogs, "англосаксонська собівартість реалізації не зʼявилась")
        self.assertAlmostEqual(
            sum(self._move_lines(invoice, acc_901).mapped("debit")), 240.0, delta=CENT)
        self.assertAlmostEqual(
            sum(self._move_lines(invoice, acc_26).mapped("credit")), 240.0, delta=CENT)
        self.assertAlmostEqual(self._balance(acc_26), 0.0, delta=CENT)

    # --- 7. ЗВВ за нормальною потужністю ----------------------------------
    def test_07_zvv_normal_capacity(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        self._zvv_entry(10000.0, start)
        allocation = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 1000.0,
            "actual_hours": 800.0,
        })
        allocation.action_post()
        # 800 / 1000 = 0,8 -> 10 000 × 0,8 = 8 000 у виробництво, 2 000 у 901
        self.assertAlmostEqual(allocation.amount_base, 10000.0, delta=CENT)
        self.assertAlmostEqual(allocation.coefficient, 0.8, delta=0.0001)
        self.assertAlmostEqual(allocation.amount_allocated, 8000.0, delta=CENT)
        self.assertAlmostEqual(allocation.amount_unallocated, 2000.0, delta=CENT)
        move = allocation.move_id
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(
            sum(self._move_lines(move, self._account("ua_psbp_231")).mapped("debit")),
            8000.0, delta=CENT)
        self.assertAlmostEqual(
            sum(self._move_lines(move, self._account("ua_psbp_901")).mapped("debit")),
            2000.0, delta=CENT)
        self.assertAlmostEqual(
            sum(self._move_lines(move, self._account("ua_psbp_91")).mapped("credit")),
            10000.0, delta=CENT)
        # 91 закрився: сальдо за період нуль, повторний розподіл нема чого робити.
        self.assertAlmostEqual(self._balance(self._account("ua_psbp_91")), 0.0, delta=CENT)

    # --- 8. Повне завантаження: нерозподілених ЗВВ немає ------------------
    def test_08_zvv_full_capacity(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        self._zvv_entry(6000.0, start)
        allocation = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 500.0,
            "actual_hours": 640.0,
        })
        allocation.action_post()
        # факт вище за норму - коефіцієнт обмежений одиницею
        self.assertAlmostEqual(allocation.coefficient, 1.0, delta=0.0001)
        self.assertAlmostEqual(allocation.amount_allocated, 6000.0, delta=CENT)
        self.assertAlmostEqual(allocation.amount_unallocated, 0.0, delta=CENT)
        self.assertFalse(
            self._move_lines(allocation.move_id, self._account("ua_psbp_901")))

    # --- 9. Змінні ЗВВ розподіляються повністю ----------------------------
    def test_09_zvv_variable_share(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        self._zvv_entry(10000.0, start)
        allocation = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 1000.0,
            "actual_hours": 800.0,
            "fixed_share": 60.0,
        })
        allocation.action_compute()
        # постійні 6 000 × 0,8 = 4 800; змінні 4 000 розподіляються повністю
        self.assertAlmostEqual(allocation.amount_fixed, 6000.0, delta=CENT)
        self.assertAlmostEqual(allocation.amount_variable, 4000.0, delta=CENT)
        self.assertAlmostEqual(allocation.amount_allocated, 8800.0, delta=CENT)
        self.assertAlmostEqual(allocation.amount_unallocated, 1200.0, delta=CENT)

    # --- 10. Вартість специфікації з вкладеною специфікацією --------------
    def test_10_bom_cost_rollup(self):
        # ніжка стає вузлом: 1 заготовка по 12 + 2 шурупи по 5 = 22
        blank = self._product("Заготовка ніжки", self.categ_raw, 12.0)
        self.env["mrp.bom"].create({
            "product_tmpl_id": self.leg.product_tmpl_id.id,
            "product_qty": 1.0,
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {"product_id": blank.id, "product_qty": 1.0}),
                (0, 0, {"product_id": self.screw.id, "product_qty": 2.0}),
            ],
        })
        self.bom.invalidate_recordset()
        # стільниця 100 + 4 ніжки × 22 + 8 гвинтів × 5 = 100 + 88 + 40 = 228
        self.assertAlmostEqual(self.bom.ua_cost_material, 228.0, delta=CENT)
        self.assertAlmostEqual(self.bom.ua_cost_operation, 0.0, delta=CENT)
        self.assertAlmostEqual(self.bom.ua_cost_total, 228.0, delta=CENT)

    # --- 11. Можемо зібрати N ---------------------------------------------
    def test_11_bom_available(self):
        self._receive(self.top, 5)     # 5 / 1 = 5
        self._receive(self.leg, 14)    # 14 / 4 = 3
        self._receive(self.screw, 40)  # 40 / 8 = 5
        self.bom.invalidate_recordset()
        self.assertAlmostEqual(self.bom.ua_available_qty, 3.0, delta=CENT)
        self._receive(self.leg, 24)    # 24 / 4 = 6, тепер вузьке місце - стільниця
        self.bom.invalidate_recordset()
        self.assertAlmostEqual(self.bom.ua_available_qty, 5.0, delta=CENT)

    # --- 12. Калькуляція: матеріали, праця, ЗВВ ---------------------------
    def test_12_calculation(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        self._receive(self.top, 4)
        self._receive(self.leg, 16)
        self._receive(self.screw, 32)
        self._produce(2, date_finished=fields.Datetime.to_datetime(start))
        self._zvv_entry(10000.0, start)
        allocation = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 1000.0,
            "actual_hours": 800.0,
        })
        allocation.action_post()
        calculation = self.env["ua.cost.calculation"].create({
            "company_id": self.company.id,
            "date_from": start,
        })
        calculation.action_compute()
        self.assertEqual(len(calculation.line_ids), 1)
        line = calculation.line_ids
        self.assertEqual(line.product_id, self.table)
        self.assertAlmostEqual(line.quantity, 2.0, delta=CENT)
        # матеріали 2 × 240 = 480, праці немає, ЗВВ - усі 8 000 на єдиний виріб
        self.assertAlmostEqual(line.amount_material, 480.0, delta=CENT)
        self.assertAlmostEqual(line.amount_labour, 0.0, delta=CENT)
        self.assertAlmostEqual(line.amount_zvv, 8000.0, delta=CENT)
        self.assertAlmostEqual(line.amount_total, 8480.0, delta=CENT)
        self.assertAlmostEqual(line.amount_unit, 4240.0, delta=CENT)
        self.assertAlmostEqual(calculation.amount_total, 8480.0, delta=CENT)

    # --- 13. Повторний розподіл того самого місяця -------------------------
    def test_13_zvv_not_doubled(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        self._zvv_entry(10000.0, start)
        first = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 1000.0,
            "actual_hours": 800.0,
        })
        first.action_post()
        second = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 1000.0,
            "actual_hours": 800.0,
        })
        second.action_compute()
        # перший документ уже закрив 91, другому розподіляти нічого
        self.assertAlmostEqual(second.amount_base, 0.0, delta=CENT)
        self.assertAlmostEqual(second.amount_allocated, 0.0, delta=CENT)

    # --- 14. Друковані форми будуються -------------------------------------
    def test_14_reports_render(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        self._receive(self.top, 2)
        self._receive(self.leg, 8)
        self._receive(self.screw, 16)
        self._produce(1, date_finished=fields.Datetime.to_datetime(start))
        self._zvv_entry(3000.0, start)
        allocation = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 100.0,
            "actual_hours": 50.0,
        })
        allocation.action_post()
        calculation = self.env["ua.cost.calculation"].create({
            "company_id": self.company.id,
            "date_from": start,
        })
        calculation.action_compute()
        for xmlid, record in (
            ("l10n_ua_mrp.action_report_ua_cost_calculation", calculation),
            ("l10n_ua_mrp.action_report_ua_zvv_allocation", allocation),
            ("l10n_ua_mrp.action_report_ua_bom_cost", self.bom),
        ):
            html = self.env["ir.actions.report"]._render_qweb_html(xmlid, record.ids)[0]
            self.assertTrue(len(html) > 400, "порожня форма %s" % xmlid)

    # --- 15. Період розподілу: витрати сусіднього місяця не беруться -------
    def test_15_zvv_period_bounds(self):
        start = fields.Date.context_today(self.env.user).replace(day=1)
        previous = start - relativedelta(months=1)
        self._zvv_entry(4000.0, previous)
        self._zvv_entry(1500.0, start)
        allocation = self.env["ua.zvv.allocation"].create({
            "company_id": self.company.id,
            "date_from": start,
            "normal_hours": 100.0,
            "actual_hours": 100.0,
        })
        allocation.action_compute()
        self.assertAlmostEqual(allocation.amount_base, 1500.0, delta=CENT)
