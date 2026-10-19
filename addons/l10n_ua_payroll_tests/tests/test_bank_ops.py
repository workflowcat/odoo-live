# -*- coding: utf-8 -*-
"""Операції банку кнопками: список виписок і форма банківського журналу.

Раніше клієнтський екран (l10n_ua_bank_ui, знятий з полиці 2026-09-22) слав ім'я методу
з поля вводу, і сервер викликав його без перевірки - відкрита поверхня. Потім був майстер
із фіксованим переліком дій; 2026-09-22 пішов і він: меню відкриває сторінку, а разові
дії стоять кнопками там, де людина дивиться на виписки. Кожна кнопка веде рівно до свого
методу ua.bank.ops, чужого входу немає, а дії «Звести з платежами» / «Застосувати правила»
рахують так, як документує ua_bank_ops.py - зведення платежем спершу, правило за текстом
лише там, де платежу немає. Єдиний параметр (рахунок і місяць) живе в діалозі
ua.bank.pull з трьох полів.

Рецепт побудови компанії/журналу/листка - той самий, що в test_bank_matching.py
(тег ua_payments): та сама виписка, той самий платіж, той самий рахунок 333.
Тут додатково користуємось демо-режимом провайдера (ua_demo), щоб перевірити
завантаження виписки і перевірку зв'язку без токена банку і без мережі."""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PERIOD = ("2026-08-01", "2026-08-31")
PAY_DATE = "2026-09-04"


