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

    def test_account_names_are_ukrainian_after_the_chart_is_loaded(self):
        """201 - «Сировина й матеріали», а не «Raw materials and supplies».

        Переклади плану брало `_load_translations` одним заходом на всі компанії
        разом. Компанія без плану (а на встановленні модуля таких усі) валила
        виклик, і в лог ішло «Не вдалося застосувати переклади плану рахунків» -
        після чого назви рахунків лишалися англійськими в усіх компаній, навіть
        у тієї, чий план щойно завантажили. Тепер кожна компанія перекладається
        окремо, а компанія без плану просто пропускається.
        """
        chartless = self.env["res.company"].create({"name": "Без плану рахунків"})
        self.assertFalse(chartless.chart_template)
        self._load_chart()
        Account = self.env["account.account"].with_company(self.company)
        account = Account.search(
            [("code", "=", "201"), ("company_ids", "in", self.company.id)])
        self.assertEqual(len(account), 1, "рахунок 201 має бути рівно один")
        self.assertEqual(account.with_context(lang="uk_UA").name,
                         "Сировина й матеріали")

    def test_chart_shape_repairs_an_already_loaded_chart(self):
        """Ремонт бази, де план уже стоїть, а назви англійські.

        Це шлях `post_init_hook`. Раніше він брав усі компанії одним викликом
        `_load_translations`, і перша ж компанія без плану валила його
        TypeError - у лог ішло «Не вдалося застосувати переклади плану
        рахунків», і жодна компанія перекладу не отримувала.
        """
        from odoo.addons.l10n_ua_chart.hooks import apply_chart_shape
        self._load_chart()
        self.env["res.company"].create({"name": "Друга без плану"})
        Account = self.env["account.account"].with_company(self.company)
        account = Account.search(
            [("code", "=", "201"), ("company_ids", "in", self.company.id)])
        # знімаємо український переклад - так виглядає база, яку треба лагодити
        self.env.cr.execute(
            "UPDATE account_account SET name = name - 'uk_UA' WHERE id = %s",
            (account.id,))
        account.invalidate_recordset(["name"])
        self.assertEqual(account.with_context(lang="uk_UA").name,
                         "Raw materials and supplies")

        apply_chart_shape(self.env)

        account.invalidate_recordset(["name"])
        self.assertEqual(account.with_context(lang="uk_UA").name,
                         "Сировина й матеріали",
                         "хук має повернути українську назву, а не спинитися "
                         "на компанії без плану")

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

    def test_doc_check_default_date_is_kyiv_date(self):
        """Майстра штатного розпису більше немає (2026-09-22); те саме правило дати
        перевіряємо на новому документі «Перевірка документів»."""
        doc = self.env["ua.hr.doc.check"].create({"company_id": self.env.company.id})
        self.assertEqual(str(doc.date), "2026-09-22")


