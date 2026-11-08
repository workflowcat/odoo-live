# -*- coding: utf-8 -*-
"""Інвентаризація необоротних активів на 02.11.2026, нова компанія з планом ПСБО.

- верстат (ОЗ-101, 12 000, введено 15.01.2026, 60 місяців): знос лютий-жовтень 9 x 200 = 1 800,
  залишкова 10 200; є, але стоїть у цеху № 2 - місце в картці оновлюється;
- ноутбук (ОЗ-102, 6 000, введено 10.03.2026): знос квітень-жовтень 7 x 100 = 700, залишкова 5 300;
  не знайдено: Дт 131 700, Дт 947 5 300, Кт 104 6 000; з винної особи 2 000 - Дт 375 Кт 716;
- принтер понад облік, оцінка 3 000: Дт 104 Кт 746, OCA створює актив ОЗ-103.

Запуск: тег ua_asset_inventory.
"""
import datetime

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "ua_asset_inventory")
class TestUaAssetInventory(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.profile = cls.env["account.asset.profile"].search([
            ("company_id", "=", cls.company.id), ("ua_tax_group", "=", "oz_04"), ("ua_rule", "=", "linear")],
            limit=1)
        Asset = cls.env["account.asset"]
        cls.machine = Asset.create({
            "name": "Верстат фрезерний (тест)", "code": "ОЗ-101", "profile_id": cls.profile.id,
            "purchase_value": 12000.0, "date_start": "2026-01-15", "method_number": 60,
            "ua_location": "Цех № 1", "ua_responsible": "Петренко П. П.", "ua_factory_number": "F-7781"})
        cls.laptop = Asset.create({
            "name": "Ноутбук конструктора (тест)", "code": "ОЗ-102", "profile_id": cls.profile.id,
            "purchase_value": 6000.0, "date_start": "2026-03-10", "method_number": 60,
            "ua_location": "Конструкторське бюро", "ua_responsible": "Петренко П. П."})
        for asset in cls.machine | cls.laptop:
            asset.validate()
            asset._compute_entries(datetime.date(2026, 10, 31))
        cls.culprit = cls.env["res.partner"].create({"name": "Іваненко Іван (тест інвентаризації)"})
        cls.inventory = cls.env["ua.asset.inventory"].create({
            "date": "2026-11-02", "order_ref": "Наказ № 45 від 28.10.2026 (тест)",
            "commission": "Голова комісії - Сидоренко С. С.\nЧлен комісії - Коваль К. К.",
            "filter_responsible": "Петренко П. П."})

    def _fill_and_mark(self):
        inv = self.inventory
        inv.action_fill()
        by_code = {l.inventory_number: l for l in inv.line_ids}
        by_code["ОЗ-101"].location_fact = "Цех № 2"
        by_code["ОЗ-102"].write({"found": False, "culprit_partner_id": self.culprit.id, "culprit_amount": 2000.0})
        inv.surplus_ids = [(0, 0, {"kind": "surplus", "name": "Принтер лазерний (тест)", "inventory_number": "ОЗ-103",
                                   "profile_id": self.profile.id, "value": 3000.0, "location_fact": "Бухгалтерія",
                                   "responsible_fact": "Петренко П. П."})]
        return by_code

    def test_01_fill_book_values(self):
        by_code = self._fill_and_mark()
        machine, laptop = by_code["ОЗ-101"], by_code["ОЗ-102"]
        self.assertEqual((machine.cost, machine.depreciation, machine.residual), (12000, 1800, 10200))
        self.assertEqual((laptop.cost, laptop.depreciation, laptop.residual), (6000, 700, 5300))
        self.assertEqual(machine.location_book, "Цех № 1")
        inv = self.inventory
        self.assertEqual((inv.count_book, inv.count_found, inv.count_missing, inv.count_surplus), (2, 1, 1, 1))
        self.assertEqual((inv.residual_book, inv.residual_missing, inv.culprit_total, inv.surplus_total),
                         (15500, 5300, 2000, 3000))
        self.assertEqual(inv.shortage_account_id.code, "947")
        self.assertEqual(inv.surplus_account_id.code, "746")

        inv.filter_responsible = "Інша особа"
        inv.action_fill()
        self.assertFalse(inv.line_ids)
        self.assertEqual(len(inv.surplus_ids), 1, "лишки не зникають під час перезаповнення")

    def test_02_post_results(self):
        self._fill_and_mark()
        inv = self.inventory
        inv.action_post()
        self.assertEqual(inv.state, "done")
        self.assertEqual(self.laptop.state, "removed")
        self.assertEqual(self.machine.ua_location, "Цех № 2")

        laptop_line = inv.line_ids.filtered(lambda l: l.inventory_number == "ОЗ-102")
        removal = laptop_line.removal_move_id
        self.assertEqual(removal.state, "posted")
        amounts = {(l.account_id.code, l.debit, l.credit) for l in removal.line_ids}
        self.assertEqual(amounts, {("131", 700, 0), ("947", 5300, 0), ("104", 0, 6000)})
        culprit = {(l.account_id.code, l.debit, l.credit) for l in laptop_line.culprit_move_id.line_ids}
        self.assertEqual(culprit, {("375", 2000, 0), ("716", 0, 2000)})
        self.assertEqual(laptop_line.culprit_move_id.line_ids.partner_id, self.culprit)

        surplus = inv.surplus_ids
        self.assertEqual({(l.account_id.code, l.debit, l.credit) for l in surplus.removal_move_id.line_ids},
                         {("104", 3000, 0), ("746", 0, 3000)})
        printer = surplus.asset_id
        self.assertTrue(printer)
        self.assertEqual((printer.code, printer.purchase_value, printer.profile_id, printer.ua_location),
                         ("ОЗ-103", 3000, self.profile, "Бухгалтерія"))
        self.assertEqual(len(inv.move_ids), 3)
        with self.assertRaises(UserError):
            inv.action_post()
        with self.assertRaises(UserError):
            inv.unlink()

    def test_03_checks_and_print(self):
        by_code = self._fill_and_mark()
        by_code["ОЗ-102"].culprit_partner_id = False
        with self.assertRaises(UserError):
            self.inventory.action_post()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_asset_inventory.report_ua_asset_inventory", self.inventory.ids)[0].decode()
        self.assertIn("Інвентаризаційний опис необоротних активів", html)
        self.assertIn("Порівняльна відомість результатів інвентаризації", html)
        self.assertIn("10 200,00", html)
        self.assertIn("5 300,00", html)
        self.assertIn("Наказ № 45", html)