@tagged("post_install", "-at_install", "ua_bank")
class TestUaBankOps(TransactionCase):

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
        from odoo.addons.l10n_ua_chart.hooks import _short_codes
        _short_codes(cls.env)
        cls.env["account.account"].invalidate_model(["code"])
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        assert cls.structure, "немає структури UA_SALARY"
        cls.calendar = cls.company.resource_calendar_id
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)
        assert cls.journal, "у компанії немає банківського журналу"

    # ------------------------------------------------------------------ рецепт test_bank_matching.py
    def _account(self, code):
        return self.env["account.account"].with_company(self.company).search(
            [("code", "=like", "%s%%" % code), ("company_ids", "in", self.company.id)],
            order="code", limit=1)

    def _employee(self, name, rnokpp, iban, wage=20000.0):
        partner = self.env["res.partner"].create({"name": name, "company_id": self.company.id})
        employee = self.env["hr.employee"].create({
            "name": name, "company_id": self.company.id, "work_contact_id": partner.id,
            "ua_rnokpp": rnokpp, "ua_contract_kind": "employment", "ua_fte": "1",
            "resource_calendar_id": self.calendar.id,
        })
        bank = self.env["res.partner.bank"].create({
            "acc_number": iban, "partner_id": partner.id, "company_id": self.company.id})
        employee.bank_account_ids = [(6, 0, bank.ids)]
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": wage, "date_version": "2026-01-01", "contract_date_start": "2026-01-01",
            "struct_id": self.structure.id, "resource_calendar_id": self.calendar.id,
        })
        return employee

    def _payslip(self, employee):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id, "date_from": PERIOD[0], "date_to": PERIOD[1],
            "struct_id": self.structure.id, "name": employee.name, "company_id": self.company.id,
        })
        slip.onchange_employee()
        slip.compute_sheet()
        slip.action_payslip_done()
        return slip

    def _paid_order(self):
        order = self.env["account.payment.order"].ua_compose(self.company, 2026, 8, "salary")
        order.ua_pay_date = PAY_DATE
        order.action_confirm()
        order.action_paid()
        return order

    def _statement_line(self, amount, ref, iban="", partner_name="", date=PAY_DATE):
        return self.env["account.bank.statement.line"].create({
            "journal_id": self.journal.id, "date": date, "payment_ref": ref,
            "amount": amount, "account_number": iban, "partner_name": partner_name,
            "company_id": self.company.id,
        })

    @staticmethod
    def _net(slip):
        return round(sum(slip.line_ids.filtered(lambda l: l.code == "NET").mapped("total")), 2)

    def _pull(self, **values):
        return self.env["ua.bank.pull"].create(dict({"journal_id": self.journal.id}, **values))

    @property
    def _statements(self):
        """Кнопки списку виписок кличуться на порожньому наборі - як їх кличе шапка списку."""
        return self.env["account.bank.statement"]

    @staticmethod
    def _message(action):
        return ((action or {}).get("params") or {}).get("message") or ""

    def _demo_provider(self, service="ua_privat"):
        provider = self.journal.online_bank_statement_provider_id
        if not provider:
            provider = self.env["online.bank.statement.provider"].create({
                "journal_id": self.journal.id, "service": service,
                "statement_creation_mode": "monthly", "interval_type": "hours", "interval_number": 12,
            })
        provider.write({"ua_demo": True, "service": service})
        return provider

    # ------------------------------------------------------------------ 1. форма
    def test_01_pull_dialog_form_view_loads(self):
        result = self.env["ua.bank.pull"].get_views([(False, "form")])
        self.assertIn("form", result["views"])
        arch = result["views"]["form"]["arch"]
        self.assertIn("action_pull", arch)
        for field in ("journal_id", "year", "month"):
            self.assertIn(field, result["models"]["ua.bank.pull"]["fields"])

    # ------------------------------------------------------------------ 2. кнопки, а не пункт меню
    def test_02_operations_are_buttons_on_the_statement_list(self):
        """Чужого входу немає: кожна дія - окремий метод, а не ім'я методу з поля."""
        for method in ("action_ua_pull", "action_ua_pull_all",
                       "action_ua_match_payments", "action_ua_apply_rules"):
            self.assertTrue(hasattr(self._statements, method), method)
        for method in ("action_ua_bank_test", "action_ua_bank_provider"):
            self.assertTrue(hasattr(self.journal, method), method)
        self.assertNotIn("ua.bank.ops.wizard", self.env, "майстра «Операції банку» немає")
        arch = self.env["account.bank.statement"].get_views([(False, "list")])["views"]["list"]["arch"]
        self.assertIn("action_ua_pull", arch, "кнопки стоять у шапці списку виписок")

    def test_03_pull_dialog_lists_ukrainian_banks_months(self):
        pull = self._pull()
        months = dict(pull._selection_month())
        self.assertEqual(months.get("1"), "Січень")
        Provider = self.env["online.bank.statement.provider"]
        services = dict(Provider.with_context(lang="uk_UA")._get_available_services())
        self.assertEqual(services.get("ua_privat"), "ПриватБанк (Автоклієнт)")
        english = dict(Provider.with_context(lang="en_US")._get_available_services())
        self.assertEqual(english.get("ua_privat"), "PrivatBank (Autoclient)")
        self.assertEqual(services.get("ua_mono"), "Monobank")

    # ------------------------------------------------------------------ 4. pull_month -> ua.bank.ops.action_pull_month
    def test_04_pull_month_dispatches_and_dedupes(self):
        self._demo_provider()
        pull = self._pull(year=2031, month="1")
        before = self.env["account.bank.statement.line"].search_count([("journal_id", "=", self.journal.id)])

        action = pull.action_pull()

        self.assertIn("Завантажено рядків", self._message(action))
        after = self.env["account.bank.statement.line"].search_count([("journal_id", "=", self.journal.id)])
        self.assertGreaterEqual(after - before, 8, "демо-зразок дає щонайменше 8 рядків")

        # повторний виклик того самого місяця не дублює (unique_import_id зі зразка детермінований)
        self.assertIn("Завантажено рядків: 0", self._message(pull.action_pull()))
        again = self.env["account.bank.statement.line"].search_count([("journal_id", "=", self.journal.id)])
        self.assertEqual(again, after, "повторне завантаження нічого не додало")

    def test_05_pull_month_without_a_connection_raises_the_ops_error(self):
        """Діалог не дублює перевірку - її вже робить ua.bank.ops._provider()."""
        self.assertFalse(self.journal.online_bank_statement_provider_id)
        with self.assertRaises(UserError):
            self._pull(year=2031, month="1").action_pull()

    # ------------------------------------------------------------------ 5. pull_all -> ua.bank.ops.action_pull_all
    def test_06_pull_all_dispatches_to_every_connected_journal(self):
        self._demo_provider()
        message = (self.env["ua.bank.ops"].action_pull_all(2031, 2) or {}).get("message") or ""

        self.assertIn(self.journal.name, message)
        self.assertIn("Завантажено рядків", message)
        count = self.env["account.bank.statement.line"].search_count(
            [("journal_id", "=", self.journal.id), ("date", ">=", "2031-02-01"), ("date", "<", "2031-03-01")])
        self.assertGreaterEqual(count, 8)

    # ------------------------------------------------------------------ 6. test -> ua.bank.ops.action_test (демо, без мережі)
    def test_07_test_connection_dispatches_in_demo_mode(self):
        self._demo_provider()
        self.assertEqual(self._message(self.journal.action_ua_bank_test()), "Банк відповідає.")

    # ------------------------------------------------------------------ 7. match_payments -> ua.bank.ops.action_match_payments
    def test_08_match_payments_matches_but_does_not_apply_rules(self):
        """match_payments зводить рядок з платежем; рядок без платежу лишає без змін -
        якщо він застосував би правило, вибір команди в майстрі не мав би значення.

        rule_employee навмисно заведений і проведений ПІСЛЯ того, як платіжне доручення
        вже складене й оплачене - тому платежу під його рядком виписки не існує взагалі
        (не лише "не той same"), а не через збіг за сумою чи IBAN."""
        matched_employee = self._employee("Тест Візард Зведення", "3200000001", "UA763052990000026207000120401")
        matched_slip = self._payslip(matched_employee)
        matched_net = self._net(matched_slip)
        self._paid_order()  # складено, поки rule_employee ще не існує - платежу для нього не буде

        rule_employee = self._employee("Тест Візард Правило", "3200000002", "UA763052990000026207000120402")
        rule_slip = self._payslip(rule_employee)
        rule_net = self._net(rule_slip)

        matched_line = self._statement_line(
            -matched_net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120401", partner_name=matched_employee.name)
        rule_line = self._statement_line(
            -rule_net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120402", partner_name=rule_employee.name)

        message = self._message(self._statements.action_ua_match_payments())

        self.assertIn("Зведено з платежами: 1", message)
        self.assertTrue(matched_line.is_reconciled, "рядок із платежем зведено")
        self.assertFalse(rule_line.is_reconciled,
                         "match_payments не застосовує правило - це дія apply_rules, не ця")

    # ------------------------------------------------------------------ 8. apply_rules -> ua.bank.ops.action_apply_rules
    def test_09_apply_rules_matches_payment_first(self):
        """Зведення з платежем - як задокументовано в ua_bank_ops.py: спершу платіж, не правило."""
        employee = self._employee("Тест Візард Правила А", "3200000003", "UA763052990000026207000120403")
        slip = self._payslip(employee)
        net = self._net(slip)
        self._paid_order()
        line = self._statement_line(
            -net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120403", partner_name=employee.name)

        message = self._message(self._statements.action_ua_apply_rules())

        self.assertIn("Зведено з платежами: 1. Звірено за правилами: 0.", message)
        self.assertTrue(line.is_reconciled)

    def test_10_apply_rules_falls_back_to_the_regex_rule_without_a_payment(self):
        employee = self._employee("Тест Візард Правила Б", "3200000004", "UA763052990000026207000120404")
        slip = self._payslip(employee)
        net = self._net(slip)
        line = self._statement_line(
            -net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120404", partner_name=employee.name)

        message = self._message(self._statements.action_ua_apply_rules())

        self.assertIn("Звірено за правилами: 1", message)
        self.assertTrue(line.is_reconciled)
        _liquidity, _suspense, other = line._seek_for_lines()
        self.assertEqual(other.account_id, self._account("661"))

    def test_11_apply_rules_leaves_a_partial_amount_waiting(self):
        employee = self._employee("Тест Візард Часткова", "3200000005", "UA763052990000026207000120405")
        slip = self._payslip(employee)
        net = self._net(slip)
        self._paid_order()
        line = self._statement_line(
            -(net - 100.0), "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120405", partner_name=employee.name)

        message = self._message(self._statements.action_ua_apply_rules())

        # рахунок за правилом знайдено (661), але платіж під ту саму пару вже стоїть -
        # правило не подвоює суму, а лишає рядок чекати бухгалтера (waiting, не skipped)
        self.assertIn("Зведено з платежами: 0. Звірено за правилами: 0.", message)
        self.assertIn("Чекають на платіж: 1", message)
        self.assertFalse(line.is_reconciled, "інша сума - рядок лишається бухгалтеру, не дублює 661")

    def test_12_apply_rules_without_a_journal_covers_the_whole_company(self):
        employee = self._employee("Тест Візард Компанія", "3200000006", "UA763052990000026207000120406")
        slip = self._payslip(employee)
        net = self._net(slip)
        line = self._statement_line(
            -net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120406", partner_name=employee.name)

        self._statements.action_ua_apply_rules()  # кнопка списку - по всій компанії

        self.assertTrue(line.is_reconciled)

    # ------------------------------------------------------------------ 9. open_provider -> дві гілки ua.bank.ops
    def test_13_provider_button_without_a_connection_lists_all_providers(self):
        self.assertFalse(self.journal.online_bank_statement_provider_id, "рахунок ще без з'єднання")
        action = self.journal.action_ua_bank_provider()
        self.assertEqual(action.get("res_model"), "online.bank.statement.provider")
        self.assertFalse(action.get("res_id"), "без з'єднання - перелік, не форма одного запису")

    def test_14_provider_button_with_an_existing_connection_opens_its_form(self):
        provider = self._demo_provider()

        action = self.journal.action_ua_bank_provider()

        self.assertEqual(action.get("res_model"), "online.bank.statement.provider")
        self.assertEqual(action.get("res_id"), provider.id)

    def test_15_creating_a_connection_needs_the_bank_service(self):
        """Створення з'єднання лишилось у ua.bank.ops: без служби банку воно неможливе."""
        self.assertFalse(self.journal.online_bank_statement_provider_id, "рахунок ще без з'єднання")
        with self.assertRaises(Exception):
            self.env["ua.bank.ops"].action_create_provider(self.journal.id, False)

    def test_16_create_provider_sets_the_service(self):
        self.assertFalse(self.journal.online_bank_statement_provider_id, "рахунок ще без з'єднання")

        action = self.env["ua.bank.ops"].action_create_provider(self.journal.id, "ua_mono")

        self.assertEqual(action.get("res_model"), "online.bank.statement.provider")
        self.assertTrue(self.journal.online_bank_statement_provider_id)
        self.assertEqual(self.journal.online_bank_statement_provider_id.service, "ua_mono")
