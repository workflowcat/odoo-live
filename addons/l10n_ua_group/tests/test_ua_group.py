"""Консолідація групи і дзеркала між компаніями на числах, порахованих руками.

Дві компанії, вісім проводок, усі суми в коментарях поруч із перевіркою.

Компанія А: внесок 100 000; зовнішній продаж 120 000; продаж компанії Б
60 000 (послуга). Компанія Б: внесок 50 000; зовнішній продаж 90 000;
послуга від А 60 000 у витрати.

    А: актив 100 000 + (120 000 + 60 000) = 280 000 = пасив
    Б: актив 50 000 + 90 000 = 140 000; борг перед А 60 000; пасив 140 000
    разом до елімінації 1300 = 420 000
    еліміновано взаємних розрахунків 60 000 → консолідовано 360 000
    Ф2: разом дохід 270 000, консолідовано 210 000 (продаж усередині групи
        не є доходом групи), чистий результат не змінюється - 210 000.
"""

import logging
from datetime import date

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

_logger = logging.getLogger(__name__)

TOL = 0.005
PIVOT = date(2026, 12, 31)
BOOK_DATE = date(2026, 3, 16)

TOTAL_LABEL = "Разом до елімінації"
ELIMINATION_LABEL = "Елімінація ВГО"
CONSOLIDATED_LABEL = "Консолідовано"


