# -*- coding: utf-8 -*-
"""Майстер «Операції банку» (ua.bank.ops.wizard): вхід до ua.bank.ops поки немає екрана.

Раніше клієнтський екран (l10n_ua_bank_ui, знятий з полиці 2026-09-22) слав ім'я методу
з поля вводу, і сервер викликав його без перевірки - відкрита поверхня. Майстер натомість
має фіксований список дій (Selection): тут перевіряємо, що кожен ключ веде рівно до свого
методу ua.bank.ops, що чужого ключа не існує технічно (не лише за угодою), і що дії
«Звести з платежами» / «Застосувати правила» рахують так, як документує ua_bank_ops.py -
зведення платежем спершу, правило за текстом лише там, де платежу немає.

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
class TestUaBankOpsWizard(TransactionCase):

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

    def _wizard(self, **values):
        return self.env["ua.bank.ops.wizard"].create(dict({"journal_id": self.journal.id}, **values))

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
    def test_01_wizard_form_view_loads(self):
        result = self.env["ua.bank.ops.wizard"].get_views([(False, "form")])
        self.assertIn("form", result["views"])
        arch = result["views"]["form"]["arch"]
        self.assertIn("action_run", arch)
        self.assertIn("operation", result["models"]["ua.bank.ops.wizard"]["fields"])

    # ------------------------------------------------------------------ 2. ключ - фіксований, не рядок
    def test_02_unknown_operation_is_impossible(self):
        """Чужого ключа немає технічно: Selection відмовляє ще до дії, не лише за угодою."""
        with self.assertRaises(ValueError):
            self._wizard(operation="run_action")  # ім'я старого відкритого входу теж не проходить
        with self.assertRaises(ValueError):
            self._wizard(operation="unlink")

    def test_03_service_selection_lists_ukrainian_banks(self):
        wizard = self._wizard()
        services = dict(wizard._selection_service())
        self.assertEqual(services.get("ua_privat"), "ПриватБанк (Автоклієнт)")
        self.assertEqual(services.get("ua_mono"), "Monobank")

    # ------------------------------------------------------------------ 4. pull_month -> ua.bank.ops.action_pull_month
    def test_04_pull_month_dispatches_and_dedupes(self):
        self._demo_provider()
        wizard = self._wizard(operation="pull_month", year=2031, month="1")
        before = self.env["account.bank.statement.line"].search_count([("journal_id", "=", self.journal.id)])

        action = wizard.action_run()

        self.assertEqual(action["res_model"], "ua.bank.ops.wizard")
        self.assertIn("Завантажено рядків", wizard.result_message)
        after = self.env["account.bank.statement.line"].search_count([("journal_id", "=", self.journal.id)])
        self.assertGreaterEqual(after - before, 8, "демо-зразок дає щонайменше 8 рядків")

        # повторний виклик того самого місяця не дублює (unique_import_id зі зразка детермінований)
        wizard.action_run()
        self.assertIn("Завантажено рядків: 0", wizard.result_message)
        again = self.env["account.bank.statement.line"].search_count([("journal_id", "=", self.journal.id)])
        self.assertEqual(again, after, "повторне завантаження нічого не додало")

    def test_05_pull_month_without_journal_raises_the_ops_error(self):
        """Майстер не дублює перевірку - її вже робить ua.bank.ops._provider()."""
        wizard = self.env["ua.bank.ops.wizard"].create({"operation": "pull_month", "year": 2031, "month": "1"})
        with self.assertRaises(UserError):
            wizard.action_run()

    # ------------------------------------------------------------------ 5. pull_all -> ua.bank.ops.action_pull_all
    def test_06_pull_all_dispatches_to_every_connected_journal(self):
        self._demo_provider()
        wizard = self._wizard(operation="pull_all", year=2031, month="2")

        wizard.action_run()

        self.assertIn(self.journal.name, wizard.result_message)
        self.assertIn("Завантажено рядків", wizard.result_message)
        count = self.env["account.bank.statement.line"].search_count(
            [("journal_id", "=", self.journal.id), ("date", ">=", "2031-02-01"), ("date", "<", "2031-03-01")])
        self.assertGreaterEqual(count, 8)

    # ------------------------------------------------------------------ 6. test -> ua.bank.ops.action_test (демо, без мережі)
    def test_07_test_connection_dispatches_in_demo_mode(self):
        self._demo_provider()
        wizard = self._wizard(operation="test")

        wizard.action_run()

        self.assertEqual(wizard.result_message, "Банк відповідає.")

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

        wizard = self._wizard(operation="match_payments")
        wizard.action_run()

        self.assertIn("Зведено з платежами: 1", wizard.result_message)
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

        wizard = self._wizard(operation="apply_rules")
        wizard.action_run()

        self.assertIn("Зведено з платежами: 1. Звірено за правилами: 0.", wizard.result_message)
        self.assertTrue(line.is_reconciled)

    def test_10_apply_rules_falls_back_to_the_regex_rule_without_a_payment(self):
        employee = self._employee("Тест Візард Правила Б", "3200000004", "UA763052990000026207000120404")
        slip = self._payslip(employee)
        net = self._net(slip)
        line = self._statement_line(
            -net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120404", partner_name=employee.name)

        wizard = self._wizard(operation="apply_rules")
        wizard.action_run()

        self.assertIn("Звірено за правилами: 1", wizard.result_message)
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

        wizard = self._wizard(operation="apply_rules")
        wizard.action_run()

        # рахунок за правилом знайдено (661), але платіж під ту саму пару вже стоїть -
        # правило не подвоює суму, а лишає рядок чекати бухгалтера (waiting, не skipped)
        self.assertIn("Зведено з платежами: 0. Звірено за правилами: 0.", wizard.result_message)
        self.assertIn("Чекають на платіж: 1", wizard.result_message)
        self.assertFalse(line.is_reconciled, "інша сума - рядок лишається бухгалтеру, не дублює 661")

    def test_12_apply_rules_without_a_journal_covers_the_whole_company(self):
        employee = self._employee("Тест Візард Компанія", "3200000006", "UA763052990000026207000120406")
        slip = self._payslip(employee)
        net = self._net(slip)
        line = self._statement_line(
            -net, "Заробітна плата за серпень 2026, остаточний розрахунок",
            iban="UA763052990000026207000120406", partner_name=employee.name)

        wizard = self.env["ua.bank.ops.wizard"].create({"operation": "apply_rules"})  # без journal_id
        wizard.action_run()

        self.assertTrue(line.is_reconciled)

    # ------------------------------------------------------------------ 9. open_provider -> дві гілки ua.bank.ops
    def test_13_open_provider_without_journal_lists_all_providers(self):
        wizard = self.env["ua.bank.ops.wizard"].create({"operation": "open_provider"})
        action = wizard.action_run()
        self.assertEqual(action.get("res_model"), "online.bank.statement.provider")
        self.assertFalse(action.get("res_id"), "без рахунку - перелік, не форма одного запису")

    def test_14_open_provider_with_an_existing_connection_opens_its_form(self):
        provider = self._demo_provider()
        wizard = self._wizard(operation="open_provider")

        action = wizard.action_run()

        self.assertEqual(action.get("res_model"), "online.bank.statement.provider")
        self.assertEqual(action.get("res_id"), provider.id)

    def test_15_open_provider_without_service_refuses_to_create_one(self):
        self.assertFalse(self.journal.online_bank_statement_provider_id, "рахунок ще без з'єднання")
        wizard = self._wizard(operation="open_provider")  # без service
        with self.assertRaises(UserError):
            wizard.action_run()

    def test_16_open_provider_creates_one_when_missing(self):
        self.assertFalse(self.journal.online_bank_statement_provider_id, "рахунок ще без з'єднання")
        wizard = self._wizard(operation="open_provider", service="ua_mono")

        action = wizard.action_run()

        self.assertEqual(action.get("res_model"), "online.bank.statement.provider")
        self.assertTrue(self.journal.online_bank_statement_provider_id)
        self.assertEqual(self.journal.online_bank_statement_provider_id.service, "ua_mono")
