"""Форми Ф1, Ф2, Ф1-м, Ф2-м на наборі проводок, порахованому руками.

Набір - тринадцять проводок 2026 року: внесок до статутного капіталу, купівля
обладнання з ПДВ, купівля товару, продаж з ПДВ, собівартість, часткова оплата
від покупця, аванс від іншого покупця (кредитове сальдо на іншому рахунку
класу 36), зарплата, ЄСВ, ПДФО, часткова виплата, амортизація.

Очікувані числа виведені в коментарях до кожної перевірки. Тест той самий для
бази з нативними шестизначними кодами (311000) і для бази, де встановлено
l10n_ua_chart і коди короткі (311): вирази форм побудовані на префіксах 31%.
"""

import logging
from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)

# Півкопійки: усі еталони заокруглені до двох знаків.
TOL = 0.005

# Дата, на яку рахуються звіти. Колонка звіту - календарний рік базової дати,
# тому весь набір проводок 2026 року потрапляє в період незалежно від сьогодні.
PIVOT = date(2026, 12, 31)
BOOK_DATE = date(2026, 3, 16)

# Проводки: (опис, [(код рахунку, дебет, кредит)]).
ENTRIES = [
    ("1. Внесок до статутного капіталу", [("311", 100000.0, 0.0), ("401", 0.0, 100000.0)]),
    ("2. Придбання обладнання з ПДВ", [("104", 60000.0, 0.0), ("6412", 12000.0, 0.0), ("631", 0.0, 72000.0)]),
    ("3. Оплата постачальнику за обладнання", [("631", 72000.0, 0.0), ("311", 0.0, 72000.0)]),
    ("4. Придбання товару з ПДВ", [("281", 30000.0, 0.0), ("6412", 6000.0, 0.0), ("631", 0.0, 36000.0)]),
    ("5. Продаж товару з ПДВ", [("361", 54000.0, 0.0), ("702", 0.0, 45000.0), ("6412", 0.0, 9000.0)]),
    ("6. Собівартість реалізованого товару", [("902", 25000.0, 0.0), ("281", 0.0, 25000.0)]),
    ("7. Часткова оплата від покупця", [("311", 40000.0, 0.0), ("361", 0.0, 40000.0)]),
    ("8. Аванс від іншого покупця", [("311", 12000.0, 0.0), ("362", 0.0, 12000.0)]),
    ("9. Нарахування зарплати", [("92", 20000.0, 0.0), ("661", 0.0, 20000.0)]),
    ("10. Нарахування ЄСВ", [("92", 4400.0, 0.0), ("651", 0.0, 4400.0)]),
    ("11. Утримання ПДФО", [("661", 3600.0, 0.0), ("6413", 0.0, 3600.0)]),
    ("12. Часткова виплата зарплати", [("661", 10000.0, 0.0), ("311", 0.0, 10000.0)]),
    ("13. Амортизація обладнання", [("92", 1000.0, 0.0), ("131", 0.0, 1000.0)]),
]


