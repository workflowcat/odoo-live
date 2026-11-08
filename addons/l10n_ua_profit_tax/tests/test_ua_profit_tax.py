"""Декларація з податку на прибуток на числах, порахованих руками.

Набір 2026 року: один продаж на 100 000 грн без податків. Фінансовий
результат до оподаткування 100 000, різниць немає, ставка 18 % - податок
18 000. Решта перевірок добудовує до цього набору по одній обставині:
збиток минулих років, амортизаційну різницю, уже сплачене, великий платник,
квартальний платник, XML за схемами ДПС.
"""

import base64
import logging
from datetime import date

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

_logger = logging.getLogger(__name__)

TOL = 0.005
YEAR = 2026
DETAILS = {
    "tin": "12345678", "sti_code": "2659", "sti_name": "ГУ ДПС у м. Києві", "kved": "30.30",
    "address": "01001, м. Київ, вул. Прикладна, 1", "phone": "044 000 00 00",
    "email": "office@example.com", "director": "Іваненко І. І.", "director_rnokpp": "1234567890",
    "accountant": "Петренко П. П.",
}
BOOK_DATE = date(2026, 3, 16)
LOSS_DATE = date(2025, 3, 16)


@tagged("post_install", "-at_install", "ua_profit")
class TestUaProfitTax(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        assert cls.journal, "немає журналу «Інші операції»"
        cls.partner = cls.env["res.partner"].create({"name": "Покупець"})
        cls._entry("Продаж 2026 року", BOOK_DATE, [
            ("361", 100000.0, 0.0), ("702", 0.0, 100000.0)])

    # ---- службове ----------------------------------------------------------

    @classmethod
    def _acc(cls, prefix):
        account = cls.env["account.account"].search(
            [("code", "=like", prefix + "%"), ("company_ids", "=", cls.company.id)],
            order="code", limit=1)
        assert account, "немає рахунку з кодом %s*" % prefix
        return account

    @classmethod
    def _entry(cls, label, when, lines):
        move = cls.env["account.move"].create({
            "move_type": "entry",
            "journal_id": cls.journal.id,
            "date": when,
            "ref": label,
            "line_ids": [(0, 0, {
                "name": label,
                "account_id": cls._acc(code).id,
                "debit": debit,
                "credit": credit,
            }) for code, debit, credit in lines],
        })
        move.action_post()
        return move

    def _declaration(self, year=YEAR, **values):
        declaration = self.env["ua.profit.declaration"].create(
            dict({"company_id": self.company.id, "year": year}, **values))
        declaration.action_compute()
        return declaration

    def _row(self, declaration, code):
        line = declaration.line_ids.filtered(lambda row: row.code == code)
        self.assertEqual(len(line), 1, "рядка %s немає або він не один" % code)
        return line.amount

    def _eq(self, got, expected, label):
        self.assertAlmostEqual(
            got, expected, delta=TOL,
            msg="%s: очікували %.2f, вийшло %.2f" % (label, expected, got))

    # ---- 1. Прибуток 100 000 - податок 18 000 ------------------------------

    def test_01_profit_gives_tax(self):
        """Фінрезультат 100 000 × 18 % = 18 000; дохід нижчий за поріг."""
        declaration = self._declaration()
        self._eq(declaration.income_total, 100000.0, "ряд. 01 дохід")
        self._eq(declaration.finres, 100000.0, "ряд. 02 фінрезультат")
        self._eq(declaration.diff_total, 0.0, "ряд. 03 різниці")
        self._eq(declaration.tax_base, 100000.0, "ряд. 04 об'єкт")
        self._eq(declaration.rate, 18.0, "ставка")
        self._eq(declaration.tax_amount, 18000.0, "ряд. 06 податок")
        self._eq(declaration.tax_to_pay, 18000.0, "ряд. 19 до сплати")
        self.assertTrue(declaration.low_income, "дохід 100 000 - це малодохідник")
        self._eq(declaration.low_income_limit, 40000000.0, "поріг малодохідника")

    # ---- 2. Фінрезультат береться з Ф2, а не рахується вдруге --------------

    def test_02_finres_comes_from_f2(self):
        """Ряд. 02 дорівнює рядку 2290 звіту Ф2 за той самий рік."""
        declaration = self._declaration()
        instance = self.env["mis.report.instance"].create({
            "name": "Ф2 для звірки",
            "report_id": self.env.ref("l10n_ua_finrep.report_f2").id,
            "target_move": "posted",
            "company_id": self.company.id,
            "period_ids": [(0, 0, {
                "name": "Рік", "mode": "fix",
                "manual_date_from": date(YEAR, 1, 1),
                "manual_date_to": date(YEAR, 12, 31), "sequence": 1})],
        })
        self._eq(declaration.finres, instance._ua_finrep_values()["2290"],
                 "ряд. 02 проти Ф2 ряд. 2290")

    # ---- 3. Збиток минулих років -------------------------------------------

    def test_03_carried_loss_lowers_the_base(self):
        """Підтверджений збиток 2025 року на 20 000 зменшує об'єкт 2026 року."""
        self._entry("Збиток 2025 року", LOSS_DATE, [
            ("92", 20000.0, 0.0), ("631", 0.0, 20000.0)])
        previous = self._declaration(year=YEAR - 1)
        self._eq(previous.finres, -20000.0, "фінрезультат 2025")
        self._eq(previous.tax_base, -20000.0, "об'єкт 2025 від'ємний")
        self._eq(previous.tax_amount, 0.0, "податок 2025 - від'ємний об'єкт не оподатковують")
        self._eq(previous.loss_left, 20000.0, "від'ємне значення на 2026 рік")
        previous.action_confirm()
        current = self._declaration()
        self._eq(current.diff_loss, -20000.0, "РІ 3.2.4 від'ємне значення минулих років")
        self._eq(current.tax_base, 80000.0, "об'єкт 2026")     # 100 000 - 20 000
        self._eq(current.tax_amount, 14400.0, "податок 2026")  # 80 000 × 18 %
        self._eq(current.loss_left, 0.0, "залишок погашено")

    # ---- 4. Амортизаційна різниця ------------------------------------------

    def test_04_amortisation_difference_raises_the_base(self):
        """Бухгалтерський строк 12 міс. проти податкових 24 міс. дає +5 000.

        Актив на 10 000 грн: у бухобліку за 2026 рік списано 10 000, у
        податковому - 10 000 / 24 × 12 = 5 000. Різниця 5 000 збільшує
        об'єкт, хоч фінрезультат від амортизації впав на 10 000.
        """
        if "account.asset" not in self.env:
            self.skipTest("l10n_ua_assets не встановлено - різниці немає з чого рахувати")
        profile = self.env["account.asset.profile"].search([
            ("company_id", "=", self.company.id),
            ("ua_tax_group", "=", "oz_04")], limit=1)
        self.assertTrue(profile, "немає профілю групи 4 основних засобів")
        self.assertEqual(profile.ua_min_months, 24, "мінімальний строк групи 4")
        asset = self.env["account.asset"].create({
            "name": "Ноутбук",
            "code": "ОЗ-001",
            "profile_id": profile.id,
            "purchase_value": 10000.0,
            # Введено першим днем року, щоб весь строк лягав у звітний рік.
            "date_start": date(YEAR, 1, 1),
            "method_number": 12,
            "ua_start_next_month": False,
        })
        asset.validate()
        lines = asset.depreciation_line_ids.filtered(
            lambda line: line.type == "depreciate"
            and line.line_date.year == YEAR)
        self.assertEqual(len(lines), 12, "за рік має бути 12 місяців амортизації")
        lines.create_move()  # створює і проводить проводки амортизації
        declaration = self._declaration()
        # 100 000 доходу - 10 000 бухгалтерської амортизації
        self._eq(declaration.finres, 90000.0, "фінрезультат після амортизації")
        self._eq(declaration.diff_amortisation, 5000.0, "ряд. 03.1 різниця")
        self._eq(declaration.tax_base, 95000.0, "об'єкт з різницею")
        self._eq(declaration.tax_amount, 17100.0, "податок")  # 95 000 × 18 %

    def test_05_no_assets_module_says_so(self):
        """Без модуля основних засобів різниця нульова, і це написано словами."""
        declaration = self._declaration()
        if "account.asset" in self.env:
            self.assertIn("активами", declaration.note or "",
                          "примітка не описує розрахунок різниці")
        else:
            self._eq(declaration.diff_amortisation, 0.0, "різниця без модуля активів")
            self.assertIn("не встановлено", declaration.note or "",
                          "примітка не пояснює нульову різницю")

    # ---- 6. Рядки декларації сходяться -------------------------------------

    def test_06_rows_add_up(self):
        """Рядки документа - це ті самі числа: 03 = сума РІ, 04 = 02 + 03, 06 = 04 × ставка."""
        declaration = self._declaration(advance_paid=5000.0)
        declaration.action_compute()
        codes = declaration.line_ids.mapped("code")
        self.assertEqual(
            codes, ["01", "02", "РІ 2.1.1", "РІ 2.2.1", "РІ 3.2.4", "03", "04", "06", "17", "19"],
            "несподіваний набір рядків декларації")
        self._eq(self._row(declaration, "03"),
                 self._row(declaration, "РІ 2.1.1") + self._row(declaration, "РІ 2.2.1")
                 + self._row(declaration, "РІ 3.2.4"),
                 "ряд. 03 = сума рядків РІ")
        self._eq(self._row(declaration, "04"),
                 self._row(declaration, "02") + self._row(declaration, "03"),
                 "ряд. 04 = 02 + 03")
        self._eq(self._row(declaration, "06"),
                 round(self._row(declaration, "04") * declaration.rate / 100.0),
                 "ряд. 06 = 04 × ставка, у гривнях")
        self._eq(self._row(declaration, "17"), self._row(declaration, "06"), "ряд. 17 = 06")
        self._eq(self._row(declaration, "19"), self._row(declaration, "17"),
                 "ряд. 19 = 17 у річного платника")
        self._eq(declaration.tax_to_pay, 13000.0, "залишок до сплати")  # 18 000 - 5 000

    # ---- 7. Параметри датовані ---------------------------------------------

    def test_07_parameters_are_dated(self):
        """Ставка і поріг беруться на дату, а не з коду."""
        Param = self.env["ua.profit.param"]
        self._eq(Param.get("profit_low_income_limit", date(2017, 6, 1)),
                 20000000.0, "поріг до 2018 року")
        self._eq(Param.get("profit_low_income_limit", date(2018, 1, 1)),
                 40000000.0, "поріг з 2018 року")
        self._eq(Param.get("profit_tax_rate", date(YEAR, 12, 31)), 18.0, "ставка 2026")
        Param.create({
            "key": "profit_tax_rate",
            "name": "Ставка податку на прибуток, %",
            "valid_from": date(2027, 1, 1),
            "value": 20.0,
            "source": "уявний закон для перевірки",
        })
        self._eq(Param.get("profit_tax_rate", date(2027, 6, 1)), 20.0,
                 "нова ставка з 2027 року")
        self._eq(Param.get("profit_tax_rate", date(YEAR, 12, 31)), 18.0,
                 "стара ставка не змінилась заднім числом")
        with self.assertRaises(UserError, msg="параметра до дати дії бути не може"):
            Param.get("profit_tax_rate", date(2000, 1, 1))

    # ---- 8. Підтвердження і повернення в чернетку --------------------------

    def test_08_confirm_and_draft(self):
        """Підтверджену декларацію не перераховують, поки не повернуть у чернетку."""
        declaration = self._declaration()
        declaration.action_confirm()
        self.assertEqual(declaration.state, "confirmed", "декларація не підтвердилась")
        with self.assertRaises(UserError, msg="підтверджену декларацію перерахували"):
            declaration.action_compute()
        declaration.action_draft()
        self.assertEqual(declaration.state, "draft", "декларація не повернулась у чернетку")
        declaration.action_compute()
        self._eq(declaration.tax_amount, 18000.0, "податок після перерахунку")

    # ---- 9. Одна декларація на рік -----------------------------------------

    @mute_logger("odoo.sql_db")
    def test_09_one_declaration_per_year(self):
        """Друга декларація за той самий рік у тій самій компанії неможлива."""
        self._declaration()
        with self.assertRaises(Exception, msg="дубль декларації за рік дозволено"):
            with self.env.cr.savepoint():
                self.env["ua.profit.declaration"].create({
                    "company_id": self.company.id, "year": YEAR})

    # ---- 10. XML декларації без різниць ------------------------------------

    def _xml(self, declaration):
        declaration.action_xml()
        main = etree.fromstring(base64.b64decode(declaration.xml_file))
        ri = (etree.fromstring(base64.b64decode(declaration.ri_xml_file))
              if declaration.ri_xml_file else None)
        return main, ri

    def test_10_xml_main_form(self):
        """Річний малодохідник без різниць: одна форма J0100129, перевірена схемою."""
        declaration = self._declaration(**DETAILS)
        main, ri = self._xml(declaration)
        self.assertIsNone(ri, "без різниць додатка РІ немає")
        head, body = main.find("DECLARHEAD"), main.find("DECLARBODY")
        self.assertEqual([head.findtext(t) for t in ("C_DOC", "C_DOC_SUB", "C_DOC_VER", "PERIOD_TYPE",
                                                     "PERIOD_MONTH", "C_REG", "C_RAJ", "C_DOC_STAN")],
                         ["J01", "001", "29", "5", "12", "26", "59", "1"])
        self.assertEqual(head.find("LINKED_DOCS").get("{http://www.w3.org/2001/XMLSchema-instance}nil"),
                         "true")
        self.assertEqual([body.findtext(t) for t in ("HZ", "HY", "H02", "HZY", "HTIN", "HSTI", "HKBOS")],
                         ["1", "1", "1", str(YEAR), "12345678", "ГУ ДПС у м. Києві", "1234567890"])
        self.assertEqual([body.findtext(t) for t in ("R001G3", "R002G3", "R004G3", "R006G1", "R006G3",
                                                     "R017G3", "R019G3")],
                         ["100000", "100000", "100000", "18.00", "18000", "18000", "18000"])
        self.assertIsNone(body.find("R003G3"), "нульові рядки у файл не йдуть")
        self.assertIsNone(body.find("HD6"), "без додатка РІ позначки HD6 немає")
        self.assertEqual(declaration.xml_name,
                         "2659" "0012345678" "J0100129" "1" "00" "0000001" "5" "12" "2026" "2659" ".XML")

    # ---- 11. Великий платник: від'ємне значення частково, додаток РІ -------

    def test_11_large_payer_loss_and_ri_annex(self):
        """Залишок 20 000 більший за 10 % об'єкта (10 000): у РІ 3.2.4 іде 50 %, тобто 10 000."""
        self._entry("Збиток 2025 року", LOSS_DATE, [
            ("92", 20000.0, 0.0), ("631", 0.0, 20000.0)])
        self._declaration(year=YEAR - 1).action_confirm()
        declaration = self._declaration(large_payer=True, **DETAILS)
        self._eq(declaration.diff_loss, -10000.0, "РІ 3.2.4")
        self._eq(declaration.tax_base, 90000.0, "об'єкт")         # 100 000 - 10 000
        self._eq(declaration.tax_amount, 16200.0, "податок")      # 90 000 × 18 %
        self._eq(declaration.loss_left, 10000.0, "залишок на 2027 рік")
        self.assertIn("частково", declaration.note)
        # Залишок не більший за 10 % додатного об'єкта - зараховується весь.
        self._eq(declaration._loss_used(5000.0, 100000.0, date(YEAR, 12, 31)), 5000.0, "до 10 %")
        self._eq(declaration._loss_used(20000.0, -5000.0, date(YEAR, 12, 31)), 10000.0, "збитковий рік")
        main, ri = self._xml(declaration)
        body, ri_body = main.find("DECLARBODY"), ri.find("DECLARBODY")
        self.assertEqual([body.findtext(t) for t in ("R003G3", "R004G3", "R006G3", "HD6")],
                         ["-10000", "90000", "16200", "1"])
        self.assertEqual([ri_body.findtext(t) for t in ("R0324G3", "R001G3", "R002G3", "R003G3", "HY")],
                         ["10000", None, "10000", "-10000", "1"])
        main_doc = main.find("DECLARHEAD/LINKED_DOCS/DOC")
        ri_doc = ri.find("DECLARHEAD/LINKED_DOCS/DOC")
        self.assertEqual((main_doc.get("TYPE"), main_doc.findtext("FILENAME")), ("1", declaration.ri_xml_name))
        self.assertEqual((ri_doc.get("TYPE"), ri_doc.findtext("FILENAME")), ("2", declaration.xml_name))
        self.assertEqual(ri.find("DECLARHEAD").findtext("C_DOC_SUB"), "118")

    # ---- 12. Квартальний платник: рядок 18 ---------------------------------

    def test_12_quarterly_payer_row_18(self):
        """За рік квартальний платник віднімає податок за 9 місяців: 18 000 - 12 000 = 6 000."""
        declaration = self._declaration(base_period="quarter", prior_tax=12000.0, **DETAILS)
        self.assertIn("18", declaration.line_ids.mapped("code"))
        self._eq(declaration.tax_due, 6000.0, "ряд. 19")
        main, _ri = self._xml(declaration)
        body = main.find("DECLARBODY")
        self.assertEqual([body.findtext(t) for t in ("H01", "R017G3", "R018G3", "R019G3")],
                         ["1", "18000", "12000", "6000"])
        self.assertIsNone(body.find("H02"))

    # ---- 13. Без коригувань на різниці -------------------------------------

    def test_13_no_adjustments_only_below_limit(self):
        """Малодохідник може не застосовувати різниці (HJ2); понад поріг - не може."""
        declaration = self._declaration(no_adjustments=True, **DETAILS)
        self._eq(declaration.amort_book + declaration.amort_tax, 0.0, "амортизація не застосовується")
        main, _ri = self._xml(declaration)
        self.assertEqual(main.find("DECLARBODY").findtext("HJ2"), "1")
        declaration.action_draft()
        self.env["ua.profit.param"].create({
            "key": "profit_low_income_limit", "name": "Поріг для перевірки",
            "valid_from": date(YEAR, 1, 1), "value": 50000.0, "company_id": self.company.id,
            "source": "уявне значення для перевірки",
        })
        with self.assertRaises(UserError):
            declaration.action_compute()

    # ---- 14. XML не роблять без реквізитів і за старою формою --------------

    def test_14_xml_needs_details_and_current_form(self):
        declaration = self._declaration(**dict(DETAILS, director_rnokpp=False, sti_name=False))
        with self.assertRaises(UserError):
            declaration.action_xml()
        old = self._declaration(year=2024, **DETAILS)
        with self.assertRaises(UserError):
            old.action_xml()
