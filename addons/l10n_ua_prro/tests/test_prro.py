# -*- coding: utf-8 -*-
"""ПРРО: фіскальні чеки на оплати покупців.

Чек продажу на 285 грн:
    акумулятор 2 x 120,00 з ПДВ 20% (включено, літера А)         = 240,00
    кабель 1 x 50,00, знижка 10%, без ПДВ (літера Е)              =  45,00
                                                                  -------
                                                                   285,00

Частина 100 грн ділиться пропорційно ставкам: 45/285 = 15,79 (Е), решта 84,21 (А).

У мережу ніхто не ходить: міст підміняється на bp.bridge._call.
Запуск: чиста база, тег ua_prro.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

BRIDGE = "odoo.addons.bp_bridge.models.bridge.Bridge._call"
CENT = 0.005


@tagged("post_install", "-at_install", "ua_prro")
class TestUaPrro(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vat = cls.env["account.tax"].create({
            "name": "ПДВ 20% у ціні (тест)", "amount": 20.0, "amount_type": "percent",
            "type_tax_use": "sale", "price_include_override": "tax_included",
            "ua_prro_letter": "А", "company_id": cls.company.id})
        cls.no_vat = cls.env["account.tax"].create({
            "name": "Без ПДВ (тест)", "amount": 0.0, "amount_type": "percent",
            "type_tax_use": "sale", "ua_prro_letter": "Е", "company_id": cls.company.id})
        cls.battery = cls.env["product.product"].create({
            "name": "Акумулятор 6S (тест)", "default_code": "BAT6S", "barcode": "4820000000017"})
        cls.cable = cls.env["product.product"].create({"name": "Кабель XT60 (тест)"})
        cls.customer = cls.env["res.partner"].create({"name": "Покупець (тест)",
                                                      "email": "buyer@example.com"})
        cls.register = cls.env["ua.prro.register"].create({"name": "Каса магазину (тест)"})
        cls.cash = cls.env["account.journal"].create({
            "name": "Каса магазину (тест)", "type": "cash", "code": "KSM",
            "company_id": cls.company.id, "ua_prro_register_id": cls.register.id})
        cls.terminal = cls.env["account.journal"].create({
            "name": "Термінал (тест)", "type": "bank", "code": "TRM",
            "company_id": cls.company.id, "ua_prro_register_id": cls.register.id})

    # --- службове -------------------------------------------------------

    def _invoice(self, move_type="out_receipt"):
        move = self.env["account.move"].create({
            "move_type": move_type, "partner_id": self.customer.id, "invoice_date": "2026-11-05",
            "invoice_line_ids": [
                (0, 0, {"product_id": self.battery.id, "quantity": 2.0, "price_unit": 120.0,
                        "tax_ids": [(6, 0, self.vat.ids)]}),
                (0, 0, {"product_id": self.cable.id, "quantity": 1.0, "price_unit": 50.0,
                        "discount": 10.0, "tax_ids": [(6, 0, self.no_vat.ids)]}),
            ]})
        move.action_post()
        self.assertAlmostEqual(move.amount_total, 285.0, delta=CENT)
        return move

    def _pay(self, moves, journal, amount=None):
        values = {"journal_id": journal.id, "payment_date": "2026-11-05"}
        if amount is not None:
            values["amount"] = amount
        wizard = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=moves.ids).create(values)
        return wizard._create_payments()

    def _bridge_mode(self):
        self.register.write({"mode": "bridge", "fiscal_number": "4000123456"})

    @staticmethod
    def _answer(routes, calls):
        def call(_self, method, path, payload=None, params=None, timeout=60):
            calls.append((path, payload))
            answer = routes[path]
            return answer(payload) if callable(answer) else answer
        return call

    # --- 1. Чек по товарах -----------------------------------------------------

    def test_01_full_payment_gives_itemised_receipt(self):
        move = self._invoice()
        payment = self._pay(move, self.cash)
        receipt = move.ua_prro_receipt_ids
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt.payment_id, payment)
        self.assertEqual(payment.ua_prro_receipt_ids, receipt)
        self.assertEqual((receipt.kind, receipt.payment_type, receipt.state),
                         ("sale", "cash", "done"))
        self.assertTrue(receipt.fiscal_code.startswith("ТЕСТ-"), "навчальний режим")
        self.assertAlmostEqual(receipt.amount_total, 285.0, delta=CENT)
        rows = [(l.product_id, l.quantity, round(l.price_unit, 2), round(l.discount_amount, 2),
                 round(l.amount, 2), l.tax_rate, l.tax_letter) for l in receipt.line_ids]
        self.assertEqual(rows, [(self.battery, 2.0, 120.0, 0.0, 240.0, 20.0, "А"),
                                (self.cable, 1.0, 50.0, 5.0, 45.0, 0.0, "Е")])
        shift = self.register.current_shift_id
        self.assertEqual(receipt.shift_id, shift)
        self.assertEqual(shift.receipt_count, 1)
        self.assertAlmostEqual(shift.sales_cash, 285.0, delta=CENT)
        self.assertEqual(move.ua_prro_receipt_count, 1)

    def test_02_partial_payment_split_by_vat_rate(self):
        move = self._invoice("out_invoice")
        self._pay(move, self.cash, amount=100.0)
        receipt = move.ua_prro_receipt_ids
        self.assertAlmostEqual(receipt.amount_total, 100.0, delta=CENT)
        rows = [(round(l.amount, 2), l.tax_rate, l.tax_letter) for l in receipt.line_ids]
        self.assertEqual(rows, [(15.79, 0.0, "Е"), (84.21, 20.0, "А")])
        self.assertIn(move.name, receipt.line_ids[0].name)
        self.assertIn("ПДВ 20%", receipt.line_ids[1].name)

    def test_03_journal_without_register_gives_no_receipt(self):
        move = self._invoice()
        self._pay(move, self.company_data["default_journal_bank"])
        self.assertFalse(move.ua_prro_receipt_ids)

    # --- 2. Через міст ----------------------------------------------------

    def test_04_bridge_payload_and_answer(self):
        self._bridge_mode()
        calls = []
        routes = {"/api/prro/receipts": (201, {
            "fiscal_code": "FN-3001", "fiscal_date": "2026-11-05 10:15:00",
            "url": "https://check.example/FN-3001", "shift": "shift-77"})}
        move = self._invoice()
        with patch(BRIDGE, self._answer(routes, calls)):
            self._pay(move, self.terminal)
        receipt = move.ua_prro_receipt_ids
        self.assertEqual((receipt.state, receipt.fiscal_code, receipt.receipt_url),
                         ("done", "FN-3001", "https://check.example/FN-3001"))
        self.assertEqual(receipt.shift_id.provider_shift_id, "shift-77")
        self.assertEqual(len(calls), 1)
        path, payload = calls[0]
        self.assertEqual(path, "/api/prro/receipts")
        self.assertEqual(payload["id"], receipt.uuid)
        self.assertEqual((payload["register"], payload["kind"], payload["total"]),
                         ("4000123456", "sale", 285.0))
        self.assertEqual(payload["payments"], [{"type": "card", "sum": 285.0}])
        self.assertEqual(payload["email"], "buyer@example.com")
        battery = payload["goods"][0]
        self.assertEqual((battery["code"], battery["barcode"], battery["quantity"],
                          battery["price"], battery["sum"]),
                         ("BAT6S", "4820000000017", 2.0, 120.0, 240.0))
        self.assertEqual(battery["taxes"], [{"rate": 20.0, "letter": "А"}])
        self.assertEqual(payload["goods"][1]["discount"], 5.0)

    def test_05_failure_keeps_payment_and_retry_uses_same_key(self):
        self._bridge_mode()
        calls = []
        move = self._invoice()
        with patch(BRIDGE, self._answer(
                {"/api/prro/receipts": (502, {"error": "Сервіс ПРРО недоступний"})}, calls)):
            payment = self._pay(move, self.cash)
        receipt = move.ua_prro_receipt_ids
        self.assertTrue(payment.exists(), "збій сервісу не скасовує оплату")
        self.assertEqual((receipt.state, receipt.attempts), ("error", 1))
        self.assertIn("недоступний", receipt.error)

        with patch(BRIDGE, side_effect=UserError("Міст недоступний: timeout")):
            receipt.action_send()
        self.assertEqual((receipt.state, receipt.attempts), ("error", 2))

        with patch(BRIDGE, self._answer(
                {"/api/prro/receipts": (200, {"fiscal_code": "FN-9", "offline": True})}, calls)):
            self.env["ua.prro.receipt"]._cron_retry()
        self.assertEqual((receipt.state, receipt.fiscal_code, receipt.attempts),
                         ("done", "FN-9", 3))
        self.assertTrue(receipt.offline)
        self.assertFalse(receipt.error)
        self.assertEqual({payload["id"] for _path, payload in calls}, {receipt.uuid},
                         "повтор іде з тим самим ключем")

    def test_06_bridge_mode_needs_fiscal_number(self):
        with self.assertRaises(UserError):
            self.env["ua.prro.register"].create({"name": "Без номера (тест)", "mode": "bridge"})

    # --- 3. Повернення ---------------------------------------------------

    def test_07_return_refers_to_sale_receipt(self):
        move = self._invoice("out_invoice")
        self._pay(move, self.cash)
        sale = move.ua_prro_receipt_ids
        refund = move._reverse_moves([{"invoice_date": "2026-11-06", "date": "2026-11-06"}])
        refund.action_post()
        self._pay(refund, self.cash)
        back = refund.ua_prro_receipt_ids
        self.assertEqual((back.kind, back.state, back.related_id), ("return", "done", sale))
        self.assertAlmostEqual(back.amount_total, 285.0, delta=CENT)
        self.assertEqual(back._payload()["related"], sale.fiscal_code)
        shift = back.shift_id
        self.assertAlmostEqual(shift.returns_total, 285.0, delta=CENT)
        self.assertAlmostEqual(shift.cash_balance, 0.0, delta=CENT)

    def test_08_return_without_fiscal_sale_waits(self):
        move = self._invoice("out_invoice")
        self._pay(move, self.company_data["default_journal_bank"])  # без каси - без чека
        refund = move._reverse_moves([{"invoice_date": "2026-11-06", "date": "2026-11-06"}])
        refund.action_post()
        self._pay(refund, self.cash)
        back = refund.ua_prro_receipt_ids
        self.assertEqual(back.state, "error")
        self.assertIn("чека продажу", back.error)

    # --- 4. Зміна і Z-звіт ------------------------------------------------

    def test_09_service_operations_and_z_report(self):
        cash_in = self.register.service_operation("service_in", 500.0)
        self.assertEqual((cash_in.state, cash_in.kind), ("done", "service_in"))
        self.assertNotIn("goods", cash_in._payload())
        self._pay(self._invoice(), self.cash)
        self.register.service_operation("service_out", 200.0)
        shift = self.register.current_shift_id
        self.assertAlmostEqual(shift.cash_balance, 585.0, delta=CENT)  # 500 + 285 - 200
        with self.assertRaises(UserError):
            self.register.service_operation("service_out", 0.0)

        pending = self.env["ua.prro.receipt"].create({
            "register_id": self.register.id, "kind": "service_in", "service_amount": 10.0,
            "shift_id": shift.id})
        with self.assertRaises(UserError):
            shift.action_close()  # ненадісланий чек
        pending.action_cancel()

        self.register.action_close_shift()
        self.assertEqual(shift.state, "closed")
        self.assertTrue(shift.z_number.startswith("Z-ТЕСТ-"))
        self.assertFalse(self.register.current_shift_id)
        self._pay(self._invoice(), self.cash)
        self.assertNotEqual(self.register.current_shift_id, shift, "наступний чек - нова зміна")

    def test_10_z_report_mismatch_is_flagged(self):
        self._bridge_mode()
        calls = []
        receipts = iter(range(1, 10))
        routes = {
            "/api/prro/receipts": lambda payload: (201, {"fiscal_code": "FN-%s" % next(receipts)}),
            "/api/prro/shifts/close": (200, {"z_number": "Z-15", "url": "https://check.example/z15",
                                             "totals": {"sales": 280.0, "returns": 0.0}}),
        }
        with patch(BRIDGE, self._answer(routes, calls)):
            self._pay(self._invoice(), self.cash)
            shift = self.register.current_shift_id
            shift.action_close()
        self.assertEqual((shift.z_number, shift.z_mismatch), ("Z-15", True))
        self.assertTrue(any("не збігається" in (m.body or "") for m in shift.message_ids))
        self.assertEqual(calls[-1][1]["totals"]["sales"], 285.0)

        routes["/api/prro/shifts/close"] = (200, {"z_number": "Z-16", "totals": {"sales": 285.0}})
        with patch(BRIDGE, self._answer(routes, calls)):
            self._pay(self._invoice(), self.cash)
            second = self.register.current_shift_id
            second.action_close()
        self.assertFalse(second.z_mismatch)

    def test_11_sent_receipt_is_kept(self):
        move = self._invoice()
        self._pay(move, self.cash)
        receipt = move.ua_prro_receipt_ids
        with self.assertRaises(UserError):
            receipt.action_cancel()
        with self.assertRaises(UserError):
            receipt.unlink()
        with self.assertRaises(UserError):
            receipt.action_send()