@tagged("post_install", "-at_install", "ua_regress")
class TestHistoryOfOneEmployee(TransactionCase):
    """Регресії, знайдені на збірці історії компанії за 21 місяць (docs/base/demo-world.md).

    Обидві проявляються лише в людини з минулим: кілька версій договору або звільнення
    посеред місяця, за який табель складають уже після наказу.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env["hr.employee"].create({
            "name": "Регрес: людина з історією", "company_id": cls.company.id, "ua_contract_kind": "employment",
            "sex": "male"})
        cls.employee.version_id.with_context(sync_contract_dates=True).write({
            "date_version": "2025-01-01", "contract_date_start": "2025-01-01", "wage": 20000.0,
            "ua_pay_type": "hourly", "ua_hour_rate": 150.0,
            "struct_id": cls.env.ref("l10n_ua_payroll_rules.struct_ua_salary").id,
        })

    def _order(self, order_type, **vals):
        return self.env["ua.hr.order"].create(dict(
            vals, order_type=order_type, employee_id=self.employee.id, company_id=self.company.id))

    def test_dismissal_closes_every_version_of_the_contract(self):
        """Після зміни окладу версій дві. Наказ про звільнення закривав лише поточну, і рідна
        перевірка відмовляла: «already has a contract running during the selected period»."""
        self._order("wage", date="2025-06-25", date_from="2025-07-01", wage=22000.0).action_post()
        versions = self.employee.with_context(active_test=False).version_ids
        self.assertEqual(len(versions), 2, "зміна окладу дала другу версію того самого договору")
        newest = versions.sorted("date_version")[-1]
        self.assertEqual(newest.wage, 22000.0)
        # нова версія - копія попередньої: поля картки і умови оплати не губляться
        self.assertEqual(newest.sex, "male", "стать живе у версії і має перейти в нову")
        self.assertEqual(newest.ua_pay_type, "hourly", "погодинник лишається погодинником")
        self.assertEqual(newest.ua_hour_rate, 150.0)
        self.assertEqual(self.employee.sex, "male")
        dismissal = self._order("dismissal", date="2025-09-26", date_to="2025-09-30",
                                dismissal_basis="п. 1 ст. 36 КЗпП (угода сторін)")
        dismissal.action_post()
        versions.invalidate_recordset()
        self.assertEqual({str(v.contract_date_end) for v in versions}, {"2025-09-30"},
                         "дата закінчення стоїть на всіх версіях договору")
        self.assertFalse(self.employee.active)
        # скасування повертає договір безстроковим на всіх версіях
        dismissal.action_cancel()
        versions.invalidate_recordset()
        self.assertFalse(any(v.contract_date_end for v in versions))
        self.assertTrue(self.employee.active)

    def test_timesheet_keeps_employee_dismissed_in_the_month(self):
        """Наказ про звільнення архівує картку одразу, а табель за цей місяць складають після.
        Звільнений посеред місяця має лишитися в табелі: дні до звільнення - робочі, далі «-»."""
        self._order("dismissal", date="2025-03-11", date_to="2025-03-14",
                    dismissal_basis="п. 1 ст. 36 КЗпП (угода сторін)").action_post()
        self.assertFalse(self.employee.active)
        sheet = self.env["ua.timesheet.sheet"].create({"company_id": self.company.id, "year": 2025, "month": 3})
        sheet.action_refill()
        line = sheet.line_ids.filtered(lambda l: l.employee_id == self.employee)
        self.assertEqual(len(line), 1, "звільнений у березні є в березневому табелі")
        self.assertEqual(line.d14, "Р", "останній день роботи - робочий")
        self.assertEqual(line.d17, "-", "після звільнення днів немає")
        later = self.env["ua.timesheet.sheet"].create({"company_id": self.company.id, "year": 2025, "month": 4})
        later.action_refill()
        self.assertNotIn(self.employee, later.line_ids.mapped("employee_id"), "у квітні його вже немає")

    def test_timesheet_counts_trip_study_and_service(self):
        """П-5: дні відрядження, навчальної відпустки і військової служби мають свої підсумки
        і разом із фактом дають норму місяця. Раніше вони не рахувалися ніде, і рядок табеля
        показував «менше норми»."""
        for code, date_from, date_to in (("TRIP", "2025-03-03", "2025-03-05"), ("STUDY", "2025-03-10", "2025-03-11"),
                                         ("MIL", "2025-03-24", "2025-03-31")):
            leave_type = self.env["hr.leave.type"].search([("work_entry_type_id.code", "=", code)], limit=1)
            self.env["hr.leave"].with_context(leave_skip_state_check=True, mail_notrack=True).create({
                "employee_id": self.employee.id, "holiday_status_id": leave_type.id,
                "request_date_from": date_from, "request_date_to": date_to}).sudo().action_approve()
        sheet = self.env["ua.timesheet.sheet"].create({"company_id": self.company.id, "year": 2025, "month": 3})
        sheet.action_refill()
        line = sheet.line_ids.filtered(lambda l: l.employee_id == self.employee)
        self.assertEqual((line.days_trip, line.days_study, line.days_mil), (3, 2, 6))
        self.assertEqual(line.d24, "ІН", "військова служба - «інші неявки, передбачені законодавством»")
        self.assertAlmostEqual(line.diff_days, 0.0, msg="факт плюс усі відсутності - рівно норма")


@tagged("post_install", "-at_install", "ua_regress")
class TestPayrollParams2025(TransactionCase):
    """Параметри закону на 2025 рік: без них листок за 2025 рік падав на «Немає параметра»."""

    def test_params_for_2025_and_2026(self):
        Param = self.env["ua.payroll.param"]
        self.assertEqual(Param.get("min_wage", "2025-06-30"), 8000.0)
        self.assertEqual(Param.get("living_wage", "2025-06-30"), 3028.0)
        self.assertEqual(Param.get("psp_base", "2025-06-30"), 1514.0)
        self.assertEqual(Param.get("psp_threshold", "2025-06-30"), 4240.0)
        self.assertEqual(Param.get("min_wage", "2026-01-31"), 8647.0)
        # кожен ключ 2026 року має значення і на 2025 рік
        for key in set(Param.search([]).mapped("key")):
            self.assertTrue(Param.get(key, "2025-01-31") is not None, key)


@tagged("post_install", "-at_install", "ua_regress")
class TestHourlyPayHasEntry(TransactionCase):
    """Погодинна оплата і надбавка за нічні мають рядок у карті проводок.

    HOURLY і NIGHT карта не знала: листок погодинника рахувався і виплачувався, а нарахування
    в книги не лягало - за 19 місяців історії на 661 зібралося 475 тис. грн дебетового залишку."""

    def test_hourly_and_night_are_mapped(self):
        Map = self.env["ua.payroll.account.map"]
        for code in ("HOURLY", "NIGHT"):
            row = Map.search([("rule_code", "=", code)], limit=1)
            self.assertTrue(row, "правило %s без проводки" % code)
            self.assertEqual(row.debit_side, "expense")
            self.assertEqual(row.credit_code, "661")
