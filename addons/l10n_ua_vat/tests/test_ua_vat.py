# -*- coding: utf-8 -*-
"""Інваріанти українського ПДВ.

Числа в очікуваннях пораховані руками, арифметика показана в коментарі поруч.
Набір перенесено з перевірок пісочниці (scripts/regress.py: перша подія,
пропорційне закриття, строки реєстрації, РК на повернення, XML ЄРПН,
компенсуючі ПЗ, зведення періоду) і доповнено випадками, яких там не було:
відвантаження раніше за оплату, неплатник ПДВ, митний ПДВ.

Запуск: одна з баз vat_* через docker compose run, теги ua_vat.
"""
import datetime
import xml.etree.ElementTree as ET

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

# Копійка: усі еталони заокруглені до двох знаків.
CENT = 0.005


@tagged("post_install", "-at_install", "ua_vat")
class TestUaVat(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "vat": "1234567890",
            "company_registry": "43217890",
        })
        chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.tax_sale_20 = chart.ref("sale_tax_template_vat20_psbo")
        cls.tax_purchase_20 = chart.ref("purchase_tax_template_vat20_psbo")
        cls.tax_sale_exempt = chart.ref("sale_tax_template_vat_free_psbo")
        cls.tax_sale_zero = chart.ref("sale_tax_template_vat0_psbo")

        cls.acc_pz = cls.company._ua_vat_account("pz_advance")      # 6431
        cls.acc_vat = cls.company._ua_vat_account("vat")            # 6412
        cls.acc_pz_unconfirmed = cls.company._ua_vat_account("pz_unconfirmed")

        cls.journal_bank = cls.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)

        cls.payer = cls.env["res.partner"].create({
            "name": "ТОВ Покупець-платник",
            "ua_vat_payer_status": "payer",
            "vat": "9988776655",
            "country_id": cls.env.ref("base.ua").id,
        })
        cls.non_payer = cls.env["res.partner"].create({
            "name": "ТОВ Неплатник",
            "ua_vat_payer_status": "non_payer",
            "country_id": cls.env.ref("base.ua").id,
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "ТОВ Постачальник",
            "ua_vat_payer_status": "payer",
            "vat": "1122334455",
            "country_id": cls.env.ref("base.ua").id,
        })
        cls.goods = cls.env["product.product"].create({
            "name": "Стіл робочий",
            "type": "consu",
            "ua_uktzed": "9403300000",
        })
        # Пільга БПЛА: п.32 підрозд.2 розд.XX ПКУ, код пільги з довідника ДПС.
        cls.relief = cls.env["ua.vat.relief"].create({
            "name": "БПЛА (безпілотні системи)",
            "basis": "пп.5 п.32 підрозд.2 розд.XX ПКУ",
            "uktzed_prefixes": "8806, 8807",
            "dps_benefit_code": "14060555",
        })
        cls.drone = cls.env["product.product"].create({
            "name": "Безпілотник",
            "type": "consu",
            "ua_uktzed": "8806100000",
        })

    # --- Допоміжні ---------------------------------------------------------

    def _invoice(self, partner, date, lines, move_type="out_invoice", post=True):
        """Рахунок з явними податками (без автопідстановки)."""
        invoice = self.env["account.move"].create({
            "move_type": move_type,
            "partner_id": partner.id,
            "invoice_date": date,
            "date": date,
            "invoice_line_ids": [
                (0, 0, {
                    "name": product.name,
                    "product_id": product.id,
                    "quantity": qty,
                    "price_unit": price,
                    "tax_ids": [(6, 0, tax.ids)],
                }) for product, qty, price, tax in lines
            ],
        })
        if post:
            invoice.action_post()
        return invoice

    def _payment(self, partner, amount, date):
        payment = self.env["account.payment"].create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": partner.id,
            "amount": amount,
            "journal_id": self.journal_bank.id,
            "date": date,
        })
        payment.action_post()
        return payment

    def _reconcile(self, invoice, payment):
        lines = (invoice.line_ids | payment.move_id.line_ids).filtered(
            lambda l: l.account_id.account_type == "asset_receivable"
            and not l.reconciled)
        lines.reconcile()

    def _fe_sum(self, kind, side):
        """Сума дебетів або кредитів рахунку 6431 у проводках першої події."""
        lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
            ("account_id", "=", self.acc_pz.id),
            ("move_id.ua_fe_kind", "=", kind),
        ])
        return round(sum(lines.mapped(side)), 2)

    # --- 1. Податкові дані після завантаження плану --------------------------

    def test_01_taxes_present_after_chart_load(self):
        """План ua_psbo дає податки ПДВ, а ми домальовуємо види нульових ставок."""
        self.assertTrue(self.tax_sale_20, "немає податку продажу 20 %")
        self.assertEqual(self.tax_sale_20.amount, 20.0)
        self.assertTrue(self.tax_purchase_20, "немає податку придбання 20 %")
        self.assertEqual(self.tax_purchase_20.amount, 20.0)
        # Нативні нульові податки без групи - модуль дочіпляє нативні ж групи.
        self.assertEqual(
            self.tax_sale_exempt.tax_group_id.ua_vat_zero_kind, "exempt",
            "податок «звільнено» не позначено як звільнення")
        self.assertEqual(
            self.tax_sale_zero.tax_group_id.ua_vat_zero_kind, "export",
            "податок 0 % не позначено як експорт")
        # Пошук за видом нуля працює з картки компанії.
        self.assertEqual(self.company._ua_vat_exempt_tax(), self.tax_sale_exempt)
        self.assertEqual(self.company._ua_vat_export_tax(), self.tax_sale_zero)
        # Рахунки ПДВ знаходяться і при шестизначних, і при коротких кодах.
        for key in ("pz_advance", "vat", "pz_unconfirmed", "other_expense",
                    "customs"):
            self.assertTrue(self.company._ua_vat_account(key),
                            "не знайдено рахунок %s" % key)

    # --- 2. Перша подія: оплата раніше за відвантаження ----------------------

    def test_02_first_event_payment(self):
        """Аванс 1200 від платника ПДВ дає ПЗ 200.

        1200 * 20 / 120 = 200,00.
        """
        payment = self._payment(self.payer, 1200.0, datetime.date(2026, 7, 7))
        self.assertTrue(payment.ua_fe_move_id,
                        "проводка першої події не створилась")
        move = payment.ua_fe_move_id
        self.assertEqual(move.ua_fe_kind, "open")
        debit = sum(move.line_ids.filtered(
            lambda l: l.account_id == self.acc_pz).mapped("debit"))
        credit = sum(move.line_ids.filtered(
            lambda l: l.account_id == self.acc_vat).mapped("credit"))
        self.assertAlmostEqual(debit, 200.0, delta=CENT)
        self.assertAlmostEqual(credit, 200.0, delta=CENT)
        self.assertFalse(payment.ua_fe_reversed)

    # --- 3. Перша подія: відвантаження раніше за оплату ----------------------

    def test_03_first_event_shipment(self):
        """Проведений рахунок без оплати - перша подія «відвантаження».

        Складу в цій базі немає, тому відвантаження засвідчує сам рахунок:
        дата першої події дорівнює даті рахунку, службових проводок немає.
        """
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 1),
            [(self.goods, 1, 1000.0, self.tax_sale_20)])
        self.assertEqual(invoice.ua_first_event, "shipment")
        self.assertEqual(invoice.ua_first_event_date, datetime.date(2026, 7, 1))
        # ПДВ уже в самому рахунку: 1000 * 20 % = 200,00.
        self.assertAlmostEqual(invoice.amount_tax, 200.0, delta=CENT)
        before = self._fe_sum("open", "debit")
        payment = self._payment(self.payer, 1200.0, datetime.date(2026, 7, 20))
        self._reconcile(invoice, payment)
        # Оплата після відвантаження: навіть якщо проводка авансу встигла
        # з'явитися, звірка закриває її повністю, чистий рух 6431 - нуль.
        opened = self._fe_sum("open", "debit") - before
        closed = self._fe_sum("close", "credit")
        self.assertAlmostEqual(opened - closed, 0.0, delta=0.01,
                               msg="після другої події 6431 не занулився")

    # --- 4. Пропорційне закриття першої події --------------------------------

    def test_04_partial_closing_is_proportional(self):
        """Аванс 1200 (ПДВ 200) і два рахунки по 600.

        Звірка з першим рахунком закриває 1200 * (600 / 1200) = половину
        авансу, тобто 200 * 0,5 = 100,00. Прапорець «закрито» ще знято.
        Другий рахунок добиває решту: 200 - 100 = 100,00, разом 200,00,
        залишок на 6431 - нуль.
        """
        partner = self.env["res.partner"].create({
            "name": "ТОВ Пропорція", "ua_vat_payer_status": "payer",
            "country_id": self.env.ref("base.ua").id})
        invoices = [
            self._invoice(partner, datetime.date(2026, 7, 7),
                          [(self.goods, 1, 500.0, self.tax_sale_20)])
            for _ in range(2)
        ]
        for invoice in invoices:
            # 500 + 20 % = 600,00
            self.assertAlmostEqual(invoice.amount_total, 600.0, delta=CENT)
        payment = self._payment(partner, 1200.0, datetime.date(2026, 7, 7))
        fe_vat = sum(payment.ua_fe_move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_pz).mapped("debit"))
        self.assertAlmostEqual(fe_vat, 200.0, delta=CENT)

        self._reconcile(invoices[0], payment)
        self.assertAlmostEqual(payment.ua_fe_closed_amount, 100.0, delta=0.01,
                               msg="після першого рахунку закрито не 100,00")
        self.assertFalse(payment.ua_fe_reversed,
                         "прапорець поставлено після часткової звірки")

        self._reconcile(invoices[1], payment)
        self.assertAlmostEqual(payment.ua_fe_closed_amount, 200.0, delta=0.01,
                               msg="після другого рахунку закрито не 200,00")
        self.assertTrue(payment.ua_fe_reversed,
                        "прапорець не поставлено після повної звірки")
        closed = round(sum(self.env["account.move.line"].search([
            ("company_id", "=", self.company.id),
            ("parent_state", "=", "posted"),
            ("account_id", "=", self.acc_pz.id),
            ("move_id.ua_fe_kind", "=", "close"),
            ("move_id.ref", "in", ["Закриття першої події: %s" % i.name
                                   for i in invoices]),
        ]).mapped("credit")), 2)
        self.assertAlmostEqual(fe_vat - closed, 0.0, delta=0.01,
                               msg="залишок першої події не нуль")

    # --- 5. Неплатник ПДВ ----------------------------------------------------

    def test_05_non_payer_has_no_first_event(self):
        """Аванс від неплатника ПДВ проводки першої події не породжує."""
        payment = self._payment(self.non_payer, 1200.0,
                                datetime.date(2026, 7, 7))
        self.assertFalse(payment.ua_fe_move_id)
        invoice = self._invoice(
            self.non_payer, datetime.date(2026, 7, 8),
            [(self.goods, 1, 1000.0, self.tax_sale_20)])
        self.assertFalse(invoice.ua_tax_invoice_needed,
                         "неплатнику виписується накладна")

    # --- 6. Воєнні строки реєстрації ПН --------------------------------------

    def test_06_pn_deadline_military_terms(self):
        """Складено 1-15 числа - до 5 числа наступного місяця, 16-кінець - до 18.

        10.07.2026 дає 05.08.2026; 20.07.2026 дає 18.08.2026;
        20.12.2026 переходить через рік і дає 18.01.2027.
        """
        cases = [
            (datetime.date(2026, 7, 10), datetime.date(2026, 8, 5)),
            (datetime.date(2026, 7, 20), datetime.date(2026, 8, 18)),
            (datetime.date(2026, 12, 20), datetime.date(2027, 1, 18)),
            (datetime.date(2026, 12, 3), datetime.date(2027, 1, 5)),
        ]
        for invoice_date, expected in cases:
            move = self.env["account.move"].new({
                "move_type": "out_invoice",
                "partner_id": self.payer.id,
                "invoice_date": invoice_date,
            })
            self.assertEqual(
                move.ua_pn_deadline, expected,
                "строк для %s очікували %s" % (invoice_date, expected))

    # --- 7. Шкала штрафу за прострочення -------------------------------------

    def test_07_pn_fine_scale(self):
        """Штраф рахується за шкалою п.90 від суми ПДВ.

        Рахунок 1000 + 20 % дає ПДВ 200,00.
        10 днів прострочення - 2 %: 200 * 0,02 = 4,00.
        20 днів - 5 %: 200 * 0,05 = 10,00.
        45 днів - 10 %: 200 * 0,10 = 20,00.
        400 днів - 25 %: 200 * 0,25 = 50,00.
        Вчасно - нуль.
        """
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 10),
            [(self.goods, 1, 1000.0, self.tax_sale_20)])
        self.assertAlmostEqual(invoice.amount_tax, 200.0, delta=CENT)
        for days, expected in [(0, 0.0), (10, 4.0), (20, 10.0),
                               (45, 20.0), (400, 50.0)]:
            self.assertAlmostEqual(
                invoice._ua_pn_fine(days), expected, delta=CENT,
                msg="штраф за %d днів очікували %.2f" % (days, expected))

    def test_08_pn_fine_exempt_capped(self):
        """Пільговий рахунок: 2 % обсягу, але не більше 1020 грн (п.120-1.1).

        Обсяг 100 000 без ПДВ: 100 000 * 0,02 = 2 000, що більше за межу,
        тому штраф - 1020,00.
        Обсяг 10 000: 10 000 * 0,02 = 200,00, межа не спрацьовує.
        """
        big = self._invoice(
            self.payer, datetime.date(2026, 7, 10),
            [(self.drone, 1, 100000.0, self.tax_sale_exempt)])
        self.assertAlmostEqual(big.amount_tax, 0.0, delta=CENT)
        self.assertAlmostEqual(big._ua_pn_fine(20), 1020.0, delta=CENT)
        small = self._invoice(
            self.payer, datetime.date(2026, 7, 11),
            [(self.drone, 1, 10000.0, self.tax_sale_exempt)])
        self.assertAlmostEqual(small._ua_pn_fine(20), 200.0, delta=CENT)

    # --- 9. Реєстр: складання ПН ідемпотентне --------------------------------

    def test_09_tax_invoice_is_idempotent(self):
        """Друге складання накладної не дублює запис, а детектор гасне."""
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 10),
            [(self.goods, 2, 500.0, self.tax_sale_20)])
        self.assertTrue(invoice.ua_tax_invoice_needed,
                        "детектор не побачив потреби в накладній")
        doc = invoice._ua_vat_materialize("tax_invoice")
        again = invoice._ua_vat_materialize("tax_invoice")
        self.assertEqual(doc, again, "повторне складання здублювало накладну")
        invoice.invalidate_recordset(["ua_tax_invoice_needed"])
        self.assertFalse(invoice.ua_tax_invoice_needed,
                         "детектор не згас після складання накладної")
        # Строк реєстрації дзеркалиться в реєстр: 10.07 дає 05.08.
        self.assertEqual(doc.ua_pn_deadline, datetime.date(2026, 8, 5))
        doc.action_mark_pn_registered()
        self.assertEqual(doc.state, "registered")
        invoice.invalidate_recordset(["ua_pn_at_risk"])
        self.assertFalse(invoice.ua_pn_at_risk,
                         "зареєстрована накладна лишилась під ризиком")

    # --- 10. XML податкової накладної ----------------------------------------

    def test_10_pn_xml_structure_and_totals(self):
        """XML J1201016 парситься, підсумки дорівнюють рахунку.

        Рахунок: 2 штуки по 500 з ПДВ 20 %.
        Обсяг без ПДВ 2 * 500 = 1000,00, ПДВ 200,00, разом 1200,00.
        Ім'я файла: 43 символи плюс «.xml» - усього 47.
        """
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 10),
            [(self.goods, 2, 500.0, self.tax_sale_20)])
        doc = invoice._ua_vat_materialize("tax_invoice")
        self.assertFalse(doc._ua_pn_missing(),
                         "накладна не готова: %s" % doc._ua_pn_missing())
        xml_bytes, fname = doc._ua_build_pn_xml()
        root = ET.fromstring(xml_bytes)
        body = root.find("DECLARBODY")
        head = root.find("DECLARHEAD")
        self.assertIsNotNone(body, "немає DECLARBODY")
        charcode = "".join(head.findtext(t) for t in
                           ("C_DOC", "C_DOC_SUB", "C_DOC_VER"))
        self.assertEqual(charcode, "J1201016")
        self.assertEqual(head.findtext("TIN"), "43217890")
        self.assertEqual(body.findtext("HKSEL"), "1234567890")
        self.assertEqual(body.findtext("HKBUY"), "9988776655")
        self.assertTrue(body.findall("RXXXXG3S"), "немає табличних рядків")
        self.assertAlmostEqual(float(body.findtext("R01G7")), 1000.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R03G11")), 200.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R04G11")), 1200.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R03G11")),
                               invoice.amount_tax, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R04G11")),
                               invoice.amount_total, delta=CENT)
        self.assertEqual(len(fname), 47, "ім'я файла не за конвенцією: %s" % fname)
        self.assertTrue(fname.endswith(".xml"))
        # Повторний експорт оновлює те саме вкладення, а не плодить копії.
        first = doc._ua_export_pn_attach()
        second = doc._ua_export_pn_attach()
        self.assertEqual(first, second)

    def test_11_pn_xml_validation_catches_missing_uktzed(self):
        """Без коду УКТ ЗЕД накладна до ЄРПН не збирається."""
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 12),
            [(self.goods, 1, 800.0, self.tax_sale_20)])
        doc = invoice._ua_vat_materialize("tax_invoice")
        self.assertFalse(doc._ua_pn_missing())
        saved = self.goods.ua_uktzed
        self.goods.ua_uktzed = False
        try:
            missing = doc._ua_pn_missing()
            self.assertTrue(any("УКТ ЗЕД" in m for m in missing),
                            "перевірка не ловить брак УКТ ЗЕД")
            with self.assertRaises(UserError):
                doc._ua_export_pn_attach()
        finally:
            self.goods.ua_uktzed = saved
        self.assertFalse(doc._ua_pn_missing())

    def test_12_exempt_line_gets_code_903(self):
        """Звільнений рядок іде кодом ставки 903 з кодом пільги ДПС.

        Обсяг 5000 без ПДВ, ПДВ нуль, тому R01G10 дорівнює 5000,00,
        а R03G11 - нулю.
        """
        self.assertEqual(self.drone.ua_vat_treatment, "exempt",
                         "товар 8806 не став звільненим")
        self.assertEqual(self.drone.ua_vat_relief_effective_id, self.relief)
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 14),
            [(self.drone, 1, 5000.0, self.tax_sale_exempt)])
        doc = invoice._ua_vat_materialize("tax_invoice")
        xml_bytes, _fname = doc._ua_build_pn_xml()
        body = ET.fromstring(xml_bytes).find("DECLARBODY")
        codes = [e.text for e in body.findall("RXXXXG008")]
        benefits = [e.text for e in body.findall("RXXXXG009") if e.text]
        self.assertIn("903", codes, "немає коду ставки 903")
        self.assertIn("14060555", benefits, "немає коду пільги з довідника ДПС")
        self.assertAlmostEqual(float(body.findtext("R01G10")), 5000.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R03G11")), 0.0, delta=CENT)
        self.assertEqual(body.findtext("R03G10S"), "Без ПДВ")

    # --- 13. Розрахунок коригування на повернення ----------------------------

    def _return(self, invoice, quantity=None):
        """Повернення до рахунку через сторно."""
        refund = invoice._reverse_moves(default_values_list=[{
            "ref": "Повернення: %s" % invoice.name,
            "invoice_date": invoice.invoice_date,
        }], cancel=False)
        if quantity is not None:
            refund.invoice_line_ids[0].quantity = quantity
        refund.action_post()
        return refund

    def test_13_rk_created_on_return(self):
        """Повернення платнику ПДВ само дає РК: причина 103, реєструє покупець."""
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 15),
            [(self.goods, 2, 500.0, self.tax_sale_20)])
        invoice._ua_vat_materialize("tax_invoice")
        refund = self._return(invoice)
        self.assertEqual(refund.move_type, "out_refund")
        doc = refund.ua_vat_document_ids.filtered(
            lambda d: d.doc_kind == "adjustment")
        self.assertTrue(doc, "РК не створився при проведенні повернення")
        self.assertEqual(doc.ua_adj_reason_code, "103",
                         "причина коригування не 103 (повернення товару)")
        self.assertEqual(doc.ua_adj_registrant, "buyer",
                         "зменшуючий РК має реєструвати покупець (п.192.1 ПКУ)")
        self.assertEqual(doc.ua_adj_direction, "decrease")
        refund.invalidate_recordset(["ua_rk_needed"])
        self.assertFalse(refund.ua_rk_needed, "детектор РК не згас")
        self.assertEqual(refund._ua_vat_materialize("adjustment"), doc,
                         "повторне складання здублювало РК")
        # Зменшуючий РК реєструє покупець: 18 календарних днів від складання.
        self.assertEqual(refund.ua_pn_deadline,
                         datetime.date(2026, 7, 15) + datetime.timedelta(days=18))

    def test_14_rk_xml_full_return(self):
        """Повне повернення: сторно всього рядка, дельти від'ємні.

        Первинний рядок - 2 штуки по 500, обсяг 1000,00, ПДВ 200,00.
        Повертають усі 2 штуки, залишку немає, тому в РК лише рядок сторно:
        обсяг -1000,00, ПДВ -200,00.
        """
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 16),
            [(self.goods, 2, 500.0, self.tax_sale_20)])
        invoice._ua_vat_materialize("tax_invoice")
        refund = self._return(invoice)
        doc = refund.ua_vat_document_ids.filtered(
            lambda d: d.doc_kind == "adjustment")
        self.assertFalse(doc._ua_rk_missing(),
                         "РК не готовий: %s" % doc._ua_rk_missing())
        xml_bytes, fname = doc._ua_build_rk_xml()
        root = ET.fromstring(xml_bytes)
        head, body = root.find("DECLARHEAD"), root.find("DECLARBODY")
        charcode = "".join(head.findtext(t) for t in
                           ("C_DOC", "C_DOC_SUB", "C_DOC_VER"))
        self.assertEqual(charcode, "J1201216")
        self.assertTrue(body.findtext("HNUM1"), "немає номера первинної ПН")
        rows = body.findall("RXXXXG5")
        self.assertEqual(len(rows), 1, "очікували один рядок сторно")
        self.assertAlmostEqual(float(rows[0].text), -2.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R01G7")), -1000.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R03G11")), -200.0, delta=CENT)
        self.assertEqual(len(fname), 47)

    def test_15_rk_xml_partial_return(self):
        """Часткове повернення: сторно плюс новий рядок на залишок.

        Первинний рядок - 2 штуки по 500 (обсяг 1000,00). Повертають 1 штуку
        на 500,00. У РК два рядки: сторно -2 штуки на -1000,00 і новий рядок
        2 - 1 = 1 штука по 500 на 500,00.
        Дельта обсягу: -1000 + 500 = -500,00; дельта ПДВ: -500 * 20 % = -100,00.
        """
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 17),
            [(self.goods, 2, 500.0, self.tax_sale_20)])
        invoice._ua_vat_materialize("tax_invoice")
        refund = self._return(invoice, quantity=1)
        doc = refund.ua_vat_document_ids.filtered(
            lambda d: d.doc_kind == "adjustment")
        xml_bytes, _fname = doc._ua_build_rk_xml()
        body = ET.fromstring(xml_bytes).find("DECLARBODY")
        quantities = [float(e.text) for e in body.findall("RXXXXG5")]
        self.assertEqual(len(quantities), 2,
                         "очікували сторно і рядок залишку")
        self.assertAlmostEqual(quantities[0], -2.0, delta=CENT)
        self.assertAlmostEqual(quantities[1], 1.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R01G7")), -500.0, delta=CENT)
        self.assertAlmostEqual(float(body.findtext("R03G11")), -100.0, delta=CENT)
        # Обидва рядки однієї групи коригування з однаковою причиною.
        groups = [e.text for e in body.findall("RXXXXG2")]
        reasons = [e.text for e in body.findall("RXXXXG2S")]
        self.assertEqual(groups, ["1", "1"])
        self.assertEqual(set(reasons), {"103"})

    # --- 16. Компенсуючі ПЗ ---------------------------------------------------

    def test_16_compensation_direct(self):
        """Купили з кредитом, продали звільнено - кредит гаситься повністю.

        Вхідний рахунок: безпілотник 1 штука по 3000 з ПДВ 20 %,
        вхідний ПДВ 3000 * 0,20 = 600,00. Товар звільнений і пільга
        компенсовна, тому це пряма компенсація на 100 %: ПЗ 600,00.
        Проводка кредитує рахунок ПДВ на ті самі 600,00.
        """
        period = datetime.date(2026, 9, 1)
        self._invoice(
            self.vendor, datetime.date(2026, 9, 5),
            [(self.drone, 1, 3000.0, self.tax_purchase_20)],
            move_type="in_invoice")
        self._invoice(
            self.payer, datetime.date(2026, 9, 20),
            [(self.drone, 1, 5000.0, self.tax_sale_exempt)])
        comp = self.env["ua.vat.compensation"].create({
            "company_id": self.company.id,
            "date_period": period,
        })
        comp.action_compute()
        self.assertTrue(comp.line_ids, "рядків компенсації немає")
        direct = comp.line_ids.filtered(lambda l: l.kind == "direct")
        self.assertTrue(direct, "пряма компенсація не визначилась")
        self.assertAlmostEqual(sum(direct.mapped("vat_in")), 600.0, delta=CENT)
        self.assertAlmostEqual(comp.direct_vat, 600.0, delta=CENT)
        # ЧВ: оподатковуваних продажів у вересні немає, усі обсяги звільнені,
        # тому частка використання в оподатковуваних операціях - нуль.
        self.assertAlmostEqual(comp.chv, 0.0, delta=0.01)
        comp.action_post()
        self.assertEqual(comp.state, "posted")
        credit = sum(comp.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_vat).mapped("credit"))
        self.assertAlmostEqual(credit, comp.comp_vat_total, delta=0.01,
                               msg="кредит рахунку ПДВ не дорівнює ПЗ")
        self.assertAlmostEqual(
            sum(comp.line_ids.mapped("comp_vat")), comp.comp_vat_total,
            delta=0.01, msg="підсумок не дорівнює сумі рядків")
        # Зведена ПН: тип причини 09, складена останнім днем вересня,
        # строк реєстрації - 20 календарних днів після 30.09.2026.
        doc = comp.doc_id
        self.assertTrue(doc, "зведеної ПН немає")
        self.assertTrue(doc.ua_pn_consolidated)
        self.assertEqual(doc.ua_pn_reason_type, "09")
        self.assertEqual(comp.move_id.date, datetime.date(2026, 9, 30))
        self.assertEqual(doc.ua_pn_deadline,
                         datetime.date(2026, 9, 30) + datetime.timedelta(days=20))
        # Повторне проведення не дублює.
        with self.assertRaises(UserError):
            comp.action_post()

    def test_17_compensation_skips_relief_without_compensation(self):
        """Пільга з прапорцем «без компенсації» компенсуючих ПЗ не дає.

        п.32 підрозд.2 розд.XX ПКУ з 26.12.2025: для БПЛА п.198.5 і ст.199 не
        застосовуються, кредит збережено.
        """
        self.relief.no_compensation = True
        self.drone.invalidate_recordset(["ua_vat_relief_effective_id"])
        self._invoice(
            self.vendor, datetime.date(2026, 10, 5),
            [(self.drone, 1, 3000.0, self.tax_purchase_20)],
            move_type="in_invoice")
        self._invoice(
            self.payer, datetime.date(2026, 10, 20),
            [(self.drone, 1, 5000.0, self.tax_sale_exempt)])
        comp = self.env["ua.vat.compensation"].create({
            "company_id": self.company.id,
            "date_period": datetime.date(2026, 10, 1),
        })
        comp.action_compute()
        self.assertFalse(
            comp.line_ids.filtered(lambda l: l.kind == "direct"),
            "пільга без компенсації все одно дала пряму компенсацію")
        # Обсяг виключено і зі знаменника ЧВ.
        self.assertAlmostEqual(comp.nocomp_base, 5000.0, delta=0.01)
        self.relief.no_compensation = False

    # --- 18. Зведення за період -----------------------------------------------

    def test_18_period_totals_are_consistent(self):
        """Зведення сходиться саме з собою.

        Рахунок клієнту 1000 + 20 % (ПДВ 200,00) і рахунок постачальника
        2000 + 20 % (ПДВ 400,00) у листопаді 2026 дають
        ПЗ 200,00, ПК 400,00, від'ємне значення 200,00.
        """
        self._invoice(
            self.payer, datetime.date(2026, 11, 10),
            [(self.goods, 1, 1000.0, self.tax_sale_20)])
        self._invoice(
            self.vendor, datetime.date(2026, 11, 12),
            [(self.goods, 1, 2000.0, self.tax_purchase_20)],
            move_type="in_invoice")
        period = self.env["ua.vat.period"].create({
            "date_from": datetime.date(2026, 11, 1),
            "date_to": datetime.date(2026, 11, 30),
        })
        period.action_compute()
        self.assertAlmostEqual(period.ua_r1_base, 1000.0, delta=CENT)
        self.assertAlmostEqual(period.ua_r1_vat, 200.0, delta=CENT)
        self.assertAlmostEqual(period.ua_pk1_base, 2000.0, delta=CENT)
        self.assertAlmostEqual(period.ua_pk1_vat, 400.0, delta=CENT)
        self.assertAlmostEqual(period.pz_total, 200.0, delta=0.01)
        self.assertAlmostEqual(period.pk_total, 400.0, delta=0.01)
        self.assertAlmostEqual(period.due_total, -200.0, delta=0.01)
        # Рядок 9 дорівнює ПЗ, рядки 18 і 19 - різниці.
        self.assertAlmostEqual(period.ua_pz_total, period.pz_total, delta=0.01)
        self.assertAlmostEqual(period.ua_pk_total, period.pk_total, delta=0.01)
        self.assertAlmostEqual(period.ua_r18, 0.0, delta=0.01)
        self.assertAlmostEqual(period.ua_r19, 200.0, delta=0.01)

    def test_19_period_zero_split_adds_up(self):
        """Звільнені і 0 % експорт розділяються, а разом дають нульовий кошик.

        Звільнений продаж 5000,00 і експортний 3000,00 у грудні 2026:
        5000 + 3000 = 8000,00.
        """
        nonresident = self.env["res.partner"].create({
            "name": "Foreign Buyer OU",
            "ua_vat_payer_status": "non_payer",
            "country_id": self.env.ref("base.ee").id,
        })
        self._invoice(
            self.payer, datetime.date(2026, 12, 5),
            [(self.drone, 1, 5000.0, self.tax_sale_exempt)])
        self._invoice(
            nonresident, datetime.date(2026, 12, 6),
            [(self.goods, 1, 3000.0, self.tax_sale_zero)])
        period = self.env["ua.vat.period"].create({
            "date_from": datetime.date(2026, 12, 1),
            "date_to": datetime.date(2026, 12, 31),
        })
        period.action_compute()
        self.assertAlmostEqual(period.ua_r_exempt_base, 5000.0, delta=0.01)
        self.assertAlmostEqual(period.ua_r_export_base, 3000.0, delta=0.01)
        self.assertAlmostEqual(period.ua_r0_base, 8000.0, delta=0.01)
        self.assertAlmostEqual(
            period.ua_r_exempt_base + period.ua_r_export_base,
            period.ua_r0_base, delta=0.01,
            msg="розділення нульових обсягів не сходиться з кошиком")

    # --- 20. Митний ПДВ --------------------------------------------------------

    def test_20_customs_vat_goes_to_credit(self):
        """Імпорт: ПДВ з митної декларації стає податковим кредитом.

        Митний ПДВ 5000,00 дає проводку Дт 6412 / Кт 3771 на 5000,00.
        Повторне натискання нічого не дублює.
        """
        # Валюта, відмінна від валюти компанії: саме це робить рахунок імпортним.
        foreign = self.env["res.currency"].with_context(active_test=False).search(
            [("name", "in", ["USD", "EUR"]),
             ("id", "!=", self.company.currency_id.id)], limit=1)
        foreign.active = True
        bill = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.vendor.id,
            "invoice_date": datetime.date(2026, 8, 10),
            "date": datetime.date(2026, 8, 10),
            "currency_id": foreign.id,
            "invoice_line_ids": [(0, 0, {
                "name": "Імпортні меблі",
                "product_id": self.goods.id,
                "quantity": 1,
                "price_unit": 1000.0,
                "tax_ids": [(6, 0, [])],
            })],
        })
        bill.action_post()
        self.assertTrue(bill.ua_is_import, "рахунок не визначився як імпортний")
        bill.ua_customs_decl_number = "UA100000/2026/123456"
        bill.ua_customs_vat = 5000.0
        bill.action_ua_post_customs_vat()
        entry = bill.ua_customs_move_id
        self.assertTrue(entry, "проводки митного ПДВ немає")
        self.assertTrue(entry.ua_customs_entry)
        debit = sum(entry.line_ids.filtered(
            lambda l: l.account_id == self.acc_vat).mapped("debit"))
        self.assertAlmostEqual(debit, 5000.0, delta=CENT)
        bill.action_ua_post_customs_vat()
        self.assertEqual(bill.ua_customs_move_id, entry,
                         "повторне натискання здублювало проводку")

    # --- 21. Компанія, чий план уже завантажено -------------------------------

    def test_21_post_init_hook_marks_loaded_chart(self):
        """Хуки @template працюють лише під час завантаження плану.

        Якщо модуль ставлять на базу, де план ua_psbo уже стоїть, ті самі дві
        правки робить post_init_hook. Перевіряємо, знявши маркери і групи
        руками і запустивши хук.
        """
        from odoo.addons.l10n_ua_vat.hooks import post_init_hook
        groups = (self.tax_sale_exempt.tax_group_id
                  | self.tax_sale_zero.tax_group_id)
        taxes = self.tax_sale_exempt | self.tax_sale_zero
        groups.ua_vat_zero_kind = False
        taxes.tax_group_id = False
        self.assertFalse(self.tax_sale_exempt.tax_group_id)

        post_init_hook(self.env)

        self.assertEqual(self.tax_sale_exempt.tax_group_id.ua_vat_zero_kind,
                         "exempt", "хук не відновив групу звільнення")
        self.assertEqual(self.tax_sale_zero.tax_group_id.ua_vat_zero_kind,
                         "export", "хук не відновив групу експорту")
        # Другий запуск нічого не міняє.
        post_init_hook(self.env)
        self.assertEqual(self.tax_sale_exempt.tax_group_id.ua_vat_zero_kind,
                         "exempt")

    def test_22_pn_unit_codes_from_uom(self):
        """Графи 4 і 5 ПН беруться з одиниці рядка, а не завжди «штука».

        Рядок 1: дріт у кілограмах - «кг», код 0301. Рядок 2: штучний товар -
        «шт», 2009. Повторний засів кодів не перезаписує ручну правку.
        """
        kgm = self.env.ref("uom.product_uom_kgm")
        self.assertEqual(kgm.ua_kspovo_code, "0301")
        self.assertEqual(
            self.env.ref("uom.product_uom_hour").ua_kspovo_code, "0175")
        wire = self.env["product.product"].create({
            "name": "Дріт мідний",
            "type": "consu",
            "uom_id": kgm.id,
            "ua_uktzed": "7408110000",
        })
        invoice = self._invoice(
            self.payer, datetime.date(2026, 7, 12),
            [(wire, 3, 400.0, self.tax_sale_20),
             (self.goods, 1, 500.0, self.tax_sale_20)])
        self.assertEqual(invoice.invoice_line_ids[0].product_uom_id, kgm)
        doc = invoice._ua_vat_materialize("tax_invoice")
        body = ET.fromstring(doc._ua_build_pn_xml()[0]).find("DECLARBODY")
        self.assertEqual([e.text for e in body.findall("RXXXXG105_2S")],
                         ["0301", "2009"])
        self.assertEqual([e.text for e in body.findall("RXXXXG4S")],
                         ["кг", "шт"])
        kgm.ua_kspovo_short = "кілограм"
        self.env["uom.uom"]._ua_kspovo_seed()
        self.assertEqual(kgm.ua_kspovo_short, "кілограм")