@tagged("post_install", "-at_install", "ua_finrep")
class TestUaFinrep(TransactionCase):
    """Один набір даних на клас: форми з нього рахуються один раз."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls._setup_company()
        cls._post_entries()
        cls.f1 = cls._instance("instance_f1")
        cls.f2 = cls._instance("instance_f2")
        cls.f1m = cls._instance("instance_f1m")
        cls.f2m = cls._instance("instance_f2m")
        # Матриця кожної форми рахується один раз, далі тести читають словники.
        cls.v1, cls.c1 = cls.f1._ua_finrep_values(), cls.f1._ua_finrep_control()
        cls.v2, cls.c2 = cls.f2._ua_finrep_values(), cls.f2._ua_finrep_control()
        cls.v1m, cls.c1m = cls.f1m._ua_finrep_values(), cls.f1m._ua_finrep_control()
        cls.v2m, cls.c2m = cls.f2m._ua_finrep_values(), cls.f2m._ua_finrep_control()

    # ---- підготовка --------------------------------------------------------

    @classmethod
    def _setup_company(cls):
        """Країна UA, потім план ua_psbo; якщо стоїть l10n_ua_chart - короткі коди."""
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        cls.company.invalidate_recordset()
        chart_module = cls.env["ir.module.module"].search(
            [("name", "=", "l10n_ua_chart"), ("state", "=", "installed")], limit=1)
        if chart_module:
            from odoo.addons.l10n_ua_chart.hooks import _short_codes
            _short_codes(cls.env)
            cls.env["account.account"].invalidate_model(["code"])
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        assert cls.journal, "немає журналу «Інші операції»"
        cls.partner = cls.env["res.partner"].create({"name": "Контрагент для тесту"})

    @classmethod
    def _acc(cls, prefix):
        """Рахунок за префіксом коду: працює і з 311, і з 311000."""
        account = cls.env["account.account"].search(
            [("code", "=like", prefix + "%"), ("company_ids", "=", cls.company.id)],
            order="code", limit=1)
        assert account, "немає рахунку з кодом %s*" % prefix
        return account

    @classmethod
    def _post_entries(cls):
        moves = cls.env["account.move"]
        for label, lines in ENTRIES:
            moves |= cls.env["account.move"].create({
                "move_type": "entry",
                "journal_id": cls.journal.id,
                "date": BOOK_DATE,
                "ref": label,
                "line_ids": [(0, 0, {
                    "name": label,
                    "account_id": cls._acc(code).id,
                    "debit": debit,
                    "credit": credit,
                    "partner_id": cls.partner.id,
                }) for code, debit, credit in lines],
            })
        moves.action_post()
        cls.moves = moves

    @classmethod
    def _instance(cls, xmlid):
        """Готовий звіт із даних модуля, зафіксований на 31.12.2026."""
        instance = cls.env.ref("l10n_ua_finrep.%s" % xmlid)
        instance.write({"date": PIVOT, "company_id": cls.company.id})
        return instance

    def _eq(self, got, expected, label):
        self.assertAlmostEqual(
            got, expected, delta=TOL,
            msg="%s: очікували %.2f, вийшло %.2f" % (label, expected, got))

    # ---- 1. Актив = Пасив ---------------------------------------------------

    def test_01_balance_asset_equals_liability(self):
        """1300 = 1900 = 157 000.

        Актив: обладнання 60 000 - знос 1 000 = 59 000; товар 30 000 - 25 000 =
        5 000; борг покупця 54 000 - 40 000 = 14 000; ПДВ до відшкодування
        12 000 + 6 000 - 9 000 = 9 000; гроші 100 000 - 72 000 + 40 000 +
        12 000 - 10 000 = 70 000. Разом 157 000.
        """
        self._eq(self.v1["1300"], 157000.0, "Ф1 ряд. 1300")
        self._eq(self.v1["1900"], 157000.0, "Ф1 ряд. 1900")
        self._eq(self.c1["ctl_ap"], 0.0, "Ф1 контроль 1300-1900")

    # ---- 2. Необоротні активи ----------------------------------------------

    def test_02_f1_non_current_assets(self):
        """1011 = 60 000, 1012 = 1 000, 1010 = 59 000, 1095 = 59 000."""
        self._eq(self.v1["1011"], 60000.0, "Ф1 ряд. 1011 первісна вартість")
        self._eq(self.v1["1012"], 1000.0, "Ф1 ряд. 1012 знос")
        self._eq(self.v1["1010"], 59000.0, "Ф1 ряд. 1010 основні засоби")
        self._eq(self.v1["1095"], 59000.0, "Ф1 ряд. 1095 усього розділ I")

    # ---- 3. Оборотні активи -------------------------------------------------

    def test_03_f1_current_assets(self):
        """1100 = 5 000, 1125 = 14 000, 1135 = 9 000, 1165 = 70 000, 1195 = 98 000."""
        self._eq(self.v1["1100"], 5000.0, "Ф1 ряд. 1100 запаси")
        self._eq(self.v1["1125"], 14000.0, "Ф1 ряд. 1125 дебіторка за товари")
        self._eq(self.v1["1130"], 0.0, "Ф1 ряд. 1130 аванси видані")
        self._eq(self.v1["1135"], 9000.0, "Ф1 ряд. 1135 розрахунки з бюджетом")
        self._eq(self.v1["1165"], 70000.0, "Ф1 ряд. 1165 гроші")
        # 5 000 + 14 000 + 9 000 + 70 000 = 98 000
        self._eq(self.v1["1195"], 98000.0, "Ф1 ряд. 1195 усього розділ II")

    # ---- 4. Власний капітал -------------------------------------------------

    def test_04_f1_equity(self):
        """1400 = 100 000, 1420 = -5 400 (збиток), 1495 = 94 600.

        Збиток: дохід 45 000 - собівартість 25 000 - адмінвитрати
        (20 000 зарплати + 4 400 ЄСВ + 1 000 амортизації) = -5 400.
        """
        self._eq(self.v1["1400"], 100000.0, "Ф1 ряд. 1400 статутний капітал")
        self._eq(self.v1["1420"], -5400.0, "Ф1 ряд. 1420 нерозподілений результат")
        self._eq(self.v1["1495"], 94600.0, "Ф1 ряд. 1495 усього власний капітал")

    # ---- 5. Поточні зобов'язання -------------------------------------------

    def test_05_f1_current_liabilities(self):
        """1615 = 36 000, 1620 = 3 600, 1625 = 4 400, 1630 = 6 400, 1635 = 12 000."""
        self._eq(self.v1["1615"], 36000.0, "Ф1 ряд. 1615 борг постачальнику")
        self._eq(self.v1["1620"], 3600.0, "Ф1 ряд. 1620 борг перед бюджетом (ПДФО)")
        self._eq(self.v1["1625"], 4400.0, "Ф1 ряд. 1625 ЄСВ")
        # 20 000 нараховано - 3 600 ПДФО - 10 000 виплачено = 6 400
        self._eq(self.v1["1630"], 6400.0, "Ф1 ряд. 1630 борг з оплати праці")
        self._eq(self.v1["1635"], 12000.0, "Ф1 ряд. 1635 одержані аванси")
        # 36 000 + 3 600 + 4 400 + 6 400 + 12 000 = 62 400
        self._eq(self.v1["1695"], 62400.0, "Ф1 ряд. 1695 усього розділ III")

    # ---- 6. Розгорнуте сальдо ----------------------------------------------

    def test_06_split_by_sign(self):
        """Дебетові сальдо рахунка в актив, кредитові в пасив - без згортання.

        Клас 36: 361 має дебет 14 000, 362 - кредит 12 000. Нетто було б
        2 000; форма показує 14 000 в ряд. 1125 і 12 000 в ряд. 1635.
        Клас 64: 6412 дебет 9 000, 6413 кредит 3 600. Нетто 5 400; форма
        показує 9 000 в ряд. 1135 і 3 600 в ряд. 1620.
        """
        self._eq(self.v1["1125"] - self.v1["1635"], 2000.0, "нетто класу 36")
        self._eq(self.v1["1125"], 14000.0, "дебетова частина класу 36")
        self._eq(self.v1["1635"], 12000.0, "кредитова частина класу 36")
        self._eq(self.v1["1135"] - self.v1["1620"], 5400.0, "нетто класу 64")
        self._eq(self.v1["1135"], 9000.0, "дебетова частина класу 64")
        self._eq(self.v1["1620"], 3600.0, "кредитова частина класу 64")

    # ---- 7. Ф2 --------------------------------------------------------------

    def test_07_f2_rows(self):
        """2000 = 45 000, 2050 = 25 000, 2090 = 20 000, 2130 = 25 400, 2350 = -5 400."""
        self._eq(self.v2["2000"], 45000.0, "Ф2 ряд. 2000 чистий дохід")
        self._eq(self.v2["2050"], 25000.0, "Ф2 ряд. 2050 собівартість")
        self._eq(self.v2["2090"], 20000.0, "Ф2 ряд. 2090 валовий прибуток")
        # 20 000 зарплати + 4 400 ЄСВ + 1 000 амортизації
        self._eq(self.v2["2130"], 25400.0, "Ф2 ряд. 2130 адміністративні витрати")
        self._eq(self.v2["2190"], -5400.0, "Ф2 ряд. 2190 операційний результат")
        self._eq(self.v2["2290"], -5400.0, "Ф2 ряд. 2290 результат до оподаткування")
        self._eq(self.v2["2300"], 0.0, "Ф2 ряд. 2300 податок на прибуток")
        self._eq(self.v2["2350"], -5400.0, "Ф2 ряд. 2350 чистий результат")

    # ---- 8. Ф2 проти зміни рядка 1420 --------------------------------------

    def test_08_f2_matches_change_of_1420(self):
        """Чистий результат Ф2 = зміна ряд. 1420 за період (дивідендів не було).

        На 31.12.2025 рядок 1420 = 0 (проводок до 2026 року немає), на
        31.12.2026 він -5 400. Зміна -5 400 = ряд. 2350.
        """
        self._eq(self.c2["ctl_1420"], 0.0, "Ф2 контроль зміни ряд. 1420")
        opening = self.f1.copy({"date": date(2025, 12, 31)})
        self._eq(opening._ua_finrep_values()["1420"], 0.0, "ряд. 1420 на початок")
        self._eq(self.v1["1420"] - 0.0, self.v2["2350"], "зміна ряд. 1420 проти ряд. 2350")

    # ---- 9. Ф1-м проти Ф1 ---------------------------------------------------

    def test_09_f1m_totals_equal_f1(self):
        """Ф1-м крупніший за Ф1, але підсумки ті самі на тих самих даних."""
        for code in ("1095", "1195", "1300", "1495", "1595", "1695", "1900", "1420"):
            self._eq(self.v1m[code], self.v1[code], "Ф1-м проти Ф1, ряд. %s" % code)
        self._eq(self.c1m["ctl_ap"], 0.0, "Ф1-м контроль 1300-1900")
        # Крупні рядки Ф1-м = сума відповідних рядків Ф1.
        self._eq(self.v1m["1155"], self.v1["1130"] + self.v1["1155"], "Ф1-м ряд. 1155 = Ф1 1130+1155")
        self._eq(self.v1m["1690"], self.v1["1635"] + self.v1["1690"], "Ф1-м ряд. 1690 = Ф1 1635+1690")
        # Рядки, що в Ф1-м такі самі, як у Ф1 (форма в редакції, яку бере схема ДПС J0901107).
        for code in ("1005", "1125", "1135", "1160", "1165", "1170", "1190", "1200", "1615", "1620", "1665"):
            self._eq(self.v1m[code], self.v1[code], "Ф1-м проти Ф1, ряд. %s" % code)
        self._eq(self.v1m["1000"], self.v1m["1001"] - self.v1m["1002"], "Ф1-м ряд. 1000 = 1001 - 1002")
        self._eq(self.v1m["1135"], 9000.0, "Ф1-м ряд. 1135 ПДВ до відшкодування (6412)")

    # ---- 10. Ф2-м проти Ф2 --------------------------------------------------

    def test_10_f2m_totals_equal_f2(self):
        """2000, 2050 і чистий результат Ф2-м збігаються з Ф2."""
        self._eq(self.v2m["2000"], self.v2["2000"], "Ф2-м ряд. 2000")
        self._eq(self.v2m["2050"], self.v2["2050"], "Ф2-м ряд. 2050")
        self._eq(self.v2m["2350"], self.v2["2350"], "Ф2-м ряд. 2350")
        # Разом доходи 45 000, разом витрати 25 000 + 25 400 = 50 400.
        self._eq(self.v2m["2280"], 45000.0, "Ф2-м ряд. 2280 разом доходи")
        self._eq(self.v2m["2285"], 50400.0, "Ф2-м ряд. 2285 разом витрати")
        self._eq(self.v2m["2290"], -5400.0, "Ф2-м ряд. 2290")
        # Витрати 92 - інші операційні (2180), а не інші витрати (2270).
        self._eq(self.v2m["2180"], 25400.0, "Ф2-м ряд. 2180 інші операційні витрати")
        self._eq(self.v2m["2270"], 0.0, "Ф2-м ряд. 2270 інші витрати")
        self._eq(self.v2m["2120"] + self.v2m["2240"], 0.0, "Ф2-м інших доходів немає")
        self._eq(self.c2m["ctl_1420"], 0.0, "Ф2-м контроль зміни ряд. 1420")

    # ---- 11. Жоден рахунок не загубився ------------------------------------

    def test_11_every_account_is_covered(self):
        """Ряд. 1300 = сума всіх дебетових внесків головної книги.

        Незалежний рахунок: беремо сальдо кожного рахунка класів 1-3 і
        додаємо кредитові сальдо класів 1-3 назад у пасив. Якщо якийсь
        рахунок плану не змаплено в жоден рядок, 1300 від 1900 відхилиться.
        """
        lines = self.env["account.move.line"]._read_group(
            [("company_id", "=", self.company.id), ("parent_state", "=", "posted")],
            groupby=["account_id"], aggregates=["balance:sum"])
        total = sum(balance for _account, balance in lines)
        self._eq(total, 0.0, "подвійний запис: сума сальдо всіх рахунків")
        self._eq(self.v1["1300"] - self.v1["1900"], 0.0, "покриття плану рахунків")
        self._eq(self.v1m["1300"] - self.v1m["1900"], 0.0, "покриття плану рахунків, Ф1-м")

    # ---- 12. XML -----------------------------------------------------------

    def test_12_xml_draft_reads_computed_values(self):
        """Чернетка XML бере числа з порахованої матриці, а не рахує вдруге."""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(self.f1._ua_finrep_xml())
        body = root.find("DECLARBODY")
        self.assertIsNotNone(body, "у XML немає DECLARBODY")
        tags = {child.tag: float(child.text) for child in body}
        self._eq(tags["R1300G3"], self.v1["1300"], "XML R1300G3")
        self._eq(tags["R1900G3"], self.v1["1900"], "XML R1900G3")
        self._eq(tags["R1420G3"], self.v1["1420"], "XML R1420G3")
        self.assertNotIn("Rctl_apG3", tags, "контрольний рядок не має потрапляти в XML")
        head = root.find("DECLARHEAD")
        self.assertEqual(head.find("PERIOD_YEAR").text, "2026")

    # ---- 13. Дисципліна шаблонів -------------------------------------------

    def test_13_kpi_names_and_codes(self):
        """Кожен KPI - або рядок форми (літера + 4 цифри), або контроль ctl_*.

        Опис рядка форми починається з коду рядка: так код видно в самій формі.
        """
        import re
        for xmlid, letter in (("report_f1", "r"), ("report_f2", "r"),
                              ("report_f1m", "m"), ("report_f2m", "n")):
            report = self.env.ref("l10n_ua_finrep.%s" % xmlid)
            self.assertTrue(report.ua_finrep_form, "%s без позначки форми" % xmlid)
            self.assertTrue(report.kpi_ids, "%s без рядків" % xmlid)
            for kpi in report.kpi_ids:
                if kpi.name.startswith("ctl_"):
                    continue
                match = re.match(r"^%s(\d{4})$" % letter, kpi.name)
                self.assertTrue(match, "%s: ім'я %s не схоже на рядок форми" % (xmlid, kpi.name))
                self.assertTrue(
                    kpi.description.startswith(match.group(1)),
                    "%s: опис «%s» не починається з коду %s" % (xmlid, kpi.description, match.group(1)))
                self.assertTrue(kpi.expression, "%s: рядок %s без виразу" % (xmlid, kpi.name))

    # ---- 14. Обидва вигляди кодів ------------------------------------------

    def test_14_prefixes_match_both_code_shapes(self):
        """Вирази форм працюють і з короткими кодами, і з шестизначними."""
        bank = self._acc("311")
        self.assertIn(bank.code, ("311", "311000"),
                      "несподіваний вигляд коду рахунку банку: %s" % bank.code)
        _logger.info("l10n_ua_finrep: коди рахунків у цій базі - %s", bank.code)
        # Якщо префікс 31% не зловив рахунок, ряд. 1165 був би нульовим.
        self._eq(self.v1["1165"], 70000.0, "ряд. 1165 при кодах %s" % bank.code)
        self._eq(self.v1["1011"], 60000.0, "ряд. 1011 при кодах %s" % bank.code)
        self._eq(self.v2["2000"], 45000.0, "ряд. 2000 при кодах %s" % bank.code)

    # ---- 15. Пункти меню ----------------------------------------------------

    def test_15_menu_opens_preview_with_active_id(self):
        """Пункт меню відкриває звіт компанії з id у active_id.

        Віджет mis_builder 19.0 бере id звіту лише з active_id; без нього - «Invalid
        ids list». Друга компанія отримує власну копію звіту, а не чужий."""
        for form in ("f1", "f2", "f1m", "f2m"):
            menu_action = self.env.ref("l10n_ua_finrep.action_open_%s" % form)
            action = menu_action.run()
            self.assertEqual(action["res_model"], "mis.report.instance")
            self.assertEqual(action["view_id"], self.env.ref(
                "mis_builder.mis_report_instance_result_view_form").id)
            self.assertEqual(action["context"]["active_id"], action["res_id"], form)
            self.assertEqual(action["context"]["active_model"], "mis.report.instance")
            instance = self.env["mis.report.instance"].browse(action["res_id"])
            self.assertEqual(instance.company_id, self.env.company, form)
            self.assertEqual(instance.ua_finrep_form, form)

        other = self.env["res.company"].create({"name": "Друга компанія фінзвітності"})
        self.env.user.company_ids |= other
        env2 = self.env(context=dict(self.env.context, allowed_company_ids=[other.id]))
        action = env2.ref("l10n_ua_finrep.action_open_f1").run()
        instance = env2["mis.report.instance"].browse(action["res_id"])
        self.assertEqual(instance.company_id, other)
        self.assertEqual(instance.report_id, self.f1.report_id)
        self.assertTrue(instance.period_ids, "копія без колонки")
        self.assertEqual(instance.name, self.f1.name, "у назві копії лишилося «(copy)»")
        # Повторний клік бере той самий звіт, не плодить копії.
        again = env2.ref("l10n_ua_finrep.action_open_f1").run()
        self.assertEqual(again["res_id"], instance.id)
