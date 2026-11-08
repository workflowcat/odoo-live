"""Прайси постачальників на вигаданих файлах з examples/.

Числа:
- «Приклад Кріплення», ціна з ПДВ 20 % за упаковку: болт М10×40 360 грн за 100 шт ->
  300 без ПДВ -> 3,00 за штуку, мінімум 100; гайка 180 за 100 -> 1,50; шайба 250 за 500 ->
  208,33 / 500 = 0,4167; у ціні Odoo два знаки, тому ціна лягає за упаковку «уп. 500 шт».
- Другий прайс того ж постачальника: болт 396 -> 3,30, зміна +10 %.
- «Приклад Метал», без ПДВ: пруток Д16Т ⌀40 350 за кг; профільна труба 40×20×2 Ст3
  140 грн за метр, маса метра (40·20 − 36·16) · 7850 · 10⁻⁶ = 1,7584 кг -> 79,62 за кг.
- ФОП Зразковий, болти на вагу: 100 грн за кг, маса 1000 шт 31 кг -> 3,10 за штуку.
- Ще один постачальник за 1000 шт: 2800 -> 2,80 за штуку. Найдешевший - він.
"""
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_path

BOLT = "Болт М10х40 DIN 933 8.8 оцинк."


@tagged("post_install", "-at_install", "ua_supplier_catalog")
class TestUaSupplierCatalog(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        Partner = cls.env["res.partner"]
        cls.fasteners = Partner.create({"name": "ТОВ «Приклад Кріплення»", "is_company": True,
                                        "email": "price@kriplennya.example"})
        cls.metal = Partner.create({"name": "ТОВ «Приклад Метал»", "is_company": True})
        cls.by_weight = Partner.create({"name": "ФОП Зразковий"})
        cls.by_thousand = Partner.create({"name": "ТОВ «Приклад Опт»", "is_company": True})
        Profile = cls.env["ua.supplier.price.profile"]
        cls.p_fasteners = Profile.create({"partner_id": cls.fasteners.id, "price_vat": "incl",
                                          "price_per": "pack", "delay": 2})
        cls.p_metal = Profile.create({"partner_id": cls.metal.id, "price_vat": "excl"})
        cls.p_weight = Profile.create({"partner_id": cls.by_weight.id, "price_vat": "excl"})
        cls.p_thousand = Profile.create({"partner_id": cls.by_thousand.id, "price_vat": "excl",
                                         "price_per": "thousand"})

    def _product(self, name, uom=None):
        tmpl = self.env["product.template"].create({
            "name": name, "type": "consu", "is_storable": True, "uom_id": (uom or self.unit).id})
        tmpl.action_ua_parse_name()
        return tmpl

    def _import(self, profile, filename=None, text=None, create_missing=False):
        if filename:
            with open(file_path("l10n_ua_supplier_catalog/examples/" + filename), "rb") as fh:
                data = fh.read()
        else:
            data = text.encode("cp1251")
            filename = "price.csv"
        imp = self.env["ua.supplier.price.import"].create({
            "profile_id": profile.id, "file": base64.b64encode(data), "file_name": filename,
            "create_missing": create_missing})
        imp.action_parse()
        return imp

    def _line(self, imp, code_or_name):
        return imp.line_ids.filtered(
            lambda x: x.raw_code == code_or_name or x.raw_name == code_or_name)

    def _info(self, partner, tmpl):
        return self.env["product.supplierinfo"].search(
            [("partner_id", "=", partner.id), ("product_tmpl_id", "=", tmpl.id)])

    def test_01_pack_prices_with_vat_and_new_products(self):
        bolt = self._product(BOLT)
        imp = self._import(self.p_fasteners, "priklad_kriplennya_2026-11.csv", create_missing=True)
        self.assertEqual(imp.count_total, 6)
        line = self._line(imp, "933-10-40-88-ZN")
        self.assertEqual((line.status, line.match, line.product_tmpl_id), ("matched", "key", bolt))
        self.assertAlmostEqual(line.price_unit, 3.0, places=4)
        self.assertEqual((line.min_qty, line.unit_mode), (100.0, "pack"))
        washer = self._line(imp, "125-10-ZN")
        self.assertEqual(washer.status, "new")
        self.assertAlmostEqual(washer.price_base, 250 / 1.2 / 500, places=4)
        kit = self._line(imp, "NAB-01")
        self.assertEqual(kit.status, "unknown")
        self.assertFalse(kit.apply)
        self.assertEqual(imp.count_new, 4)

        imp.action_apply()
        info = self._info(self.fasteners, bolt)
        self.assertEqual(len(info), 1)
        self.assertEqual((info.product_code, info.min_qty, info.delay, info.ua_stock),
                         ("933-10-40-88-ZN", 100.0, 2, 45.0))
        self.assertAlmostEqual(info.price, 3.0, places=4)
        self.assertAlmostEqual(info.ua_price_base, 3.0, places=4)
        nut = self._line(imp, "934-10-ZN").product_tmpl_id
        self.assertEqual((nut.name, nut.ua_component_class_id.code),
                         ("Гайка М10 DIN 934 цинк", "nut_hex"))
        self.assertAlmostEqual(self._info(self.fasteners, nut).price, 1.5, places=4)
        # 0,4167 за шайбу не вміщається в ціну з двома знаками: ціна лягла за упаковку.
        washer_info = self._info(self.fasteners, washer.product_tmpl_id)
        self.assertTrue(washer_info.product_uom_id.name.startswith("уп. 500 "))
        self.assertEqual(washer_info.min_qty, 1.0)
        self.assertAlmostEqual(washer_info.price, 208.33, places=2)
        self.assertAlmostEqual(washer_info.ua_price_base, 0.4167, places=4)
        self.assertFalse(kit.product_tmpl_id)
        self.assertIn("нових товарів 4", imp.summary)

        # Наступний прайс: інша назва, той самий код - ціна оновлюється, зміна видна.
        again = self._import(self.p_fasteners, text=(
            "Артикул;Найменування;Од.;Фасовка;Ціна, грн\n"
            "933-10-40-88-ZN;Болт 933 M10x40 8.8 Zn;уп;100;396,00\n"))
        line = again.line_ids
        self.assertEqual((line.match, line.product_tmpl_id), ("code", bolt))
        self.assertAlmostEqual(line.price_old, 3.0, places=4)
        self.assertAlmostEqual(line.change_pct, 10.0, places=1)
        self.assertEqual(again.count_changed, 1)
        again.action_apply()
        info = self._info(self.fasteners, bolt)
        self.assertEqual(len(info), 1)
        self.assertAlmostEqual(info.price, 3.3, places=4)
        self.assertEqual(info.ua_import_id, again)

    def test_02_metal_by_kg_and_by_metre(self):
        bar = self._product("Пруток Д16Т ф40", uom=self.kg)
        pipe = self._product("Труба профільна 40х20х2 ст3", uom=self.kg)
        pipe.action_ua_units()
        imp = self._import(self.p_metal, "priklad_metal_2026-11.csv")
        bar_line = self._line(imp, "Круг Д16Т ф40")
        self.assertEqual((bar_line.status, bar_line.product_tmpl_id), ("matched", bar))
        self.assertAlmostEqual(bar_line.price_base, 350.0, places=2)
        pipe_line = self._line(imp, "Труба профільна 40х20х2 ст3")
        self.assertEqual((pipe_line.product_tmpl_id, pipe_line.unit_mode), (pipe, "uom"))
        self.assertAlmostEqual(pipe.ua_mass_per_m, 1.7584, places=3)
        self.assertAlmostEqual(pipe_line.price_base, 140 / pipe.ua_mass_per_m, places=2)
        self.assertEqual(self._line(imp, "Круг ст45 ф40").status, "new")
        self.assertFalse(self._line(imp, "Круг ст45 ф40").apply)
        imp.action_apply()
        info = self._info(self.metal, pipe)
        self.assertEqual(info.product_uom_id, pipe_line.uom_id)
        self.assertAlmostEqual(info.ua_price_base, 79.62, places=1)
        self.assertFalse(self.env["product.supplierinfo"].search_count(
            [("partner_id", "=", self.metal.id), ("product_tmpl_id.name", "ilike", "Сталь 45")]))

    def test_03_compare_by_kg_by_piece_by_thousand(self):
        bolt = self._product(BOLT)
        bolt._ua_set_values("bolt_hex", {"mass_1000": 31.0})
        self._import(self.p_fasteners, "priklad_kriplennya_2026-11.csv").action_apply()
        weight = self._import(self.p_weight, "zrazkovyi_vahovi_2026-11.csv")
        line = self._line(weight, "Z-1040")
        self.assertEqual((line.product_tmpl_id, line.unit_mode), (bolt, "kg_pieces"))
        self.assertAlmostEqual(line.price_base, 3.1, places=4)
        # Болта М8 немає в базі, і маси для нього теж: рядок лишається новим.
        self.assertEqual(self._line(weight, "Z-0830").status, "new")
        weight.action_apply()
        info = self._info(self.by_weight, bolt)
        self.assertTrue(info.product_uom_id.name.startswith("кг ("))
        self.assertAlmostEqual(info.price, 100.0, places=2)
        self.assertAlmostEqual(info.ua_price_base, 3.1, places=3)

        thousand = self._import(self.p_thousand, text=(
            "Найменування;Ціна за 1000 шт\nБолт М10х40 DIN 933 8.8 цинк;2800\n"))
        self.assertAlmostEqual(thousand.line_ids.price_base, 2.8, places=4)
        thousand.action_apply()
        bolt.invalidate_recordset()
        self.assertEqual(bolt.ua_supplier_count, 3)
        self.assertEqual(bolt.ua_best_partner_id, self.by_thousand)
        self.assertAlmostEqual(bolt.ua_best_price, 2.8, places=4)
        action = bolt.action_ua_compare_suppliers()
        rows = self.env["product.supplierinfo"].search(action["domain"], order="ua_price_base")
        self.assertEqual(rows.mapped("partner_id").ids,
                         [self.by_thousand.id, self.fasteners.id, self.by_weight.id])

    def test_04_where_to_find(self):
        bolt_class = self.env["ua.component.class"].search([("code", "=", "bolt_hex")])
        bolt = self._product(BOLT)
        self._import(self.p_fasteners, "priklad_kriplennya_2026-11.csv").action_apply()
        action = bolt_class.action_ua_find_suppliers()
        wizard = self.env["ua.supplier.find"].browse(action["res_id"])
        self.assertIn("cpv=44531400-5", wizard.links_html)
        self.assertIn("search_term=", wizard.links_html)
        self.assertIn("dinmark", wizard.links_html)
        self.assertIn("Приклад Кріплення", wizard.known_html)
        # Для прокату продавець кріплення не показується.
        bar_class = self.env["ua.component.class"].search([("code", "=", "bar_round")])
        wizard = self.env["ua.supplier.find"].browse(
            bar_class.action_ua_find_suppliers()["res_id"])
        self.assertNotIn("dinmark", wizard.links_html or "")
        product_wizard = self.env["ua.supplier.find"].browse(
            bolt.action_ua_find_suppliers()["res_id"])
        self.assertEqual(product_wizard.query, bolt.ua_component_name)
        suppliers = bolt_class.action_ua_suppliers()
        self.assertTrue(self.env["product.supplierinfo"].search_count(suppliers["domain"]))

    def test_05_bad_files(self):
        with self.assertRaises(UserError):
            self._import(self.p_metal, text="Код;Ціна\n1;2\n")
        imp = self._import(self.p_metal, text="Найменування;Ціна\nКруг Д16Т ф40;\n")
        self.assertEqual(imp.line_ids.status, "error")
        with self.assertRaises(UserError):
            self.env["ua.supplier.price.import"].create(
                {"profile_id": self.p_metal.id}).action_apply()