@tagged("post_install", "-at_install", "ua_group")
class TestUaGroup(AccountTestInvoicingCommon):
    """Один набір даних на клас: матриці звітів рахуються по одному разу."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.data_b = cls.setup_other_company(name="Компанія Б")
        cls.company_b = cls.data_b["company"]
        cls.env.user.company_ids = [(4, cls.company_b.id)]
        cls.env.user.group_ids = [
            (4, cls.env.ref("account.group_account_invoice").id)]
        cls.group = cls.company_a + cls.company_b
        cls.external = cls.env["res.partner"].create({"name": "Зовнішній покупець"})
        cls._post_entries()

    # ---- підготовка --------------------------------------------------------

    @classmethod
    def _acc(cls, company, prefix):
        """Рахунок компанії за префіксом коду: працює і з 361, і з 361000."""
        account = cls.env["account.account"].with_company(company).search(
            [("code", "=like", prefix + "%"), ("company_ids", "=", company.id)],
            order="code", limit=1)
        assert account, "немає рахунку %s* у «%s»" % (prefix, company.name)
        return account

    @classmethod
    def _entry(cls, company, label, lines):
        journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", company.id)], limit=1)
        assert journal, "немає журналу «Інші операції» у «%s»" % company.name
        move = cls.env["account.move"].with_company(company).create({
            "move_type": "entry",
            "journal_id": journal.id,
            "company_id": company.id,
            "date": BOOK_DATE,
            "ref": label,
            "line_ids": [(0, 0, {
                "name": label,
                "account_id": cls._acc(company, code).id,
                "partner_id": partner.id if partner else False,
                "debit": debit,
                "credit": credit,
            }) for code, debit, credit, partner in lines],
        })
        move.action_post()
        return move

    @classmethod
    def _post_entries(cls):
        a, b = cls.company_a, cls.company_b
        cls._entry(a, "А: внесок до статутного капіталу", [
            ("311", 100000.0, 0.0, None), ("401", 0.0, 100000.0, None)])
        cls._entry(a, "А: зовнішній продаж", [
            ("361", 120000.0, 0.0, cls.external),
            ("702", 0.0, 120000.0, cls.external)])
        cls._entry(a, "А: продаж послуги компанії Б", [
            ("361", 60000.0, 0.0, b.partner_id),
            ("702", 0.0, 60000.0, b.partner_id)])
        cls._entry(b, "Б: внесок до статутного капіталу", [
            ("311", 50000.0, 0.0, None), ("401", 0.0, 50000.0, None)])
        cls._entry(b, "Б: зовнішній продаж", [
            ("361", 90000.0, 0.0, cls.external),
            ("702", 0.0, 90000.0, cls.external)])
        cls._entry(b, "Б: послуга від компанії А", [
            ("92", 60000.0, 0.0, a.partner_id),
            ("631", 0.0, 60000.0, a.partner_id)])

    # ---- службове ----------------------------------------------------------

    def _build(self, form, companies=None):
        """Звіт консолідації, зібраний чарівником, готовий до читання матриці."""
        companies = companies or self.group
        wizard = self.env["ua.group.consolidation"].with_context(
            allowed_company_ids=companies.ids).create({
                "company_ids": [(6, 0, companies.ids)],
                "form": form,
                "date_from": date(2026, 1, 1),
                "date_to": PIVOT,
            })
        action = wizard.action_build()
        return self.env["mis.report.instance"].with_context(
            allowed_company_ids=companies.ids).browse(action["res_id"])

    def _matrix(self, form, companies=None):
        return self._build(form, companies)._ua_group_matrix()

    def _eq(self, got, expected, label):
        self.assertAlmostEqual(
            got, expected, delta=TOL,
            msg="%s: очікували %.2f, вийшло %.2f" % (label, expected, got))

    # ---- 1. Колонки звіту ---------------------------------------------------

    def test_01_wizard_builds_columns(self):
        """Колонок стільки, скільки компаній, плюс разом, елімінація і підсумок."""
        instance = self._build("f1")
        self.assertTrue(instance.ua_group_consolidation, "звіт без позначки консолідації")
        self.assertTrue(instance.multi_company, "звіт не в багатокомпанійному режимі")
        self.assertEqual(instance.query_company_ids, self.group,
                         "звіт шукає дані не по тих компаніях")
        labels = instance.period_ids.sorted("sequence").mapped("name")
        self.assertEqual(
            labels,
            [self.company_a.name, self.company_b.name,
             TOTAL_LABEL, ELIMINATION_LABEL, CONSOLIDATED_LABEL],
            "несподіваний набір колонок")
        column_a = instance.period_ids.filtered(lambda p: p.name == self.company_a.name)
        self.assertEqual(
            column_a.analytic_domain, repr([("company_id", "=", self.company_a.id)]),
            "колонка компанії не обмежена її проводками")
        consolidated = instance.period_ids.filtered(
            lambda p: p.name == CONSOLIDATED_LABEL)
        self.assertEqual(consolidated.source, "sumcol", "підсумок не є сумою колонок")
        signs = consolidated.source_sumcol_ids.mapped("sign")
        self.assertEqual(signs.count("+"), 2, "компанії мають додаватись")
        self.assertEqual(signs.count("-"), 1, "елімінація має відніматись")

    # ---- 2. Кожна компанія окремо ------------------------------------------

    def test_02_company_columns_are_separate_books(self):
        """Колонка компанії показує тільки її книги, і кожна сходиться сама по собі."""
        matrix = self._matrix("f1")
        a = matrix[self.company_a.name]
        b = matrix[self.company_b.name]
        # А: 100 000 грошей + 180 000 дебіторки
        self._eq(a["1300"], 280000.0, "А, ряд. 1300")
        self._eq(a["1900"], 280000.0, "А, ряд. 1900")
        self._eq(a["ctl_ap"], 0.0, "А, контроль 1300-1900")
        # Б: 50 000 грошей + 90 000 дебіторки
        self._eq(b["1300"], 140000.0, "Б, ряд. 1300")
        self._eq(b["1615"], 60000.0, "Б, ряд. 1615 борг перед А")
        self._eq(b["ctl_ap"], 0.0, "Б, контроль 1300-1900")

    # ---- 3. Разом до елімінації --------------------------------------------

    def test_03_total_is_plain_sum(self):
        """«Разом» - проста сума колонок компаній, без жодних згортань."""
        matrix = self._matrix("f1")
        total = matrix[TOTAL_LABEL]
        self._eq(total["1300"],
                 matrix[self.company_a.name]["1300"] + matrix[self.company_b.name]["1300"],
                 "разом ряд. 1300 = сума компаній")
        self._eq(total["1300"], 420000.0, "разом ряд. 1300")  # 280 000 + 140 000

    # ---- 4. Що саме елімінується -------------------------------------------

    def test_04_elimination_column_holds_mutual_settlements(self):
        """Колонка елімінації - дзеркальна пара: дебіторка А = кредиторка Б."""
        elimination = self._matrix("f1")[ELIMINATION_LABEL]
        self._eq(elimination["1125"], 60000.0, "еліміновано дебіторки")
        self._eq(elimination["1615"], 60000.0, "еліміновано кредиторки")
        self._eq(elimination["1300"], elimination["1900"],
                 "пара незбалансована - книги компаній розійшлися")
        # Зовнішня дебіторка 120 000 + 90 000 в елімінацію не потрапляє.
        self._eq(elimination["1300"], 60000.0, "в елімінацію потрапило зайве")

    # ---- 5. Консолідований баланс ------------------------------------------

    def test_05_consolidated_balance(self):
        """1300 групи = сума компаній мінус взаємні розрахунки; А = П."""
        matrix = self._matrix("f1")
        consolidated = matrix[CONSOLIDATED_LABEL]
        # 420 000 - 60 000 = 360 000
        self._eq(consolidated["1300"], 360000.0, "консолідований ряд. 1300")
        self._eq(consolidated["1900"], 360000.0, "консолідований ряд. 1900")
        self._eq(consolidated["ctl_ap"], 0.0, "консолідований контроль 1300-1900")
        self._eq(consolidated["1125"], 210000.0,
                 "консолідована дебіторка")  # 180 000 + 90 000 - 60 000
        self._eq(consolidated["1615"], 0.0, "внутрішньогрупового боргу не лишилось")

    # ---- 6. Ф1-м дає ті самі підсумки --------------------------------------

    def test_06_f1m_consolidated_equals_f1(self):
        """Дрібна форма Ф1-м зводиться так само: підсумки збігаються з Ф1."""
        f1 = self._matrix("f1")[CONSOLIDATED_LABEL]
        f1m = self._matrix("f1m")[CONSOLIDATED_LABEL]
        for code in ("1195", "1300", "1495", "1695", "1900"):
            self._eq(f1m[code], f1[code], "Ф1-м проти Ф1, ряд. %s" % code)
        self._eq(f1m["ctl_ap"], 0.0, "Ф1-м консолідований контроль")

    # ---- 7. Консолідований дохід -------------------------------------------

    def test_07_consolidated_revenue_excludes_intragroup_sale(self):
        """Продаж усередині групи не є доходом групи, а результат не змінюється."""
        matrix = self._matrix("f2")
        total, consolidated = matrix[TOTAL_LABEL], matrix[CONSOLIDATED_LABEL]
        self._eq(total["2000"], 270000.0, "разом дохід")     # 180 000 + 90 000
        self._eq(matrix[ELIMINATION_LABEL]["2000"], 60000.0, "еліміновано доходу")
        self._eq(consolidated["2000"], 210000.0, "консолідований дохід")
        # Витрати Б на послугу від А зникають разом із доходом А.
        self._eq(consolidated["2130"], 0.0, "внутрішньогрупових витрат не лишилось")
        # Результат групи не змінився: 120 000 + 90 000 зовнішнього доходу.
        self._eq(total["2350"], 210000.0, "разом чистий результат")
        self._eq(consolidated["2350"], 210000.0, "консолідований чистий результат")
        self._eq(consolidated["2350"], total["2350"],
                 "елімінація не має чіпати результат групи")

    # ---- 8. Розбіжність звірки видима --------------------------------------

    def test_08_mirror_mismatch_shows_in_control_row(self):
        """Односторонній борг ламає контроль рівно на розбіжність - і це видно.

        Компанія Б визнає ще 10 000 боргу перед А, а А такої дебіторки не
        має. Колонка елімінації перестає бути дзеркальною парою, і
        консолідований контроль 1300-1900 показує рівно 10 000.
        """
        self._entry(self.company_b, "Б: борг перед А без дзеркала", [
            ("92", 10000.0, 0.0, self.company_a.partner_id),
            ("631", 0.0, 10000.0, self.company_a.partner_id)])
        matrix = self._matrix("f1")
        elimination, consolidated = matrix[ELIMINATION_LABEL], matrix[CONSOLIDATED_LABEL]
        self._eq(elimination["1615"], 70000.0, "кредиторка в елімінації")
        self._eq(elimination["1125"], 60000.0, "дебіторка в елімінації")
        self._eq(consolidated["ctl_ap"], 10000.0,
                 "розбіжність звірки не показалась у контрольному рядку")

    # ---- 9. Дзеркало рахунку (OCA) -----------------------------------------

    def _mirror_setup(self):
        """Товар, видимий обом компаніям, з податками продажу А і купівлі Б."""
        product = self.env["product.product"].create({
            "name": "Послуга групи", "type": "service", "list_price": 1000.0})
        product.with_company(self.company_a).taxes_id = [
            (6, 0, self.company_data["default_tax_sale"].ids)]
        product.with_company(self.company_b).supplier_taxes_id = [
            (6, 0, self.data_b["default_tax_purchase"].ids)]
        # Дзеркало має лишитись чернеткою: бухгалтер Б перевіряє його сам.
        self.company_b.invoice_auto_validation = False
        return product

    def _sale_to_group(self, product, quantity=3.0):
        invoice = self.env["account.move"].with_company(self.company_a).create({
            "move_type": "out_invoice",
            "company_id": self.company_a.id,
            "partner_id": self.company_b.partner_id.id,
            "invoice_date": BOOK_DATE,
            "date": BOOK_DATE,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "quantity": quantity,
                "price_unit": 1000.0,
            })],
        })
        invoice.action_post()
        return invoice

    def test_09_mirror_creates_draft_bill(self):
        """Продаж компанії групи дає чернетку вхідного рахунку з тими ж рядками."""
        product = self._mirror_setup()
        invoice = self._sale_to_group(product)
        mirror = self.env["account.move"].sudo().search(
            [("auto_invoice_id", "=", invoice.id)])
        self.assertEqual(len(mirror), 1, "дзеркал %d, очікували 1" % len(mirror))
        self.assertEqual(mirror.company_id, self.company_b, "дзеркало не в тій компанії")
        self.assertEqual(mirror.move_type, "in_invoice", "дзеркало не є вхідним рахунком")
        self.assertEqual(mirror.state, "draft", "дзеркало проведено без бухгалтера Б")
        self.assertEqual(mirror.partner_id, self.company_a.partner_id,
                         "у дзеркалі не той контрагент")
        source_line = invoice.invoice_line_ids
        mirror_line = mirror.invoice_line_ids
        self.assertEqual(mirror_line.product_id, source_line.product_id, "інший товар")
        self._eq(mirror_line.quantity, source_line.quantity, "інша кількість")
        self._eq(mirror_line.price_unit, source_line.price_unit, "інша ціна")
        self.assertEqual(mirror_line.tax_ids.mapped("amount"),
                         source_line.tax_ids.mapped("amount"),
                         "ставка податку в дзеркалі не збігається")
        self._eq(mirror.amount_total, invoice.amount_total, "сума дзеркала")

    def test_10_no_double_mirror(self):
        """Повторний виклик дзеркала дубля не створює."""
        product = self._mirror_setup()
        invoice = self._sale_to_group(product)
        invoice.sudo().with_company(self.company_b).with_context(
            skip_check_amount_difference=True)._inter_company_create_invoice(
                self.company_b)
        count = self.env["account.move"].sudo().search_count(
            [("auto_invoice_id", "=", invoice.id)])
        self.assertEqual(count, 1, "після повторного виклику дзеркал %d" % count)

    def test_11_mirror_pair_eliminates_without_mismatch(self):
        """Дзеркальна пара зводиться: консолідований контроль лишається 0.

        Інваріант УО-13 пісочниці: після дзеркалення розбіжність кожної пари
        звірки дорівнює нулю. Тут він перевіряється тим самим контрольним
        рядком форми - іншого місця для розбіжності немає.
        """
        product = self._mirror_setup()
        invoice = self._sale_to_group(product)
        mirror = self.env["account.move"].sudo().search(
            [("auto_invoice_id", "=", invoice.id)])
        mirror.with_company(self.company_b).action_post()
        matrix = self._matrix("f1")
        elimination, consolidated = matrix[ELIMINATION_LABEL], matrix[CONSOLIDATED_LABEL]
        # 60 000 з проводок набору + сума дзеркальної пари.
        self._eq(elimination["1125"], 60000.0 + invoice.amount_total,
                 "дебіторка А до Б в елімінації")
        self._eq(elimination["1300"], elimination["1900"],
                 "дзеркальна пара не зійшлась")
        self._eq(consolidated["ctl_ap"], 0.0, "консолідований контроль після дзеркала")

    # ---- 12. Журнал змін ----------------------------------------------------

    def test_12_auditlog_catches_invoice_edit(self):
        """Правка проведеного рахунку лишає запис аудиту з потрібним полем.

        Правила лежать у l10n_ua_changes (файл data/auditlog_rules_account.xml).
        Якщо журналу змін у базі немає, перевіряти нічого.
        """
        rule = self.env.ref("l10n_ua_changes.rule_account_move",
                            raise_if_not_found=False)
        if not rule:
            self.skipTest("l10n_ua_changes не встановлено - правил аудиту немає")
        watched = set(rule.ua_field_ids.mapped("field_name"))
        for field_name in ("state", "date", "ref", "partner_id",
                           "amount_total", "journal_id"):
            self.assertIn(field_name, watched,
                          "поле %s не під наглядом журналу змін" % field_name)
        product = self._mirror_setup()
        invoice = self._sale_to_group(product)
        Log = self.env["auditlog.log"].sudo()
        before = Log.search_count([("model_model", "=", "account.move")])
        invoice.sudo().write({"ref": "Правка після проведення"})
        logs = Log.search([("model_model", "=", "account.move"),
                           ("res_id", "=", invoice.id)])
        self.assertGreater(
            Log.search_count([("model_model", "=", "account.move")]), before,
            "правка рахунку не потрапила в аудит")
        changed = logs.line_ids.mapped("field_name")
        self.assertIn("ref", changed, "у записі аудиту немає поля ref")
        # Рядок account.move.line теж має власне правило.
        line_rule = self.env.ref("l10n_ua_changes.rule_account_move_line",
                                 raise_if_not_found=False)
        self.assertTrue(line_rule, "немає правила аудиту на рядки проводок")
        self.assertEqual(line_rule.state, "confirmed", "правило рядків не увімкнене")
