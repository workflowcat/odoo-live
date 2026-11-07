# -*- coding: utf-8 -*-
"""ЕДО з контрагентами: відправка через міст, стан, повтор, відхилення, акт звірки, вхідні.

Міст підмінено: відповіді задає тест, запити записуються. Покупець «ТОВ Покупець ЕДО»
(ЄДРПОУ 12345678), компанія - 87654321. Рахунок на 1 500 без ПДВ, послуга - тож форма за
замовчуванням - акт виконаних робіт.

Запуск: чиста база, тег ua_edo.
"""
import base64
from datetime import date, datetime
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

BRIDGE = "odoo.addons.bp_bridge.models.bridge.Bridge._call"


class FakeBridge:
    """Відповіді за (метод, шлях); кожен запит пишеться в calls."""

    def __init__(self):
        self.routes, self.calls = {}, []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        answer = self.routes.get((method, path), (404, {"error": "немає маршруту %s" % path}))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def patch(self):
        fake = self

        def call(_self, method, path, payload=None, params=None, timeout=60):
            return fake(method, path, payload)
        return patch(BRIDGE, call)

    def sent(self, method, path):
        return [payload for m, p, payload in self.calls if (m, p) == (method, path)]


def b64(raw):
    return base64.b64encode(raw).decode()


