"""Оборонний контракт: калькуляція за статтями постанови № 309, графік, акт, паспорт.

Числа пораховані вручну. Нормативи контракту: додаткова зарплата 10% від 04, ЄСВ 22%,
загальновиробничі 150% від 04, адміністративні 50% від 04, прибуток 1% на покупні і
20% на власні витрати, ПДВ 20%.

Планова калькуляція квадрокоптера (на 1 виріб):
  Рама в зборі (власна специфікація): карбон 2 x 400 = 800 (01); операція 30 хв на
  центрі «Складання» (зарплата 200/год, енергія 20/год, обладнання 100/год):
  04 = 0,5 x 200 = 100, 03 = 0,5 x 20 = 10, 07 = 0,5 x 100 = 50; обрізки карбону
  0,2 кг x 50 = 10 (10).
  Квадрокоптер: рама 1, камера 6 000 (02), польотний контролер 3 000 (02), мотор
  4 x 800 = 3 200 (02); операція 90 хв: 04 = 300, 03 = 30, 07 = 150.
  01 = 800; 02 = 12 200; 03 = 40; 04 = 400; 07 = 200; 10 = 10; години 2,0.
  05 = 400 x 10% = 40; 06 = (400 + 40) x 22% = 96,80; 08 = 400 x 150% = 600; 09 = 0.
  11 = 800 + 12 200 + 40 + 400 + 40 + 96,80 + 200 + 600 - 10 = 14 366,80.
  12 = 400 x 50% = 200; 13 = 14 = 15 = 0; 16 = 14 566,80.
  17 = 12 200 x 1% + (14 566,80 - 12 200) x 20% = 122 + 473,36 = 595,36.
  18 = 15 162,16; 19 = 3 032,43; 20 = 18 194,59.

Фактична калькуляція наземної станції (специфікація без операцій): планшет 6 000 (02),
корпус 2 x 400 (01); випущено 2. На виріб: 01 = 800, 02 = 6 000; 04 = 0, тож 05-09 і
адміністративні нуль; 11 = 16 = 6 800; 17 = 60 + 160 = 220; 18 = 7 020; 19 = 1 404;
20 = 8 424.
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

CENT = 0.005


@tagged("post_install", "-at_install", "ua_defense")
class TestUaDefense(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        categ = cls.env["product.category"].with_company(cls.company)
        cls.categ_raw = categ.search([("name", "=", "Сировина і матеріали")], limit=1)
        cls.categ_finished = categ.search([("name", "=", "Готова продукція")], limit=1)

        cls.customer = cls.env["res.partner"].create({"name": "Державний замовник", "is_company": True})
        cls.contract = cls.env["ua.contract"].create({
            "name": "ОК-12/2026",
            "date": date(2026, 3, 2),
            "partner_id": cls.customer.id,
            "ua_defense": True,
            "ua_customer_kind": "dot",
            "ua_procurement_ref": "UA-2026-03-02-000123-a",
            "ua_rate_additional_wage": 10.0,
            "ua_rate_esv": 22.0,
            "ua_rate_overhead": 150.0,
            "ua_rate_admin": 50.0,
            "ua_rate_profit_purchased": 1.0,
            "ua_rate_profit_own": 20.0,
            "ua_vat_rate": 20.0,
        })

        cls.assembly = cls.env["mrp.workcenter"].create({
            "name": "Складання", "costs_hour": 100.0, "ua_wage_hour": 200.0, "ua_energy_hour": 20.0,
        })
        unit = cls.env.ref("uom.product_uom_unit")
        kg = cls.env.ref("uom.product_uom_kgm")
        cls.carbon = cls._product("Карбонова пластина", 400.0, "01")
        cls.scrap = cls._product("Обрізки карбону", 50.0, "01", uom=kg)
        cls.camera = cls._product("Камера денна", 6000.0, "02")
        cls.controller = cls._product("Польотний контролер", 3000.0, "02")
        cls.motor = cls._product("Мотор безколекторний", 800.0, "02")
        cls.frame = cls._product("Рама в зборі", 0.0, "01")
        cls.drone = cls._product("Квадрокоптер розвідувальний з камерою", 0.0, "01",
                                 categ=cls.categ_finished, tracking="serial")
        cls.tablet = cls._product("Планшет захищений", 6000.0, "02")
        cls.case = cls._product("Корпус", 400.0, "01")
        cls.station = cls._product("Наземна станція керування", 0.0, "01", categ=cls.categ_finished)

        frame_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.frame.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "bom_line_ids": [(0, 0, {"product_id": cls.carbon.id, "product_qty": 2.0})],
            "byproduct_ids": [(0, 0, {"product_id": cls.scrap.id, "product_qty": 0.2,
                                      "product_uom_id": kg.id})],
        })
        cls.env["mrp.routing.workcenter"].create({
            "name": "Збирання рами", "workcenter_id": cls.assembly.id,
            "time_cycle_manual": 30.0, "bom_id": frame_bom.id,
        })
        cls.drone_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "bom_line_ids": [
                (0, 0, {"product_id": cls.frame.id, "product_qty": 1.0, "product_uom_id": unit.id}),
                (0, 0, {"product_id": cls.camera.id, "product_qty": 1.0}),
                (0, 0, {"product_id": cls.controller.id, "product_qty": 1.0}),
                (0, 0, {"product_id": cls.motor.id, "product_qty": 4.0}),
            ],
        })
        cls.env["mrp.routing.workcenter"].create({
            "name": "Загальне складання", "workcenter_id": cls.assembly.id,
            "time_cycle_manual": 90.0, "bom_id": cls.drone_bom.id,
        })
        cls.station_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.station.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "bom_line_ids": [
                (0, 0, {"product_id": cls.tablet.id, "product_qty": 1.0}),
                (0, 0, {"product_id": cls.case.id, "product_qty": 2.0}),
            ],
        })

    @classmethod
    def _product(cls, name, price, item, uom=None, categ=None, tracking="none"):
        vals = {
            "name": name,
            "type": "consu",
            "is_storable": True,
            "categ_id": (categ or cls.categ_raw).id,
            "standard_price": price,
            "ua_cost_item": item,
            "tracking": tracking,
        }
        if uom:
            vals["uom_id"] = uom.id
        return cls.env["product.product"].create(vals)

    def _receive(self, product, quantity):
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": product.id,
            "location_id": self.stock_location.id,
            "inventory_quantity": quantity,
        })
        quant.action_apply_inventory()

    def _amounts(self, calculation):
        return {line.code: line.amount for line in calculation.line_ids}

    # ------------------------------------------------------------------
    # Контракт
    # ------------------------------------------------------------------
    def test_01_defense_contract_keeps_separate_accounting(self):
        self.assertEqual(self.contract.kind, "sale")
        self.assertTrue(self.contract.separate_accounting)
        self.assertTrue(self.contract.analytic_account_id)
        with self.assertRaises(ValidationError):
            self.contract.kind = "purchase"
        with self.assertRaises(ValidationError):
            self.contract.separate_accounting = False

    # ------------------------------------------------------------------
    # Калькуляція
    # ------------------------------------------------------------------
    def test_10_plan_calculation_by_resolution_309_items(self):
        calculation = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.drone.id, "kind": "plan",
        })
        self.assertEqual(calculation.bom_id, self.drone_bom)
        calculation.action_compute()
        a = self._amounts(calculation)
        self.assertEqual(sorted(a), ["%02d" % n for n in range(1, 21)])
        expected = {
            "01": 800.0, "02": 12200.0, "03": 40.0, "04": 400.0, "05": 40.0, "06": 96.8,
            "07": 200.0, "08": 600.0, "09": 0.0, "10": 10.0, "11": 14366.8, "12": 200.0,
            "13": 0.0, "14": 0.0, "15": 0.0, "16": 14566.8, "17": 595.36, "18": 15162.16,
            "19": 3032.43, "20": 18194.59,
        }
        for code, value in expected.items():
            self.assertAlmostEqual(a[code], value, delta=CENT, msg="стаття %s" % code)
        self.assertAlmostEqual(calculation.hours, 2.0, delta=0.0001)
        self.assertAlmostEqual(calculation.price_unit, 15162.16, delta=CENT)
        self.assertAlmostEqual(calculation.price_unit_vat, 18194.59, delta=CENT)
        # Розшифровка: карбон з рами, три покупні, обрізки - зворотні відходи.
        rows = {(row.item, row.product_id): row.amount for row in calculation.component_ids}
        self.assertAlmostEqual(rows[("01", self.carbon)], 800.0, delta=CENT)
        self.assertAlmostEqual(rows[("02", self.motor)], 3200.0, delta=CENT)
        self.assertAlmostEqual(rows[("10", self.scrap)], 10.0, delta=CENT)
        self.assertNotIn(("01", self.frame), rows, "напівфабрикат розкладено, а не взято цілим")

    def test_11_indirect_costs_on_production_cost_base(self):
        """База адміністративних - виробнича собівартість: 12 = 14 366,80 x 50% = 7 183,40."""
        self.contract.ua_indirect_base = "cost"
        calculation = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.drone.id,
        })
        calculation.action_compute()
        a = self._amounts(calculation)
        self.assertAlmostEqual(a["12"], 7183.4, delta=CENT)
        # 16 = 14 366,80 + 7 183,40 = 21 550,20; 17 = 122 + (21 550,20 - 12 200) x 20% = 1 992,04.
        self.assertAlmostEqual(a["16"], 21550.2, delta=CENT)
        self.assertAlmostEqual(a["17"], 1992.04, delta=CENT)

    def test_12_approved_calculation_is_frozen(self):
        calculation = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.drone.id,
        })
        with self.assertRaises(UserError):
            calculation.action_approve()          # ще не перераховано
        calculation.action_compute()
        calculation.action_approve()
        with self.assertRaises(UserError):
            calculation.action_compute()

    def test_13_actual_calculation_from_done_productions(self):
        plan = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.station.id, "kind": "plan",
        })
        plan.action_compute()
        self._receive(self.tablet, 2)
        self._receive(self.case, 4)
        production = self.env["mrp.production"].create({
            "product_id": self.station.id, "bom_id": self.station_bom.id, "product_qty": 2.0,
            "company_id": self.company.id, "ua_contract_id": self.contract.id,
        })
        production.action_confirm()
        production.qty_producing = 2.0
        production.move_raw_ids.picked = True
        production.button_mark_done()
        self.assertEqual(production.state, "done")

        actual = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.station.id, "kind": "actual",
        })
        actual.action_compute()
        self.assertEqual(actual.plan_id, plan)
        self.assertEqual(actual.production_ids, production)
        self.assertAlmostEqual(actual.quantity, 2.0, delta=0.0001)
        a = self._amounts(actual)
        expected = {"01": 800.0, "02": 6000.0, "04": 0.0, "11": 6800.0, "16": 6800.0,
                    "17": 220.0, "18": 7020.0, "19": 1404.0, "20": 8424.0}
        for code, value in expected.items():
            self.assertAlmostEqual(a[code], value, delta=CENT, msg="стаття %s" % code)
        # План без операцій збігся з фактом: відхилень немає.
        for line in actual.line_ids:
            self.assertAlmostEqual(line.difference, 0.0, delta=CENT, msg="стаття %s" % line.code)

    def test_14_actual_needs_done_productions(self):
        actual = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.station.id, "kind": "actual",
        })
        with self.assertRaises(UserError):
            actual.action_compute()

    # ------------------------------------------------------------------
    # Графік, акт приймання, паспорт
    # ------------------------------------------------------------------
    def _lots(self, count):
        return self.env["stock.lot"].create([{
            "name": "КВ-%04d" % n, "product_id": self.drone.id, "company_id": self.company.id,
        } for n in range(1, count + 1)])

    def test_20_acceptance_closes_the_schedule_in_date_order(self):
        self.contract.ua_schedule_ids = [
            (0, 0, {"product_id": self.drone.id, "quantity": 2.0, "date": date(2026, 4, 1)}),
            (0, 0, {"product_id": self.drone.id, "quantity": 2.0, "date": date(2099, 1, 1)}),
        ]
        lots = self._lots(4)
        act = self.env["ua.defense.acceptance"].create({
            "contract_id": self.contract.id,
            "date": date(2026, 4, 2),
            "representative": "Представник замовника Петренко П. П.",
            "line_ids": [
                (0, 0, {"product_id": self.drone.id, "quantity": 3.0, "lot_ids": [(6, 0, lots[:3].ids)]}),
                (0, 0, {"product_id": self.drone.id, "quantity": 1.0, "result": "rework",
                        "lot_ids": [(6, 0, lots[3:].ids)], "note": "Люфт підвісу камери"}),
            ],
        })
        self.assertTrue(act.name.startswith("АП-"))
        first, second = self.contract.ua_schedule_ids.sorted("date")
        self.assertEqual(first.state, "late")         # строк минув, нічого не прийнято
        act.action_done()
        self.contract.ua_schedule_ids.invalidate_recordset()
        self.assertAlmostEqual(first.qty_accepted, 2.0)
        self.assertEqual(first.state, "done")
        self.assertAlmostEqual(second.qty_accepted, 1.0)   # 3 прийнято: 2 у перший рядок, 1 у другий
        self.assertEqual(second.state, "planned")
        self.assertEqual(lots[:3].ua_acceptance_id, act)
        self.assertEqual(lots[:3].ua_contract_id, self.contract)
        self.assertFalse(lots[3].ua_acceptance_id, "виріб на доопрацюванні не прийнято")

    def test_21_serial_count_must_match(self):
        lots = self._lots(1)
        act = self.env["ua.defense.acceptance"].create({
            "contract_id": self.contract.id,
            "line_ids": [(0, 0, {"product_id": self.drone.id, "quantity": 2.0, "lot_ids": [(6, 0, lots.ids)]})],
        })
        with self.assertRaises(UserError):
            act.action_done()

    def test_22_passport_prints_contract_and_act(self):
        lot = self._lots(1)
        lot.ua_passport_number = "П-0001"
        self.drone.ua_warranty_months = 12
        act = self.env["ua.defense.acceptance"].create({
            "contract_id": self.contract.id,
            "date": date(2026, 4, 2),
            "line_ids": [(0, 0, {"product_id": self.drone.id, "quantity": 1.0, "lot_ids": [(6, 0, lot.ids)]})],
        })
        act.action_done()
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_defense.action_report_ua_product_passport", lot.ids)
        html = html.decode() if isinstance(html, bytes) else html
        for text in ("ПАСПОРТ ВИРОБУ", "П-0001", "КВ-0001", "ОК-12/2026", act.name, "12 міс."):
            self.assertIn(text, html)

    def test_23_calculation_and_act_print(self):
        calculation = self.env["ua.defense.calculation"].create({
            "contract_id": self.contract.id, "product_id": self.drone.id,
        })
        calculation.action_compute()
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_defense.action_report_ua_defense_calculation", calculation.ids)
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn("ПЛАНОВА КАЛЬКУЛЯЦІЯ", html)
        self.assertIn("№ 309", html)
        self.assertIn("Зворотні відходи", html)

    def test_24_contract_button_makes_a_plan_for_the_scheduled_product(self):
        self.contract.ua_schedule_ids = [
            (0, 0, {"product_id": self.drone.id, "quantity": 5.0, "date": date(2099, 1, 1)}),
        ]
        action = self.contract.action_new_plan_calculation()
        calculation = self.env["ua.defense.calculation"].browse(action["res_id"])
        self.assertEqual(calculation.product_id, self.drone)
        self.assertAlmostEqual(calculation.price_unit, 15162.16, delta=CENT)

    # ------------------------------------------------------------------
    # ВТК: пункти перевірки операцій, випуск, приймання, паспорт
    # ------------------------------------------------------------------
    def _drone_production(self, contract=None):
        self.drone_bom.operation_ids.ua_checks = "Підвіс камери без люфту\nКалібрування компаса"
        for product, quantity in ((self.frame, 1), (self.camera, 1), (self.controller, 1),
                                  (self.motor, 4)):
            self._receive(product, quantity)
        production = self.env["mrp.production"].create({
            "product_id": self.drone.id, "bom_id": self.drone_bom.id, "product_qty": 1.0,
            "company_id": self.company.id,
            "ua_contract_id": contract.id if contract else False,
        })
        production.action_confirm()
        production.action_generate_serial()
        production.move_raw_ids.picked = True
        return production

    def test_30_quality_gate_blocks_release_until_all_checks_are_yes(self):
        production = self._drone_production(self.contract)
        workorder = production.workorder_ids
        self.assertEqual(len(workorder), 1)
        self.assertEqual(production.ua_quality_state, "pending")
        with self.assertRaises(UserError):
            production.button_mark_done()
        workorder.ua_answer_check(1, "ok")
        workorder.ua_answer_check(2, "fail", "відхилення 4 градуси")
        production.invalidate_recordset(["ua_quality_state"])
        self.assertEqual(production.ua_quality_state, "failed")
        with self.assertRaises(UserError):
            production.button_mark_done()
        workorder.ua_answer_check(2, "ok", "після перекалібрування")
        production.invalidate_recordset(["ua_quality_state"])
        self.assertEqual(production.ua_quality_state, "passed")
        production.button_mark_done()
        self.assertEqual(production.state, "done")

        lot = production.lot_producing_ids
        self.assertEqual(lot.ua_production_id, production)
        self.assertEqual(lot.ua_quality_state, "passed")
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_defense.action_report_ua_product_passport", lot.ids)
        html = html.decode() if isinstance(html, bytes) else html
        for text in ("Контроль якості під час виготовлення", "Калібрування компаса",
                     "після перекалібрування", "Загальне складання"):
            self.assertIn(text, html)

    def test_31_gate_off_lets_release_but_acceptance_still_checks(self):
        """Замовлення без контракту закрили з «ні»; акт за контрактом із ВТК такий виріб не бере."""
        production = self._drone_production()
        workorder = production.workorder_ids
        workorder.ua_answer_check(1, "ok")
        workorder.ua_answer_check(2, "fail", "компас не калібрується")
        production.button_mark_done()
        self.assertEqual(production.state, "done")
        lot = production.lot_producing_ids
        self.assertEqual(lot.ua_quality_state, "failed")

        act = self.env["ua.defense.acceptance"].create({
            "contract_id": self.contract.id,
            "line_ids": [(0, 0, {"product_id": self.drone.id, "quantity": 1.0,
                                 "lot_ids": [(6, 0, lot.ids)]})],
        })
        with self.assertRaises(UserError):
            act.action_done()
        act.line_ids.result = "rework"
        act.action_done()
        self.assertEqual(act.state, "done")
        self.assertFalse(lot.ua_acceptance_id)

    def test_32_products_without_checks_are_not_stopped(self):
        """Наземна станція не має операцій: ВТК нема чого перевіряти, випуск іде як раніше."""
        self.assertTrue(self.contract.ua_quality_gate)
        self._receive(self.tablet, 1)
        self._receive(self.case, 2)
        production = self.env["mrp.production"].create({
            "product_id": self.station.id, "bom_id": self.station_bom.id, "product_qty": 1.0,
            "company_id": self.company.id, "ua_contract_id": self.contract.id,
        })
        production.action_confirm()
        self.assertEqual(production.ua_quality_state, "none")
        production.qty_producing = 1.0
        production.move_raw_ids.picked = True
        production.button_mark_done()
        self.assertEqual(production.state, "done")
