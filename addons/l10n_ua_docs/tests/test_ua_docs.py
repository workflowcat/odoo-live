"""Первинка: сума прописом і друковані форми.

Суми прописом звірені з формами, які бухгалтер бачить у BAS: ціла частина
словами, копійки цифрами, слова «гривня» і «копійка» узгоджені з числом.
Друковані форми перевіряються по-справжньому: рахунок будується в транзакції
тесту з планом ua_psbo і податком ПДВ 20 %, звіт рендериться в HTML, і в тексті
шукаються реквізити обох сторін, IBAN, сума, ПДВ і пропис.
"""
import re

from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from odoo.addons.l10n_ua_docs.models.tools import (
    amount_to_text_uk,
    int_to_words_uk,
    mfo_from_iban,
    plural_form,
)


@tagged("post_install", "-at_install", "ua_docs")
class TestUaDocsWords(AccountTestInvoicingCommon):
    """Сума прописом. Чиста функція, бази майже не торкається."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()

    def test_01_words_zero(self):
        """0.00 - нуль гривень, копійки теж у родовому."""
        self.assertEqual(amount_to_text_uk(0), "Нуль гривень 00 копійок")

    def test_02_words_one_kopeck(self):
        """1.01 - жіночий рід у гривні й однина в копійці."""
        self.assertEqual(amount_to_text_uk(1.01), "Одна гривня 01 копійка")

    def test_03_words_two_fifty(self):
        """2.50 - «дві гривні», не «два»; 50 копійок у родовому."""
        self.assertEqual(amount_to_text_uk(2.50), "Дві гривні 50 копійок")

    def test_04_words_eleven(self):
        """11 - виняток на -надцять: «гривень», а не «гривня»."""
        self.assertEqual(amount_to_text_uk(11), "Одинадцять гривень 00 копійок")

    def test_05_words_twenty_one(self):
        """21 - закінчення 1 дає однину: «двадцять одна гривня»."""
        self.assertEqual(amount_to_text_uk(21), "Двадцять одна гривня 00 копійок")

    def test_06_words_hundred_one(self):
        """101 - сотня плюс однина."""
        self.assertEqual(amount_to_text_uk(101), "Сто одна гривня 00 копійок")

    def test_07_words_thousand(self):
        """1 000 - «одна тисяча», але «гривень»: число кратне десяти."""
        self.assertEqual(amount_to_text_uk(1000), "Одна тисяча гривень 00 копійок")

    def test_08_words_two_thousand(self):
        """2 000 - «дві тисячі», тисяча жіночого роду."""
        self.assertEqual(amount_to_text_uk(2000), "Дві тисячі гривень 00 копійок")

    def test_09_words_five_thousand(self):
        """5 000 - родовий відмінок розряду: «п'ять тисяч»."""
        self.assertEqual(amount_to_text_uk(5000), "П'ять тисяч гривень 00 копійок")

    def test_10_words_twenty_one_thousand(self):
        """21 000 - «двадцять одна тисяча», узгодження за останньою цифрою."""
        self.assertEqual(amount_to_text_uk(21000), "Двадцять одна тисяча гривень 00 копійок")

    def test_11_words_million(self):
        """1 000 000 - мільйон чоловічого роду: «один мільйон»."""
        self.assertEqual(amount_to_text_uk(1000000), "Один мільйон гривень 00 копійок")

    def test_12_words_two_million_99(self):
        """2 000 000.99 - «два мільйони» і 99 копійок."""
        self.assertEqual(
            amount_to_text_uk(2000000.99), "Два мільйони гривень 99 копійок")

    def test_13_words_teens_and_hundreds(self):
        """Десятки, сотні й порожні розряди посередині."""
        cases = {
            12: "Дванадцять гривень 00 копійок",
            19: "Дев'ятнадцять гривень 00 копійок",
            112: "Сто дванадцять гривень 00 копійок",
            200: "Двісті гривень 00 копійок",
            999: "Дев'ятсот дев'яносто дев'ять гривень 00 копійок",
            1000001: "Один мільйон одна гривня 00 копійок",
            1000100: "Один мільйон сто гривень 00 копійок",
            1234567.89: "Один мільйон двісті тридцять чотири тисячі "
                        "п'ятсот шістдесят сім гривень 89 копійок",
        }
        for amount, expected in cases.items():
            self.assertEqual(amount_to_text_uk(amount), expected, "сума %s" % amount)

    def test_14_words_kopecks_and_rounding(self):
        """Форми копійки і заокруглення половини вгору."""
        self.assertEqual(amount_to_text_uk(5.02), "П'ять гривень 02 копійки")
        self.assertEqual(amount_to_text_uk(5.11), "П'ять гривень 11 копійок")
        self.assertEqual(amount_to_text_uk(5.21), "П'ять гривень 21 копійка")
        # 0.005 округлюється вгору до копійки, а не зникає.
        self.assertEqual(amount_to_text_uk(0.005), "Нуль гривень 01 копійка")
        # 99.999 -> 100.00, а не «дев'яносто дев'ять гривень 100 копійок».
        self.assertEqual(amount_to_text_uk(99.999), "Сто гривень 00 копійок")
        self.assertEqual(amount_to_text_uk(-1.01), "Мінус одна гривня 01 копійка")

    def test_15_plural_and_int_words(self):
        """Правило узгодження і числівник без валюти."""
        forms = ("гривня", "гривні", "гривень")
        self.assertEqual(plural_form(1, forms), "гривня")
        self.assertEqual(plural_form(11, forms), "гривень")
        self.assertEqual(plural_form(111, forms), "гривень")
        self.assertEqual(plural_form(22, forms), "гривні")
        self.assertEqual(plural_form(114, forms), "гривень")
        self.assertEqual(int_to_words_uk(2, "m"), "два")
        self.assertEqual(int_to_words_uk(2, "f"), "дві")
        self.assertEqual(int_to_words_uk(0), "нуль")

    def test_16_mfo_from_iban(self):
        """МФО - шість цифр коду банку з українського IBAN."""
        self.assertEqual(mfo_from_iban("UA213223130000026007233566001"), "322313")
        self.assertEqual(mfo_from_iban("UA21 3223 1300 0002 6007 2335 6600 1"), "322313")
        self.assertEqual(mfo_from_iban("DE89370400440532013000"), "")
        self.assertEqual(mfo_from_iban(""), "")
        self.assertEqual(mfo_from_iban(False), "")


