# -*- coding: utf-8 -*-
"""Incoming invoice email -> intake -> unverified supplier -> ЄДР -> draft bill. Workers AI and the bridge are mocked."""
import copy
from datetime import date
from email.message import EmailMessage
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models import codes

NOVA = {
    "doc_type": "invoice", "number": "НП-2026-0917", "date": "2026-09-12", "due_date": "2026-09-22", "currency": "UAH",
    "contract": "Договір № 12-ПД від 03.02.2026",
    "supplier": {"name": "ТОВ «Нова Пошта»", "code": "31316718", "ipn": "313167116014",
                 "iban": "UA863052990000026004000123456", "bank": "АТ КБ «ПриватБанк»",
                 "address": "03045, м. Київ, Столичне шосе, 103, корп. 1", "email": "invoices@novaposhta-billing.example"},
    "buyer": {"name": "ТОВ «Ясен Меблі»", "code": "43715285"},
    "lines": [{"name": "Послуги з доставки відправлень за серпень 2026", "quantity": 1, "uom": "послуга", "price_unit": 12500, "amount": 12500},
              {"name": "Пакування відправлень", "quantity": 40, "uom": "шт", "price_unit": 35, "amount": 1400},
              {"name": "Зберігання вантажу на складі", "quantity": 1, "uom": "міс.", "price_unit": 2100, "amount": 2100}],
    "amount_untaxed": 16000, "vat_rate": 20, "amount_tax": 3200, "amount_total": 19200,
}
BAD = {
    "doc_type": "invoice", "number": "ВП-118", "date": "2026-09-10", "due_date": "", "currency": "UAH", "contract": "",
    "supplier": {"name": "ТОВ «Вигадка Постач»", "code": "12345670", "ipn": "", "iban": "UA213223130000026007233566001",
                 "bank": "АТ «Банк Вигадка»", "address": "01001, м. Київ, вул. Неіснуюча, 1", "email": "office@vygadka.example"},
    "buyer": {"name": "ТОВ «Ясен Меблі»", "code": "43715285"},
    "lines": [{"name": "Папір офісний А4", "quantity": 20, "uom": "пач.", "price_unit": 250, "amount": 5000},
              {"name": "Картридж HP 85A", "quantity": 5, "uom": "шт", "price_unit": 1000, "amount": 5000}],
    "amount_untaxed": 10000, "vat_rate": 20, "amount_tax": 2000, "amount_total": 12600,
}
REGISTRY = {
    "code": "31316718", "kind": "company", "cached": False,
    "registry": {"full_name": 'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "НОВА ПОШТА"', "short_name": 'ТОВ "НОВА ПОШТА"',
                 "status": "зареєстровано", "registration_date": "2001-01-19", "head": "Тафійчук Євген Олександрович",
                 "kved": "53.20 Інша поштова та кур'єрська діяльність", "vat_status": "active", "vat_code": "313167116014",
                 "address": "Україна, 03045, місто Київ, Столичне шосе, будинок 103", "email": "", "beneficiaries": []},
    "checks": [{"key": "status", "title": "Стан у ЄДР", "severity": "info", "present": False, "detail": "зареєстровано"},
               {"key": "tax_debts", "title": "Податковий борг", "severity": "warn", "present": True, "detail": "є борг"}],
}


def make_email(subject, msgid, with_pdf=True, image=False):
    msg = EmailMessage()
    msg["From"] = "Бухгалтерія <invoices@novaposhta-billing.example>"
    msg["To"] = "rahunky@yasen-mebli.example"
    msg["Subject"] = subject
    msg["Message-Id"] = msgid
    msg.set_content("Рахунок у вкладенні.")
    if image:
        msg.add_attachment(b"\xff\xd8\xff\xe0 fake jpeg", maintype="image", subtype="jpeg", filename="IMG_0001.jpg")
    elif with_pdf:
        msg.add_attachment(b"%PDF-1.4 test invoice", maintype="application", subtype="pdf", filename="rahunok.pdf")
    return bytes(msg).decode()


@tagged("post_install", "-at_install", "bp_purchase_intake")
class TestCodes(TransactionCase):
    def test_codes(self):
        self.assertTrue(codes.edrpou_valid("31316718"))
        self.assertTrue(codes.edrpou_valid("14360570"))
        self.assertFalse(codes.edrpou_valid("12345670"))
        self.assertTrue(codes.iban_valid("UA86 3052 9900 0002 6004 0001 2345 6"))
        self.assertFalse(codes.iban_valid("UA863052990000026004000123457"))
        self.assertEqual(codes.parse_date("12 вересня 2026 р."), date(2026, 9, 12))
        self.assertEqual(codes.parse_date("03.02.2026"), date(2026, 2, 3))
        self.assertEqual(codes.to_float("12 500,00"), 12500.0)
        self.assertEqual(codes.name_key("ТОВ «Нова Пошта»"), codes.name_key('ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "НОВА ПОШТА"'))


