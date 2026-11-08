# -*- coding: utf-8 -*-
"""Примітки за 2026 рік, нова компанія з планом ПСБО, два активи в реєстрі.

Основні засоби (розділ II):
- верстат (104, актив А): куплено 01.02.2025 за 60 000, знос 2025 - 6 000; 2026: знос 9 000,
  30.09 продано: Дт 131 Кт 104 15 000, Дт 976 Кт 104 45 000; 01.05 частину (2 000) перекласифіковано
  в інвентар (Дт 106 Кт 104); 01.03 новий верстат з капітальних інвестицій Дт 104 Кт 1521 30 000;
- будівля (103, актив Б): 120 000, знос 2025 - 4 000; 2026: дооцінка Дт 103 Кт 411 12 000 і
  Дт 411 Кт 131 2 000, знос 5 000, уцінка корисності Дт 972 Кт 131 1 000;
- знос 500 без активу - у рядку 180 і зауваження.
Рядок 130: 60 000 / 6 000 на початок; надійшло 30 000; вибуло 60 000 / 15 000; знос 9 000;
інші зміни (2 000); на кінець 28 000 / 0.
Рядок 120: 120 000 / 4 000; переоцінка 12 000 / 2 000; знос 5 000; корисність 1 000; на кінець
132 000 / 12 000. Рядок 260: на кінець 162 000 / 12 500.
НМА (розділ I): Дт 125 Кт 631 8 000 (рядок 050), амортизація 800 без активу (рядок 070).
III: Дт 1521 Кт 631 30 000 - рядок 290 за рік 30 000, на кінець 0.
VI: каса 3 000, поточний рахунок 44 000, в дорозі 1 000, разом 48 000.
VII: відпустки 1 000 на початок, нараховано 4 000, використано 3 000, сторновано 500, на кінець
1 500; резерв сумнівних боргів нараховано 2 500.
VIII: матеріали 5 300 (уцінка 600, збільшення ЧВР 100), незавершене 1 000, готова продукція
3 000, товари 5 000, разом 14 300.
IX: покупець А 35 000 = 15 000 (01.11.2026, до 12 місяців) + 20 000 (з 01.06.2025, 18-36);
покупець Б 5 000 з 15.09.2025 (12-18); 3771 2 000 і 375 200 - до 12 місяців; списано
безнадійної 1 000.
X: нестачі 200, визнано за винними 200. XII: поточний податок 3 600. XIII: нараховано 15 300.
V: оренда Дт 685 Кт 713 2 400 (440); штрафи одержані 700 і сплачені 300 (470); проценти Дт 951
Кт 684 1 200 (540, лише витрати); проценти одержані 732 150 (560); дивіденди 731 900 (530); закриття
713 і 951 на 791 не рахується. Рядок 490: доходи 716, 719 - 800, витрати 944, 946, 947 - 4 300,
з них 491 - 3 500, 492 - 200; 590 - 1 000 (972), 620 - 45 000 (976).

Запуск: тег ua_notes.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "ua_notes")
class TestUaNotes(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.misc = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        Partner = cls.env["res.partner"]
        cls.buyer_a = Partner.create({"name": "ТОВ Покупець А (тест Ф5)"})
        cls.buyer_b = Partner.create({"name": "ТОВ Покупець Б (тест Ф5)"})
        cls.buyer_c = Partner.create({"name": "ТОВ Покупець В (тест Ф5)"})
        cls.debtor = Partner.create({"name": "ТОВ Боржник (тест Ф5)"})
        Profile = cls.env["account.asset.profile"].sudo()

        def profile(code):
            return Profile.create({
                "name": "Група %s (тест Ф5)" % code, "account_asset_id": cls._acc(code).id,
                "account_depreciation_id": cls._acc("131").id,
                "account_expense_depreciation_id": cls._acc("92").id, "journal_id": cls.misc.id,
                "company_id": cls.company.id})
        Asset = cls.env["account.asset"].sudo()
        cls.machine = Asset.create({"name": "Верстат (тест Ф5)", "profile_id": profile("104").id,
                                    "purchase_value": 60000, "date_start": date(2025, 2, 1)})
        cls.building = Asset.create({"name": "Будівля (тест Ф5)", "profile_id": profile("103").id,
                                     "purchase_value": 120000, "date_start": date(2025, 3, 1)})
        A, B = cls.machine, cls.building
        # Рядки на рахунках активів несуть актив, як після модуля активів (інакше OCA створить новий).
        entries = [
            (date(2025, 2, 1), [("104", 60000, A), ("631", -60000)]),
            (date(2025, 3, 1), [("103", 120000, B), ("631", -120000)]),
            (date(2025, 12, 31), [("92", 6000), ("131", -6000, A)]),
            (date(2025, 12, 31), [("92", 4000), ("131", -4000, B)]),
            (date(2026, 2, 15), [("1521", 30000), ("631", -30000)]),
            (date(2026, 3, 1), [("104", 30000), ("1521", -30000)]),
            (date(2026, 5, 1), [("106", 2000), ("104", -2000, A)]),
            (date(2026, 6, 30), [("103", 12000, B), ("411", -12000)]),
            (date(2026, 6, 30), [("411", 2000), ("131", -2000, B)]),
            (date(2026, 8, 31), [("92", 9000), ("131", -9000, A)]),
            (date(2026, 9, 30), [("131", 15000, A), ("104", -15000, A)]),
            (date(2026, 9, 30), [("976", 45000), ("104", -45000, A)]),
            (date(2026, 12, 31), [("92", 5000), ("131", -5000, B)]),
            (date(2026, 12, 31), [("972", 1000), ("131", -1000, B)]),
            (date(2026, 12, 31), [("92", 500), ("131", -500)]),
            (date(2026, 4, 1), [("125", 8000), ("631", -8000)]),
            (date(2026, 12, 31), [("92", 800), ("133", -800)]),
            # Дебіторська заборгованість і гроші.
            (date(2025, 1, 10), [("361", 1000, cls.buyer_c), ("702", -1000)]),
            (date(2025, 6, 1), [("361", 70000, cls.buyer_a), ("702", -70000)]),
            (date(2025, 9, 15), [("361", 5000, cls.buyer_b), ("703", -5000)]),
            (date(2026, 1, 10), [("311", 50000), ("361", -50000, cls.buyer_a)]),
            (date(2026, 11, 1), [("361", 15000, cls.buyer_a), ("702", -15000)]),
            (date(2026, 12, 20), [("944", 1000), ("361", -1000, cls.buyer_c)]),
            (date(2026, 2, 1), [("301", 3000), ("311", -3000)]),
            (date(2026, 3, 1), [("333", 1000), ("311", -1000)]),
            (date(2026, 12, 1), [("3771", 2000, cls.debtor), ("311", -2000)]),
            # Забезпечення і резерв.
            (date(2025, 12, 31), [("92", 1000), ("471", -1000)]),
            (date(2026, 6, 30), [("92", 4000), ("471", -4000)]),
            (date(2026, 8, 31), [("471", 3000), ("661", -3000)]),
            (date(2026, 12, 31), [("471", 500), ("719", -500)]),
            (date(2026, 12, 31), [("944", 2500), ("381", -2500)]),
            # Запаси, нестачі.
            (date(2026, 2, 1), [("201", 10000), ("631", -10000)]),
            (date(2026, 3, 1), [("231", 4000), ("201", -4000)]),
            (date(2026, 4, 1), [("26", 3000), ("231", -3000)]),
            (date(2026, 5, 1), [("281", 5000), ("631", -5000)]),
            (date(2026, 12, 31), [("946", 600), ("201", -600)]),
            (date(2026, 12, 31), [("201", 100), ("719", -100)]),
            (date(2026, 11, 15), [("947", 200), ("201", -200)]),
            (date(2026, 11, 20), [("375", 200), ("716", -200)]),
            # Податок на прибуток.
            (date(2026, 12, 31), [("981", 3600), ("6413", -3600)]),
            # V. Інші доходи і витрати.
            (date(2026, 4, 30), [("685", 2400), ("713", -2400)]),
            (date(2026, 5, 10), [("685", 700), ("715", -700)]),
            (date(2026, 5, 20), [("948", 300), ("685", -300)]),
            (date(2026, 6, 30), [("951", 1200), ("684", -1200)]),
            (date(2026, 7, 31), [("685", 150), ("732", -150)]),
            (date(2026, 8, 31), [("685", 900), ("731", -900)]),
            (date(2026, 12, 31), [("713", 2400), ("791", -2400)]),
            (date(2026, 12, 31), [("791", 1200), ("951", -1200)]),
        ]
        for day, rows in entries:
            cls._entry(day, rows)
        cls.Statement = cls.env["ua.notes.statement"]
        cls.st = cls.Statement.create({"date_from": date(2026, 1, 1), "date_to": date(2026, 12, 31)})
        cls.st.action_compute()

    @classmethod
    def _acc(cls, code):
        Account = cls.env["account.account"].with_company(cls.company)
        domain = [("company_ids", "in", cls.company.id)]
        return Account.search(domain + [("code", "=", code)], limit=1) or \
            Account.search(domain + [("code", "=like", code + "%")], order="code", limit=1)

    @classmethod
    def _entry(cls, day, rows):
        lines = []
        for row in rows:
            code, amount = row[0], row[1]
            values = {"account_id": cls._acc(code).id, "name": "Тест Ф5 %s" % code,
                      "debit": max(amount, 0), "credit": max(-amount, 0)}
            extra = row[2] if len(row) > 2 else None
            if extra and extra._name == "account.asset":
                values["asset_id"] = extra.id
            elif extra:
                values["partner_id"] = extra.id
            lines.append((0, 0, values))
        move = cls.env["account.move"].with_context(allow_asset=True).create({
            "move_type": "entry", "date": day, "journal_id": cls.misc.id, "line_ids": lines})
        move.action_post()
        return move

    def _row(self, section, code, *columns):
        line = self.st.line_ids.filtered(lambda l: l.section == section and l.code == code)
        self.assertEqual(len(line), 1, "%s %s" % (section, code))
        return [line["c%d" % c] for c in columns]

    def test_01_fixed_assets(self):
        cols = range(3, 16)
        self.assertEqual(self._row("fixed", "130", *cols),
                         [60000, 6000, 30000, 0, 0, 60000, 15000, 9000, 0, -2000, 0, 28000, 0])
        self.assertEqual(self._row("fixed", "120", *cols),
                         [120000, 4000, 0, 12000, 2000, 0, 0, 5000, 1000, 0, 0, 132000, 12000])
        self.assertEqual(self._row("fixed", "150", 12, 14), [2000, 2000])
        self.assertEqual(self._row("fixed", "180", 10, 15), [500, 500])
        self.assertEqual(self._row("fixed", "260", *cols),
                         [180000, 10000, 30000, 12000, 2000, 60000, 15000, 14500, 1000, 0, 0, 162000, 12500])
        self.assertIn("без активу", self.st.check_text)
        self.assertNotIn("не дорівнює сальдо", self.st.check_text)

    def test_02_intangible_capex_cash(self):
        self.assertEqual(self._row("intangible", "050", 5, 14), [8000, 8000])
        self.assertEqual(self._row("intangible", "070", 10, 15), [800, 800])
        self.assertEqual(self._row("intangible", "080", 5, 10, 14, 15), [8000, 800, 8000, 800])
        self.assertEqual(self._row("capex", "290", 3, 4), [30000, 0])
        self.assertEqual(self._row("capex", "340", 3, 4), [30000, 0])
        self.assertEqual([self._row("cash", c, 3)[0] for c in ("640", "650", "660", "670", "680", "690")],
                         [3000, 44000, 0, 1000, 0, 48000])

    def test_03_provisions_inventory_receivables(self):
        self.assertEqual(self._row("provision", "710", *range(3, 10)), [1000, 4000, 0, 3000, 500, 0, 1500])
        self.assertEqual(self._row("provision", "775", 4, 9), [2500, 2500])
        self.assertEqual(self._row("provision", "780", 3, 4, 6, 7, 9), [1000, 6500, 3000, 500, 4000])
        self.assertEqual(self._row("inventory", "800", 3, 4, 5), [5300, 100, 600])
        self.assertEqual([self._row("inventory", c, 3)[0] for c in ("890", "900", "910", "920")],
                         [1000, 3000, 5000, 14300])
        self.assertEqual(self._row("receivable", "940", 3, 4, 5, 6), [40000, 15000, 5000, 20000])
        self.assertEqual(self._row("receivable", "950", 3, 4, 5, 6), [2200, 2200, 0, 0])
        self.assertEqual(self._row("receivable", "951", 3), [1000])

    def test_04_shortage_tax_amortization_and_print(self):
        self.assertEqual(self._row("shortage", "960", 3) + self._row("shortage", "970", 3), [200, 200])
        self.assertEqual(self._row("tax", "1210", 3) + self._row("tax", "1240", 3), [3600, 3600])
        self.assertEqual(self._row("tax", "1225", 3), [0])
        self.assertEqual(self._row("amortization", "1300", 3), [15300])
        codes = self.st.line_ids.filtered(lambda l: l.section == "tax").sorted("sequence").mapped("code")
        self.assertEqual(codes[:7], ["1210", "1220", "1225", "1230", "1235", "1240", "1241"])

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_notes.report_ua_notes", self.st.ids)[0].decode()
        self.assertIn("Примітки до річної фінансової звітності", html)
        self.assertIn("162 000.00", html)
        self.assertIn("(2 000.00)", html)
        self.assertIn("XIII. Використання амортизаційних відрахувань", html)

        self.st.action_done()
        with self.assertRaises(UserError):
            self.st.action_compute()

    def test_05_other_income_and_expenses(self):
        rows = {code: self._row("income", code, 3, 4) for code in
                ("440", "450", "470", "490", "491", "492", "530", "540", "560", "590", "620", "630")}
        self.assertEqual(rows, {"440": [2400, 0], "450": [0, 0], "470": [700, 300], "490": [800, 4300],
                                "491": [0, 3500], "492": [0, 200], "530": [900, 0], "540": [0, 1200],
                                "560": [150, 0], "590": [0, 1000], "620": [0, 45000], "630": [0, 0]})
        self.assertNotIn("Розділ V", self.st.check_text or "")

        odd = self.env["account.account"].sudo().create({
            "code": "959", "name": "Рахунок поза формою (тест Ф5)", "account_type": "expense",
            "company_ids": [(6, 0, self.company.ids)]})
        self._entry(date(2026, 12, 1), [(odd.code, 50), ("685", -50)])
        self.st.action_compute()
        self.assertIn("Розділ V", self.st.check_text)
        self.assertIn("51 850.00".replace(" ", ""), self.st.check_text.replace(" ", ""))
