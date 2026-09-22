"""Закупівлі: ризик постачальника, історія, ланцюг запиту, ліміт, пад.

Усі очікувані числа пораховані вручну, арифметика записана в коментарі поруч.
База будується з нуля в транзакції тесту: країна Україна, план ua_psbo,
товари з артикулами, постачальник, підрозділ.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install", "ua_purchase")
class TestUaPurchase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading(
                "ua_psbo", cls.company, install_demo=False
            )
        cls.company.invalidate_recordset()

        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.picking_type_in = cls.env.ref("stock.picking_type_in")
        cls.acc_92 = cls.env["account.account"].search(
            [("code", "=like", "92%"), ("company_ids", "in", cls.company.id)],
            limit=1, order="code",
        )
        assert cls.acc_92, "у плані ua_psbo немає рахунку 92"

        cls.department = cls.env["hr.department"].create({"name": "Виробництво"})
        cls.vendor = cls.env["res.partner"].create({
            "name": "ТОВ Постачальник",
            "is_company": True,
            "supplier_rank": 1,
            "company_registry": "12345678",
        })
        cls.env["res.partner.bank"].create({
            "acc_number": "UA123456789012345678901234567",
            "partner_id": cls.vendor.id,
        })
        cls.product_a = cls._product("АРТ-001", "Мотор")
        cls.product_b = cls._product("АРТ-002", "Стійка")

        cls.purchase_journal = cls.env["account.journal"].search(
            [("type", "=", "purchase"), ("company_id", "=", cls.company.id)], limit=1
        )
        cls.bank_journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1
        )

    # ------------------------------------------------------------------
    # Допоміжне
    # ------------------------------------------------------------------
    @classmethod
    def _product(cls, code, name):
        return cls.env["product.product"].create({
            "name": name,
            "default_code": code,
            "type": "consu",
            "purchase_ok": True,
            "purchase_method": "purchase",
            "standard_price": 100.0,
        })

    def _bill(self, amount, invoice_date=None, due_date=None, post=True):
        """Вхідний рахунок на одну позицію без податків - щоб сума рахунку
        дорівнювала сумі рядка і арифметику можна було звірити очима."""
        today = fields.Date.context_today(self)
        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.vendor.id,
            "invoice_date": invoice_date or today,
            "invoice_date_due": due_date or invoice_date or today,
            "journal_id": self.purchase_journal.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": self.product_a.id,
                "quantity": 1,
                "price_unit": amount,
                "tax_ids": [(5, 0, 0)],
                "account_id": self.acc_92.id,
            })],
        })
        if post:
            move.action_post()
        return move

    def _pay(self, move, payment_date):
        """Оплатити рахунок повністю вказаною датою."""
        wizard = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=move.ids,
        ).create({
            "payment_date": payment_date,
            "journal_id": self.bank_journal.id,
        })
        return wizard.action_create_payments()

    def _request(self, qty=5.0, estimated_cost=0.0, user=None, product=None):
        """Запит створюємо від адміністратора, але записуємо автора: звичайний
        працівник не має доступу до плану рахунків, а правило видимості
        запиту дивиться саме на автора."""
        return self.env["purchase.request"].create({
            "picking_type_id": self.picking_type_in.id,
            "requested_by": (user or self.env.user).id,
            "ua_department_id": self.department.id,
            "ua_expense_account_id": self.acc_92.id,
            "line_ids": [(0, 0, {
                "product_id": (product or self.product_a).id,
                "product_uom_id": self.uom_unit.id,
                "product_qty": qty,
                "estimated_cost": estimated_cost,
            })],
        })

    # ==================================================================
    # 1. Ризик постачальника
    # ==================================================================
    def test_risk_clean_supplier(self):
        """Чистий постачальник: код є, рахунок є, сигналів немає - нуль балів."""
        self.assertEqual(self.vendor.ua_supplier_risk_score, 0)
        self.assertEqual(self.vendor.ua_supplier_risk_level, "low")
        self.assertEqual(self.vendor.ua_supplier_risk_note, "зауважень немає")

    def test_risk_no_code_no_bank(self):
        """Без коду і без рахунку: 10 + 10 = 20 балів, середній ризик."""
        partner = self.env["res.partner"].create({"name": "Безіменний"})
        self.assertEqual(partner.ua_supplier_risk_score, 20)
        self.assertEqual(partner.ua_supplier_risk_level, "medium")

    def test_risk_terminated_non_payer_late(self):
        """Припинений неплатник, що платить із запізненням.

        припинено в ЄДР                 40
        неплатник ПДВ                   10
        оплата на 45 днів пізніше строку 20   (45 > 30)
        разом                           70 -> високий
        """
        today = fields.Date.context_today(self)
        due = today - timedelta(days=60)
        bill = self._bill(1000.0, invoice_date=due, due_date=due)
        self._pay(bill, due + timedelta(days=45))
        self.vendor.invalidate_recordset()
        self.assertEqual(self.vendor.ua_purchase_avg_delay_days, 45)

        self.vendor.write({
            "ua_supplier_edr_terminated": True,
            "ua_supplier_vat_non_payer": True,
        })
        self.assertEqual(self.vendor.ua_supplier_risk_score, 70)
        self.assertEqual(self.vendor.ua_supplier_risk_level, "high")
        # І поруч - чистий: та сама база, нуль балів.
        clean = self.env["res.partner"].create({
            "name": "ТОВ Чистий", "company_registry": "87654321",
        })
        self.env["res.partner.bank"].create({
            "acc_number": "UA999999999999999999999999999",
            "partner_id": clean.id,
        })
        self.assertEqual(clean.ua_supplier_risk_score, 0)

    def test_risk_kyc_block_is_high_alone(self):
        """Рішення KYC «відхилено» саме по собі дає 40 балів - високий."""
        self.vendor.ua_supplier_kyc_block = True
        self.assertEqual(self.vendor.ua_supplier_risk_score, 40)
        self.assertEqual(self.vendor.ua_supplier_risk_level, "high")

    def test_risk_signals_sync_keeps_manual_value(self):
        """«Оновити сигнали» без сусідніх модулів не затирає ручний прапорець,
        але ставить дату."""
        self.vendor.ua_supplier_edr_terminated = True
        self.vendor.action_ua_supplier_sync()
        if "ua_vat_payer_status" not in self.vendor._fields:
            self.assertTrue(self.vendor.ua_supplier_edr_terminated)
        self.assertTrue(self.vendor.ua_supplier_signals_date)

    # ==================================================================
    # 2. Історія закупівель
    # ==================================================================
    def test_history_three_bills(self):
        """Три рахунки: 1200 + 3600 + 600 = 5400; сплачено 1200;
        заборгованість 5400 - 1200 = 4200."""
        today = fields.Date.context_today(self)
        first = self._bill(1200.0)
        self._bill(3600.0)
        self._bill(600.0)
        self._pay(first, today)
        self.vendor.invalidate_recordset()
        self.assertEqual(self.vendor.ua_purchase_bill_count, 3)
        self.assertAlmostEqual(self.vendor.ua_purchase_bill_total, 5400.0, 2)
        self.assertAlmostEqual(self.vendor.ua_purchase_paid_total, 1200.0, 2)
        self.assertAlmostEqual(self.vendor.ua_purchase_open_balance, 4200.0, 2)

    def test_history_average_delay(self):
        """Два сплачені рахунки: запізнення 10 і 40 днів.
        Середнє (10 + 40) / 2 = 25 днів -> 10 балів (6..30)."""
        today = fields.Date.context_today(self)
        due = today - timedelta(days=60)
        first = self._bill(100.0, invoice_date=due, due_date=due)
        second = self._bill(100.0, invoice_date=due, due_date=due)
        self._pay(first, due + timedelta(days=10))
        self._pay(second, due + timedelta(days=40))
        self.vendor.invalidate_recordset()
        self.assertEqual(self.vendor.ua_purchase_avg_delay_days, 25)
        self.assertEqual(self.vendor.ua_supplier_risk_score, 10)
        self.assertEqual(self.vendor.ua_supplier_risk_level, "medium")

    def test_history_early_payment_is_not_a_delay(self):
        """Оплата достроково - нуль днів, не відʼємне число."""
        today = fields.Date.context_today(self)
        due = today + timedelta(days=30)
        bill = self._bill(500.0, invoice_date=today, due_date=due)
        self._pay(bill, today)
        self.vendor.invalidate_recordset()
        self.assertEqual(self.vendor.ua_purchase_avg_delay_days, 0)
        self.assertEqual(self.vendor.ua_supplier_risk_score, 0)

    def test_history_overpriced_bill(self):
        """Замовлення на 1000, рахунок на 1200: 1200 > 1000 * 1,1 = 1100,
        тому відхилення рахується і додає 15 балів."""
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "order_line": [(0, 0, {
                "product_id": self.product_a.id,
                "product_qty": 10,
                "price_unit": 100.0,
                "tax_ids": [(5, 0, 0)],
            })],
        })
        order.button_confirm()
        self.assertAlmostEqual(order.amount_total, 1000.0, 2)
        order.action_create_invoice()
        bill = order.invoice_ids
        bill.invoice_date = fields.Date.context_today(self)
        bill.invoice_line_ids.price_unit = 120.0
        bill.action_post()
        self.assertAlmostEqual(bill.amount_total, 1200.0, 2)
        self.vendor.invalidate_recordset()
        self.assertEqual(self.vendor.ua_purchase_overprice_count, 1)
        self.assertEqual(self.vendor.ua_supplier_risk_score, 15)

    # ==================================================================
    # 3. Запит -> замовлення
    # ==================================================================
    def test_request_to_order_keeps_qty_and_department(self):
        """Кількість 7 і підрозділ доїжджають із запиту в замовлення."""
        request = self._request(qty=7.0)
        line = request.line_ids
        request.button_to_approve()
        request.button_approved()
        wizard = self.env["purchase.request.line.make.purchase.order"].with_context(
            active_model="purchase.request.line",
            active_ids=line.ids,
            active_id=line.id,
        ).create({"supplier_id": self.vendor.id})
        wizard.make_purchase_order()
        order = line.purchase_lines.order_id
        self.assertEqual(len(order), 1)
        self.assertAlmostEqual(line.purchase_lines.product_qty, 7.0, 2)
        self.assertEqual(order.ua_department_id, self.department)
        self.assertEqual(order.ua_request_id, request)
        self.assertEqual(order.ua_expense_account_id, self.acc_92)

    def _order_from_request(self, request):
        """Провести запит чарівником OCA і віддати рядок замовлення."""
        line = request.line_ids
        request.button_to_approve()
        request.button_approved()
        wizard = self.env["purchase.request.line.make.purchase.order"].with_context(
            active_model="purchase.request.line",
            active_ids=line.ids,
            active_id=line.id,
        ).create({"supplier_id": self.vendor.id})
        wizard.make_purchase_order()
        return line.purchase_lines

    def test_order_price_from_product_when_nothing_else_is_known(self):
        """Чарівник OCA ставить нуль - рядок не має лишитися нульовим.

        Ні каталогу постачальника, ні історії закупівель: ціна береться
        з облікової ціни товару, як у звичайному замовленні Odoo.
        """
        po_line = self._order_from_request(self._request(qty=3.0))
        self.assertAlmostEqual(po_line.price_unit, 100.0, 2)
        self.assertAlmostEqual(po_line.order_id.amount_untaxed, 300.0, 2)

    def test_order_price_from_last_confirmed_order(self):
        """Історія важить більше за облікову ціну: 137,50 з минулого замовлення."""
        previous = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "order_line": [(0, 0, {
                "product_id": self.product_b.id,
                "product_qty": 10,
                "price_unit": 137.5,
                "tax_ids": [(5, 0, 0)],
            })],
        })
        previous.button_confirm()
        po_line = self._order_from_request(self._request(qty=4.0, product=self.product_b))
        self.assertAlmostEqual(po_line.price_unit, 137.5, 2)

    def test_order_price_from_posted_bill(self):
        """Замовлень не було - беремо ціну з проведеного рахунку постачальника."""
        bill = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.vendor.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": self.purchase_journal.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": self.product_b.id,
                "quantity": 5,
                "price_unit": 88.0,
                "tax_ids": [(5, 0, 0)],
                "account_id": self.acc_92.id,
            })],
        })
        bill.action_post()
        po_line = self._order_from_request(self._request(qty=2.0, product=self.product_b))
        self.assertAlmostEqual(po_line.price_unit, 88.0, 2)

    def test_order_price_from_supplierinfo_wins(self):
        """Каталог постачальника є - ціну рахує Odoo, історію не питаємо."""
        self.env["product.supplierinfo"].create({
            "partner_id": self.vendor.id,
            "product_tmpl_id": self.product_b.product_tmpl_id.id,
            "price": 61.0,
            "min_qty": 0.0,
        })
        previous = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "order_line": [(0, 0, {
                "product_id": self.product_b.id,
                "product_qty": 10,
                "price_unit": 137.5,
                "tax_ids": [(5, 0, 0)],
            })],
        })
        previous.button_confirm()
        po_line = self._order_from_request(self._request(qty=4.0, product=self.product_b))
        self.assertAlmostEqual(po_line.price_unit, 61.0, 2)

    def test_expense_account_lands_on_bill(self):
        """Рахунок витрат із замовлення перебиває рахунок з товару."""
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "ua_expense_account_id": self.acc_92.id,
            "order_line": [(0, 0, {
                "product_id": self.product_a.id,
                "product_qty": 3,
                "price_unit": 50.0,
                "tax_ids": [(5, 0, 0)],
            })],
        })
        order.button_confirm()
        order.action_create_invoice()
        bill_line = order.invoice_ids.invoice_line_ids.filtered("product_id")
        self.assertEqual(bill_line.account_id, self.acc_92)

    # ==================================================================
    # 4. Ліміт погодження
    # ==================================================================
    def test_approval_limit_blocks_plain_user(self):
        """Ліміт 1000, запит на 1500.

        Погоджувач запитів без права керівника закупівель далі не йде:
        кнопку «Погодити» в OCA бачить керівник запитів, а понад ліміт
        потрібен ще й керівник закупівель.
        """
        self.company.ua_purchase_approval_limit = 1000.0
        user = new_test_user(
            self.env, login="ua_pr_user",
            groups="purchase_request.group_purchase_request_manager",
        )
        request = self._request(estimated_cost=1500.0, user=user)
        self.assertAlmostEqual(request.estimated_cost, 1500.0, 2)
        self.assertTrue(request.ua_over_limit)
        request.button_to_approve()
        with self.assertRaises(UserError):
            request.with_user(user).button_approved()

    def test_approval_limit_passes_manager(self):
        """Той самий запит керівник закупівель погоджує."""
        self.company.ua_purchase_approval_limit = 1000.0
        manager = new_test_user(
            self.env, login="ua_pr_manager",
            groups="purchase_request.group_purchase_request_manager,"
                   "purchase.group_purchase_manager",
        )
        request = self._request(estimated_cost=1500.0)
        request.button_to_approve()
        request.with_user(manager).button_approved()
        self.assertEqual(request.state, "approved")

    def test_approval_limit_under_the_line_passes(self):
        """Ліміт 1000, запит на 900: погоджує будь-який керівник запитів."""
        self.company.ua_purchase_approval_limit = 1000.0
        user = new_test_user(
            self.env, login="ua_pr_user_small",
            groups="purchase_request.group_purchase_request_manager",
        )
        request = self._request(estimated_cost=900.0, user=user)
        self.assertFalse(request.ua_over_limit)
        request.button_to_approve()
        request.with_user(user).button_approved()
        self.assertEqual(request.state, "approved")

    def test_native_order_threshold_two_step(self):
        """Нативне погодження замовлення: поріг 1000, замовлення на 1200.

        Звичайний закупівельник дістає стан «на погодженні», керівник -
        одразу «замовлення». Наш модуль сюди не лізе, тест стереже нативне.
        """
        self.company.po_double_validation = "two_step"
        self.company.po_double_validation_amount = 1000.0
        buyer = new_test_user(
            self.env, login="ua_po_buyer", groups="purchase.group_purchase_user",
        )
        boss = new_test_user(
            self.env, login="ua_po_boss", groups="purchase.group_purchase_manager",
        )
        vals = {
            "partner_id": self.vendor.id,
            "order_line": [(0, 0, {
                "product_id": self.product_a.id,
                "product_qty": 12,
                "price_unit": 100.0,
                "tax_ids": [(5, 0, 0)],
            })],
        }
        small = self.env["purchase.order"].create(vals)
        self.assertAlmostEqual(small.amount_total, 1200.0, 2)
        small.with_user(buyer).button_confirm()
        self.assertEqual(small.state, "to approve")
        big = self.env["purchase.order"].create(vals)
        big.with_user(boss).button_confirm()
        self.assertEqual(big.state, "purchase")

    # ==================================================================
    # 5. Пад швидкого замовлення
    # ==================================================================
    def test_pad_parses_multiplier_and_semicolon(self):
        """«АРТ-001 x 5» і «АРТ-002;3» читаються як 5 і 3 штуки,
        «АРТ-001» без кількості - як одна."""
        pad = self.env["ua.purchase.pad"].create({
            "raw_text": "АРТ-001 x 5\nАРТ-002;3\nАРТ-001",
        })
        lines = pad._ua_pad_lines()
        self.assertEqual(len(lines), 2)
        by_code = {product.default_code: qty for product, qty in lines}
        # 5 з першого рядка плюс 1 з третього - однаковий артикул складається.
        self.assertAlmostEqual(by_code["АРТ-001"], 6.0, 2)
        self.assertAlmostEqual(by_code["АРТ-002"], 3.0, 2)

    def test_pad_unknown_article_is_rejected(self):
        """Невідомий артикул зупиняє пад і називається в помилці."""
        pad = self.env["ua.purchase.pad"].create({
            "raw_text": "АРТ-001 2\nАРТ-999 1",
        })
        with self.assertRaises(UserError) as caught:
            pad._ua_pad_lines()
        self.assertIn("АРТ-999", str(caught.exception))

    def test_pad_creates_request_lines(self):
        """Пад робить запит із правильними товарами, кількостями і підрозділом."""
        pad = self.env["ua.purchase.pad"].create({
            "raw_text": "АРТ-001 x 4\nАРТ-002;2",
            "department_id": self.department.id,
            "expense_account_id": self.acc_92.id,
            "description": "Ремонт цеху",
        })
        action = pad.action_create_request()
        request = self.env["purchase.request"].browse(action["res_id"])
        self.assertEqual(len(request.line_ids), 2)
        self.assertEqual(request.ua_department_id, self.department)
        self.assertEqual(request.ua_expense_account_id, self.acc_92)
        by_product = {
            line.product_id.default_code: line.product_qty
            for line in request.line_ids
        }
        self.assertAlmostEqual(by_product["АРТ-001"], 4.0, 2)
        self.assertAlmostEqual(by_product["АРТ-002"], 2.0, 2)
        # Орієнтовна вартість: (4 + 2) позицій по 100 = 600.
        self.assertAlmostEqual(request.estimated_cost, 600.0, 2)
