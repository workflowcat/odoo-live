"""Перенесення з 1С/BAS: кодування, роздільники, числа, рахунки, баланс.

Файли-зразки лежать у tests/fixtures і зроблені такими ж, як реальні
вивантаження: cp1251, крапка з комою, кома в числах, заголовки російською.
Очікувані суми пораховані руками.

Запуск: docker compose run ... --test-tags=ua_migrate
"""
import base64
import io
import os
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return base64.b64encode(fh.read())


@tagged("post_install", "-at_install", "ua_migrate")
class TestUaMigrate(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _wizard(self, kind, filename, **extra):
        vals = {
            "import_type": kind,
            "data_file": fixture(filename),
            "data_filename": filename,
            "dry_run": False,
        }
        vals.update(extra)
        return self.env["ua.migrate"].create(vals)

    def _account(self, prefix):
        acc = self.env["account.account"].search([
            ("code", "=like", prefix + "%"),
            ("company_ids", "in", self.company.id)], order="code", limit=1)
        self.assertTrue(acc, "у плані немає рахунку %s" % prefix)
        return acc

    # ------------------------------------------------------------------
    # 1. utf-8, роздільник кома.
    # ------------------------------------------------------------------
    def test_01_partners_utf8_comma(self):
        self._wizard("partners", "partners_utf8.csv").action_import()
        promin = self.env["res.partner"].search([("company_registry", "=", "32165498")])
        self.assertEqual(len(promin), 1)
        self.assertEqual(promin.name, "ТОВ «Промінь»")
        self.assertEqual(promin.city, "Київ")
        self.assertEqual(promin.vat, "321654987654")
        self.assertTrue(promin.is_company)
        fop = self.env["res.partner"].search([("company_registry", "=", "2233445566")])
        self.assertEqual(fop.phone, "+380671112233")

    # ------------------------------------------------------------------
    # 2. cp1251 і крапка з комою; повторений ЄДРПОУ не дублює контрагента.
    # ------------------------------------------------------------------
    def test_02_partners_cp1251_duplicate_edrpou(self):
        wizard = self._wizard("partners", "partners_cp1251.csv")
        wizard.action_import()
        svitanok = self.env["res.partner"].search([("company_registry", "=", "12345678")])
        self.assertEqual(len(svitanok), 1, "той самий ЄДРПОУ створив другого контрагента")
        # другий рядок оновив телефон першого
        self.assertEqual(svitanok.phone, "+380442223355")
        self.assertEqual(svitanok.name, "ТОВ Світанок")
        yavir = self.env["res.partner"].search([("company_registry", "=", "87654321")])
        self.assertEqual(len(yavir), 1)
        self.assertIn("створено 2, оновлено 1", wizard.result_html)

    # ------------------------------------------------------------------
    # 3. Десяткова кома і пробіл у тисячах.
    # ------------------------------------------------------------------
    def test_03_products_decimal_comma(self):
        self._wizard("products", "products_cp1251.csv").action_import()
        cable = self.env["product.product"].search([("default_code", "=", "A-001")])
        self.assertEqual(len(cable), 1)
        # «1 250,50» -> 1250.50, «980,25» -> 980.25
        self.assertAlmostEqual(cable.list_price, 1250.50, delta=CENT)
        self.assertAlmostEqual(cable.standard_price, 980.25, delta=CENT)
        self.assertEqual(cable.barcode, "4820001234567")
        breaker = self.env["product.product"].search([("default_code", "=", "A-002")])
        self.assertAlmostEqual(breaker.list_price, 327.0, delta=CENT)
        self.assertFalse(breaker.barcode)

    # ------------------------------------------------------------------
    # 4. Сальдо короткими кодами 1С лягають у нативну початкову проводку.
    # ------------------------------------------------------------------
    def test_04_balances_short_codes(self):
        self._wizard("balances", "balances_short.csv",
                     date_opening=date(2026, 1, 1)).action_import()
        move = self.company.account_opening_move_id
        self.assertTrue(move, "нативної початкової проводки не створено")
        # сальдо на 1 січня - це проводка попереднього дня
        self.assertEqual(move.date, date(2025, 12, 31))
        self.assertEqual(move.state, "draft")
        # 150 000 + 40 000 = 190 000 Дт; 60 000 + 130 000 = 190 000 Кт
        self.assertAlmostEqual(sum(move.line_ids.mapped("debit")), 190000.0, delta=CENT)
        self.assertAlmostEqual(sum(move.line_ids.mapped("credit")), 190000.0, delta=CENT)
        acc_311 = self._account("311")
        line = move.line_ids.filtered(lambda l: l.account_id == acc_311)
        self.assertAlmostEqual(sum(line.mapped("debit")), 150000.0, delta=CENT)

    # ------------------------------------------------------------------
    # 5. Та сама база з доповненими кодами і субрахунком 3611.
    # ------------------------------------------------------------------
    def test_05_balances_padded_codes(self):
        self._wizard("balances", "balances_padded.csv",
                     date_opening=date(2026, 1, 1)).action_import()
        move = self.company.account_opening_move_id
        self.assertAlmostEqual(sum(move.line_ids.mapped("debit")), 190000.0, delta=CENT)
        # 3611 у плані немає - рядок пішов на 361
        acc_361 = self._account("361")
        line = move.line_ids.filtered(lambda l: l.account_id == acc_361)
        self.assertAlmostEqual(sum(line.mapped("debit")), 40000.0, delta=CENT)

    def test_06_account_matching_both_shapes(self):
        wizard = self.env["ua.migrate"].new({"import_type": "balances"})
        by_code, widths = wizard._account_index()
        acc_361 = self._account("361")
        for raw in ("361", "361000", "3611", "361.1"):
            self.assertEqual(
                wizard._match_account(raw, by_code, widths), acc_361,
                "код %s не знайшов рахунок 361" % raw)
        self.assertFalse(wizard._match_account("", by_code, widths))

    # ------------------------------------------------------------------
    # 7. Небаланс не приймається.
    # ------------------------------------------------------------------
    def test_07_unbalanced_rejected(self):
        wizard = self._wizard("balances", "balances_unbalanced.csv")
        with self.assertRaises(UserError):
            wizard.action_import()
        self.assertFalse(self.company.account_opening_move_id.line_ids)

    def test_08_unbalanced_allowed_goes_to_earnings(self):
        self._wizard("balances", "balances_unbalanced.csv",
                     allow_unbalanced=True).action_import()
        move = self.company.account_opening_move_id
        # 100 000 Дт проти 60 000 Кт: різницю 40 000 нативний Odoo кладе
        # на рахунок нерозподіленого прибутку
        self.assertAlmostEqual(sum(move.line_ids.mapped("debit")), 100000.0, delta=CENT)
        self.assertAlmostEqual(sum(move.line_ids.mapped("credit")), 100000.0, delta=CENT)
        balancing = move.line_ids.filtered(
            lambda l: l.account_id.account_type == "equity_unaffected")
        self.assertAlmostEqual(sum(balancing.mapped("credit")), 40000.0, delta=CENT)

    # ------------------------------------------------------------------
    # 9. Пробний прогін не записує нічого.
    # ------------------------------------------------------------------
    def test_09_dry_run_writes_nothing(self):
        before = self.env["res.partner"].search_count([])
        wizard = self._wizard("partners", "partners_cp1251.csv", dry_run=True)
        wizard.action_import()
        self.assertEqual(self.env["res.partner"].search_count([]), before)
        self.assertFalse(self.env["res.partner"].search([("company_registry", "=", "12345678")]))
        self.assertIn("нічого не записано", wizard.result_html)
        self.assertIn("створено 2, оновлено 1", wizard.result_html)
        # сальдо в пробному прогоні теж не створюють проводки
        dry = self._wizard("balances", "balances_short.csv", dry_run=True)
        dry.action_import()
        self.assertFalse(self.company.account_opening_move_id.line_ids)

    # ------------------------------------------------------------------
    # 10. XLSX читається тим самим автомапінгом.
    # ------------------------------------------------------------------
    def test_10_xlsx(self):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.append(["Наименование", "Код по ЕДРПОУ", "Город"])
        sheet.append(["ТОВ Ексель", "55667788", "Харків"])
        stream = io.BytesIO()
        book.save(stream)
        wizard = self.env["ua.migrate"].create({
            "import_type": "partners",
            "data_file": base64.b64encode(stream.getvalue()),
            "data_filename": "kontragenty.xlsx",
            "dry_run": False,
        })
        wizard.action_import()
        partner = self.env["res.partner"].search([("company_registry", "=", "55667788")])
        self.assertEqual(partner.name, "ТОВ Ексель")
        self.assertEqual(partner.city, "Харків")

    # ------------------------------------------------------------------
    # 11. Немає обов'язкової колонки - зрозуміла помилка, а не трейсбек.
    # ------------------------------------------------------------------
    def test_11_missing_column(self):
        raw = "Коментар;Сума\nщось;100\n".encode("cp1251")
        wizard = self.env["ua.migrate"].create({
            "import_type": "balances",
            "data_file": base64.b64encode(raw),
            "data_filename": "saldo.csv",
            "dry_run": False,
        })
        with self.assertRaises(UserError):
            wizard.action_import()
