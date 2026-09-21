# -*- coding: utf-8 -*-
"""Інваріанти обліку основних засобів.

Числа в очікуваннях пораховані руками, арифметика показана в коментарі
поруч. Перевіряємо рівно те, що додано поверх OCA: набір профілів під
податкові групи, стійкість до довжини коду рахунку (104000 і 104), старт
амортизації з наступного місяця, МНМА, проводки, списання і попередження
про мінімальний строк.

Запуск: чиста база через docker compose run, теги ua_assets.
"""
import datetime

from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005


@tagged("post_install", "-at_install", "ua_assets")
class TestUaAssets(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env["account.chart.template"].with_company(cls.company)
        cls.Profile = cls.env["account.asset.profile"]
        cls.Asset = cls.env["account.asset"]

    # --- службове -------------------------------------------------------

    @classmethod
    def _profile(cls, group, rule="linear"):
        return cls.Profile.search([
            ("company_id", "=", cls.company.id),
            ("ua_tax_group", "=", group),
            ("ua_rule", "=", rule),
        ], limit=1)

    def _asset(self, profile, value, date_start, months=None, **extra):
        values = {
            "name": "Тест %s" % profile.ua_tax_group,
            "code": extra.pop("code", "ОЗ-001"),
            "profile_id": profile.id,
            "purchase_value": value,
            "date_start": date_start,
        }
        if months is not None:
            values["method_number"] = months
        values.update(extra)
        return self.Asset.create(values)

    # --- 1. Набір профілів зʼявився разом із планом рахунків -------------
    def test_01_profiles_exist_after_chart_load(self):
        profiles = self.Profile.search([
            ("company_id", "=", self.company.id),
            ("ua_tax_group", "!=", False),
        ])
        # 16 груп ОЗ + 6 груп НМА + окремий профіль МНМА 50/50 = 23
        self.assertEqual(len(profiles), 23)
        self.assertEqual(len(profiles.mapped("ua_tax_group")), 23)
        self.assertEqual(len(set(profiles.mapped("ua_tax_group"))), 22)
        # мінімальні строки за ПКУ
        self.assertEqual(self._profile("oz_05").ua_min_months, 60)   # транспорт, 5 років
        self.assertEqual(self._profile("oz_06").ua_min_months, 48)   # інвентар, 4 роки
        self.assertEqual(self._profile("oz_09").ua_min_months, 144)  # інші ОЗ, 12 років
        self.assertEqual(self._profile("nma_4").ua_min_months, 24)   # НМА, не менше 2 років

    # --- 2. Рахунки в профілях ті, що треба ------------------------------
    def test_02_account_mapping(self):
        oz4 = self._profile("oz_04")
        self.assertEqual(oz4.account_asset_id, self.chart.ref("ua_psbp_104"))
        self.assertEqual(oz4.account_depreciation_id, self.chart.ref("ua_psbp_131"))
        self.assertEqual(
            oz4.account_expense_depreciation_id, self.chart.ref("ua_psbp_92")
        )
        self.assertEqual(
            oz4.account_residual_value_id, self.chart.ref("ua_psbp_976")
        )
        mnma = self._profile("oz_11", "mnma_100")
        self.assertEqual(mnma.account_asset_id, self.chart.ref("ua_psbp_112"))
        self.assertEqual(mnma.account_depreciation_id, self.chart.ref("ua_psbp_132"))
        nma = self._profile("nma_4")
        self.assertEqual(nma.account_asset_id, self.chart.ref("ua_psbp_124"))
        self.assertEqual(nma.account_depreciation_id, self.chart.ref("ua_psbp_133"))
        # рахунку 109 у шаблоні немає - створили самі, код тієї ж довжини
        oz9 = self._profile("oz_09")
        self.assertTrue(oz9.account_asset_id.code.startswith("109"))
        self.assertEqual(
            len(oz9.account_asset_id.code),
            len(oz4.account_asset_id.code),
        )

    # --- 3. Скорочені коди (l10n_ua_chart) нічого не ламають -------------
    def test_03_profiles_with_short_codes(self):
        """Той самий набір має зібратися, коли коди рахунків скорочені до
        104 замість 104000. Рахунок шукаємо за xmlid, не за кодом."""
        account_104 = self.chart.ref("ua_psbp_104")
        account_131 = self.chart.ref("ua_psbp_131")
        self.Profile.search([("company_id", "=", self.company.id)]).unlink()
        for account, code in (
            (account_104, "104"),
            (account_131, "131"),
            (self.chart.ref("ua_psbp_92"), "92"),
            (self.chart.ref("ua_psbp_976"), "976"),
        ):
            account.with_company(self.company).code = code
        created = self.Profile._ua_create_profiles(self.company)
        self.assertEqual(len(created), 23)
        oz4 = self._profile("oz_04")
        self.assertEqual(oz4.account_asset_id, account_104)
        self.assertEqual(oz4.account_asset_id.code, "104")
        self.assertEqual(oz4.account_depreciation_id, account_131)

    # --- 4. Амортизація починається з місяця, наступного за введенням ----
    def test_04_first_depreciation_next_month(self):
        # 120 000 грн, 60 місяців, введено 15 серпня 2026
        asset = self._asset(
            self._profile("oz_04"), 120000.0, "2026-08-15", months=60
        )
        asset.validate()
        lines = asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate"
        ).sorted(key=lambda line: line.line_date)
        self.assertEqual(asset.ua_depreciation_start, datetime.date(2026, 9, 1))
        # перший рядок - 30 вересня, а не 31 серпня
        self.assertEqual(lines[0].line_date, datetime.date(2026, 9, 30))
        # 120 000 / 60 = 2 000 на місяць
        self.assertAlmostEqual(lines[0].amount, 2000.0, delta=CENT)
        self.assertAlmostEqual(lines[1].amount, 2000.0, delta=CENT)

    # --- 5. Таблиця: 60 рядків, сума дорівнює вартості -------------------
    def test_05_sixty_lines(self):
        asset = self._asset(
            self._profile("oz_04"), 120000.0, "2026-08-15", months=60
        )
        asset.validate()
        lines = asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate"
        ).sorted(key=lambda line: line.line_date)
        self.assertEqual(len(lines), 60)
        # 60 місяців з вересня 2026 -> останній рядок серпень 2031
        self.assertEqual(lines[-1].line_date, datetime.date(2031, 8, 31))
        self.assertAlmostEqual(sum(lines.mapped("amount")), 120000.0, delta=CENT)

    # --- 6. Проводка: Дт 92 Кт 131 --------------------------------------
    def test_06_posting_expense_and_depreciation(self):
        asset = self._asset(
            self._profile("oz_04"), 120000.0, "2026-08-15", months=60
        )
        asset.validate()
        asset._compute_entries(datetime.date(2026, 9, 30))
        line = asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate" and line.move_check
        )
        self.assertEqual(len(line), 1)
        move = line.move_id
        self.assertEqual(move.state, "posted")
        debit = move.line_ids.filtered(lambda l: l.debit)
        credit = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(debit.account_id, self.chart.ref("ua_psbp_92"))
        self.assertEqual(credit.account_id, self.chart.ref("ua_psbp_131"))
        self.assertAlmostEqual(debit.debit, 2000.0, delta=CENT)
        self.assertAlmostEqual(credit.credit, 2000.0, delta=CENT)

    # --- 7. МНМА: 100 % у першому місяці --------------------------------
    def test_07_mnma_hundred_percent(self):
        asset = self._asset(
            self._profile("oz_11", "mnma_100"), 3000.0, "2026-08-20", code="МНМА-1"
        )
        asset.validate()
        lines = asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate"
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.line_date, datetime.date(2026, 9, 30))
        self.assertAlmostEqual(lines.amount, 3000.0, delta=CENT)
        asset._compute_entries(datetime.date(2026, 9, 30))
        move = lines.move_id
        self.assertEqual(
            move.line_ids.filtered(lambda l: l.credit).account_id,
            self.chart.ref("ua_psbp_132"),
        )
        self.assertAlmostEqual(asset.value_residual, 0.0, delta=CENT)

    # --- 8. МНМА: 50 % у першому місяці, 50 % лишаються ------------------
    def test_08_mnma_half(self):
        asset = self._asset(
            self._profile("oz_11", "mnma_50_50"), 3000.0, "2026-08-20", code="МНМА-2"
        )
        asset.validate()
        lines = asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate"
        )
        self.assertEqual(len(lines), 1)
        # ліквідаційна вартість 50 % = 1 500, у витрати одразу теж 1 500
        self.assertAlmostEqual(asset.salvage_value, 1500.0, delta=CENT)
        self.assertAlmostEqual(lines.amount, 1500.0, delta=CENT)
        asset._compute_entries(datetime.date(2026, 9, 30))
        self.assertAlmostEqual(asset.value_depreciated, 1500.0, delta=CENT)
        self.assertAlmostEqual(asset.value_residual, 1500.0, delta=CENT)

    # --- 9. Списання: залишкова вартість лягає на 976 --------------------
    def test_09_removal_posts_residual(self):
        # 12 000 за 60 місяців = 200 на місяць; проводимо 2 місяці -> знос 400,
        # залишок 11 600
        asset = self._asset(
            self._profile("oz_04"), 12000.0, "2026-08-15", months=60, code="ОЗ-009"
        )
        asset.validate()
        asset._compute_entries(datetime.date(2026, 10, 31))
        self.assertAlmostEqual(asset.value_depreciated, 400.0, delta=CENT)
        wizard = self.env["account.asset.remove"].with_context(
            active_id=asset.id, active_ids=asset.ids
        ).create({
            "date_remove": "2026-10-31",
            "posting_regime": "residual_value",
            "account_residual_value_id": self.chart.ref("ua_psbp_976").id,
        })
        wizard.remove()
        self.assertEqual(asset.state, "removed")
        move = self.env["account.move"].search([
            ("ref", "=", asset._get_depreciation_entry_name(3)),
            ("company_id", "=", self.company.id),
        ], limit=1)
        by_account = {l.account_id.code: (l.debit, l.credit) for l in move.line_ids}
        depr_code = self.chart.ref("ua_psbp_131").code
        asset_code = self.chart.ref("ua_psbp_104").code
        residual_code = self.chart.ref("ua_psbp_976").code
        self.assertAlmostEqual(by_account[depr_code][0], 400.0, delta=CENT)
        self.assertAlmostEqual(by_account[asset_code][1], 12000.0, delta=CENT)
        self.assertAlmostEqual(by_account[residual_code][0], 11600.0, delta=CENT)

    # --- 10. Попередження про мінімальний строк за ПКУ -------------------
    def test_10_minimum_life_warning(self):
        short = self._asset(
            self._profile("oz_05"), 60000.0, "2026-08-15", months=24, code="ОЗ-010"
        )
        # транспорт: мінімум 60 міс., обрали 24
        self.assertEqual(short.ua_life_months, 24)
        self.assertIn("60", short.ua_life_warning or "")
        ok = self._asset(
            self._profile("oz_05"), 60000.0, "2026-08-15", months=60, code="ОЗ-011"
        )
        self.assertFalse(ok.ua_life_warning)

    # --- 11. Друковані форми ОЗ-1, ОЗ-3, ОЗ-6 будуються ------------------
    def test_11_reports_render(self):
        asset = self._asset(
            self._profile("oz_04"),
            120000.0,
            "2026-08-15",
            months=60,
            code="ОЗ-011",
            ua_location="Офіс, Київ",
            ua_responsible="Петренко П. П.",
            ua_commission="Іваненко І. І., головний інженер",
            ua_disposal_reason="Фізичний знос",
        )
        asset.validate()
        for report in ("report_ua_asset_oz1", "report_ua_asset_oz3",
                       "report_ua_asset_oz6"):
            html = self.env["ir.actions.report"]._render_qweb_html(
                "l10n_ua_assets." + report, asset.ids
            )[0].decode()
            self.assertIn("ОЗ-011", html, report)
            self.assertIn(self.company.name, html, report)

    # --- 12. Відомість нарахування амортизації за місяць ------------------
    def test_12_depreciation_sheet(self):
        asset = self._asset(
            self._profile("oz_04"), 120000.0, "2026-08-15", months=60, code="ОЗ-012"
        )
        asset.validate()
        sheet = self.env["ua.depreciation.sheet"].create({
            "company_id": self.company.id,
            "year": 2026,
            "month": "9",
        })
        rows = sheet.sheet_rows()
        self.assertEqual([row["code"] for row in rows], ["ОЗ-012"])
        self.assertAlmostEqual(rows[0]["amount"], 2000.0, delta=CENT)
        self.assertAlmostEqual(sheet.total(), 2000.0, delta=CENT)
        # у серпні амортизації ще немає
        august = self.env["ua.depreciation.sheet"].create({
            "company_id": self.company.id, "year": 2026, "month": "8",
        })
        self.assertEqual(august.sheet_rows(), [])
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_assets.report_ua_depreciation_sheet", sheet.ids
        )[0].decode()
        self.assertIn("вересень", html)

    # --- 13. Земля не амортизується --------------------------------------
    def test_13_land_is_not_depreciated(self):
        land = self._profile("oz_01", "none")
        self.assertEqual(land.method_number, 0)
        asset = self._asset(land, 500000.0, "2026-08-15", code="ЗЕМ-1")
        asset.validate()
        self.assertFalse(asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate"
        ))
        self.assertAlmostEqual(asset.value_residual, 500000.0, delta=CENT)
