"""Класифікатор комплектуючих: розбір назв, шаблони, дублі, аналоги, маса прокату, розбір 1С.

Числа маси рахуються з густини марки в класифікаторі:
- пруток Д16Т ⌀40: переріз π·40²/4 = 1256,64 мм², густина 2780 кг/м³,
  1256,64 · 2780 · 10⁻⁶ = 3,4935 кг/м; 2 м = 6,987 кг;
- лист 09Г2С 10 мм: 10 · 7850 / 1000 = 78,5 кг/м²; лист 1500×6000 - 9 м² = 706,5 кг;
- болт з масою 1000 шт 31 кг: 1 кг = 1000 / 31 = 32,258 шт.
"""
import base64

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_path

BOLT_DIN = "Болт М10х40 DIN 933 8.8 оцинк."
BOLT_DIN_MESSY = "болт оцинк. M10*40 кл.8,8 DIN933"
BOLT_ISO_109 = "Болт ISO 4017 M10x40 10.9 цинк"
BOLT_ISO_M8 = "Болт ISO 4017 M8x40 8.8 цинк"


@tagged("post_install", "-at_install", "ua_component")
class TestUaComponent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]
        cls.Class = cls.env["ua.component.class"]
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.categ = cls.env["product.category"].create({"name": "Тест комплектуючих"})

    def _product(self, name, uom=None, parse=True, **vals):
        values = {"name": name, "type": "consu", "is_storable": True,
                  "uom_id": (uom or self.unit).id, "categ_id": self.categ.id}
        values.update(vals)
        tmpl = self.Tmpl.create(values)
        if parse:
            tmpl.action_ua_parse_name()
        return tmpl

    # ------------------------------------------------------------ класифікатор
    def test_01_classifier_loaded_and_reload_keeps_user_records(self):
        bolt = self.Class.search([("code", "=", "bolt_hex")])
        self.assertEqual(len(bolt), 1)
        self.assertTrue(bolt.from_file)
        self.assertEqual(bolt.parent_id.code, "fastener")
        self.assertEqual(bolt._ua_inherited("prefix"), "BLT")
        self.assertEqual(bolt._ua_inherited("uom_id"), self.unit)
        self.assertEqual(self.Class.search([("code", "=", "bar_round")])._ua_inherited("uom_id"),
                         self.kg)
        self.assertGreaterEqual(self.Class.search_count([]), 50)
        self.assertGreaterEqual(self.env["ua.component.equivalence"].search_count([]), 40)
        standard = self.env["ua.component.attribute"].search([("code", "=", "standard")])
        din933 = standard.choice_ids.filtered(lambda c: c.code == "din933")
        self.assertEqual(din933.spanner, "din")

        # Своя марка лишається, зіпсована базова відновлюється з файла.
        material = self.env["ua.component.attribute"].search([("code", "=", "material")])
        own = self.env["ua.component.choice"].create({
            "attribute_id": material.id, "code": "own_alloy", "name": "Сплав заводу",
            "density": 2700.0})
        d16t = material.choice_ids.filtered(lambda c: c.code == "d16t")
        d16t.density = 1.0
        counts = {m: self.env[m].search_count([]) for m in (
            "ua.component.attribute", "ua.component.choice", "ua.component.class",
            "ua.component.class.line", "ua.component.equivalence")}
        self.Class._ua_load_classifier()
        for model, count in counts.items():
            self.assertEqual(self.env[model].search_count([]), count, model)
        self.assertEqual(d16t.density, 2780.0)
        self.assertTrue(own.exists())

    def test_02_parse_name_template_and_code(self):
        bolt = self._product(BOLT_DIN)
        self.assertEqual(bolt.ua_component_class_id.code, "bolt_hex")
        values = bolt._ua_values()
        self.assertEqual((values["thread"], values["length"], values["standard"],
                          values["grade"], values["coating"]),
                         ("m10", 40.0, "din933", "g88", "zn"))
        self.assertEqual(values["pitch"], 1.5)
        self.assertEqual(bolt.ua_component_name, "Болт М10×40 DIN 933 8.8 цинк")
        self.assertEqual(bolt.ua_component_code, "BLT-DIN933-M10x40-88-ZN")
        self.assertFalse(bolt.ua_component_missing)
        self.assertEqual(bolt.ua_dk021_id.code, "44531400-5")
        bolt.action_ua_apply_template()
        self.assertEqual(bolt.name, "Болт М10×40 DIN 933 8.8 цинк")
        self.assertEqual(bolt.default_code, "BLT-DIN933-M10x40-88-ZN")

        # Без класу міцності виріб не повний: поле «Бракує» не порожнє лише для обов'язкових.
        bare = self._product("Болт М12х50")
        self.assertEqual(bare.ua_component_class_id.code, "bolt_hex")
        self.assertIn("Стандарт", bare.ua_component_missing or "")

        bearing = self._product("Підшипник 180204")
        self.assertEqual(bearing.ua_component_code, "BRB-6204-2RS")

    def test_03_duplicates_by_fingerprint(self):
        a = self._product(BOLT_DIN)
        b = self._product(BOLT_DIN_MESSY)
        c = self._product(BOLT_ISO_M8)
        self.assertEqual(a.ua_component_key, b.ua_component_key)
        self.assertNotEqual(a.ua_component_key, c.ua_component_key)
        self.assertEqual((a.ua_duplicate_count, b.ua_duplicate_count, c.ua_duplicate_count),
                         (1, 1, 0))
        action = a.action_ua_duplicates()
        self.assertEqual(set(self.Tmpl.search(action["domain"]).ids), {a.id, b.id})

    # ------------------------------------------------------------ аналоги
    def test_04_analogs_by_rules(self):
        din = self._product(BOLT_DIN)
        dup = self._product(BOLT_DIN_MESSY)
        iso = self._product(BOLT_ISO_109)
        m8 = self._product(BOLT_ISO_M8)
        rows = {r["analog_tmpl_id"]: r for r in din._ua_find_analogs()}
        self.assertNotIn(m8.id, rows)
        self.assertEqual(rows[dup.id]["level"], "full")
        self.assertIn("дубль", rows[dup.id]["reason"])
        self.assertEqual(rows[iso.id]["level"], "check")
        self.assertIn("ISO 4017 - заміна DIN 933", rows[iso.id]["reason"])
        self.assertIn("10.9 замість 8.8", rows[iso.id]["reason"])
        self.assertIn("17 → 16", rows[iso.id]["reason"])
        # Повна заміна йде першою.
        self.assertEqual(din._ua_find_analogs()[0]["analog_tmpl_id"], dup.id)
        # 8.8 не замінює 10.9.
        self.assertNotIn(din.id, [r["analog_tmpl_id"] for r in iso._ua_find_analogs()])
        only_full = din._ua_find_analogs(include_check=False)
        self.assertEqual([r["analog_tmpl_id"] for r in only_full], [dup.id])

    def test_05_finder_saves_analogs(self):
        din = self._product(BOLT_DIN)
        dup = self._product(BOLT_DIN_MESSY)
        iso = self._product(BOLT_ISO_109)
        action = din.action_ua_analogs()
        finder = self.env["ua.component.analog.finder"].browse(action["res_id"])
        by_tmpl = {line.analog_tmpl_id: line for line in finder.line_ids}
        # Збереження перебудовує список, тому обидва рядки зберігаються одним викликом.
        (by_tmpl[dup] | by_tmpl[iso]).action_save()
        self.assertTrue(all(finder.line_ids.filtered(
            lambda x: x.analog_tmpl_id in (dup | iso)).mapped("saved")))
        Analog = self.env["ua.component.analog"]
        self.assertEqual(Analog.search_count([("product_tmpl_id", "=", din.id)]), 2)
        # Повна заміна записується в обидва боки, заміна з перевіркою - лише в один.
        self.assertEqual(Analog.search_count([("product_tmpl_id", "=", dup.id),
                                              ("analog_tmpl_id", "=", din.id)]), 1)
        self.assertEqual(Analog.search_count([("product_tmpl_id", "=", iso.id)]), 0)
        saved = din.ua_analog_ids.filtered(lambda a: a.analog_tmpl_id == iso)
        self.assertEqual((saved.level, saved.source), ("check", "rule"))
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                Analog.create({"product_tmpl_id": din.id, "analog_tmpl_id": din.id})
        # Записаний вручну аналог іншого виду теж показується.
        nut = self._product("Гайка М10 DIN 934 цинк")
        din.ua_analog_ids = [Command.create({"analog_tmpl_id": nut.id, "level": "check",
                                             "note": "лист конструктора"})]
        self.assertIn(nut.id, [r["analog_tmpl_id"] for r in din._ua_find_analogs()])

    # ------------------------------------------------------------ маса і одиниці
    def test_06_bar_mass_and_units(self):
        bar = self._product("Пруток Д16Т ф40", uom=self.kg)
        self.assertEqual(bar.ua_component_class_id.code, "bar_round")
        self.assertAlmostEqual(bar.ua_mass_per_m, 3.4935, places=3)
        self.assertEqual(bar.ua_component_name, "Пруток Д16Т ⌀40")
        bar.action_ua_units()
        metre = bar.uom_ids.filtered(lambda u: u.name.startswith("м ("))
        self.assertEqual(len(metre), 1)
        self.assertEqual(metre.relative_uom_id, self.kg)
        self.assertAlmostEqual(metre._compute_quantity(2.0, self.kg, round=False), 6.987, places=2)
        # Повторний виклик не плодить одиниць.
        bar.action_ua_units()
        self.assertEqual(len(bar.uom_ids.filtered(lambda u: u.name.startswith("м ("))), 1)

    def test_07_sheet_mass_and_units(self):
        sheet = self._product("Лист 09Г2С 10х1500х6000", uom=self.kg)
        self.assertEqual(sheet.ua_component_class_id.code, "sheet")
        self.assertAlmostEqual(sheet.ua_mass_per_m2, 78.5, places=2)
        self.assertAlmostEqual(sheet.ua_piece_mass, 706.5, places=1)
        sheet.action_ua_units()
        leaf = sheet.uom_ids.filtered(lambda u: u.name.startswith("лист"))
        self.assertAlmostEqual(leaf._compute_quantity(1.0, self.kg, round=False), 706.5, places=1)

    def test_08_fastener_units_from_mass_1000(self):
        bolt = self._product(BOLT_DIN)
        with self.assertRaises(UserError):
            bolt.action_ua_units()
        bolt._ua_set_values("bolt_hex", {"mass_1000": 31.0})
        self.assertAlmostEqual(bolt.ua_piece_mass, 0.031, places=4)
        bolt.action_ua_units()
        kg_of_bolts = bolt.uom_ids.filtered(lambda u: u.name.startswith("кг"))
        self.assertAlmostEqual(kg_of_bolts._compute_quantity(1.0, self.unit, round=False),
                               32.258, places=2)
        # Маса 1000 шт не входить у відбиток: дубль лишається дублем.
        twin = self._product(BOLT_DIN_MESSY)
        self.assertEqual(bolt.ua_component_key, twin.ua_component_key)

    # ------------------------------------------------------------ розбір номенклатури
    def _csv(self, rows, encoding="cp1251"):
        text = "\r\n".join(";".join(r) for r in rows)
        return base64.b64encode(text.encode(encoding))

    def test_09_intake_from_1c_file(self):
        existing = self._product("Болт M12x50 DIN 933 8.8 цинк")
        data = self._csv([
            ("Номенклатура за 2026-11-01", "", ""),
            ("Код", "Найменування", "Од."),
            ("00-001", BOLT_DIN, "шт"),
            ("00-002", BOLT_DIN_MESSY, "шт"),
            ("00-003", "Пруток Д16Т ф40", "кг"),
            ("00-004", "Товар без зрозумілої назви", "шт"),
            ("00-005", "болт М12*50 DIN933 кл.8,8 оц", "шт"),
        ])
        intake = self.env["ua.component.intake"].create({
            "source": "file", "file": data, "file_name": "nomenclature.csv"})
        intake.action_parse()
        lines = intake.line_ids.sorted("sequence")
        self.assertEqual(lines.mapped("raw_code"), ["00-001", "00-002", "00-003", "00-004", "00-005"])
        self.assertEqual(lines.mapped("status"), ["ok", "duplicate", "ok", "unknown", "exists"])
        self.assertEqual(lines[4].duplicate_of_id, existing)
        self.assertEqual((intake.count_total, intake.count_ok, intake.count_unknown,
                          intake.count_duplicate), (5, 2, 1, 2))
        self.assertFalse(lines[3].apply)

        intake.action_apply()
        self.assertEqual(intake.state, "applied")
        bolt = lines[0].product_tmpl_id
        self.assertEqual((bolt.name, bolt.default_code, bolt.ua_component_class_id.code),
                         (BOLT_DIN, "00-001", "bolt_hex"))
        self.assertEqual(lines[1].product_tmpl_id, bolt)
        bar = lines[2].product_tmpl_id
        self.assertEqual(bar.uom_id, self.kg)
        self.assertEqual(bar.tracking, "lot")
        self.assertEqual(lines[4].product_tmpl_id, existing)
        self.assertFalse(lines[3].product_tmpl_id)
        self.assertIn("Створено 2", intake.summary)
        with self.assertRaises(UserError):
            intake.action_apply()

    def test_10_intake_from_products_archives_duplicates(self):
        main = self._product(BOLT_DIN, parse=False)
        twin = self._product(BOLT_DIN_MESSY, parse=False)
        nut = self._product("Гайка М10 DIN 934 цинк", parse=False)
        intake = self.env["ua.component.intake"].create({
            "source": "products", "categ_id": self.categ.id, "rename": True,
            "archive_duplicates": True})
        intake.action_parse()
        self.assertEqual(len(intake.line_ids), 3)
        twin_line = intake.line_ids.filtered(lambda x: x.product_tmpl_id == twin)
        self.assertEqual(twin_line.status, "duplicate")
        intake.action_apply()
        self.assertEqual(main.name, "Болт М10×40 DIN 933 8.8 цинк")
        self.assertEqual(main.default_code, "BLT-DIN933-M10x40-88-ZN")
        self.assertFalse(twin.active)
        self.assertIn("архівовано", twin_line.result)
        self.assertEqual(nut.ua_component_class_id.code, "nut_hex")
        # Повторний розбір класифікованих не бере.
        again = self.env["ua.component.intake"].create({
            "source": "products", "categ_id": self.categ.id})
        again.action_parse()
        self.assertFalse(again.line_ids)

    # ------------------------------------------------------------ приклад прийому і пакети
    def test_11_intake_example_from_1c(self):
        """intake_example/nomenclature_1c.csv: 105 рядків вигаданої компанії, cp1251.

        58 різних виробів, 39 рядків - ті самі вироби під іншими назвами, 5 рядків без
        обов'язкової характеристики («Пруток ф40» без марки), 8 рядків - не комплектуючі
        (папір, послуги, рукавиці). Різні стандарти (DIN 933 і ГОСТ 7798) - не дублі, а аналоги.
        """
        with open(file_path("l10n_ua_component/intake_example/nomenclature_1c.csv"), "rb") as fh:
            data = base64.b64encode(fh.read())
        intake = self.env["ua.component.intake"].create({
            "source": "file", "file": data, "file_name": "nomenclature_1c.csv"})
        intake.action_parse()
        self.assertEqual((intake.count_total, intake.count_ok, intake.count_partial,
                          intake.count_unknown, intake.count_duplicate), (105, 53, 5, 8, 39))
        intake.action_apply()
        self.assertIn("Створено 53", intake.summary)
        din = self.Tmpl.search([("ua_component_key", "=",
                                 "bolt_hex|coating=zn|grade=g88|length=30|pitch=1.25|"
                                 "standard=din933|thread=m8")])
        gost = self.Tmpl.search([("ua_component_key", "=",
                                  "bolt_hex|coating=zn|grade=g88|length=30|pitch=1.25|"
                                  "standard=gost7798|thread=m8")])
        self.assertEqual((len(din), len(gost)), (1, 1))
        rows = {r["analog_tmpl_id"]: r for r in din._ua_find_analogs()}
        self.assertEqual(rows[gost.id]["level"], "check")
        # Три написання болта М8×30 DIN 933 - один товар; ГОСТ 7798 - окремий, це аналог.
        lines = intake.line_ids.filtered(lambda x: x.key == din.ua_component_key)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines.product_tmpl_id, din)

    def test_12_component_packs(self):
        Catalog = self.env["ua.catalog"]
        packs = Catalog._ua_packs()
        for pack in ("components_fasteners", "components_metals", "components_tools",
                     "components_uav"):
            self.assertEqual(packs[pack]["module"], "l10n_ua_component")
            self.assertEqual(packs[pack]["missing"], [], pack)
        company = self.env.company
        stats = Catalog._ua_load_pack("components_fasteners", company)
        self.assertEqual(stats["products"].get("created"), 51, stats)
        bolt = self.Tmpl.search([("default_code", "=", "BLT-DIN933-M8x30-88-ZN")])
        self.assertEqual((bolt.name, bolt.ua_component_class_id.code),
                         ("Болт М8×30 DIN 933 8.8 цинк", "bolt_hex"))
        self.assertEqual(bolt.ua_dk021_id.code, "44531400-5")
        again = Catalog._ua_load_pack("components_fasteners", company)
        self.assertNotIn("created", again["products"], again)
        Catalog._ua_load_pack("components_metals", company)
        bar = self.Tmpl.search([("default_code", "=", "MRD-D16T-40")])
        self.assertEqual((bar.uom_id, bar.tracking), (self.kg, "lot"))
        self.assertAlmostEqual(bar.ua_mass_per_m, 3.4935, places=3)
        Catalog._ua_load_pack("components_tools", company)
        caliper = self.Tmpl.search([("ua_component_class_id.code", "=", "caliper")], limit=1)
        self.assertEqual(caliper.tracking, "serial")
        Catalog._ua_load_pack("components_uav", company)
        wire = self.Tmpl.search([("default_code", "=", "WSI-14awg")])
        self.assertEqual(wire.uom_id, self.env.ref("uom.product_uom_meter"))
