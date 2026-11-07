# -*- coding: utf-8 -*-
"""Обмін з клієнт-банком у форматі 1CClientBankExchange.

Виписка нижче - два наших рахунки, два дні залишків по першому:
    рахунок 1: 10 000,00 + 12 000,00 (покупець за IBAN) = 22 000,00 на кінець першого дня;
               22 000,00 + 3 600,50 (покупець за кодом ЄДРПОУ) - 150,00 (комісія банку)
               - 5 000,00 (переказ на рахунок 2) = 20 450,50;
    рахунок 2: 0 + 5 000,00 = 5 000,00.
Усі назви, коди і рахунки вигадані.

Запуск: чиста база, теги ua_bank_1c.
"""
import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ua_bank_1c.models import bank1c_format as fmt

CENT = 0.005
OWN_1 = "UA743052990000026007233566001"
OWN_2 = "UA903220010000026000300123456"
BUYER_A = "UA923808050000026001234567890"
BANK_FEE = "UA653003460000026009876543210"

STATEMENT = """1CClientBankExchange
ВерсияФормата=1.02
Кодировка=Windows
Отправитель=Клієнт-банк
Получатель=Бухгалтерія
ДатаСоздания=04.11.2026
ВремяСоздания=09:15:00
ДатаНачала=02.11.2026
ДатаКонца=03.11.2026
РасчСчет={own1}
РасчСчет={own2}
СекцияРасчСчет
ДатаНачала=02.11.2026
ДатаКонца=02.11.2026
РасчСчет={own1}
НачальныйОстаток=10000.00
ВсегоПоступило=12000.00
ВсегоСписано=0.00
КонечныйОстаток=22000.00
КонецРасчСчет
СекцияРасчСчет
ДатаНачала=03.11.2026
ДатаКонца=03.11.2026
РасчСчет={own1}
НачальныйОстаток=22000.00
ВсегоПоступило=3600.50
ВсегоСписано=5150.00
КонечныйОстаток=20450.50
КонецРасчСчет
СекцияРасчСчет
ДатаНачала=02.11.2026
ДатаКонца=03.11.2026
РасчСчет={own2}
НачальныйОстаток=0.00
ВсегоПоступило=5000.00
ВсегоСписано=0.00
КонечныйОстаток=5000.00
КонецРасчСчет
СекцияДокумент=Платежное поручение
Номер=118
Дата=02.11.2026
Сумма=12000.00
ПлательщикСчет={buyer_a}
ДатаСписано=02.11.2026
Плательщик=ТОВ "Покупець А"
ПлательщикОКПО=41234560
ПлательщикМФО=380805
ПолучательСчет={own1}
ДатаПоступило=02.11.2026
Получатель=ТОВ "Ясен"
ПолучательОКПО=12345678
НазначениеПлатежа=Оплата за рахунком № 15 від 28.10.2026, у т.ч. ПДВ 20 % - 2000,00 грн
КонецДокумента
СекцияДокумент=Платежное поручение
Номер=7
Дата=03.11.2026
Сумма=3600,50
ПлательщикСчет=UA213510050000026001111111111
Плательщик1=ФОП Коваль О. О.
ПлательщикИНН=3012345678
ПолучательСчет={own1}
ДатаПоступило=03.11.2026
Получатель=ТОВ "Ясен"
НазначениеПлатежа=Оплата за ремонт,
НазначениеПлатежа1=без ПДВ
КонецДокумента
СекцияДокумент=Банковский ордер
Номер=55120
Дата=03.11.2026
Сумма=150.00
ПлательщикСчет={own1}
ДатаСписано=03.11.2026
Плательщик=ТОВ "Ясен"
ПолучательСчет={fee}
Получатель=Банк (комісії)
НазначениеПлатежа=Комісія за обслуговування рахунку за жовтень 2026
КонецДокумента
СекцияДокумент=Платежное поручение
Номер=12
Дата=03.11.2026
Сумма=5000.00
ПлательщикСчет={own1}
ДатаСписано=03.11.2026
ПолучательСчет={own2}
ДатаПоступило=03.11.2026
НазначениеПлатежа=Переказ власних коштів, без ПДВ
КонецДокумента
КонецФайла
""".format(own1=OWN_1, own2=OWN_2, buyer_a=BUYER_A, fee=BANK_FEE)


