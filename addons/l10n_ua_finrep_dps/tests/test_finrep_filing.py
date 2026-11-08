"""Фінзвітність до ДПС: дві графи, тисячі гривень, перевірка підсумків, XML за схемою.

Проводки (числа порахровані вручну):
    2025-03-01  внесок до статутного капіталу 100 000 (311 / 401)
    2025-04-10  товар 30 000 (281 / 631)
    2025-08-20  продаж 60 000 з ПДВ 10 000 (361 / 702, 6412); собівартість 30 000 (902 / 281)
    2026-05-15  продаж 36 000 з ПДВ 6 000 (361 / 702, 6412)
    2026-06-30  зарплата адміністрації 12 345,67 (92 / 661)
На 31.12.2025: гроші 100 000, дебіторка 60 000, кредиторка 30 000, ПДВ 10 000, капітал 100 000,
прибуток 20 000. На 30.09.2026: дебіторка 96 000, ПДВ 16 000, зарплата 12 345,67, прибуток
20 000 + 30 000 - 12 345,67 = 37 654,33.
"""
from datetime import date

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

ENTRIES = [
    (date(2025, 3, 1), [("311", 100000.0, 0.0), ("401", 0.0, 100000.0)]),
    (date(2025, 4, 10), [("281", 30000.0, 0.0), ("631", 0.0, 30000.0)]),
    (date(2025, 8, 20), [("361", 60000.0, 0.0), ("702", 0.0, 50000.0), ("6412", 0.0, 10000.0)]),
    (date(2025, 8, 20), [("902", 30000.0, 0.0), ("281", 0.0, 30000.0)]),
    (date(2026, 5, 15), [("361", 36000.0, 0.0), ("702", 0.0, 30000.0), ("6412", 0.0, 6000.0)]),
    (date(2026, 6, 30), [("92", 12345.67, 0.0), ("661", 0.0, 12345.67)]),
]