@tagged("post_install", "-at_install", "ua_docs")
class TestUaDocsReports(AccountTestInvoicingCommon):
    """Друковані форми на справжньому проведеному рахунку."""

    IBAN = "UA213223130000026007233566001"

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "vat": "123456789012",
            "company_registry": "43217890",
            "ua_director_name": "Іваненко Іван Іванович",
            "ua_accountant_name": "Петренко Петро Петрович",
            "x_ua_acts_on_basis": "Статуту",
        })
        cls.company.partner_id.write({
            "street": "вул. Хрещатик, 1",
            "city": "Київ",
            "zip": "01001",
        })
        cls.bank = cls.env["res.partner.bank"].create({
            "acc_number": cls.IBAN,
            "partner_id": cls.company.partner_id.id,
            "bank_id": cls.env["res.bank"].create({"name": "АТ «Банк Приклад»"}).id,
            "company_id": cls.company.id,
            # Без цього Odoo не дає провести рахунок із «недовіреним» рахунком.
            "allow_out_payment": True,
        })
        cls.buyer = cls.env["res.partner"].create({
            "name": "ТОВ «Покупець»",
            "company_registry": "12345678",
            "vat": "123456789099",
            "street": "вул. Січових Стрільців, 7",
            "city": "Львів",
            "zip": "79000",
            "country_id": cls.env.ref("base.ua").id,
            "x_ua_signatory_name": "Сидоренко Сидір Сидорович",
            "x_ua_signatory_basis": "довіреності № 4 від 02.01.2026",
        })
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_20 = chart.ref("sale_tax_template_vat20_psbo")
        cls.goods = cls.env["product.product"].create({
            "name": "Стіл робочий", "type": "consu", "list_price": 5000.0,
        })
        cls.service = cls.env["product.product"].create({
            "name": "Послуга консультаційна", "type": "service", "list_price": 1000.0,
        })

    # --- Допоміжне ---------------------------------------------------------
    @classmethod
    def _invoice(cls, product, qty, price, tax, post=True):
        invoice = cls.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": cls.buyer.id,
            "invoice_date": "2026-09-21",
            "date": "2026-09-21",
            "ref": "Договір № 7 від 01.09.2026",
            "partner_bank_id": cls.bank.id,
            "invoice_line_ids": [(0, 0, {
                "name": product.name,
                "product_id": product.id,
                "quantity": qty,
                "price_unit": price,
                "tax_ids": [(6, 0, tax.ids if tax else [])],
            })],
        })
        if post:
            invoice.action_post()
        return invoice

    def _html(self, report, record):
        return self.env["ir.actions.report"]._render_qweb_html(report, record.ids)[0].decode()

    # --- Перевірки ---------------------------------------------------------
    def test_20_invoice_bill_renders(self):
        """Рахунок на оплату: обидва ЄДРПОУ, IBAN, підсумки, ПДВ, пропис."""
        # 2 столи по 5 000 = 10 000 без ПДВ; ПДВ 20 % = 2 000; разом 12 000.
        invoice = self._invoice(self.goods, 2, 5000.0, self.tax_20)
        self.assertAlmostEqual(invoice.amount_untaxed, 10000.0, delta=0.005)
        self.assertAlmostEqual(invoice.amount_tax, 2000.0, delta=0.005)

        html = self._html("l10n_ua_docs.report_ua_invoice_bill", invoice)
        for needle in ("Рахунок на оплату", "43217890", "12345678", self.IBAN,
                       "МФО", "322313", "ПДВ 20 %",
                       "Дванадцять тисяч гривень 00 копійок",
                       "Договір № 7 від 01.09.2026", "Іваненко Іван Іванович"):
            self.assertIn(needle, html, "у рахунку немає «%s»" % needle)
        # Сума цифрами - без прив'язки до роздільників локалі бази.
        self.assertTrue(
            re.search(r"12[\s ,.]?000[.,]00", html),
            "у рахунку немає суми 12 000.00")

    def test_21_service_act_renders(self):
        """Акт наданих послуг: сторони, підстави підпису, суми, пропис."""
        # 3 години по 1 000 = 3 000 без ПДВ; ПДВ 600; разом 3 600.
        invoice = self._invoice(self.service, 3, 1000.0, self.tax_20)
        html = self._html("l10n_ua_docs.report_ua_service_act", invoice)
        for needle in ("Акт №", "наданих послуг", "Виконавець", "Замовник",
                       "43217890", "12345678", "ПДВ 20 %",
                       "Три тисячі шістсот гривень 00 копійок",
                       "Статуту", "довіреності № 4 від 02.01.2026",
                       "Сидоренко Сидір Сидорович"):
            self.assertIn(needle, html, "в акті немає «%s»" % needle)

    def test_22_delivery_note_renders(self):
        """Видаткова накладна: УКТ ЗЕД, довіреність, підписи обох сторін."""
        invoice = self._invoice(self.goods, 1, 2500.50, self.tax_20)
        html = self._html("l10n_ua_docs.report_ua_delivery_note", invoice)
        for needle in ("Видаткова накладна", "Код УКТ ЗЕД", "Довіреність",
                       "Відпустив(ла)", "Отримав(ла)", self.IBAN,
                       # 2 500.50 + 20 % = 3 000.60
                       "Три тисячі гривень 60 копійок"):
            self.assertIn(needle, html, "у накладній немає «%s»" % needle)
        self.assertTrue(invoice._ua_docs_has_goods())

    def test_23_invoice_without_vat_prints_bez_pdv(self):
        """Рахунок без ПДВ друкує «без ПДВ», а не нульову суму податку."""
        invoice = self._invoice(self.service, 1, 1000.0, tax=None)
        self.assertAlmostEqual(invoice.amount_tax, 0.0, delta=0.005)
        self.assertEqual(invoice._ua_docs_vat_label(), "Без ПДВ")
        html = self._html("l10n_ua_docs.report_ua_invoice_bill", invoice)
        self.assertIn("Без ПДВ", html)
        self.assertIn("без ПДВ", html)
        self.assertNotIn("ПДВ 20 %", html)
        self.assertIn("Одна тисяча гривень 00 копійок", html)

    def test_24_party_helpers(self):
        """Реквізити сторін зібрані з нативних полів, без власних дублів."""
        invoice = self._invoice(self.goods, 1, 100.0, self.tax_20, post=False)
        seller = invoice._ua_docs_seller()
        buyer = invoice._ua_docs_buyer()
        self.assertEqual(seller["registry"], "43217890")
        self.assertEqual(seller["vat"], "123456789012")
        self.assertEqual(seller["iban"], self.IBAN)
        self.assertEqual(seller["mfo"], "322313")
        self.assertEqual(seller["bank_name"], "АТ «Банк Приклад»")
        self.assertEqual(seller["director"], "Іваненко Іван Іванович")
        self.assertEqual(seller["accountant"], "Петренко Петро Петрович")
        self.assertEqual(seller["basis"], "Статуту")
        self.assertIn("01001", seller["address"])
        self.assertEqual(buyer["registry"], "12345678")
        self.assertEqual(buyer["director"], "Сидоренко Сидір Сидорович")
        self.assertEqual(buyer["iban"], "")
        self.assertEqual(self.bank.x_ua_mfo, "322313")

    def test_25_lines_and_number(self):
        """Позиції і номер документа беруться з нативного рахунку."""
        invoice = self._invoice(self.goods, 2, 5000.0, self.tax_20)
        rows = invoice._ua_docs_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["index"], 1)
        self.assertAlmostEqual(rows[0]["quantity"], 2.0, delta=0.005)
        self.assertAlmostEqual(rows[0]["subtotal"], 10000.0, delta=0.005)
        self.assertAlmostEqual(rows[0]["tax"], 2000.0, delta=0.005)
        # Номер - хвіст нативного номера рахунку (INV/2026/00001 -> 00001).
        self.assertEqual(invoice._ua_docs_number(), invoice.name.split("/")[-1])
        self.assertEqual(invoice._ua_docs_basis(), "Договір № 7 від 01.09.2026")
        self.assertEqual(invoice._ua_docs_totals()["count"], 1)

    def test_26_vendor_bill_refused(self):
        """Первинку продавця не друкують з рахунку постачальника."""
        from odoo.exceptions import UserError
        bill = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.buyer.id,
            "invoice_date": "2026-09-21",
            "invoice_line_ids": [(0, 0, {
                "name": "Оренда", "quantity": 1, "price_unit": 100.0,
            })],
        })
        with self.assertRaises(UserError):
            bill._ua_docs_check()
        # Перевірка стоїть не для краси: друк теж має впертися.
        with self.assertRaises(UserError):
            self._html("l10n_ua_docs.report_ua_invoice_bill", bill)
        self.assertTrue(self._invoice(self.goods, 1, 10.0, self.tax_20)._ua_docs_check())


