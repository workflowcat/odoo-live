# -*- coding: utf-8 -*-
"""Платіж відомості і рядок виписки закривають гроші один раз. Тег `ua_payments`.

Раніше проведений платіж робив Дт 661 / Кт 311, і рядок виписки про ту саму зарплату
правило звірки теж кодувало на 661: сума лягала двічі. Тепер банківський журнал має
рахунок 333 «Грошові кошти в дорозі», платіж іде Дт 661 / Кт 333, а рядок виписки
зводиться з цим платежем і робить Дт 333 / Кт 311. Тут перевіряємо саме це коло:
рахунок у журналі, проводку платежу, зведення, межі зведення (інша сума не зводиться,
однакові суми розрізняються за IBAN), повторний прогін і повний шлях від листків до нуля
на 661, 333 і одного руху на 311.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PERIOD = ("2026-08-01", "2026-08-31")
PAY_DATE = "2026-09-04"


@tagged("post_install", "-at_install", "ua_payments")
class TestUaBankMatching(TransactionCase):

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

    # ------------------------------------------------------------------ побудова даних
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
        """Відомість за серпень, проведена до кінця: платежі стоять на 333."""
        order = self.env["account.payment.order"].ua_compose(self.company, 2026, 8, "salary")
        order.ua_pay_date = PAY_DATE
        order.action_confirm()
        order.action_paid()
        return order

    def _statement_line(self, amount, ref, iban="", partner_name="", date=PAY_DATE):
        """Рядок виписки так, як його дає банк: сума зі знаком, призначення, рахунок."""
        return self.env["account.bank.statement.line"].create({
            "journal_id": self.journal.id, "date": date, "payment_ref": ref,
            "amount": amount, "account_number": iban, "partner_name": partner_name,
            "company_id": self.company.id,
        })

    def _apply_rules(self):
        return self.env["ua.bank.ops"].action_apply_rules(self.journal.id)

    def _balance(self, code, date_to="2026-09-30"):
        account = self._account(code)
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("parent_state", "=", "posted"),
            ("company_id", "=", self.company.id), ("date", "<=", date_to),
        ])
        return round(sum(lines.mapped("balance")), 2)

    @staticmethod
    def _net(slip):
        return round(sum(slip.line_ids.filtered(lambda l: l.code == "NET").mapped("total")), 2)

    # ------------------------------------------------------------------ 1. рахунок у журналі
    def test_01_bank_journal_gets_the_transit_account(self):
        """План ua_psbo дає банківському журналу рахунок 333 в обидва боки."""
        transit = self._account("333")
        self.assertTrue(transit, "у плані має бути рахунок 333")
        self.assertEqual(transit.code, "333")
        self.assertTrue(transit.reconcile, "333 має бути звірюваним: на ньому сходяться платіж і виписка")
        lines = (self.journal.inbound_payment_method_line_ids |
                 self.journal.outbound_payment_method_line_ids)
        self.assertTrue(lines, "у журналу мають бути способи платежу")
        for line in lines:
            self.assertEqual(line.payment_account_id, transit,
                             "спосіб платежу «%s» має платити через 333" % line.name)
        self.assertIn(transit, self.journal._get_journal_outbound_outstanding_payment_accounts())
        self.assertIn(transit, self.journal._get_journal_inbound_outstanding_payment_accounts())

    # ------------------------------------------------------------------ 2. проводка платежу
    def test_02_payment_debits_661_and_credits_333(self):
        """Проведений платіж відомості: Дт 661 / Кт 333, рахунку 311 він не чіпає."""
        employee = self._employee("Тест Транзит", "3100000001", "UA763052990000026207000110401")
        slip = self._payslip(employee)
        order = self._paid_order()

        payment = order.payment_ids
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.outstanding_account_id, self._account("333"))
        self.assertEqual(payment.destination_account_id, self._account("661"))
        lines = payment.move_id.line_ids
        debit = lines.filtered(lambda l: l.debit > 0)
        credit = lines.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit.account_id, self._account("661"))
        self.assertEqual(credit.account_id, self._account("333"))
        self.assertAlmostEqual(credit.credit, self._net(slip), 2)
        self.assertNotIn(self.journal.default_account_id, lines.account_id,
                         "гроші ще не дійшли до банку, тому 311 у проводці платежу немає")

    # ------------------------------------------------------------------ 3. зведення
    def test_03_matched_line_clears_333_and_leaves_661_alone(self):
        """Рядок виписки зводиться з платежем: 333 у нуль, 661 не рухається вдруге."""
        employee = self._employee("Тест Зведення", "3100000002", "UA763052990000026207000110402")
        slip = self._payslip(employee)
        net = self._net(slip)
        order = self._paid_order()
        balance_661 = self._balance("661")
        self.assertAlmostEqual(self._balance("333"), -net, 2, "гроші поки в дорозі")

        line = self._statement_line(-net, "Заробітна плата за серпень 2026, остаточний розрахунок",
                                    iban="UA763052990000026207000110402", partner_name=employee.name)
        result = self._apply_rules()

        self.assertEqual(result["matched"], 1, result["message"])
        self.assertEqual(result["applied"], 0, "правило за текстом не спрацювало: платіж уже є")
        self.assertTrue(line.is_reconciled)
        self.assertAlmostEqual(self._balance("333"), 0.0, 2, "333 закрито рядком виписки")
        self.assertAlmostEqual(self._balance("661"), balance_661, 2,
                               "661 закрив платіж; виписка його вдруге не чіпає")
        self.assertTrue(order.payment_ids.is_matched, "платіж позначено як такий, що дійшов")

    # ------------------------------------------------------------------ 4. запасний шлях
    def test_04_line_without_a_payment_falls_back_to_the_661_rule(self):
        """Без платежу рядок виписки закриває правило за текстом - як і раніше."""
        employee = self._employee("Тест Без Платежу", "3100000003", "UA763052990000026207000110403")
        slip = self._payslip(employee)
        net = self._net(slip)
        balance_661 = self._balance("661")

        line = self._statement_line(-net, "Заробітна плата за серпень 2026, остаточний розрахунок",
                                    iban="UA763052990000026207000110403", partner_name=employee.name)
        result = self._apply_rules()

        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["applied"], 1, result["message"])
        self.assertTrue(line.is_reconciled)
        _liquidity, _suspense, other = line._seek_for_lines()
        self.assertEqual(other.account_id, self._account("661"))
        self.assertAlmostEqual(self._balance("661"), balance_661 + net, 2,
                               "виписка сама закрила борг перед працівником")

    # ------------------------------------------------------------------ 5. інша сума
    def test_05_a_different_amount_does_not_match_and_does_not_fall_back(self):
        """Часткова оплата не зводиться - і правило за текстом її теж не чіпає."""
        employee = self._employee("Тест Часткова", "3100000004", "UA763052990000026207000110404")
        slip = self._payslip(employee)
        net = self._net(slip)
        self._paid_order()
        balance_661 = self._balance("661")

        line = self._statement_line(-(net - 100.0),
                                    "Заробітна плата за серпень 2026, остаточний розрахунок",
                                    iban="UA763052990000026207000110404", partner_name=employee.name)
        result = self._apply_rules()

        self.assertEqual(result["matched"], 0, "суми різні - платіж не той")
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["waiting"], 1, result["message"])
        self.assertFalse(line.is_reconciled, "рядок лишається бухгалтеру, а не тихо дублює 661")
        self.assertAlmostEqual(self._balance("661"), balance_661, 2)

    # ------------------------------------------------------------------ 6. однакові суми
    def test_06_same_amount_two_employees_are_told_apart_by_iban(self):
        """Дві однакові суми розрізняються за IBAN: кожен рядок бере свій платіж."""
        first = self._employee("Тест Однакова А", "3100000005", "UA763052990000026207000110405")
        second = self._employee("Тест Однакова Б", "3100000006", "UA763052990000026207000110406")
        slips = self._payslip(first) + self._payslip(second)
        nets = {slip.employee_id: self._net(slip) for slip in slips}
        self.assertAlmostEqual(nets[first], nets[second], 2, "однакова ставка - однакова сума")
        net = nets[first]
        order = self._paid_order()

        lines = {}
        for employee, iban in ((first, "UA763052990000026207000110405"),
                               (second, "UA763052990000026207000110406")):
            lines[employee] = self._statement_line(
                -net, "Заробітна плата за серпень 2026, остаточний розрахунок",
                iban=iban, partner_name=employee.name)
        result = self._apply_rules()

        self.assertEqual(result["matched"], 2, result["message"])
        by_partner = {payment.partner_id: payment for payment in order.payment_ids}
        for employee, line in lines.items():
            self.assertTrue(line.is_reconciled)
            _liquidity, _suspense, other = line._seek_for_lines()
            partner = employee.work_contact_id
            self.assertEqual(other.partner_id, partner,
                             "рядок узяв платіж саме того працівника, чий IBAN стоїть у виписці")
            self.assertTrue(by_partner[partner].is_matched)
        self.assertAlmostEqual(self._balance("333"), 0.0, 2)

    # ------------------------------------------------------------------ 7. повторний прогін
    def test_07_running_it_twice_changes_nothing(self):
        """Другий прогін не зводить нічого вдруге і не рухає жодного залишку."""
        employee = self._employee("Тест Повтор", "3100000007", "UA763052990000026207000110407")
        slip = self._payslip(employee)
        net = self._net(slip)
        self._paid_order()
        self._statement_line(-net, "Заробітна плата за серпень 2026, остаточний розрахунок",
                             iban="UA763052990000026207000110407", partner_name=employee.name)

        first = self._apply_rules()
        self.assertEqual(first["matched"], 1)
        snapshot = (self._balance("661"), self._balance("333"), self._balance("311"))

        second = self._apply_rules()
        self.assertEqual(second["matched"], 0)
        self.assertEqual(second["applied"], 0)
        self.assertEqual((self._balance("661"), self._balance("333"), self._balance("311")),
                         snapshot, "залишки після другого прогону ті самі")

    # ------------------------------------------------------------------ 8. повне коло
    def test_08_full_circle_leaves_661_and_333_at_zero_and_311_moved_once(self):
        """Листки -> відомість -> проведення -> виписка: 661 = 0, 333 = 0, 311 рушив раз."""
        people = [
            ("Тест Коло Перший", "3100000008", "UA763052990000026207000110408", 20000.0),
            ("Тест Коло Другий", "3100000009", "UA763052990000026207000110409", 17000.0),
            ("Тест Коло Третій", "3100000010", "UA763052990000026207000110410", 24000.0),
        ]
        employees = [self._employee(*person) for person in people]
        slips = [self._payslip(employee) for employee in employees]
        nets = [self._net(slip) for slip in slips]
        total = round(sum(nets), 2)

        order = self._paid_order()
        self.assertAlmostEqual(order.total_company_currency, total, 2)
        self.assertEqual(len(order.payment_ids), 3)

        bank = self.journal.default_account_id
        before_311 = self._balance(bank.code)
        for (_name, _rnokpp, iban, _wage), net in zip(people, nets):
            self._statement_line(-net, "Заробітна плата за серпень 2026, остаточний розрахунок",
                                 iban=iban)
        result = self._apply_rules()

        self.assertEqual(result["matched"], 3, result["message"])
        self.assertEqual(result["applied"], 0)
        self.assertAlmostEqual(self._balance("661"), 0.0, 2,
                               "борг перед працівниками закрито рівно один раз")
        self.assertAlmostEqual(self._balance("333"), 0.0, 2, "грошей у дорозі не лишилось")
        self.assertAlmostEqual(self._balance(bank.code), before_311 - total, 2,
                               "з рахунку пішла сума відомості, і лише вона")
        moves = self.env["account.move.line"].search([
            ("account_id", "=", bank.id), ("parent_state", "=", "posted"),
            ("company_id", "=", self.company.id), ("credit", ">", 0)])
        self.assertEqual(len(moves), 3, "на кожного працівника - один рух по рахунку банку")
        self.assertTrue(all(payment.is_matched for payment in order.payment_ids))