@tagged("post_install", "-at_install", "ua_finrep_dps")
class TestUaFinrepFiling(TransactionCase):
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
        journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)], limit=1)
        partner = cls.env["res.partner"].create({"name": "Контрагент фінзвітності"})
        moves = cls.env["account.move"]
        for on_date, lines in ENTRIES:
            moves |= cls.env["account.move"].create({
                "move_type": "entry", "journal_id": journal.id, "date": on_date,
                "line_ids": [(0, 0, {"name": "тест", "account_id": cls._acc(code).id, "debit": debit,
                                     "credit": credit, "partner_id": partner.id})
                             for code, debit, credit in lines]})
        moves.action_post()

    @classmethod
    def _acc(cls, prefix):
        account = cls.env["account.account"].search(
            [("code", "=like", prefix + "%"), ("company_ids", "in", cls.company.id)], order="code", limit=1)
        assert account, "немає рахунку %s" % prefix
        return account

    def _filing(self, form, **vals):
        doc = self.env["ua.finrep.filing"].create(dict({
            "form": form, "year": 2026, "period": "9", "tin": "12345678", "sti_code": "2659",
            "kved": "30.30", "koatuu": "8038200000", "legal_form": "240", "director": "Іваненко І. І.", "accountant": "Петренко П. П.",
            "address": "01001, м. Київ, вул. Прикладна, 1", "phone": "044 000 00 00",
        }, **vals))
        doc.action_compute()
        return doc

    @staticmethod
    def _rows(doc, part=None):
        return {line.code: line for line in doc.line_ids if not part or line.part == part}

    @staticmethod
    def _xml(doc):
        name, data = doc._ua_xml()
        return name, etree.fromstring(data)

    def test_01_balance_columns_in_thousands(self):
        doc = self._filing("J0900108")
        self.assertEqual((doc.date_from, doc.date_to), (date(2026, 1, 1), date(2026, 9, 30)))
        rows = self._rows(doc)
        self.assertEqual((rows["1165"].g3, rows["1165"].g4), (100.0, 100.0))
        self.assertEqual((rows["1125"].g3, rows["1125"].g4), (60.0, 96.0))
        self.assertEqual((rows["1420"].g3, rows["1420"].g4), (20.0, 38.0))  # 37 654,33 -> 38
        self.assertAlmostEqual(rows["1420"].uah_g4, 37654.33, places=2)
        self.assertEqual((rows["1630"].g3, rows["1630"].g4), (0.0, 12.0))
        self.assertEqual((rows["1300"].g4, rows["1900"].g4), (196.0, 196.0))
        self.assertEqual((rows["1300"].g3, rows["1900"].g3), (160.0, 160.0))
        self.assertFalse(doc.check_text, doc.check_text)

    def test_02_balance_xml_matches_schema(self):
        doc = self._filing("J0900108")
        name, root = self._xml(doc)
        head, body = root.find("DECLARHEAD"), root.find("DECLARBODY")
        self.assertEqual([head.findtext(t) for t in ("C_DOC", "C_DOC_SUB", "C_DOC_VER", "PERIOD_TYPE",
                                                     "PERIOD_MONTH", "C_REG", "C_RAJ", "C_STI_ORIG")],
                         ["J09", "001", "8", "4", "9", "26", "59", "2659"])
        self.assertEqual(body.findtext("H01"), "1")
        self.assertEqual((body.findtext("HPERIOD"), body.findtext("HKOATUU")), ("30 вересня", "8038200000"))
        self.assertEqual(body.findtext("R1300G4"), "196")
        self.assertEqual(body.findtext("R1420G4"), "38")
        self.assertIsNone(body.find("R1005G3"), "нульові рядки у файл не йдуть")
        # ДПІ, ЄДРПОУ (10 знаків), форма, стан 1, тип 00, номер 0000001, період 4, місяць 09, рік, ДПІ.
        self.assertEqual(name, "2659" "0012345678" "J0900108" "1" "00" "0000001" "4" "09" "2026" "2659" ".XML")

    def test_03_pnl_columns_and_split(self):
        doc = self._filing("J0900207")
        rows = self._rows(doc)
        # Графа 3 - 9 місяців 2026, графа 4 - 9 місяців 2025.
        self.assertEqual((rows["2000"].g3, rows["2000"].g4), (30.0, 50.0))
        self.assertEqual((rows["2050"].g3, rows["2050"].g4), (0.0, 30.0))
        self.assertEqual((rows["2130"].g3, rows["2130"].g4), (12.0, 0.0))
        self.assertEqual((rows["2350"].g3, rows["2350"].g4), (18.0, 20.0))  # 17 654,33 -> 18
        self.assertEqual((rows["2355"].g3, rows["2355"].g4), (0.0, 0.0))
        self.assertFalse(doc.check_text, doc.check_text)
        # Збиток іде окремим рядком, додатним.
        loss = doc._ua_present("2350", -5400.0, 100.0)
        self.assertEqual([(r["code"], r["uah_g3"], r["uah_g4"]) for r in loss],
                         [("2350", 0.0, 100.0), ("2355", 5400.0, 0.0)])
        _name, root = self._xml(doc)
        self.assertEqual(root.find("DECLARBODY").findtext("R2350G3"), "18")
        self.assertEqual(root.find("DECLARBODY").findtext("HPERIOD"), "9 місяців")

    def test_04_small_company_form(self):
        doc = self._filing("J0901107")
        f1m, f2m = self._rows(doc, "f1m"), self._rows(doc, "f2m")
        self.assertEqual((f1m["1420"].g3, f1m["1420"].g4), (20.0, 37.7))
        self.assertEqual(f1m["1135"].g4, 0.0)
        self.assertEqual(f1m["1620"].g4, 16.0)
        self.assertEqual((f1m["1695"].g4, f1m["1900"].g4), (58.3, 196.0))
        self.assertEqual((f2m["2000"].g3, f2m["2180"].g3, f2m["2290"].g3), (30.0, 12.3, 17.7))
        self.assertEqual((f2m["2000"].g4, f2m["2050"].g4), (50.0, 30.0))
        self.assertFalse(doc.check_text, doc.check_text)
        name, root = self._xml(doc)
        head, body = root.find("DECLARHEAD"), root.find("DECLARBODY")
        self.assertEqual((head.findtext("C_DOC_SUB"), head.findtext("C_DOC_VER")), ("011", "7"))
        self.assertEqual(body.findtext("R1420G4"), "37.7")
        self.assertEqual(body.findtext("R2290G3"), "17.7")
        self.assertEqual(body.findtext("HZY1"), "2026")
        self.assertEqual((body.findtext("HPERIOD"), body.findtext("HPERIOD1")), ("30 вересня", "9 місяців"))
        self.assertEqual(name, "2659" "0012345678" "J0901107" "1" "00" "0000001" "4" "09" "2026" "2659" ".XML")

    def test_05_rounding_check_and_manual_fix(self):
        doc = self._filing("J0900108")
        line = self._rows(doc)["1630"]
        line.g4 = 13.0
        doc.action_check()
        self.assertIn("1695", doc.check_text)
        self.assertIn("1900", doc.check_text)
        with self.assertRaises(UserError):
            doc.action_done()
        line.g4 = 12.0
        doc.action_done()
        self.assertEqual(doc.state, "done")
        with self.assertRaises(UserError):
            doc.action_compute()

    def test_06_xml_needs_details(self):
        doc = self._filing("J0900207", tin=False, director=False)
        with self.assertRaises(UserError):
            doc.action_xml()
        doc.write({"tin": "12345678", "director": "Іваненко І. І."})
        doc.action_xml()
        self.assertTrue(doc.xml_file)
        self.assertTrue(doc.xml_name.endswith(".XML"))
