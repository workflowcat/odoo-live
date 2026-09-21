# -*- coding: utf-8 -*-
"""Регресії, знайдені на збірці демо-простору «Ясен Меблі» (docs/base/demo-data.md).

Кожен тест відтворює рівно ту послідовність, у якій помилка проявлялася на чистій базі,
і жоден не спирається на дані стенду. Тег `ua_regress`.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, freeze_time


@tagged("post_install", "-at_install", "ua_regress")
class TestEmployeeSecondVersion(TransactionCase):
    """Друга версія контракту на щойно створеній картці працівника.

    Odoo заводить разом із карткою версію без contract_date_start. Обчислення
    ua_first_hire_date робило min() над сумішшю False і дат - TypeError щоразу, коли
    з'являлася друга версія (повторне прийняття).
    """

    def test_second_version_does_not_break_first_hire_date(self):
        employee = self.env["hr.employee"].create({
            "name": "Регрес: друга версія",
            "company_id": self.env.company.id,
        })
        # версія, яку Odoo створило разом із карткою, дати початку не має
        self.assertFalse(employee.version_id.contract_date_start)
        self.assertFalse(employee.ua_first_hire_date)

        self.env["hr.version"].with_context(sync_contract_dates=True).create({
            "employee_id": employee.id,
            "date_version": "2026-08-17",
            "contract_date_start": "2026-08-17",
        })
        employee.invalidate_recordset()
        self.assertEqual(str(employee.ua_first_hire_date), "2026-08-17",
                         "перша дата прийняття - найраніша з непорожніх")

        # третя версія - попередній період роботи, раніший за другий (повторне прийняття):
        # мінімум має посунутися назад. Саме так робить scripts/demo_company.py.
        self.env["hr.version"].with_context(sync_contract_dates=True).create({
            "employee_id": employee.id,
            "date_version": "2026-03-02",
            "contract_date_start": "2026-03-02",
            "contract_date_end": "2026-05-31",
        })
        employee.invalidate_recordset()
        self.assertEqual(str(employee.ua_first_hire_date), "2026-03-02")
        # сусідні обчислення на тих самих версіях теж не падають
        self.assertGreater(employee.ua_days_in_company, 0)


@tagged("post_install", "-at_install", "ua_regress")
class TestChartLoadedAfterInstall(TransactionCase):
    """План рахунків завантажують ПІСЛЯ встановлення модулів - звичайний порядок.

    Раніше все, що потребує готового плану, робилося в post_init_hook і на чистій базі
    тихо не робилося взагалі: правил звірки немає, коди шестизначні, назви англійські,
    касового журналу немає, прайс-лист у доларі.
    """

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.assertNotEqual(self.company.chart_template, "ua_psbo",
                            "тест має починатися з компанії без плану")
        self.company.country_id = self.env.ref("base.ua")

    def _load_chart(self):
        self.env["account.chart.template"].try_loading(
            "ua_psbo", self.company, install_demo=False)
        self.company.invalidate_recordset()
        self.env["account.account"].invalidate_model(["code"])

    def test_reconcile_models_appear_with_the_chart(self):
        from odoo.addons.l10n_ua_bank.hooks import RULES
        self._load_chart()
        names = self.env["account.reconcile.model"].search(
            [("company_id", "=", self.company.id)]).mapped("name")
        for _sequence, name, _code, _words in RULES:
            self.assertIn(name, names, "правило звірки «%s» має з'явитися разом із планом" % name)
        salary = self.env["account.reconcile.model"].search(
            [("company_id", "=", self.company.id), ("name", "=", "Зарплата на картки (661)")])
        self.assertEqual(salary.sequence, 90, "зарплата стоїть останньою в черзі правил")
        self.assertTrue(salary.line_ids.account_id.code.startswith("661"))

    def test_short_codes_and_ukrainian_names(self):
        self._load_chart()
        Account = self.env["account.account"].with_company(self.company)
        for code in ("26", "201", "301", "311", "661", "6411", "901", "92"):
            self.assertTrue(
                Account.search_count([("code", "=", code), ("company_ids", "in", self.company.id)]),
                "рахунок %s має мати короткий код, а не доповнений нулями" % code)
        account = Account.search([("code", "=", "301"), ("company_ids", "in", self.company.id)])
        self.assertEqual(account.with_context(lang="uk_UA").name,
                         "Готівка в національній валюті")
        journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.company.id)], limit=1)
        self.assertEqual(journal.with_context(lang="uk_UA").name, "Реалізація")

    def test_cash_journal_appears_with_the_chart(self):
        self._load_chart()
        journals = self.env["account.journal"].search(
            [("type", "=", "cash"), ("company_id", "=", self.company.id)])
        self.assertEqual(len(journals), 1, "рівно один касовий журнал")
        self.assertEqual(journals.name, "Каса")
        self.assertTrue(journals.default_account_id.code.startswith("301"),
                        "журнал каси працює через рахунок 301, а не через типовий рахунок Odoo")

    def test_default_pricelist_follows_company_currency(self):
        """Типовий прайс-лист створено в доларі до плану - після плану він у гривні.

        Експортний прайс-лист в іншій валюті заводять свідомо, і його не чіпаємо.
        """
        Pricelist = self.env["product.pricelist"].sudo()
        before = self.company.currency_id
        self.assertNotEqual(before.name, "UAH", "тест має починатися не з гривні")
        default = Pricelist.create({"name": "Default", "company_id": self.company.id,
                                    "currency_id": before.id})
        euro = self.env.ref("base.EUR")
        euro.active = True
        export = Pricelist.create({"name": "Експорт (EUR)", "company_id": self.company.id,
                                   "currency_id": euro.id})

        self._load_chart()

        self.assertEqual(self.company.currency_id.name, "UAH")
        self.assertEqual(default.currency_id, self.company.currency_id,
                         "типовий прайс-лист має піти за валютою компанії, "
                         "інакше замовлення мовчки виходять у доларах")
        self.assertEqual(export.currency_id, euro,
                         "експортний прайс-лист заведено свідомо - його не чіпаємо")


@tagged("post_install", "-at_install", "ua_regress")
class TestBankMfoNotBic(TransactionCase):
    """МФО має шість цифр, BIC - вісім або одинадцять.

    OCA account_payment_order перевіряє довжину BIC, тому банк з МФО в полі bic
    створити не можна. МФО живе у власному полі ua_mfo, bic лишається порожнім.
    """

    def test_bank_with_mfo_and_empty_bic(self):
        bank = self.env["res.bank"].create({
            "name": "АТ КБ «ПриватБанк»",
            "ua_mfo": "305299",
            "country": self.env.ref("base.ua").id,
        })
        self.assertEqual(bank.ua_mfo, "305299")
        self.assertFalse(bank.bic)

    def test_bic_check_of_payment_order_is_still_on(self):
        if "account.payment.order" not in self.env:
            self.skipTest("account_payment_order не встановлено - перевіряти нічого")
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env["res.bank"].create({"name": "Хибний BIC", "bic": "305299"})

    def test_mfo_must_be_six_digits(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env["res.bank"].create({"name": "Хибний МФО", "ua_mfo": "30529"})

    def test_partner_bank_mfo_comes_from_iban_then_from_bank(self):
        bank = self.env["res.bank"].create({"name": "Банк", "ua_mfo": "300465"})
        partner = self.env["res.partner"].create({"name": "Регрес: контрагент"})
        account = self.env["res.partner.bank"].create({
            "acc_number": "UA213223130000026007233566001",
            "partner_id": partner.id, "bank_id": bank.id,
        })
        self.assertEqual(account.ua_mfo, "322313", "IBAN важить більше за довідник")
        account.acc_number = "DE89370400440532013000"
        self.assertEqual(account.ua_mfo, "300465", "не український IBAN - МФО з довідника")


@tagged("post_install", "-at_install", "ua_regress")
@freeze_time("2026-09-21 23:30:00")
class TestDocumentDateIsUserDate(TransactionCase):
    """Дата документа - робочий день користувача, а не дата сервера.

    О 23:30 UTC у Києві вже 22 вересня. fields.Date.today віддавав 21-ше, і штатний
    розпис розходився в даті з наказом, який складає ua_compose.
    """

    def setUp(self):
        super().setUp()
        self.env.user.tz = "Europe/Kyiv"

    def test_staff_list_default_date_is_kyiv_date(self):
        staff_list = self.env["ua.staff.list"].create({"company_id": self.env.company.id})
        self.assertEqual(str(staff_list.date), "2026-09-22",
                         "після 21:00 UTC київська дата вже наступна")

    def test_military_documents_use_the_same_date(self):
        military = self.env["ua.military.list"].create({
            "company_id": self.env.company.id, "tcc": "Львівський районний ТЦК та СП"})
        self.assertEqual(str(military.date), "2026-09-22")
        reserved = self.env["ua.military.reserved"].create({"company_id": self.env.company.id})
        self.assertEqual(str(reserved.date), "2026-09-22")

    def test_wizard_defaults_use_the_same_date(self):
        wizard = self.env["ua.staff.list.wizard"].create({})
        self.assertEqual(str(wizard.date), "2026-09-22")