@tagged("post_install", "-at_install", "ua_bank_1c")
class TestBank1C(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.company.company_registry = "12345678"
        cls.env.user.group_ids |= cls.env.ref("account_payment_order.group_account_payment")
        cls.bank = cls.company_data["default_journal_bank"]
        cls.bank.bank_account_id = cls._iban(cls.company.partner_id, OWN_1)
        cls.bank2 = cls.env["account.journal"].create({
            "name": "Банк 2", "type": "bank", "code": "BNK2", "company_id": cls.company.id,
            "bank_account_id": cls._iban(cls.company.partner_id, OWN_2).id,
        })
        cls.buyer_a = cls.env["res.partner"].create({"name": "ТОВ Покупець А (тест)"})
        cls._iban(cls.buyer_a, BUYER_A)
        cls.fop = cls.env["res.partner"].create({"name": "ФОП Коваль О. О. (тест)",
                                                 "company_registry": "3012345678"})
        cls.vendor = cls.env["res.partner"].create({"name": "ТОВ Постачальник (тест)",
                                                    "company_registry": "87654321"})
        cls.vendor_bank = cls._iban(cls.vendor, "UA213510050000026002222222222")

    @classmethod
    def _iban(cls, partner, number):
        return cls.env["res.partner.bank"].create({
            "acc_number": number, "partner_id": partner.id, "allow_out_payment": True})

    def _import(self, text=STATEMENT, encoding="cp1251"):
        wizard = self.env["account.statement.import"].create({
            "statement_file": base64.b64encode(text.encode(encoding)),
            "statement_filename": "vypyska.txt",
        })
        return wizard.import_file_button()

    def _lines(self, journal):
        return self.env["account.bank.statement.line"].search(
            [("journal_id", "=", journal.id)], order="date, id")

    # --- формат без бази ---------------------------------------------------

    def test_01_parse(self):
        parsed = fmt.parse(STATEMENT.encode("cp1251"))
        self.assertEqual(parsed["accounts"], [OWN_1, OWN_2])
        self.assertEqual(len(parsed["documents"]), 4)
        by_account = fmt.transactions(parsed)
        self.assertEqual([row["amount"] for row in by_account[OWN_1]],
                         [12000.0, 3600.5, -150.0, -5000.0])
        self.assertEqual([row["amount"] for row in by_account[OWN_2]], [5000.0])
        self.assertEqual(fmt.balances(parsed, OWN_1)[:2], (10000.0, 20450.5))
        fop = by_account[OWN_1][1]
        self.assertEqual(fop["partner"]["code"], "3012345678")
        self.assertEqual(fop["purpose"], "Оплата за ремонт, без ПДВ")
        self.assertTrue(fmt.is_bank1c(STATEMENT.encode("utf-8")))
        self.assertFalse(fmt.is_bank1c(b"date;amount\n"))

    def test_02_bad_files(self):
        with self.assertRaises(fmt.Bank1CError):
            fmt.parse(STATEMENT.replace("КонецДокумента\nКонецФайла", "КонецФайла"))
        with self.assertRaises(fmt.Bank1CError):
            fmt.transactions(fmt.parse(STATEMENT.replace("Сумма=150.00", "Сумма=сто")))
        with self.assertRaises(UserError):
            self._import(STATEMENT.replace("Дата=03.11.2026\nСумма=150.00",
                                           "Дата=2026/11/03\nСумма=150.00")
                         .replace("ДатаСписано=03.11.2026\nПлательщик=ТОВ", "Плательщик=ТОВ"))

    # --- імпорт ------------------------------------------------------------

    def test_03_import_two_accounts(self):
        self._import()
        lines = self._lines(self.bank)
        self.assertEqual(lines.mapped("amount"), [12000.0, 3600.5, -150.0, -5000.0])
        statement = lines.statement_id
        self.assertEqual(len(statement), 1)
        self.assertAlmostEqual(statement.balance_start, 10000.0, delta=CENT)
        self.assertAlmostEqual(statement.balance_end_real, 20450.5, delta=CENT)
        self.assertEqual(statement.date, fields.Date.to_date("2026-11-03"))
        # контрагент за IBAN, за кодом ЄДРПОУ (ДРФО у ФОП), і ніякого для комісії банку
        self.assertEqual(lines[0].partner_id, self.buyer_a)
        self.assertEqual(lines[1].partner_id, self.fop)
        self.assertFalse(lines[2].partner_id)
        self.assertEqual(lines[2].partner_name, "Банк (комісії)")
        self.assertIn("Комісія", lines[2].payment_ref)
        other = self._lines(self.bank2)
        self.assertEqual(other.mapped("amount"), [5000.0])
        self.assertAlmostEqual(other.statement_id.balance_end_real, 5000.0, delta=CENT)

    def test_04_reimport_creates_nothing(self):
        self._import()
        count = len(self._lines(self.bank))
        with self.assertRaises(UserError):
            self._import()
        self.assertEqual(len(self._lines(self.bank)), count)

    def test_05_utf8_and_dos(self):
        self._import(STATEMENT, "utf-8")
        self.assertEqual(len(self._lines(self.bank)), 4)
        dos = STATEMENT.replace("Кодировка=Windows", "Кодировка=DOS")
        parsed = fmt.parse(dos.encode("cp1125"))
        self.assertEqual(parsed["documents"][2]["Получатель"], "Банк (комісії)")
        self.assertEqual(parsed["header"]["Кодировка"], "DOS")

    def test_06_ambiguous_code_left_to_accountant(self):
        self.env["res.partner"].create({"name": "Двійник (тест)", "company_registry": "3012345678"})
        self._import()
        self.assertFalse(self._lines(self.bank)[1].partner_id)

    # --- платіжки ----------------------------------------------------------

    def _bill(self, price=1000.0, mode=None, partner=None):
        tax = self.company_data["default_tax_purchase"]
        partner = partner or self.vendor
        bill = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": partner.id,
            "partner_bank_id": partner.bank_ids[:1].id,
            "ref": "РФ-204",
            "invoice_date": fields.Date.context_today(self.env.user),
            "payment_mode_id": mode.id if mode else False,
            "invoice_line_ids": [(0, 0, {"name": "Комплектуючі", "quantity": 1,
                                         "price_unit": price, "tax_ids": [(6, 0, tax.ids)]})],
        })
        bill.action_post()
        return bill

    def test_07_export_payment(self):
        bill = self._bill()
        payment = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=bill.ids).create({
                "journal_id": self.bank.id,
                "partner_bank_id": self.vendor_bank.id,
            })._create_payments()
        content, filename = payment._ua_bank1c_file()
        self.assertTrue(filename.endswith(".txt"))
        text = content.decode("cp1251")
        self.assertTrue(text.startswith("1CClientBankExchange\r\n"))
        parsed = fmt.parse(content)
        document = parsed["documents"][0]
        self.assertEqual(document["ПлательщикСчет"], OWN_1)
        self.assertEqual(document["ПлательщикОКПО"], "12345678")
        self.assertEqual(document["ПлательщикМФО"], "305299")
        self.assertEqual(document["ПолучательСчет"], "UA213510050000026002222222222")
        self.assertEqual(document["ПолучательОКПО"], "87654321")
        self.assertEqual(document["ПолучательМФО"], "351005")
        self.assertEqual(fmt.amount(document["Сумма"]), bill.amount_total)
        purpose = document["НазначениеПлатежа"]
        if bill.amount_tax:
            vat = ("%.2f" % bill.amount_tax).replace(".", ",")
            self.assertIn("ПДВ", purpose)
            self.assertIn(vat, purpose)
        else:
            self.assertIn("без ПДВ", purpose)
        # прочитаний назад файл дає списання з нашого рахунку
        self.assertEqual(fmt.transactions(parsed)[OWN_1][0]["amount"], -bill.amount_total)
        action = payment.action_ua_bank1c_export()
        self.assertEqual(action["type"], "ir.actions.act_url")

    def test_08_export_needs_recipient_account(self):
        nobank = self.env["res.partner"].create({"name": "ТОВ Без рахунку (тест)"})
        bill = self._bill(partner=nobank)
        payment = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=bill.ids).create({
                "journal_id": self.bank.id})._create_payments()
        self.assertFalse(payment.partner_bank_id)
        with self.assertRaises(UserError):
            payment._ua_bank1c_file()

    def test_09_payment_order_file(self):
        method = self.env.ref("l10n_ua_bank_1c.payment_method_ua_1c_exchange")
        self.assertIn(method, self.bank.outbound_payment_method_line_ids.payment_method_id)
        mode = self.env["account.payment.mode"].create({
            "name": "Клієнт-банк 1С (тест)",
            "company_id": self.company.id,
            "bank_account_link": "fixed",
            "fixed_journal_id": self.bank.id,
            "payment_method_id": method.id,
        })
        bills = self._bill(1000.0, mode) + self._bill(500.0, mode)
        bills.create_account_payment_line()
        order = self.env["account.payment.order"].search(
            [("payment_mode_id", "=", mode.id), ("state", "=", "draft")], limit=1)
        self.assertEqual(len(order.payment_line_ids), 2)
        order.draft2open()
        order.open2generated()
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", "account.payment.order"), ("res_id", "=", order.id)], limit=1)
        parsed = fmt.parse(base64.b64decode(attachment.datas))
        total = sum(fmt.amount(document["Сумма"]) for document in parsed["documents"])
        self.assertAlmostEqual(total, sum(bills.mapped("amount_total")), delta=CENT)
        self.assertTrue(all(document["ПолучательОКПО"] == "87654321"
                            for document in parsed["documents"]))