@tagged("post_install", "-at_install", "ua_edo")
class TestUaEdo(TransactionCase):

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
        cls.company.write({"company_registry": "87654321", "ua_edo_mode": "test",
                           "ua_edo_provider": "vchasno"})
        cls.income = cls.env["account.account"].search(
            [("code", "=like", "70%"), ("company_ids", "in", cls.company.id)], limit=1, order="code")
        cls.sale_journal = cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", cls.company.id)], limit=1)
        cls.customer = cls.env["res.partner"].create({
            "name": "ТОВ Покупець ЕДО", "is_company": True, "company_registry": "12345678",
            "email": "buyer@edo.example"})
        cls.no_code = cls.env["res.partner"].create({"name": "Покупець без коду", "is_company": True})
        cls.vendor = cls.env["res.partner"].create({
            "name": "ТОВ Постачальник ЕДО", "is_company": True, "company_registry": "22223333"})
        cls.Document = cls.env["ua.edo.document"]
        cls.Wizard = cls.env["ua.edo.send.wizard"]

    # ------------------------------------------------------------- службове
    def _invoice(self, partner=None, amount=1500.0, post=True):
        move = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": (partner or self.customer).id,
            "invoice_date": date(2026, 10, 20), "journal_id": self.sale_journal.id,
            "invoice_line_ids": [Command.create({
                "name": "Обслуговування обладнання", "quantity": 1, "price_unit": amount,
                "tax_ids": [Command.clear()], "account_id": self.income.id})]})
        if post:
            move.action_post()
        return move

    def _wizard(self, records, **values):
        action = records.action_ua_edo_send() if len(records) == 1 else \
            self.Wizard.action_open(records)
        wizard = self.Wizard.with_context(action["context"]).create(values)
        return wizard

    def _send(self, records, **values):
        result = self._wizard(records, **values).action_send()
        return self.Document.search(result["domain"])

    def _bridge_mode(self):
        self.company.ua_edo_mode = "bridge"

    # ---------------------------------------------------------------- тести
    def test_01_test_mode_send_and_no_double_send(self):
        invoice = self._invoice()
        wizard = self._wizard(invoice)
        self.assertEqual(wizard.report_id, self.env.ref("l10n_ua_docs.action_report_ua_service_act"))
        self.assertEqual((wizard.kind, wizard.record_count, wizard.already_count), ("act", 1, 0))
        result = wizard.action_send()
        doc = self.Document.browse(result["res_id"])
        self.assertEqual(doc.state, "sent")
        self.assertTrue(doc.provider_id.startswith("ТЕСТ-"))
        self.assertEqual((doc.partner_id, doc.partner_code, doc.amount, doc.doc_number),
                         (self.customer, "12345678", 1500.0, invoice.name))
        self.assertTrue(doc.attachment_id.raw)
        self.assertIn(invoice.name.replace("/", "-"), doc.attachment_id.name)  # назва з друку звіту
        invoice.invalidate_recordset()
        self.assertEqual((invoice.ua_edo_count, invoice.ua_edo_state), (1, "sent"))
        self.assertEqual(doc.source_name, invoice.display_name)

        again = self._wizard(invoice)
        self.assertEqual(again.already_count, 1)
        self.assertFalse(self.Document.search(again.action_send()["domain"]),
                         "переданий акт удруге не йде")
        with self.assertRaises(UserError):
            self._wizard(self._invoice(post=False)).action_send()

    def test_02_bridge_send_status_and_signature(self):
        self._bridge_mode()
        invoice = self._invoice()
        bridge = FakeBridge()
        bridge.routes[("POST", "/api/edo/documents")] = (
            201, {"id": "V-1", "status": "to_sign", "url": "https://edo.example/d/V-1"})
        with bridge.patch():
            doc = self._send(invoice)
        self.assertEqual((doc.state, doc.provider_id, doc.provider_status, doc.attempts),
                         ("sent", "V-1", "to_sign", 1))
        [payload] = bridge.sent("POST", "/api/edo/documents")
        self.assertEqual(payload["id"], doc.uuid)
        self.assertEqual((payload["kind"], payload["number"], payload["amount"]),
                         ("act", invoice.name, 1500.0))
        self.assertEqual(payload["recipient"], {"code": "12345678", "name": "ТОВ Покупець ЕДО",
                                                "email": "buyer@edo.example"})
        self.assertEqual(payload["sender"]["code"], "87654321")
        self.assertEqual(base64.b64decode(payload["file"]["data"]), doc.attachment_id.raw)

        bridge.routes[("GET", "/api/edo/documents/V-1")] = (200, {"status": "delivered"})
        with bridge.patch():
            doc.action_refresh()
        self.assertEqual(doc.state, "delivered")

        bridge.routes[("GET", "/api/edo/documents/V-1")] = (200, {
            "status": "signed", "signed_at": "2026-11-05T10:15:00Z",
            "signed_file": {"name": "act-signed.p7s", "mimetype": "application/pkcs7-signature",
                            "data": b64(b"SIGNATURE")}})
        bridge.routes[("POST", "/api/edo/inbox")] = (200, {"documents": []})
        with bridge.patch():
            self.Document._cron_refresh()
        self.assertEqual((doc.state, doc.signed_how), ("signed", "edo"))
        self.assertEqual(doc.date_signed, datetime(2026, 11, 5, 10, 15))
        self.assertEqual(doc.signed_attachment_id.raw, b"SIGNATURE")
        self.assertTrue(invoice.message_ids.filtered(lambda m: "підписано контрагентом" in m.body))

    def test_03_failure_then_retry_with_same_key(self):
        self._bridge_mode()
        invoice = self._invoice()
        bridge = FakeBridge()
        bridge.routes[("POST", "/api/edo/documents")] = UserError("Міст недоступний: тайм-аут")
        with bridge.patch():
            doc = self._send(invoice)
        self.assertEqual((doc.state, doc.attempts), ("error", 1))
        self.assertIn("тайм-аут", doc.error)

        bridge.routes[("POST", "/api/edo/documents")] = (422, {"error": "Контрагента немає в сервісі"})
        with bridge.patch():
            doc.action_send()
        self.assertEqual((doc.state, doc.error), ("error", "Контрагента немає в сервісі"))

        bridge.routes[("POST", "/api/edo/documents")] = (200, {"id": "V-2", "status": "sent"})
        with bridge.patch():
            doc.action_send()
        self.assertEqual((doc.state, doc.attempts, doc.error), ("sent", 3, False))
        keys = {payload["id"] for payload in bridge.sent("POST", "/api/edo/documents")}
        self.assertEqual(keys, {doc.uuid}, "повтор іде з тим самим ключем")
        with self.assertRaises(UserError):
            doc.action_send()

    def test_04_batch_with_missing_code(self):
        good, bad = self._invoice(), self._invoice(partner=self.no_code)
        docs = self._send(good | bad)
        self.assertEqual(len(docs), 2)
        by_partner = {d.partner_id: d for d in docs}
        self.assertEqual(by_partner[self.customer].state, "sent")
        failed = by_partner[self.no_code]
        self.assertEqual(failed.state, "error")
        self.assertIn("ЄДРПОУ", failed.error)
        with self.assertRaises(UserError):
            failed.action_send()
        self.no_code.company_registry = "3012345678"  # ФОП: РНОКПП
        failed.partner_code = "3012345678"
        failed.action_send()
        self.assertEqual(failed.state, "sent")

    def test_05_rejected_by_counterparty(self):
        self._bridge_mode()
        bridge = FakeBridge()
        bridge.routes[("POST", "/api/edo/documents")] = (200, {"id": "V-3", "status": "sent"})
        bridge.routes[("GET", "/api/edo/documents/V-3")] = (
            200, {"status": "rejected", "reason": "Сума не збігається з договором"})
        invoice = self._invoice()
        with bridge.patch():
            doc = self._send(invoice)
            doc.action_refresh()
        self.assertEqual((doc.state, doc.reject_reason),
                         ("rejected", "Сума не збігається з договором"))
        self.assertEqual(doc.activity_ids.summary, "Контрагент відхилив документ ЕДО")
        self.assertTrue(invoice.message_ids.filtered(lambda m: "відхилено" in m.body))

    def test_06_reconciliation_act_follows_the_document(self):
        self._bridge_mode()
        self._invoice(amount=6000.0)
        act = self.env["ua.reconciliation.act"].create({
            "partner_id": self.customer.id, "date_from": date(2026, 10, 1),
            "date_to": date(2026, 10, 31)})
        act.action_fill()
        self.assertEqual(act.closing_balance, 6000.0)
        bridge = FakeBridge()
        bridge.routes[("POST", "/api/edo/documents")] = (200, {"id": "R-1", "status": "sent"})
        with bridge.patch():
            wizard = self._wizard(act)
            self.assertEqual(wizard.kind, "reconciliation")
            doc = self.Document.browse(wizard.action_send()["res_id"])
        self.assertEqual((doc.kind, doc.amount, act.state), ("reconciliation", 6000.0, "sent"))
        bridge.routes[("GET", "/api/edo/documents/R-1")] = (200, {"status": "signed"})
        with bridge.patch():
            doc.action_refresh()
        self.assertEqual((act.state, act.their_filled, act.difference), ("agreed", True, 0.0))

    def test_07_inbox_sign_and_reject(self):
        self._bridge_mode()
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": self.vendor.id, "ref": "ВН-17",
            "invoice_date": date(2026, 10, 31),
            "invoice_line_ids": [Command.create({"name": "Ремонт", "quantity": 1,
                                                 "price_unit": 1200.0,
                                                 "tax_ids": [Command.clear()]})]})
        inbox = {"documents": [
            {"id": "IN-1", "kind": "act", "number": "ВН-17", "date": "2026-10-31", "amount": 1200,
             "currency": "UAH", "status": "to_sign",
             "sender": {"code": "22223333", "name": "ТОВ Постачальник ЕДО"},
             "file": {"name": "act.pdf", "mimetype": "application/pdf",
                      "data": b64(b"%PDF-1.4 test")}},
            {"id": "IN-2", "kind": "weird", "number": "5",
             "sender": {"code": "99990000", "name": "Невідомий постачальник"}},
        ], "cursor": "c-2"}
        bridge = FakeBridge()
        bridge.routes[("POST", "/api/edo/inbox")] = (200, inbox)
        with bridge.patch():
            docs = self.Document._fetch_inbox(self.company)
            self.assertFalse(self.Document._fetch_inbox(self.company), "дублів немає")
        self.assertEqual(bridge.sent("POST", "/api/edo/inbox")[1]["after"], "c-2")
        known = docs.filtered(lambda d: d.provider_id == "IN-1")
        unknown = docs - known
        self.assertEqual((known.direction, known.state, known.partner_id, known.res_id),
                         ("in", "received", self.vendor, bill.id))
        self.assertEqual(known.attachment_id.raw, b"%PDF-1.4 test")
        self.assertEqual((unknown.kind, unknown.partner_id.id, unknown.partner_name),
                         ("other", False, "Невідомий постачальник"))
        self.assertIn("невідомого контрагента", unknown.activity_ids.summary)

        bridge.routes[("POST", "/api/edo/documents/IN-1/sign")] = (200, {"status": "signed"})
        bridge.routes[("POST", "/api/edo/documents/IN-2/reject")] = (200, {"status": "rejected"})
        with bridge.patch():
            known.action_sign()
            with self.assertRaises(UserError):
                unknown.action_reject()
            unknown.reject_reason = "Договору з вами немає"
            unknown.action_reject()
        self.assertEqual((known.state, unknown.state), ("signed", "rejected"))
        self.assertEqual(bridge.sent("POST", "/api/edo/documents/IN-2/reject"),
                         [{"reason": "Договору з вами немає"}])
        self.assertTrue(bill.message_ids.filtered(lambda m: "підписано" in m.body))

    def test_08_revoke_paper_and_delete(self):
        sent = self._send(self._invoice())
        with self.assertRaises(UserError):
            sent.unlink()
        sent.action_revoke()
        self.assertEqual(sent.state, "cancel")

        draft = self._send(self._invoice(), send_now=False)
        self.assertEqual(draft.state, "draft")
        with self.assertRaises(UserError):
            draft.action_mark_signed()
        draft.signed_attachment_id = self.env["ir.attachment"].create({
            "name": "скан.pdf", "raw": b"%PDF scan", "res_model": draft._name, "res_id": draft.id})
        draft.action_mark_signed()
        self.assertEqual((draft.state, draft.signed_how), ("signed", "paper"))

        spare = self._send(self._invoice(), send_now=False)
        spare.unlink()
        self.assertFalse(spare.exists())