@tagged("post_install", "-at_install", "bp_purchase_intake")
class TestIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # податок закупівлі 20 % приходить з планом рахунків; на свіжій базі його немає
        ukraine = cls.env.ref("base.ua")
        if cls.env.company.country_id != ukraine:
            cls.env.company.country_id = ukraine
        if cls.env.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.env.company, install_demo=False)
        cls.env.company.invalidate_recordset()
        cls.env.company.company_registry = "43715285"
        cls.Intake = cls.env["bp.purchase.intake"]
        # the stand may hold records from scripts/intake_check.py with the same codes; clear them inside the test transaction
        codes_used = ["31316718", "12345670"]
        live = cls.Intake.search([("supplier_code", "in", codes_used)])
        cls.env["account.move"].search([("bp_intake_id", "in", live.ids)]).unlink()
        live.unlink()
        cls.env["res.partner"].with_context(active_test=False).search([("company_registry", "in", codes_used)]).unlink()

    def receive(self, doc, subject="Рахунок № НП-2026-0917", msgid="<t1@test>", with_pdf=True, registry=None, image=False, status=200):
        calls = []
        seen = {}
        registry = registry or REGISTRY

        def fake_md(_self, filename, content, mimetype="application/pdf"):
            return "Рахунок на оплату від постачальника, позиції і суми. " * 3, 42

        def fake_json(_self, spec, text=None, images=None):
            seen["images"] = len(images or [])
            return copy.deepcopy(doc), {"neurons": 55.0}, "@cf/test/model"

        def fake_call(_self, method, path, payload=None, params=None, timeout=60):
            calls.append(path)
            return status, copy.deepcopy(registry)

        with patch.object(type(self.env["bp.ai"]), "to_markdown", fake_md), \
                patch.object(type(self.env["bp.ai"]), "extract_json", fake_json), \
                patch.object(type(self.env["bp.bridge"]), "_call", fake_call):
            thread_id = self.env["mail.thread"].message_process("bp.purchase.intake", make_email(subject, msgid, with_pdf, image))
        self.seen = seen
        return self.Intake.browse(thread_id), calls

    def levels(self, intake):
        return {c.key: c.level for c in intake.check_ids}

    def test_email_creates_unverified_supplier_and_draft_bill(self):
        intake, calls = self.receive(NOVA)
        self.assertEqual(intake.state, "bill", intake.check_ids.mapped(lambda c: (c.key, c.level, c.detail)))
        self.assertTrue(intake.attachment_id)
        self.assertIn("invoices@novaposhta-billing.example", intake.email_from)
        partner = intake.partner_id
        self.assertEqual(partner.company_registry, "31316718")
        self.assertEqual(partner.bp_supplier_status, "unverified")
        self.assertEqual(partner.bp_registry_head, "Тафійчук Євген Олександрович")
        self.assertIn("Податковий борг", partner.bp_registry_markers)
        # base_iban (приходить з OCA account_payment_order) зберігає номер згрупованим
        # по чотири; цифри ті самі, форма запису - справа Odoo.
        self.assertEqual("".join(partner.bank_ids.acc_number.split()),
                         "UA863052990000026004000123456")
        self.assertEqual(calls, ["/api/odb/screen/31316718"])
        move = intake.move_id
        self.assertEqual((move.move_type, move.state, move.ref), ("in_invoice", "draft", "НП-2026-0917"))
        self.assertAlmostEqual(move.amount_total, 19200.0, places=2)
        self.assertAlmostEqual(move.amount_tax, 3200.0, places=2)
        self.assertTrue(move.message_main_attachment_id)
        self.assertEqual(intake.error_count, 0)
        lv = self.levels(intake)
        self.assertEqual((lv["code"], lv["iban"], lv["total"], lv["registry_vat"], lv["odb_tax_debts"]), ("ok", "ok", "ok", "ok", "warn"))

    def test_posting_blocked_until_supplier_verified(self):
        intake, _ = self.receive(NOVA)
        with self.assertRaises(UserError):
            intake.move_id.action_post()
        intake.partner_id.action_bp_mark_verified()
        intake.move_id.action_post()
        self.assertEqual(intake.move_id.state, "posted")

    def test_second_email_is_duplicate(self):
        first, _ = self.receive(NOVA)
        second, _ = self.receive(NOVA, subject="Повторно: Рахунок № НП-2026-0917", msgid="<t2@test>")
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.duplicate_of_id, first)
        self.assertFalse(second.move_id)
        self.assertEqual(second.partner_id, first.partner_id)
        self.assertEqual(self.levels(second)["iban_known"], "ok")

    def test_bad_document_goes_to_review_without_registry_call(self):
        intake, calls = self.receive(BAD, subject="Рахунок № ВП-118", msgid="<t3@test>")
        self.assertEqual(intake.state, "review")
        self.assertFalse(intake.move_id)
        lv = self.levels(intake)
        self.assertEqual((lv["code"], lv["total"]), ("error", "error"))
        self.assertEqual(calls, [])
        self.assertEqual(intake.partner_id.bp_supplier_status, "unverified")

    def test_changed_iban_for_known_supplier_stops_the_bill(self):
        partner = self.env["res.partner"].create({"name": "Нова Пошта", "is_company": True, "company_registry": "31316718",
                                                  "bp_supplier_status": "verified"})
        self.env["res.partner.bank"].create({"partner_id": partner.id, "acc_number": "UA213223130000026007233566001"})
        intake, _ = self.receive(NOVA, msgid="<t4@test>")
        self.assertEqual(intake.partner_id, partner)
        self.assertEqual(self.levels(intake)["iban_known"], "error")
        self.assertEqual(intake.state, "review")
        self.assertFalse(intake.move_id)
        self.assertEqual(len(partner.bank_ids), 1)

    def test_invoice_for_another_company(self):
        doc = copy.deepcopy(NOVA)
        doc["buyer"] = {"name": "ТОВ «Інша»", "code": "14360570"}
        intake, _ = self.receive(doc, msgid="<t5@test>")
        self.assertEqual(self.levels(intake)["buyer"], "error")
        self.assertEqual(intake.state, "review")

    def test_email_without_pdf(self):
        intake, _ = self.receive(NOVA, msgid="<t6@test>", with_pdf=False)
        self.assertEqual(intake.state, "error")
        self.assertIn("PDF", intake.error_message)

    def test_photo_attachment_is_read_as_image(self):
        intake, _ = self.receive(NOVA, msgid="<t7@test>", image=True)
        self.assertEqual(intake.source_kind, "image")
        self.assertEqual(self.seen["images"], 1)
        self.assertEqual(intake.state, "bill")

    def test_tax_invoice_is_not_billed(self):
        doc = copy.deepcopy(NOVA)
        doc["doc_type"] = "tax_invoice"
        intake, _ = self.receive(doc, msgid="<t8@test>")
        self.assertEqual(self.levels(intake)["doc_type"], "error")
        self.assertEqual(intake.state, "review")
        self.assertFalse(intake.move_id)

    def test_supplier_missing_from_registry(self):
        intake, _ = self.receive(NOVA, msgid="<t9@test>", registry={"error": "ЄДР не знайшов юрособу з таким кодом"}, status=502)
        self.assertEqual(self.levels(intake)["registry"], "error")
        self.assertEqual(intake.state, "review")
        other, _ = self.receive(BAD | {"supplier": NOVA["supplier"] | {"code": "0000145820", "ipn": ""}, "number": "14",
                                       "amount_total": 12000, "vat_rate": 20},
                                msgid="<t11@test>", registry={"error": 'OpenDataBot 404: {"error":"Edr unexpected status"}'}, status=502)
        self.assertEqual(self.levels(other)["registry"], "error")

    def test_prices_with_vat(self):
        doc = copy.deepcopy(NOVA)
        doc.update({"prices_include_vat": True, "amount_untaxed": 15900, "amount_tax": 3200, "amount_total": 19200,
                    "lines": [{"name": "Послуги", "quantity": 1, "uom": "послуга", "price_unit": 15000, "amount": 15000},
                              {"name": "Пакування", "quantity": 40, "uom": "шт", "price_unit": 42, "amount": 1680},
                              {"name": "Зберігання", "quantity": 1, "uom": "міс.", "price_unit": 2520, "amount": 2520}]})
        intake, _ = self.receive(doc, msgid="<t10@test>")
        self.assertAlmostEqual(intake.amount_untaxed, 16000.0, places=2)
        self.assertEqual(self.levels(intake)["lines"], "ok")
        self.assertEqual(intake.state, "bill")
        self.assertAlmostEqual(intake.move_id.amount_total, 19200.0, places=2)
