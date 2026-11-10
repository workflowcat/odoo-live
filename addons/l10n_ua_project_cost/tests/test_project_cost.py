# -*- coding: utf-8 -*-
"""Витрати на створення НМА: зарплата за проєктами -> 154 -> актив -> амортизація на ліцензії.

Розробник за вересень: 120 годин на проєкті, що створює програму (рахунок 154), і 40 годин на
підтримці (рахунок витрат працівника). Проведений листок ділить кожну суму витрат 3:1. Потім
вартість проєкту з 154 вводиться в експлуатацію активом НМА, а амортизація активу ділиться між
проданими ліцензіями за кількістю. Суми листка тримають еталонні сценарії; тут - поділ.

Запуск: чиста база, тег ua_project_cost.
"""
import calendar
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

YEAR = 2026


@tagged("post_install", "-at_install", "ua_project_cost")
class TestUaProjectCost(TransactionCase):

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
        Profile = cls.env["account.asset.profile"]
        if not Profile.search([("company_id", "=", cls.company.id), ("ua_tax_group", "=", "nma_5")], limit=1):
            Profile._ua_create_profiles(cls.company)
        cls.profile = Profile.search([("company_id", "=", cls.company.id), ("ua_tax_group", "=", "nma_5"),
                                      ("ua_rule", "=", "linear")], limit=1)
        cls.capex = cls.env["ua.ia.capitalization"]._default_source_account()
        if not cls.capex:
            cls.capex = cls.env["account.account"].create({
                "code": "154", "name": "Придбання (створення) нематеріальних активів",
                "account_type": "asset_non_current", "company_ids": [(6, 0, cls.company.ids)]})
        plan = cls.env["account.analytic.plan"].create({"name": "Проєкти (тест)"})
        Analytic = cls.env["account.analytic.account"]
        cls.build = Analytic.create({"name": "Програма обліку (розробка)", "plan_id": plan.id})
        cls.support = Analytic.create({"name": "Підтримка клієнтів", "plan_id": plan.id})

        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.calendar = cls.company.resource_calendar_id
        cls.developer = cls.env["hr.employee"].create({
            "name": "Розробник (тест)", "company_id": cls.company.id, "ua_contract_kind": "employment",
            "ua_main_job": True, "ua_rnokpp": "3000000888", "resource_calendar_id": cls.calendar.id})
        cls.developer.version_id.with_context(sync_contract_dates=True).write({
            "wage": 40000.0, "date_version": date(YEAR, 1, 1), "contract_date_start": date(YEAR, 1, 1),
            "struct_id": cls.structure.id, "resource_calendar_id": cls.calendar.id})

    # ---- службове ----------------------------------------------------------------------
    def _allocation(self, month=9):
        return self.env["ua.payroll.allocation"].create({
            "company_id": self.company.id, "month": date(YEAR, month, 20),
            "line_ids": [
                (0, 0, {"employee_id": self.developer.id, "analytic_account_id": self.build.id,
                        "account_id": self.capex.id, "hours": 120.0}),
                (0, 0, {"employee_id": self.developer.id, "analytic_account_id": self.support.id, "hours": 40.0}),
            ]})

    def _slip(self, month=9):
        start, end = date(YEAR, month, 1), date(YEAR, month, calendar.monthrange(YEAR, month)[1])
        slip = self.env["hr.payslip"].create({
            "employee_id": self.developer.id, "date_from": start, "date_to": end,
            "struct_id": self.structure.id, "name": self.developer.name, "company_id": self.company.id})
        slip.onchange_employee()
        slip.compute_sheet()
        slip.action_payslip_done()
        self.assertTrue(slip.move_id)
        return slip

    @staticmethod
    def _analytic_of(line):
        return set((line.analytic_distribution or {}).keys())

    # ---- 1. Листок ділить витрати за годинами -----------------------------------------
    def test_payslip_expense_split_by_hours(self):
        allocation = self._allocation()
        self.assertEqual(allocation.month, date(YEAR, 9, 1), "місяць документа - перше число")
        allocation.action_confirm()
        slip = self._slip()
        expense = slip._ua_expense_account()
        lines = slip.move_id.line_ids
        to_build = lines.filtered(lambda l: l.account_id == self.capex)
        to_support = lines.filtered(lambda l: l.account_id == expense)
        self.assertTrue(to_build and to_support, "витрати лягли на 154 і на рахунок працівника")
        self.assertTrue(all(self._analytic_of(l) == {str(self.build.id)} for l in to_build))
        self.assertTrue(all(self._analytic_of(l) == {str(self.support.id)} for l in to_support))
        build = sum(to_build.mapped("balance"))
        support = sum(to_support.mapped("balance"))
        total = build + support
        self.assertGreater(total, 40000.0, "зарплата плюс ЄСВ")
        # кожна сума ділиться окремо, тож частка 3/4 точна до копійки на рядок
        self.assertAlmostEqual(build, total * 0.75, delta=0.01 * len(to_build))
        self.assertAlmostEqual(sum(lines.mapped("balance")), 0.0, places=2, msg="проводка збалансована")
        texts = " ".join(check["text"] for check in allocation._checks())
        self.assertNotIn("до затвердження", texts)

    def test_draft_allocation_does_not_split(self):
        allocation = self._allocation()
        slip = self._slip()
        self.assertFalse(slip.move_id.line_ids.filtered(lambda l: l.account_id == self.capex),
                         "чернетка розподілу не діє")
        allocation.action_confirm()
        texts = " ".join(check["text"] for check in allocation._checks())
        self.assertIn("до затвердження", texts, "листок, проведений раніше, видно в перевірках")

    # ---- 2. Введення НМА в експлуатацію ------------------------------------------------
    def test_capitalization_creates_asset_and_clears_154(self):
        self._allocation().action_confirm()
        self._slip()
        Cap = self.env["ua.ia.capitalization"]
        built = Cap._analytic_balance(self.capex, self.build, self.company, date(YEAR, 9, 30))
        self.assertGreater(built, 0.0)
        doc = Cap.create({"name": "Програма обліку, версія 1", "date": date(YEAR, 9, 30),
                          "analytic_account_id": self.build.id, "source_account_id": self.capex.id,
                          "profile_id": self.profile.id})
        doc.action_post()
        self.assertEqual(doc.state, "posted")
        self.assertAlmostEqual(doc.amount, built, places=2)
        asset = doc.asset_id
        self.assertTrue(asset, "картку активу створено")
        self.assertEqual(asset.state, "open")
        self.assertAlmostEqual(asset.purchase_value, built, places=2)
        self.assertEqual(asset.profile_id, self.profile)
        self.assertAlmostEqual(Cap._analytic_balance(self.capex, self.build, self.company, date(YEAR, 9, 30)), 0.0,
                               places=2, msg="на 154 за проєктом нічого не лишилось")

        doc.action_cancel()
        self.assertEqual(doc.state, "cancel")
        self.assertFalse(asset.exists(), "скасування прибирає картку активу")
        self.assertAlmostEqual(Cap._analytic_balance(self.capex, self.build, self.company, date(YEAR, 9, 30)),
                               built, places=2, msg="сторно повертає вартість на 154")

    def test_capitalization_needs_a_balance(self):
        doc = self.env["ua.ia.capitalization"].create({
            "name": "Порожній проєкт", "date": date(YEAR, 9, 30), "analytic_account_id": self.support.id,
            "source_account_id": self.capex.id, "profile_id": self.profile.id})
        with self.assertRaises(UserError):
            doc.action_post()

    # ---- 3. Амортизація на ліцензії ---------------------------------------------------
    def _depreciating_asset(self):
        # 12 000 за 24 місяці = 500 на місяць, з вересня
        asset = self.env["account.asset"].create({
            "name": "Програма (тест ліцензій)", "code": "НМА-1", "profile_id": self.profile.id,
            "purchase_value": 12000.0, "date_start": date(YEAR, 8, 15), "method_number": 24,
            "analytic_distribution": {str(self.build.id): 100.0}})
        asset.validate()
        asset._compute_entries(date(YEAR, 9, 30))
        return asset

    def test_license_split_by_quantity(self):
        asset = self._depreciating_asset()
        products = self.env["product.product"].create([{"name": "Ліцензія Старт"}, {"name": "Ліцензія Про"}])
        plan = self.build.plan_id
        start_a = self.env["account.analytic.account"].create({"name": "Ліцензії Старт", "plan_id": plan.id})
        pro_a = self.env["account.analytic.account"].create({"name": "Ліцензії Про", "plan_id": plan.id})
        split = self.env["ua.ia.license.split"].create({
            "asset_id": asset.id, "month": date(YEAR, 9, 1),
            "line_ids": [(0, 0, {"product_id": products[0].id, "analytic_account_id": start_a.id, "quantity": 3}),
                         (0, 0, {"product_id": products[1].id, "analytic_account_id": pro_a.id, "quantity": 1})]})
        self.assertAlmostEqual(split.amount, 500.0, places=2, msg="амортизація за вересень")
        self.assertEqual(split.line_ids.mapped("amount"), [375.0, 125.0])
        split.action_post()
        move = split.move_id
        self.assertEqual(move.state, "posted")
        expense = asset.profile_id.account_expense_depreciation_id
        credit = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id, expense)
        self.assertAlmostEqual(credit.credit, 500.0, places=2)
        self.assertEqual(self._analytic_of(credit), {str(self.build.id)}, "кредит знімає амортизацію з проєкту")
        by_analytic = {tuple(self._analytic_of(l)): l.debit for l in move.line_ids.filtered(lambda l: l.debit)}
        self.assertEqual(by_analytic, {(str(start_a.id),): 375.0, (str(pro_a.id),): 125.0})

    def test_license_split_fills_from_sales(self):
        asset = self._depreciating_asset()
        product = self.env["product.product"].create({"name": "Ліцензія на рік", "type": "service"})
        asset.ua_license_product_ids = product
        partner = self.env["res.partner"].create({"name": "Покупець ліцензій (тест)"})
        lines = [(0, 0, {"product_id": product.id, "quantity": 5, "price_unit": 1000.0, "tax_ids": [(5, 0, 0)],
                         "analytic_distribution": {str(self.support.id): 100.0}})]
        invoice = self.env["account.move"].create({"move_type": "out_invoice", "partner_id": partner.id,
                                                   "invoice_date": date(YEAR, 9, 10), "invoice_line_ids": lines})
        invoice.action_post()
        refund_lines = [(0, 0, {"product_id": product.id, "quantity": 1, "price_unit": 1000.0, "tax_ids": [(5, 0, 0)],
                                "analytic_distribution": {str(self.support.id): 100.0}})]
        refund = self.env["account.move"].create({"move_type": "out_refund", "partner_id": partner.id,
                                                  "invoice_date": date(YEAR, 9, 20), "invoice_line_ids": refund_lines})
        refund.action_post()
        split = self.env["ua.ia.license.split"].create({"asset_id": asset.id, "month": date(YEAR, 9, 1)})
        split.action_fill_from_sales()
        self.assertEqual(len(split.line_ids), 1)
        self.assertEqual(split.line_ids.quantity, 4.0, "5 продано, 1 повернено")
        self.assertEqual(split.line_ids.analytic_account_id, self.support, "аналітика - з рядка рахунку")
