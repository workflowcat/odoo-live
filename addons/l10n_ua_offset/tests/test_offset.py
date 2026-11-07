# -*- coding: utf-8 -*-
"""Взаємозалік з контрагентом, який і купує в компанії, і продає їй.

ТОВ Зустрічний (тест), два договори: продаж С-1 і купівля П-1. Без ПДВ, щоб суми були
круглі:
    реалізація 10.01 на 30 000 (С-1) і 10.02 на 20 000 (С-1) - контрагент винен 50 000;
    надходження 20.01 на 35 000 (П-1) - компанія винна 35 000.
Залік бере меншу суму, 35 000: перша реалізація закривається повністю, з другої - 5 000,
надходження - повністю. Скасування повертає 30 000, 20 000 і 35 000.

Запуск: чиста база, тег ua_offset.
"""
from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_offset")
class TestUaDebtOffset(TransactionCase):

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
        Account = cls.env["account.account"]
        cls.income = Account.search(
            [("code", "=like", "70%"), ("company_ids", "in", cls.company.id)], limit=1, order="code")
        cls.expense = Account.search(
            [("account_type", "=", "expense"), ("company_ids", "in", cls.company.id)], limit=1,
            order="code")
        cls.partner = cls.env["res.partner"].create({
            "name": "ТОВ Зустрічний (тест)", "is_company": True, "company_registry": "33334444"})
        Contract = cls.env["ua.contract"]
        cls.sale_contract = Contract.create({
            "name": "С-1", "date": date(2026, 1, 3), "partner_id": cls.partner.id, "kind": "sale"})
        cls.purchase_contract = Contract.create({
            "name": "П-1", "date": date(2026, 1, 3), "partner_id": cls.partner.id, "kind": "purchase"})
        cls.inv1 = cls._doc("out_invoice", 30000.0, date(2026, 1, 10), cls.sale_contract)
        cls.inv2 = cls._doc("out_invoice", 20000.0, date(2026, 2, 10), cls.sale_contract)
        cls.bill = cls._doc("in_invoice", 35000.0, date(2026, 1, 20), cls.purchase_contract,
                            ref="ВН-17")

    @classmethod
    def _doc(cls, move_type, amount, day, contract, ref=None):
        move = cls.env["account.move"].create({
            "move_type": move_type, "partner_id": cls.partner.id, "invoice_date": day,
            "ref": ref, "ua_contract_id": contract.id,
            "invoice_line_ids": [Command.create({
                "name": "Комплектуючі (тест)", "quantity": 1, "price_unit": amount,
                "tax_ids": [Command.clear()],
                "account_id": (cls.income if move_type == "out_invoice" else cls.expense).id})]})
        move.action_post()
        return move

    def _offset(self, **values):
        return self.env["ua.debt.offset"].create(dict({"partner_id": self.partner.id}, **values))

    def test_01_fill_post_cancel(self):
        offset = self._offset()
        self.assertEqual(offset.open_amounts(), (50000.0, 35000.0))
        offset.action_fill()
        rows = [(l.side, l.move_id, l.amount) for l in offset.line_ids]
        self.assertEqual(sorted(rows, key=lambda r: (r[0], r[1].id)), sorted([
            ("receivable", self.inv1, 30000.0), ("receivable", self.inv2, 5000.0),
            ("payable", self.bill, 35000.0)], key=lambda r: (r[0], r[1].id)))
        self.assertEqual((offset.receivable_total, offset.payable_total, offset.amount),
                         (35000.0, 35000.0, 35000.0))

        offset.action_post()
        self.assertEqual(offset.state, "posted")
        self.assertEqual(offset.move_id.state, "posted")
        self.assertEqual((self.inv1.amount_residual, self.inv2.amount_residual,
                          self.bill.amount_residual), (0.0, 15000.0, 0.0))
        self.assertEqual(offset.open_amounts(), (15000.0, 0.0))
        lines = offset.move_id.line_ids
        self.assertEqual(sum(lines.mapped("debit")), 35000.0)
        self.assertEqual(lines.filtered(lambda l: l.debit).ua_contract_id, self.purchase_contract)
        self.assertEqual(lines.filtered(lambda l: l.credit).ua_contract_id, self.sale_contract)
        self.assertTrue(lines.filtered(lambda l: l.debit).account_id.code.startswith("63"))
        self.assertTrue(lines.filtered(lambda l: l.credit).account_id.code.startswith("36"))
        with self.assertRaises(UserError):
            offset.unlink()

        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_offset.report_ua_debt_offset", offset.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("АКТ ВЗАЄМОЗАЛІКУ", offset.name, "ТОВ Зустрічний (тест)", "33334444",
                         "35 000,00", "5 000,00", "Надходження № ВН-17", "статтею 601", "С-1"):
            self.assertIn(expected, text)
        if offset.currency_id.name == "UAH":
            self.assertIn("Тридцять п", text)  # апостроф у HTML екранується
            self.assertIn("тисяч гривень 00 копійок", text)

        offset.action_cancel()
        self.assertEqual((offset.state, offset.move_id.state), ("cancel", "cancel"))
        self.assertEqual((self.inv1.amount_residual, self.inv2.amount_residual,
                          self.bill.amount_residual), (30000.0, 20000.0, 35000.0))

    def test_02_limit_and_contract(self):
        offset = self._offset(amount_limit=10000.0, receivable_contract_id=self.sale_contract.id,
                              payable_contract_id=self.purchase_contract.id)
        offset.action_fill()
        self.assertEqual([(l.move_id, l.amount) for l in offset.line_ids.sorted("side")],
                         [(self.bill, 10000.0), (self.inv1, 10000.0)])
        offset.action_post()
        self.assertEqual((self.inv1.amount_residual, self.bill.amount_residual), (20000.0, 25000.0))

        other = self.env["ua.contract"].create({
            "name": "С-2", "date": date(2026, 1, 3), "partner_id": self.partner.id, "kind": "sale"})
        empty = self._offset(receivable_contract_id=other.id)
        with self.assertRaises(UserError):
            empty.action_fill()  # за С-2 контрагент нічого не винен
        stranger = self.env["res.partner"].create({"name": "Інший (тест)", "is_company": True})
        with self.assertRaises(ValidationError):
            self._offset(receivable_contract_id=self.env["ua.contract"].create({
                "name": "Х-1", "date": date(2026, 1, 3), "partner_id": stranger.id,
                "kind": "sale"}).id)

    def test_03_guards(self):
        offset = self._offset()
        offset.action_fill()
        offset.line_ids.filtered(lambda l: l.side == "payable").amount = 30000.0
        with self.assertRaises(UserError):
            offset.action_post()  # сторони не рівні
        offset.action_fill()
        first = self._offset()
        first.action_fill()
        first.action_post()
        with self.assertRaises(UserError):
            offset.action_post()  # борги вже закрито першим заліком
        with self.assertRaises(ValidationError):
            offset.line_ids.filtered(lambda l: l.side == "payable").side = "receivable"
