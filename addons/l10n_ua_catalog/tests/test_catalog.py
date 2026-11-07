"""Галузеві пакети: завантаження, повтор, друга компанія, оновлення, калькуляція.

Пакет оборонки перевіряємо до копійки через калькуляцію за постановою № 309: так
видно, що норми, ціни і ставки з JSON справді доходять до ціни виробу.

Квадрокоптер (рама власного виробництва розкладається на карбон і операцію ЧПК):
  01 матеріали: карбон 0,08 м2 * 6500 = 520; провід 0,6 * 45 = 27;
     термоусадка 0,3 * 12 = 3,6; припій 0,02 * 1800 = 36. Разом 586,60.
  02 покупні: двигуни 4 * 1150 = 4600; регулятор 2100; контролер 2400; відео 1900;
     камера 1100; тепловізор 38000; приймач 650; GNSS 900; пропелери 4 * 90 = 360;
     антена 250; метизи 180. Разом 52440,00.
  10 відходи: обрізки 0,05 кг * 150 = 7,50.
  Години: ЧПК 25 хв, монтаж 50, складання 40, налаштування 30, ВТК 20, політ 25 -
  190 хв = 3,1667 год.
  04 зарплата: 25/60*260 + 50/60*260 + 40/60*240 + 30/60*300 + 20/60*280 + 25/60*300
     = 108,33 + 216,67 + 160 + 150 + 93,33 + 125 = 853,33.
  03 енергія: 25/60*45 + 50/60*20 + 40/60*8 + 30/60*4 + 20/60*3 + 25/60*25 = 54,17.
  07 утримання обладнання: 25/60*220 + 50/60*180 + 40/60*120 + 30/60*60 + 20/60*50
     + 25/60*150 = 430,83.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_ua_catalog.models.catalog import read_pack

CENT = 0.01
PACKS = {"defense_uav", "defense_ugv", "defense_apparel", "defense_machining",
         "procurement", "small_shop"}


@tagged("post_install", "-at_install", "ua_catalog")
class TestUaCatalog(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Catalog = cls.env["ua.catalog"]
        cls.packs = cls.Catalog._ua_packs()

    def _rec(self, pack, key, company=None, shared=False):
        if shared:
            return self.env.ref("ua_catalog.%s__%s" % (pack, key))
        company = company or self.company
        return self.env.ref("ua_catalog.%s__c%d__%s" % (pack, company.id, key))

    def _data(self, pack):
        return read_pack(self.packs[pack]["path"])

    def test_01_packs_found_and_installable(self):
        self.assertTrue(PACKS <= set(self.packs), sorted(self.packs))
        for pack_id in PACKS:
            self.assertEqual(self.packs[pack_id]["missing"], [], pack_id)
            self.assertEqual(self.packs[pack_id]["module"], "l10n_ua_catalog")

    def test_02_defense_uav_loads_everything(self):
        data = self._data("defense_uav")
        stats = self.Catalog._ua_load_pack("defense_uav", self.company)
        self.assertEqual(stats["products"].get("created"), len(data["products"]), stats)
        self.assertEqual(stats["workcenters"].get("created"), 6, stats)
        self.assertEqual(stats["boms"].get("created"), 5, stats)
        self.assertFalse(stats.get("skipped_fields"), stats.get("skipped_fields"))

        quad = self._rec("defense_uav", "f_quad")
        self.assertEqual(quad.company_id, self.company)
        self.assertEqual(quad.tracking, "serial")
        self.assertEqual(quad.ua_uktzed, "8806220000")
        self.assertEqual(quad.ua_dk021_id.code, "35613000-4")
        self.assertEqual(quad.ua_warranty_months, 12)
        self.assertEqual(quad.categ_id.complete_name, "Оборонне виробництво / Готові вироби")

        bom = self._rec("defense_uav", "b_quad")
        self.assertEqual(len(bom.bom_line_ids), 15)
        self.assertEqual(bom.operation_ids.mapped("time_cycle_manual"), [50, 40, 30, 20, 25])
        self.assertIn("Відмова зв'язку", bom.operation_ids[2].ua_checks)
        frame_bom = self._rec("defense_uav", "b_frame")
        self.assertEqual(frame_bom.byproduct_ids.product_id.product_tmpl_id,
                         self._rec("defense_uav", "w_carbon"))
        self.assertEqual(self._rec("defense_uav", "b_zip").type, "phantom")

        carbon = self._rec("defense_uav", "m_carbon")
        self.assertEqual(carbon.uom_id, self.env.ref("uom.product_uom_square_meter"))
        self.assertEqual(carbon.with_company(self.company).standard_price, 6500)
        self.assertEqual(self._rec("defense_uav", "c_motor").ua_cost_item, "02")
        kit = self._rec("defense_uav", "u_kit", shared=True)
        self.assertEqual((kit.ua_kspovo_code, kit.ua_kspovo_short), ("2938", "компл"))
        self.assertEqual(self._rec("defense_uav", "f_zip").uom_id, kit)
        assembly = self._rec("defense_uav", "wc_asm")
        self.assertEqual((assembly.costs_hour, assembly.ua_wage_hour, assembly.ua_energy_hour),
                         (120, 240, 8))
        self.assertIn(self.env.ref("stock.group_production_lot"),
                      self.env.ref("base.group_user").implied_ids)

    def test_03_second_load_changes_nothing(self):
        self.Catalog._ua_load_pack("defense_uav", self.company)
        count = self.env["product.template"].search_count([("company_id", "=", self.company.id)])
        stats = self.Catalog._ua_load_pack("defense_uav", self.company)
        for section, actions in stats.items():
            if isinstance(actions, dict):
                self.assertNotIn("created", actions, section)
        self.assertEqual(count, self.env["product.template"].search_count(
            [("company_id", "=", self.company.id)]))

    def test_04_plan_calculation_from_pack(self):
        self.Catalog._ua_load_pack("defense_uav", self.company)
        customer = self.env["res.partner"].create({"name": "Державний замовник", "is_company": True})
        contract = self.env["ua.contract"].create({
            "name": "ОК-7/2026",
            "date": date(2026, 4, 1),
            "partner_id": customer.id,
            "ua_defense": True,
            "ua_customer_kind": "dot",
            "ua_rate_additional_wage": 10.0,
            "ua_rate_esv": 22.0,
            "ua_rate_overhead": 150.0,
            "ua_rate_profit_purchased": 1.0,
            "ua_rate_profit_own": 20.0,
            "ua_vat_rate": 20.0,
        })
        quad = self._rec("defense_uav", "f_quad")
        calculation = self.env["ua.defense.calculation"].create({
            "contract_id": contract.id, "product_id": quad.product_variant_id.id, "kind": "plan"})
        self.assertEqual(calculation.bom_id, self._rec("defense_uav", "b_quad"))
        calculation.action_compute()
        a = {line.code: line.amount for line in calculation.line_ids}
        expected = {"01": 586.6, "02": 52440.0, "10": 7.5, "04": 853.33, "03": 54.17,
                    "07": 430.83}
        for code, value in expected.items():
            self.assertAlmostEqual(a[code], value, delta=CENT, msg="стаття %s" % code)
        self.assertAlmostEqual(calculation.hours, 190 / 60, delta=0.0001)
        direct = sum(a["%02d" % n] for n in range(1, 10)) - a["10"]
        self.assertAlmostEqual(a["11"], direct, delta=CENT)

    def test_05_second_company_gets_its_own_copy(self):
        self.Catalog._ua_load_pack("defense_uav", self.company)
        other = self.env["res.company"].create({"name": "Друга компанія"})
        stats = self.Catalog._ua_load_pack("defense_uav", other)
        self.assertEqual(stats["products"].get("created"), len(self._data("defense_uav")["products"]))
        self.assertEqual(stats["categories"], {"kept": 7})
        quad_1 = self._rec("defense_uav", "f_quad")
        quad_2 = self._rec("defense_uav", "f_quad", company=other)
        self.assertNotEqual(quad_1, quad_2)
        self.assertEqual(quad_2.company_id, other)
        self.assertEqual(quad_1.categ_id, quad_2.categ_id)
        self.assertEqual(self._rec("defense_uav", "b_quad", company=other).company_id, other)

    def test_06_update_mode_restores_values_not_structure(self):
        self.Catalog._ua_load_pack("defense_uav", self.company)
        quad = self._rec("defense_uav", "f_quad")
        bom = self._rec("defense_uav", "b_quad")
        quad.list_price = 1.0
        bom.bom_line_ids[-1].unlink()
        stats = self.Catalog._ua_load_pack("defense_uav", self.company, mode="update")
        self.assertEqual(quad.list_price, 98000)
        self.assertEqual(len(bom.bom_line_ids), 14, "склад специфікації не перебудовується")
        self.assertEqual(stats["boms"], {"updated": 5})

    def test_07_existing_product_is_picked_up(self):
        own = self.env["product.template"].create({
            "name": "Двигун зі старого довідника", "default_code": "CMP-001",
            "company_id": self.company.id})
        stats = self.Catalog._ua_load_pack("defense_uav", self.company)
        self.assertEqual(stats["products"].get("matched"), 1)
        self.assertEqual(self._rec("defense_uav", "c_motor"), own)
        self.assertEqual(self.env["product.template"].search_count(
            [("default_code", "=", "CMP-001"), ("company_id", "=", self.company.id)]), 1)

    def test_08_every_pack_loads_and_reloads(self):
        for pack_id in sorted(PACKS):
            first = self.Catalog._ua_load_pack(pack_id, self.company)
            self.assertTrue(first.get("products"), pack_id)
            second = self.Catalog._ua_load_pack(pack_id, self.company)
            for section, actions in second.items():
                if isinstance(actions, dict):
                    self.assertNotIn("created", actions, "%s: %s" % (pack_id, section))
        # Спільні позиції пакетів БпЛА і НРК - один товар, а не два.
        self.assertEqual(self._rec("defense_uav", "m_wire"), self._rec("defense_ugv", "m_wire"))
        self.assertEqual(self._rec("defense_uav", "wc_asm"), self._rec("defense_ugv", "wc_asm"))
        sugar = self._rec("small_shop", "sugar")
        self.assertEqual(sugar.barcode, "2000000010014")
        month = self._rec("procurement", "u_month", shared=True)
        self.assertEqual(month.ua_kspovo_code, "0171")
        self.assertEqual(self._rec("procurement", "guard").uom_id, month)

    def test_09_wizard(self):
        wizard = self.env["ua.catalog.load"].create({"pack": "small_shop"})
        self.assertIn("Товари і послуги: 21", wizard.info)
        self.assertIn("Джерела:", wizard.info)
        action = wizard.action_load()
        self.assertEqual(action["res_id"], wizard.id)
        self.assertEqual(wizard.state, "done")
        self.assertIn("Товари і послуги: створено 21", wizard.result)

    def test_10_unknown_pack(self):
        with self.assertRaises(UserError):
            self.Catalog._ua_load_pack("no_such_pack", self.company)
