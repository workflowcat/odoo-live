"""Договори контрагентів і акт звірки.

Числа прості, щоб звірити очима. Покупець має два договори:
  Д1 «15/2026» - основний, сума 10 000, понад суму не проводити;
  Д2 «16/2026» - другий, без суми.
До періоду: рахунок 15.01.2026 за Д1 на 1 000.
Період 01.02-31.03.2026:
  рахунок 10.02 за Д1 на 6 000,
  оплата 20.02 за Д1 на 4 000,
  рахунок 05.03 за Д2 на 2 500.
Акт за всіма договорами: сальдо на початок 1 000, дебет 6 000 + 2 500 = 8 500,
кредит 4 000, сальдо на кінець 1 000 + 8 500 - 4 000 = 5 500.
Акт за Д1: 1 000 + 6 000 - 4 000 = 3 000. Сальдо Д1 те саме: 3 000; виставлено 7 000.
Рахунки без ПДВ, щоб сума рахунку дорівнювала сумі рядка.
"""
from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_contract")
class TestUaContract(TransactionCase):
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

        cls.income = cls.env["account.account"].search(
            [("code", "=like", "70%"), ("company_ids", "in", cls.company.id)], limit=1, order="code")
        assert cls.income, "у плані ua_psbo немає рахунку 70"
        cls.sale_journal = cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", cls.company.id)], limit=1)
        cls.bank_journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1)

        cls.customer = cls.env["res.partner"].create({
            "name": "ТОВ Покупець", "is_company": True, "company_registry": "12345678",
        })
        cls.contact = cls.env["res.partner"].create({
            "name": "Олена Контактна", "parent_id": cls.customer.id,
        })
        Contract = cls.env["ua.contract"]
        cls.c1 = Contract.create({
            "name": "15/2026", "date": date(2026, 1, 3), "partner_id": cls.contact.id,
            "kind": "sale", "is_main": True, "amount": 10000.0, "limit_mode": "block",
        })
        cls.c2 = Contract.create({
            "name": "16/2026", "date": date(2026, 2, 3), "partner_id": cls.customer.id, "kind": "sale",
        })

    # ------------------------------------------------------------------
    # Допоміжне
    # ------------------------------------------------------------------
    def _invoice(self, amount, day, contract=None, post=True, partner=None):
        vals = {
            "move_type": "out_invoice",
            "partner_id": (partner or self.customer).id,
            "invoice_date": day,
            "journal_id": self.sale_journal.id,
            "invoice_line_ids": [Command.create({
                "name": "Обслуговування обладнання",
                "quantity": 1,
                "price_unit": amount,
                "tax_ids": [Command.clear()],
                "account_id": self.income.id,
            })],
        }
        if contract is not None:
            vals["ua_contract_id"] = contract.id
        move = self.env["account.move"].create(vals)
        if post:
            move.action_post()
        return move

    def _pay(self, move, amount, day):
        wizard = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=move.ids,
        ).create({"payment_date": day, "amount": amount, "journal_id": self.bank_journal.id})
        wizard.action_create_payments()
        return self.env["account.payment"].search(
            [("partner_id", "=", self.customer.id), ("date", "=", day)], limit=1)

    def _history(self):
        i0 = self._invoice(1000.0, date(2026, 1, 15))
        i1 = self._invoice(6000.0, date(2026, 2, 10))
        pay = self._pay(i1, 4000.0, date(2026, 2, 20))
        i2 = self._invoice(2500.0, date(2026, 3, 5), contract=self.c2)
        return i0, i1, pay, i2

    def _act(self, contract=None):
        act = self.env["ua.reconciliation.act"].create({
            "partner_id": self.contact.id,
            "contract_id": contract.id if contract else False,
            "date_from": date(2026, 2, 1),
            "date_to": date(2026, 3, 31),
        })
        act.action_fill()
        return act

    # ------------------------------------------------------------------
    # Договір
    # ------------------------------------------------------------------
    def test_01_contract_belongs_to_the_company_partner(self):
        """Контактна особа замінюється на її компанію; друкована назва - як у підставі."""
        self.assertEqual(self.c1.partner_id, self.customer)
        self.assertEqual(self.c1._ua_print_name(), "Договір № 15/2026 від 03.01.2026")

    def test_02_one_main_contract_per_partner_and_kind(self):
        with self.assertRaises(ValidationError):
            self.env["ua.contract"].create({
                "name": "17/2026", "partner_id": self.customer.id, "kind": "sale", "is_main": True,
            })
        # Основний договір іншого виду - можна.
        self.env["ua.contract"].create({
            "name": "П-1", "partner_id": self.customer.id, "kind": "purchase", "is_main": True,
        })

    def test_03_new_documents_take_the_main_contract(self):
        invoice = self._invoice(100.0, date(2026, 2, 1), post=False)
        self.assertEqual(invoice.ua_contract_id, self.c1)
        self.assertEqual(invoice._ua_docs_basis(), "Договір № 15/2026 від 03.01.2026")
        # Контрагент без договорів - договору немає.
        other = self.env["res.partner"].create({"name": "ФОП Інший", "is_company": True})
        self.assertFalse(self._invoice(100.0, date(2026, 2, 1), post=False, partner=other).ua_contract_id)
        # Лише один чинний договір - він і підставляється, навіть не основний.
        single = self.env["ua.contract"].create({"name": "1", "partner_id": other.id, "kind": "sale"})
        self.assertEqual(self._invoice(100.0, date(2026, 2, 1), post=False, partner=other).ua_contract_id, single)

    def test_04_payment_and_journal_lines_carry_the_contract(self):
        _i0, i1, pay, _i2 = self._history()
        self.assertEqual(pay.ua_contract_id, self.c1)
        self.assertTrue(pay.move_id, "оплата має проводку")
        self.assertEqual(pay.move_id.ua_contract_id, self.c1)
        self.assertEqual(set(pay.move_id.line_ids.ua_contract_id.ids), {self.c1.id})
        self.assertEqual(set(i1.line_ids.ua_contract_id.ids), {self.c1.id})

    def test_05_contract_totals(self):
        self._history()
        # Виставлено за Д1: 1 000 + 6 000 = 7 000; залишок 10 000 - 7 000 = 3 000.
        self.assertAlmostEqual(self.c1.invoiced_amount, 7000.0, 2)
        self.assertAlmostEqual(self.c1.remaining_amount, 3000.0, 2)
        # Сальдо Д1: 7 000 - 4 000 = 3 000; Д2: 2 500.
        self.assertAlmostEqual(self.c1.balance, 3000.0, 2)
        self.assertAlmostEqual(self.c2.balance, 2500.0, 2)

    def test_06_contract_amount_blocks_posting(self):
        self._history()
        # 7 000 + 3 500 = 10 500 > 10 000.
        over = self._invoice(3500.0, date(2026, 3, 10), post=False)
        with self.assertRaises(UserError):
            over.action_post()
        # Рівно до суми договору - проводиться: 7 000 + 3 000 = 10 000.
        exact = self._invoice(3000.0, date(2026, 3, 10))
        self.assertEqual(exact.state, "posted")

    def test_07_warn_mode_posts_with_a_note(self):
        self.c1.limit_mode = "warn"
        self._history()
        over = self._invoice(3500.0, date(2026, 3, 10))
        self.assertEqual(over.state, "posted")
        self.assertTrue(any("перевищує суму договору" in (m.body or "") for m in over.message_ids))

    def test_08_closed_contract_blocks_posting(self):
        self.c2.action_close()
        invoice = self._invoice(100.0, date(2026, 3, 10), contract=self.c2, post=False)
        with self.assertRaises(UserError):
            invoice.action_post()

    def test_09_separate_accounting_puts_analytics_on_lines(self):
        contract = self.env["ua.contract"].create({
            "name": "ДК-7", "partner_id": self.customer.id, "kind": "sale", "separate_accounting": True,
        })
        self.assertTrue(contract.analytic_account_id)
        self.assertEqual(contract.analytic_account_id.plan_id,
                         self.env.ref("l10n_ua_contract.analytic_plan_contracts"))
        invoice = self._invoice(500.0, date(2026, 3, 10), contract=contract)
        line = invoice.invoice_line_ids
        self.assertEqual(line.analytic_distribution, {str(contract.analytic_account_id.id): 100})

    def test_10_sale_order_passes_its_contract_to_the_invoice(self):
        product = self.env["product.product"].create({
            "name": "Ремонт", "type": "service", "invoice_policy": "order",
            "list_price": 300.0, "taxes_id": [Command.clear()],
        })
        order = self.env["sale.order"].create({
            "partner_id": self.contact.id,
            "order_line": [Command.create({"product_id": product.id, "product_uom_qty": 1})],
        })
        self.assertEqual(order.ua_contract_id, self.c1)
        order.ua_contract_id = self.c2
        order.action_confirm()
        invoice = order._create_invoices()
        self.assertEqual(invoice.ua_contract_id, self.c2)

    # ------------------------------------------------------------------
    # Акт звірки
    # ------------------------------------------------------------------
    def test_20_act_for_all_contracts(self):
        self._history()
        act = self._act()
        self.assertEqual(act.partner_id, self.customer)
        self.assertTrue(act.name.startswith("АЗВ-2026-"))
        self.assertAlmostEqual(act.opening_balance, 1000.0, 2)
        self.assertAlmostEqual(act.debit_total, 8500.0, 2)
        self.assertAlmostEqual(act.credit_total, 4000.0, 2)
        self.assertAlmostEqual(act.closing_balance, 5500.0, 2)
        self.assertEqual(len(act.line_ids), 3)
        self.assertEqual(act.line_ids.mapped("date"), [date(2026, 2, 10), date(2026, 2, 20), date(2026, 3, 5)])
        self.assertTrue(act.line_ids[0].document.startswith("Реалізація № "))
        self.assertTrue(act.line_ids[1].document.startswith("Оплата від контрагента"))
        self.assertEqual(act.line_ids[2].contract_id, self.c2)
        text = act._ua_conclusion()
        self.assertTrue(text.startswith("Станом на 31.03.2026 заборгованість ТОВ Покупець перед "), text)

    def test_21_act_for_one_contract(self):
        self._history()
        act = self._act(self.c1)
        self.assertAlmostEqual(act.opening_balance, 1000.0, 2)
        self.assertAlmostEqual(act.debit_total, 6000.0, 2)
        self.assertAlmostEqual(act.credit_total, 4000.0, 2)
        self.assertAlmostEqual(act.closing_balance, 3000.0, 2)

    def test_22_agreeing_needs_matching_figures(self):
        self._history()
        act = self._act()
        act.action_mark_sent()
        with self.assertRaises(UserError):
            act.action_mark_agreed()          # дані контрагента не внесено
        act.write({"their_filled": True, "their_closing_balance": 5400.0})
        self.assertAlmostEqual(act.difference, 100.0, 2)
        with self.assertRaises(UserError):
            act.action_mark_agreed()
        act.their_closing_balance = 5500.0
        act.action_mark_agreed()
        self.assertEqual(act.state, "agreed")
        with self.assertRaises(UserError):
            act.action_fill()                 # узгоджений акт не перезаповнюється

    def test_23_act_prints(self):
        self._history()
        act = self._act()
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_contract.action_report_ua_reconciliation_act", act.ids)
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("АКТ ЗВІРКИ", html)
        self.assertIn("ТОВ Покупець", html)
        flat = html.replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace(",", "")
        self.assertIn("5500.00", flat)

    def test_24_contract_button_opens_an_act_for_this_year(self):
        action = self.c1.action_new_reconciliation_act()
        act = self.env["ua.reconciliation.act"].browse(action["res_id"])
        today = date.today()
        self.assertEqual(act.contract_id, self.c1)
        self.assertEqual(act.partner_id, self.customer)
        self.assertEqual(act.date_from, today.replace(month=1, day=1))