@tagged("post_install", "-at_install", "ua_docs")
class TestUaDocsBridges(AccountTestInvoicingCommon):
    """Мости sale і stock. Пропускаються, коли міст не встановлено."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "company_registry": "43217890",
            "ua_director_name": "Іваненко Іван Іванович",
        })
        cls.buyer = cls.env["res.partner"].create({
            "name": "ТОВ «Покупець»", "company_registry": "12345678",
        })
        cls.goods = cls.env["product.product"].create({
            "name": "Стіл робочий", "type": "consu", "list_price": 5000.0,
        })

    def _installed(self, module):
        return bool(self.env["ir.module.module"].search_count([
            ("name", "=", module), ("state", "=", "installed"),
        ]))

    def _html(self, report, record):
        report_service = self.env["ir.actions.report"].sudo()
        return report_service._render_qweb_html(report, record.ids)[0].decode()

    def test_30_sale_bridge_renders(self):
        """Рахунок на оплату з замовлення на продаж плюс номер договору."""
        if not self._installed("l10n_ua_docs_sale"):
            self.skipTest("l10n_ua_docs_sale не встановлено")
        chart = self.env["account.chart.template"].with_company(self.company)
        tax_20 = chart.ref("sale_tax_template_vat20_psbo")
        # Користувач набору тестів бухгалтерії не має груп продажу і складу,
        # а перевіряємо ми друк, а не права: працюємо від адміністратора.
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.buyer.id,
            "x_ua_contract_number": "12-А",
            "x_ua_contract_date": "2026-09-01",
            "order_line": [(0, 0, {
                "product_id": self.goods.id,
                "product_uom_qty": 2,
                "price_unit": 5000.0,
                "tax_ids": [(6, 0, tax_20.ids)],
            })],
        })
        self.assertAlmostEqual(order.amount_total, 12000.0, delta=0.005)
        self.assertIn("12-А", order._ua_docs_basis())
        html = self._html("l10n_ua_docs_sale.report_ua_sale_invoice_bill", order)
        for needle in ("Рахунок на оплату", "43217890", "12345678", "ПДВ 20 %",
                       "Дванадцять тисяч гривень 00 копійок", "Договір № 12-А"):
            self.assertIn(needle, html, "у рахунку із замовлення немає «%s»" % needle)

    def test_31_stock_bridge_renders(self):
        """Видаткова накладна і ТТН з доставки плюс довіреність."""
        if not self._installed("l10n_ua_docs_stock"):
            self.skipTest("l10n_ua_docs_stock не встановлено")
        warehouse = self.env["stock.warehouse"].sudo().search(
            [("company_id", "=", self.company.id)], limit=1)
        customers = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].sudo().create({
            "partner_id": self.buyer.id,
            "picking_type_id": warehouse.out_type_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": customers.id,
            "origin": "SO-TEST",
            "x_ua_proxy_number": "СЕР № 001234",
            "x_ua_proxy_date": "2026-09-20",
            "x_ua_proxy_person": "Коваленко Коваль Ковальович",
            "move_ids": [(0, 0, {
                "product_id": self.goods.id,
                "product_uom_qty": 3,
                "product_uom": self.goods.uom_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": customers.id,
            })],
        })
        picking.action_confirm()
        proxy = picking._ua_docs_proxy()
        self.assertEqual(proxy["number"], "СЕР № 001234")
        self.assertEqual(proxy["person"], "Коваленко Коваль Ковальович")

        html = self._html("l10n_ua_docs_stock.report_ua_picking_delivery_note", picking)
        for needle in ("Видаткова накладна", "43217890", "12345678",
                       "СЕР № 001234", "Стіл робочий"):
            self.assertIn(needle, html, "у накладній з доставки немає «%s»" % needle)

        ttn = self._html("l10n_ua_docs_stock.report_ua_waybill", picking)
        for needle in ("Товарно-транспортна накладна", "Автомобіль",
                       "Пункт навантаження", "Стіл робочий"):
            self.assertIn(needle, ttn, "у ТТН немає «%s»" % needle)
