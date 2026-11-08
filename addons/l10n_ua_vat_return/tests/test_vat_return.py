# -*- coding: utf-8 -*-
"""Декларація з ПДВ і Д2: рядки зі зведення, підсумки 9-21, перенос між місяцями, XML за схемою.

Числа пораховані руками в коментарях поруч. Компанія тестова, реквізити вигадані.
"""
import base64
import datetime

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

DETAILS = {
    "sti_code": "2650",
    "sti_name": "ГУ ДПС у м. Києві",
    "address": "01001, м. Київ, вул. Вигадана, 1",
    "phone": "044 000 00 00",
    "email": "office@example.com",
    "director": "Петренко Олена",
    "director_rnokpp": "1234567890",
    "accountant": "Коваль Іван",
    "accountant_rnokpp": "2345678901",
}


@tagged("post_install", "-at_install", "ua_vat_return")
class TestUaVatReturn(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({"vat": "1234567890", "company_registry": "43217890", "zip": "01001"})
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_sale_20 = chart.ref("sale_tax_template_vat20_psbo")
        cls.tax_purchase_20 = chart.ref("purchase_tax_template_vat20_psbo")
        country = cls.env.ref("base.ua").id
        cls.payer = cls.env["res.partner"].create({
            "name": "ТОВ Покупець", "ua_vat_payer_status": "payer", "vat": "9988776655", "country_id": country})
        cls.vendor = cls.env["res.partner"].create({
            "name": "ТОВ Постачальник", "ua_vat_payer_status": "payer", "vat": "1122334455",
            "country_id": country})
        cls.vendor2 = cls.env["res.partner"].create({
            "name": "ТОВ Другий постачальник", "ua_vat_payer_status": "payer", "vat": "5566778899",
            "country_id": country})
        cls.goods = cls.env["product.product"].create({"name": "Кронштейн", "type": "consu"})

    def _invoice(self, partner, day, amount, move_type="out_invoice"):
        tax = self.tax_sale_20 if move_type == "out_invoice" else self.tax_purchase_20
        move = self.env["account.move"].create({
            "move_type": move_type, "partner_id": partner.id, "invoice_date": day, "date": day,
            "invoice_line_ids": [(0, 0, {"name": self.goods.name, "product_id": self.goods.id, "quantity": 1,
                                         "price_unit": amount, "tax_ids": [(6, 0, tax.ids)]})],
        })
        move.action_post()
        return move

    def _return(self, month, **vals):
        doc = self.env["ua.vat.return"].create(dict(DETAILS, year=2026, month=str(month), **vals))
        doc.action_compute()
        return doc

    @staticmethod
    def _xml(data):
        return etree.fromstring(base64.b64decode(data))

    @staticmethod
    def _row(doc, code):
        return doc.line_ids.filtered(lambda l: l.code == code)

    def test_01_positive_month(self):
        """Продаж 10 000 + 2 000 ПДВ, купівля 5 000 + 1 000 ПДВ: 9 = 2 000, 17 = 1 000, 18 = 1 000, без Д2."""
        self._invoice(self.payer, datetime.date(2026, 10, 10), 10000.0)
        self._invoice(self.vendor, datetime.date(2026, 10, 12), 5000.0, "in_invoice")
        doc = self._return(10)
        self.assertEqual((self._row(doc, "1.1").base, self._row(doc, "1.1").vat), (10000.0, 2000.0))
        self.assertEqual((self._row(doc, "10.1").base, self._row(doc, "10.1").vat), (5000.0, 1000.0))
        self.assertEqual((doc.r9, doc.r17, doc.r18, doc.r19, doc.r21), (2000.0, 1000.0, 1000.0, 0.0, 0.0))
        self.assertFalse(doc.d2_line_ids)
        doc.action_xml()
        self.assertFalse(doc.d2_xml_file)
        self.assertTrue(doc.xml_name.startswith("26500043217890J0200126100"), doc.xml_name)
        root = self._xml(doc.xml_file)
        head = root.find("DECLARHEAD")
        self.assertEqual((head.findtext("C_DOC"), head.findtext("C_DOC_SUB"), head.findtext("C_DOC_VER")),
                         ("J02", "001", "26"))
        self.assertEqual((head.findtext("PERIOD_TYPE"), head.findtext("PERIOD_MONTH")), ("1", "10"))
        body = root.find("DECLARBODY")
        self.assertEqual(body.findtext("HNPDV"), "1234567890")
        for tag, value in [("R11GA", "10000"), ("R11GB", "2000"), ("R101GB", "1000"), ("R90GB", "2000"),
                           ("R170GB", "1000"), ("R180GB", "1000")]:
            self.assertEqual(body.findtext(tag), value, tag)
        self.assertIsNone(body.find("HD2"))
        doc.action_done()
        self.assertEqual(doc.state, "done")

    def test_02_negative_month_with_d2(self):
        """ПЗ 200, ПК 1 000 + 400: рядок 19 = 1 200 понад Σнакл 0, увесь у 21; Д2 на двох постачальників."""
        self._invoice(self.payer, datetime.date(2026, 10, 3), 1000.0)
        self._invoice(self.vendor, datetime.date(2026, 10, 5), 5000.0, "in_invoice")
        self._invoice(self.vendor2, datetime.date(2026, 10, 20), 2000.0, "in_invoice")
        doc = self._return(10)
        self.assertEqual((doc.r9, doc.r17, doc.r18, doc.r19), (200.0, 1400.0, 0.0, 1200.0))
        self.assertEqual((doc.r19_1, doc.r20, doc.r21), (1200.0, 0.0, 1200.0))
        # Нова частина лягає з найпізнішої накладної: другий постачальник 400, перший - решта 800.
        amounts = {line.ipn: line.amount for line in doc.d2_line_ids}
        self.assertEqual(amounts, {"5566778899": 400.0, "1122334455": 800.0})
        self.assertEqual(set(doc.d2_line_ids.mapped("origin_month")), {10})
        self.assertEqual(sum(doc.d2_line_ids.mapped("carry_amount")), 1200.0)
        doc.action_xml()
        main, d2 = self._xml(doc.xml_file), self._xml(doc.d2_xml_file)
        self.assertEqual(main.find("DECLARBODY").findtext("HD2"), "1")
        link = main.find("DECLARHEAD/LINKED_DOCS/DOC")
        self.assertEqual((link.get("TYPE"), link.findtext("FILENAME")), ("1", doc.d2_xml_name))
        back = d2.find("DECLARHEAD/LINKED_DOCS/DOC")
        self.assertEqual((back.get("TYPE"), back.findtext("FILENAME")), ("2", doc.xml_name))
        body = d2.find("DECLARBODY")
        self.assertEqual([cell.get("ROWNUM") for cell in body.findall("T1RXXXXG6")], ["1", "2"])
        self.assertEqual(sorted(cell.text for cell in body.findall("T1RXXXXG4")),
                         ["1122334455", "5566778899"])
        self.assertEqual((body.findtext("R01G6"), body.findtext("R01G10")), ("1200", "1200"))

    def test_03_refund_and_carry_into_next_month(self):
        """Жовтень: 19 = 1 200, Σнакл 1 000, відшкодування 300: 19.1 = 200, 20.3 = 700, 21 = 900.
        Листопад: ПЗ 400, ПК лише 16.1 = 900: 19 = 500, Д2 - залишок жовтня, зменшений на 400."""
        self._invoice(self.payer, datetime.date(2026, 10, 3), 1000.0)
        self._invoice(self.vendor, datetime.date(2026, 10, 5), 5000.0, "in_invoice")
        self._invoice(self.vendor2, datetime.date(2026, 10, 20), 2000.0, "in_invoice")
        october = self._return(10, limit_amount=1000.0, r20_2_1=300.0)
        self.assertEqual((october.r19, october.r19_1, october.r20, october.r20_2, october.r20_3, october.r21),
                         (1200.0, 200.0, 1000.0, 300.0, 700.0, 900.0))
        self.assertEqual(sum(october.d2_line_ids.mapped("refund_amount")), 300.0)
        self.assertEqual(sum(october.d2_line_ids.mapped("carry_amount")), 900.0)
        october.action_done()

        self._invoice(self.payer, datetime.date(2026, 11, 10), 2000.0)
        november = self._return(11)
        self.assertEqual((november.r16_1, november.r9, november.r17, november.r19), (900.0, 400.0, 900.0, 500.0))
        self.assertEqual(sum(november.d2_line_ids.mapped("amount")), 500.0)
        self.assertEqual(set(november.d2_line_ids.mapped("origin_month")), {10})
        november.action_xml()
        body = self._xml(november.xml_file).find("DECLARBODY")
        self.assertEqual((body.findtext("R160GB"), body.findtext("R161GB"), body.findtext("R190GB")),
                         ("900", "900", "500"))

    def test_04_refund_over_row_20_is_refused(self):
        """Σнакл 0: рядок 20 нульовий, відшкодування 100 не проходить ні в XML, ні на затвердження."""
        self._invoice(self.payer, datetime.date(2026, 10, 3), 1000.0)
        self._invoice(self.vendor, datetime.date(2026, 10, 5), 5000.0, "in_invoice")
        doc = self._return(10, r20_2_1=100.0)
        self.assertIn("рядок 20", doc.problems)
        with self.assertRaises(UserError):
            doc.action_done()
        with self.assertRaises(UserError):
            doc.action_xml()

    def test_05_rates_go_to_their_rows(self):
        """7 % - рядки 1.2 і 10.2, 14 % - 1.3 і 10.3 (у зведенні це поля r3/pk3 і r2/pk2)."""
        summary = self.env["ua.vat.period"].create({
            "date_from": datetime.date(2026, 10, 1), "date_to": datetime.date(2026, 10, 31)})
        summary.write({"ua_r3_base": 1000.0, "ua_r3_vat": 70.0, "ua_r2_base": 1000.0, "ua_r2_vat": 140.0,
                       "ua_pk3_base": 500.0, "ua_pk3_vat": 35.0, "ua_pk2_base": 500.0, "ua_pk2_vat": 70.0,
                       "ua_customs_vat": 200.0})
        doc = self.env["ua.vat.return"].create(dict(DETAILS, year=2026, month="10"))
        rows = doc._ua_row_values(summary)
        self.assertEqual(rows["1.2"], (1000.0, 70.0))
        self.assertEqual(rows["1.3"], (1000.0, 140.0))
        self.assertEqual(rows["10.2"], (500.0, 35.0))
        self.assertEqual(rows["10.3"], (500.0, 70.0))
        self.assertEqual(rows["11.1"], (1000.0, 200.0))

    def test_06_missing_details_and_old_form(self):
        """Без коду ДПІ XML не робиться; для вересня 2024 діяла інша версія форми."""
        self._invoice(self.payer, datetime.date(2026, 10, 3), 1000.0)
        doc = self._return(10, sti_code=False)
        with self.assertRaisesRegex(UserError, "код ДПІ"):
            doc.action_xml()
        old = self.env["ua.vat.return"].create(dict(DETAILS, year=2024, month="9"))
        old.action_compute()
        with self.assertRaisesRegex(UserError, "J0200126"):
            old.action_xml()
