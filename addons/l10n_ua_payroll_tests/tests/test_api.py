# -*- coding: utf-8 -*-
"""Договір читання для інтерфейсу (модель `ua.api`). Тег `ua_api`.

Інтерфейс живе в іншому репозиторії і не може «швидко подивитися в код», коли
відповідь змінила форму. Тому тут перевіряється не текст документації, а сама
відповідь: склад ключів, збіг чисел із моделями, відсутність записів у базу і
права доступу.

Два класи. `TestUaApi` - бек-офіс (місяць, документи, картка, звітність),
`TestUaApiStock` - склад і виробництво (карта, залишки, підлога, складання,
інвентаризація).

Групи однакові в обох:
  форма відповіді кожного методу; значення дорівнюють тому, що кажуть самі моделі
  (другого розрахунку немає); читання нічого не пише - ані нових записів, ані
  INSERT/UPDATE/DELETE; користувач без потрібних прав дістає AccessError, а не дані.
"""
import json
from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

YEAR, MONTH = 2026, 3
FIRST, LAST = date(YEAR, MONTH, 1), date(YEAR, MONTH, 31)

# Ключі верхнього рівня кожної відповіді - саме на них спирається UI.
MONTH_KEYS = {"company", "period", "blockers", "plan", "payslips", "documents"}
CARD_KEYS = {"employee", "tabs", "children", "version", "documents", "orders",
             "leaves", "alerts", "targets"}
DOCUMENT_KEYS = {"kind", "label", "model", "present", "records", "target"}
REPORT_KEYS = {"code", "label", "period_type", "run_id", "name", "state", "state_label",
               "doc_kind", "submitted_date", "checks", "files", "receipts", "target"}
DOCUMENT_KINDS = ["timesheet", "staff_list", "advance_sheet", "pfu_claim", "payment_order",
                  "military_list", "military_notice", "military_reserved"]
# Ключі верхнього рівня складських відповідей.
MAP_KEYS = {"company", "sizes", "roots", "locations"}
MAP_LOCATION_KEYS = {"id", "name", "path", "parent_id", "level", "capacity", "used",
                     "own", "free", "overflow", "fill", "floor", "purpose",
                     "purpose_label", "plan", "items", "target"}
GLANCE_KEYS = {"company", "total", "offset", "limit", "count", "truncated", "rows"}
GLANCE_ROW_KEYS = {"product", "code", "category", "location", "uom", "qty", "reserved",
                   "free", "free_total", "value", "min", "month", "need", "level",
                   "enough_for", "size", "size_label", "slots", "last_move", "target"}
FLOOR_ROW_KEYS = {"source", "product", "code", "category", "lot", "uom", "location",
                  "quantity", "reserved", "free", "size", "size_label", "per_unit", "slots",
                  "order", "done_date", "suggest", "target"}
ASSEMBLY_KEYS = {"product", "code", "drawing_svg", "drawing_name", "operations",
                 "total_minutes"}
PART_KEYS = {"pos", "product", "product_id", "qty", "bin_location", "bin_source"}

# Запис пізнається за ПЕРШИМ словом запиту: «... FOR UPDATE» у SELECT записом не є.
WRITE_SQL = ("insert into", "update ", "delete from", "truncate ")

# Моделі, за кількістю записів у яких стежить шпигун: якщо читання щось завело,
# лічильник це покаже навіть тоді, коли SQL проскочив повз фільтр.
WATCHED = ["hr.payslip", "hr.payslip.run", "account.move", "ua.change.log",
           "ua.period.close", "ua.timesheet.sheet", "ua.staff.list", "ua.report.run",
           "ua.employee.document", "ir.attachment", "stock.quant", "stock.move",
           "stock.move.line", "stock.picking", "stock.location",
           "ua.stock.inventory", "ua.stock.inventory.line", "mrp.production"]


class NoWriteMixin:
    """Перевірка «це читання»: ані INSERT/UPDATE/DELETE, ані нових записів.

    Колишній scripts/readonly_check.py доводив те саме лічильниками pg_stat на
    стенді. Тут те саме рахується в транзакції: і сам SQL, який ядро встигло
    виконати, і кількість записів у базі до і після."""

    def assert_reads_only(self, calls):
        self.env.flush_all()
        before = {model: self.env[model].sudo().search_count([]) for model in WATCHED}

        cursor = self.env.cr
        original = cursor.execute
        seen = []

        def spy(query, params=None, log_exceptions=True):
            seen.append(" ".join(str(query).split()).lower())
            return original(query, params, log_exceptions)

        cursor.execute = spy
        try:
            for call in calls:
                call()
        finally:
            cursor.execute = original

        writes = [query for query in seen if query.startswith(WRITE_SQL)]
        self.assertEqual(writes, [], "читання виконало запис: %s" % (writes[:1] or ""))

        self.env.flush_all()
        after = {model: self.env[model].sudo().search_count([]) for model in WATCHED}
        self.assertEqual(before, after, "читання створило записи")


@tagged("post_install", "-at_install", "ua_api")
class TestUaApi(NoWriteMixin, TransactionCase):

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
        cls.Api = cls.env["ua.api"]
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.employee = cls.env["hr.employee"].create({
            "name": "Договірна Оксана", "company_id": cls.company.id,
            "ua_rnokpp": "3444444444", "ua_main_job": True, "ua_psp": "none",
            "ua_esv_category": "standard", "ua_contract_kind": "employment",
            "ua_fte": "1", "ua_index_off": True, "ua_mil_status": "liable",
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })
        cls.employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 21000.0, "contract_date_start": "2025-01-01",
            "struct_id": cls.structure.id,
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })
        # місяць із табелем і листками - інакше перевіряти було б нічого
        cls.env["hr.payslip.run"].ua_prepare_month(cls.company, YEAR, MONTH)

    # ------------------------------------------------------------------ службове
    def _plain_user(self):
        """Внутрішній користувач без кадрових і зарплатних прав."""
        return self.env["res.users"].create({
            "name": "Без прав", "login": "ua_api_no_rights",
            "company_id": self.company.id, "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    def _json_safe(self, payload):
        """Відповідь має пережити json.dumps без default= - це і є «прості типи»."""
        return json.loads(json.dumps(payload))

    # ------------------------------------------------------------------ 1. місяць
    def test_01_month_summary_shape(self):
        """month_summary() віддає всі шість блоків і переживає json.dumps."""
        data = self.Api.month_summary(self.company.id, YEAR, MONTH)
        self.assertEqual(set(data), MONTH_KEYS)
        self.assertEqual(data["company"]["id"], self.company.id)

        period = data["period"]
        for key in ("year", "month", "label", "closed", "hard", "closed_by",
                    "closed_date", "periods"):
            self.assertIn(key, period, "у смузі періоду має бути %s" % key)
        self.assertEqual((period["year"], period["month"]), (YEAR, MONTH))
        self.assertEqual(len(period["periods"]), 6, "смуга - шість місяців")
        self.assertTrue(any(item["current"] for item in period["periods"]))

        self.assertEqual(set(data["payslips"]),
                         {"count", "draft", "done", "cancel", "totals", "target"})
        self.assertEqual(set(data["payslips"]["totals"]),
                         {"GROSS", "PDFO", "VZ", "ESV", "NET", "ADV_PAID"})
        for row in data["plan"]:
            self.assertIn(row["level"], ("info", "warn", "crit"))
        self.assertEqual(data, self._json_safe(data), "відповідь - лише прості типи")

    # ------------------------------------------------------------------ 2. документи місяця
    def test_02_documents_for_month_shape(self):
        """Вісім видів документів завжди на місці, у сталому порядку, з перевірками."""
        rows = self.Api.documents_for_month(self.company.id, YEAR, MONTH)
        self.assertEqual([row["kind"] for row in rows], DOCUMENT_KINDS)
        for row in rows:
            self.assertEqual(set(row), DOCUMENT_KEYS)
            self.assertEqual(row["present"], bool(row["records"]))
            for record in row["records"]:
                self.assertEqual(set(record),
                                 {"id", "name", "state", "state_label", "level",
                                  "errors", "warns", "checks", "target"})
                self.assertIn(record["level"], ("ok", "warn", "error"))
                for check in record["checks"]:
                    self.assertEqual(set(check), {"level", "text", "fact", "target"})
                    self.assertIn(check["level"], ("ok", "warn", "error"))
        self.assertEqual(rows, self._json_safe(rows))

        timesheet = next(row for row in rows if row["kind"] == "timesheet")
        self.assertTrue(timesheet["present"], "ua_prepare_month створив табель місяця")

    # ------------------------------------------------------------------ 3. картка
    def test_03_employee_card_shape(self):
        """employee_card() віддає шапку, чотири вкладки, огляд і переліки."""
        card = self.Api.employee_card(self.employee.id)
        self.assertEqual(set(card), CARD_KEYS)
        self.assertEqual(card["employee"]["id"], self.employee.id)
        self.assertEqual(set(card["tabs"]), {"person", "pay", "vacation", "military", "overview"})
        self.assertIn("ua_rnokpp", card["tabs"]["person"])
        self.assertIn("ua_vacation_balance", card["tabs"]["vacation"])
        self.assertIn("ua_mil_status", card["tabs"]["military"])
        self.assertEqual(set(card["leaves"]), {"allocations", "requests"})
        self.assertEqual(set(card["alerts"]), {"count", "docs_expiring", "military_needs_check", "items"})
        self.assertEqual(set(card["targets"]), {"form", "documents", "orders"})
        self.assertEqual(card["targets"]["form"],
                         {"model": "hr.employee", "res_id": self.employee.id})
        self.assertEqual(card, self._json_safe(card))

    # ------------------------------------------------------------------ 4. звітність
    def test_04_reporting_status_shape(self):
        """reporting_status() перелічує всі звіти робочого місця, навіть без прогонів."""
        data = self.Api.reporting_status(self.company.id, YEAR, MONTH)
        self.assertEqual(set(data), {"company", "year", "month", "reports"})
        codes = [row["code"] for row in data["reports"]]
        self.assertEqual(codes, [code for code, _label
                                 in self.env["ua.report.run"]._fields["report_code"].selection])
        for row in data["reports"]:
            self.assertEqual(set(row), REPORT_KEYS)
            self.assertEqual(set(row["checks"]), {"ok", "warn", "error", "rows"})
            self.assertIn(row["period_type"], ("month", "date", "year"))
            self.assertFalse(row["run_id"], "жодного прогону ще немає - метод їх не створює")
        self.assertEqual(data, self._json_safe(data))

    # ------------------------------------------------------------------ 5. числа = моделі
    def test_05_month_numbers_equal_the_models(self):
        """Підсумки і перешкоди - не другий розрахунок, а ті самі методи ядра."""
        data = self.Api.month_summary(self.company.id, YEAR, MONTH)
        Close = self.env["ua.period.close"]

        slips = self.env["hr.payslip"].search([
            ("company_id", "=", self.company.id),
            ("date_from", ">=", FIRST), ("date_from", "<=", LAST)])
        self.assertEqual(data["payslips"]["count"], len(slips))
        lines = slips.filtered(lambda s: s.state != "cancel").mapped("line_ids")
        gross = round(sum(lines.filtered(lambda l: l.code == "GROSS").mapped("total")), 2)
        self.assertEqual(data["payslips"]["totals"]["GROSS"], gross)

        rows = Close.blocker_rows(self.company, YEAR, MONTH)
        self.assertEqual([row["key"] for row in data["blockers"]], [row["key"] for row in rows])
        self.assertEqual([row["text"] for row in data["blockers"]], [row["text"] for row in rows])
        self.assertEqual(len(data["plan"]), len(Close.plan(self.company, YEAR, MONTH)))
        self.assertEqual(data["period"]["closed"],
                         Close.state_of(self.company, YEAR, MONTH)["state"] == "closed")

    def test_06_card_values_equal_the_employee(self):
        """Поля картки дорівнюють полям працівника, а перевірки документів - _checks()."""
        card = self.Api.employee_card(self.employee.id)
        self.assertEqual(card["employee"]["name"], self.employee.name)
        self.assertEqual(card["tabs"]["person"]["ua_rnokpp"], self.employee.ua_rnokpp)
        self.assertEqual(card["tabs"]["vacation"]["ua_vacation_balance"],
                         self.employee.ua_vacation_balance)
        self.assertEqual(card["alerts"]["count"], self.employee.ua_overview_alert_count)
        self.assertEqual(len(card["alerts"]["items"]), card["alerts"]["count"])
        for item in card["alerts"]["items"]:
            self.assertEqual(set(item), {"level", "text"})
            self.assertIn(item["level"], ("crit", "warn"))
        self.assertEqual(card["version"]["wage"], self.employee.version_id.wage)

        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company.id), ("year", "=", YEAR), ("month", "=", MONTH)],
            limit=1)
        rows = self.Api.documents_for_month(self.company.id, YEAR, MONTH)
        timesheet = next(row for row in rows if row["kind"] == "timesheet")
        self.assertEqual([record["id"] for record in timesheet["records"]], sheet.ids)
        self.assertEqual([check["text"] for check in timesheet["records"][0]["checks"]],
                         [check["text"] for check in sheet._checks_summary()["checks"]])

    # ------------------------------------------------------------------ 7. читання не пише
    def test_07_reading_writes_nothing(self):
        """Жоден із чотирьох бек-офісних методів не пише - ні записом, ні SQL."""
        self.assert_reads_only([
            lambda: self.Api.month_summary(self.company.id, YEAR, MONTH),
            lambda: self.Api.documents_for_month(self.company.id, YEAR, MONTH),
            lambda: self.Api.employee_card(self.employee.id),
            lambda: self.Api.reporting_status(self.company.id, YEAR, MONTH),
        ])

    # ------------------------------------------------------------------ 8-10. права
    def test_08_month_summary_needs_hr_rights(self):
        """Користувач без кадрових прав дістає AccessError, а не порожній місяць."""
        user = self._plain_user()
        with self.assertRaises(AccessError):
            self.env["ua.api"].with_user(user).month_summary(self.company.id, YEAR, MONTH)

    def test_09_employee_card_needs_hr_rights(self):
        """Картка чужого працівника без кадрових прав - AccessError."""
        user = self._plain_user()
        with self.assertRaises(AccessError):
            self.env["ua.api"].with_user(user).employee_card(self.employee.id)

    def test_10_documents_for_month_needs_hr_rights(self):
        """Документи місяця без кадрових прав - AccessError, не порожній перелік."""
        user = self._plain_user()
        with self.assertRaises(AccessError):
            self.env["ua.api"].with_user(user).documents_for_month(self.company.id, YEAR, MONTH)


@tagged("post_install", "-at_install", "ua_api")
class TestUaApiStock(NoWriteMixin, TransactionCase):
    """Склад і виробництво: карта, залишки, підлога, складання, інвентаризація.

    Склад на порожній базі доводиться будувати самому: дві полиці з різною
    місткістю, підлога під однією з них, три товари різного габариту, правило
    поповнення, специфікація з операцією і опис інвентаризації. Зате після цього
    перевіряються не форми відповідей, а числа: зайняті місця проти
    `ua_capacity_used`, «на скільки вистачить» проти специфікації, план проти
    `ua.stock.inventory.plan()`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Api = cls.env["ua.api"]
        cls.Quant = cls.env["stock.quant"]

        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], order="sequence, id", limit=1)
        # Двокрокове приймання вмикає локацію WH/Input - без неї джерела «input»
        # у відповіді не буває, і перевіряти було б нічого.
        cls.warehouse.reception_steps = "two_steps"
        cls.stock = cls.warehouse.lot_stock_id
        cls.input = cls.warehouse.wh_input_stock_loc_id

        Location = cls.env["stock.location"]
        cls.shelf_big = Location.create({
            "name": "Полиця М1", "usage": "internal", "location_id": cls.stock.id,
            "company_id": cls.company.id, "ua_capacity": 40})
        cls.shelf_small = Location.create({
            "name": "Полиця М2", "usage": "internal", "location_id": cls.stock.id,
            "company_id": cls.company.id, "ua_capacity": 2})
        cls.floor = Location.create({
            "name": "Підлога", "usage": "internal", "location_id": cls.shelf_big.id,
            "company_id": cls.company.id})

        Product = cls.env["product.product"]
        # Категорію ставимо руками: у Odoo 19 `product.template.categ_id` не
        # обовʼязкове і без замовчування - товар без категорії там звичайна річ.
        cls.category = cls.env["product.category"].create({"name": "Комплектуючі"})
        cls.small = Product.create({
            "name": "Гвинт М3", "is_storable": True, "default_code": "GV-3",
            "categ_id": cls.category.id, "ua_size": "s", "standard_price": 2.0})
        cls.medium = Product.create({
            "name": "Мотор 2207", "is_storable": True, "default_code": "MT-2207",
            "categ_id": cls.category.id, "ua_size": "m", "standard_price": 900.0})
        cls.large = Product.create({
            "name": "Рама карбон", "is_storable": True, "default_code": "RM-7",
            "categ_id": cls.category.id, "ua_size": "l", "standard_price": 1500.0})

        # 3 великих на малій полиці: 3 × 16 = 48 місць проти двох - переповнення.
        cls.Quant._update_available_quantity(cls.large, cls.shelf_small, 3)
        # 10 дрібних і 2 середніх на великій: 10 × 1 + 2 × 4 = 18 місць із 40.
        cls.Quant._update_available_quantity(cls.small, cls.shelf_big, 10)
        cls.Quant._update_available_quantity(cls.medium, cls.shelf_big, 2)
        # нерозкладене: одне на підлозі полиці, одне в прийманні
        cls.Quant._update_available_quantity(cls.medium, cls.floor, 1)
        cls.Quant._update_available_quantity(cls.small, cls.input, 5)

        cls.env["stock.warehouse.orderpoint"].create({
            "product_id": cls.small.id, "location_id": cls.stock.id,
            "company_id": cls.company.id, "product_min_qty": 100.0,
            "product_max_qty": 200.0})

        # Виріб зі специфікацією на партію 2: по 4 гвинти і 1 рамі на ОДИН виріб.
        cls.drone = Product.create({
            "name": "Дрон Шершень", "is_storable": True, "default_code": "SH-7",
            "categ_id": cls.category.id})
        cls.workcenter = cls.env["mrp.workcenter"].create({
            "name": "Стіл складання", "company_id": cls.company.id})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id,
            "product_qty": 2.0, "type": "normal", "company_id": cls.company.id,
            "bom_line_ids": [
                (0, 0, {"product_id": cls.large.id, "product_qty": 2.0, "sequence": 1}),
                (0, 0, {"product_id": cls.small.id, "product_qty": 8.0, "sequence": 2}),
            ],
            "operation_ids": [(0, 0, {
                "name": "Збирання рами", "workcenter_id": cls.workcenter.id,
                "time_cycle_manual": 20.0, "sequence": 1,
                "ua_steps": "Розпакувати раму\nПоставити мотори",
                "ua_checks": "Люфтів немає"})],
        })
        cls.bom.bom_line_ids[0].operation_id = cls.bom.operation_ids[0].id

        cls.inventory = cls.env["ua.stock.inventory"].create({
            "company_id": cls.company.id, "location_id": cls.stock.id,
            "date": date.today(), "ua_client_ref": "api-test-1"})

    def _json_safe(self, payload):
        return json.loads(json.dumps(payload))

    def _plain_user(self):
        """Внутрішній користувач без складських і виробничих прав."""
        return self.env["res.users"].create({
            "name": "Без складу", "login": "ua_api_no_stock",
            "company_id": self.company.id, "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    # ------------------------------------------------------------------ 11. карта
    def test_11_warehouse_map_shape(self):
        """warehouse_map() віддає дерево локацій із місткістю і переживає json.dumps."""
        data = self.Api.warehouse_map(self.company.id)
        self.assertEqual(set(data), MAP_KEYS)
        self.assertEqual(data["sizes"], {"s": 1, "m": 4, "l": 16, "default": "s"})
        self.assertTrue(data["roots"], "хоч одна локація має бути коренем дерева")

        by_id = {row["id"]: row for row in data["locations"]}
        for row in data["locations"]:
            self.assertEqual(set(row), MAP_LOCATION_KEYS)
            if row["parent_id"] and row["parent_id"][0] in by_id:
                self.assertEqual(row["level"], by_id[row["parent_id"][0]]["level"] + 1,
                                 "рівень дитини - рівень батька плюс один")
            for item in row["items"]:
                self.assertEqual(set(item), {"product", "code", "category", "quantity",
                                             "reserved", "uom", "size", "size_label",
                                             "slots"})
        self.assertTrue(by_id[self.floor.id]["floor"], "«Підлога» позначена як підлога")
        self.assertFalse(by_id[self.shelf_big.id]["floor"])
        self.assertEqual(data, self._json_safe(data))

    def test_12_map_slots_are_the_model(self):
        """Зайняті місця, переповнення і залишок - з ua_capacity_used, а не з нової формули."""
        data = self.Api.warehouse_map(self.company.id)
        by_id = {row["id"]: row for row in data["locations"]}

        small = by_id[self.shelf_small.id]
        self.assertEqual(small["capacity"], 2)
        self.assertEqual(small["used"], self.shelf_small.ua_capacity_used)
        self.assertEqual(small["used"], 48, "3 великих × 16 місць")
        self.assertTrue(small["overflow"], "48 місць у полиці на 2 - переповнення")
        self.assertEqual(small["free"], 0, "вільного не буває менше за нуль")

        big = by_id[self.shelf_big.id]
        self.assertEqual(big["own"], 18, "10 × S + 2 × M = 10 + 8 місць")
        self.assertEqual(big["used"], self.shelf_big.ua_capacity_used)
        self.assertEqual(big["used"], 22, "18 своїх плюс 4 місця з підлоги")
        self.assertFalse(big["overflow"])
        self.assertEqual(big["free"], 18)
        self.assertEqual(big["fill"], 55.0)

        floor = by_id[self.floor.id]
        self.assertEqual(floor["capacity"], 0, "місткості не задано")
        self.assertFalse(floor["overflow"], "без місткості переповнення не рахується")
        self.assertFalse(floor["free"])

    # ------------------------------------------------------------------ 13-15. залишки
    def test_13_stock_glance_shape(self):
        """stock_glance() віддає рядок на залишок із мінімумом, потребою і габаритом."""
        data = self.Api.stock_glance(self.company.id)
        self.assertEqual(set(data), GLANCE_KEYS)
        self.assertFalse(data["truncated"])
        self.assertEqual(data["count"], len(data["rows"]))
        self.assertTrue(data["rows"])
        for row in data["rows"]:
            self.assertEqual(set(row), GLANCE_ROW_KEYS)
            self.assertIn(row["level"], ("ok", "warn", "bad"))
            self.assertEqual(row["need"], max(row["min"], row["month"]))
            for item in row["enough_for"]:
                self.assertEqual(set(item), {"product", "per_unit", "units"})
        self.assertEqual(data, self._json_safe(data))

    def test_14_glance_numbers_equal_the_models(self):
        """Кількість, резерв і мінімум дорівнюють quant і правилу поповнення."""
        data = self.Api.stock_glance(self.company.id, location_ids=[self.shelf_big.id])
        rows = {(row["product"][0], row["location"][0]): row for row in data["rows"]}
        self.assertEqual(sorted({key[1] for key in rows}), [self.shelf_big.id, self.floor.id],
                         "звуження локацією бере полицю разом із дочірніми")

        quant = self.Quant.search([("product_id", "=", self.small.id),
                                   ("location_id", "=", self.shelf_big.id)], limit=1)
        row = rows[(self.small.id, self.shelf_big.id)]
        self.assertEqual(row["qty"], quant.quantity)
        self.assertEqual(row["reserved"], quant.reserved_quantity)
        self.assertEqual(row["free"], quant.available_quantity)
        self.assertEqual(row["min"], 100.0, "мінімум з stock.warehouse.orderpoint")
        self.assertEqual(row["level"], "warn", "вільного менше за мінімум")
        self.assertEqual(row["size"], "s")
        self.assertEqual(row["slots"], 10.0, "10 штук × одне місце")

        # звуження категорією не вигадує рядків, яких немає в незвуженій відповіді
        narrowed = self.Api.stock_glance(self.company.id,
                                         category_ids=[self.category.id])
        self.assertTrue(narrowed["rows"])
        everything = {(row["product"][0], row["location"][0])
                      for row in self.Api.stock_glance(self.company.id)["rows"]}
        for row in narrowed["rows"]:
            self.assertIn((row["product"][0], row["location"][0]), everything)
            self.assertEqual(row["category"][0], self.category.id,
                             "звуження категорією не пускає чужі товари")

    def test_15_enough_for_counts_by_the_bom(self):
        """«На скільки вистачить» рахується від потреби на ОДНУ одиницю виробу."""
        data = self.Api.stock_glance(self.company.id)
        row = next(row for row in data["rows"]
                   if row["product"][0] == self.small.id
                   and row["location"][0] == self.shelf_big.id)
        made = {item["product"][0]: item for item in row["enough_for"]}
        self.assertIn(self.drone.product_tmpl_id.id, made,
                      "гвинт іде в специфікацію дрона")
        item = made[self.drone.product_tmpl_id.id]
        self.assertEqual(item["per_unit"], 4.0, "8 гвинтів на партію 2 - це 4 на виріб")
        self.assertEqual(item["units"], int(row["free_total"] // 4.0))
        self.assertEqual(item["units"], 3, "15 вільних гвинтів - три дрони")

        rama = next(row for row in data["rows"] if row["product"][0] == self.large.id)
        frame = next(item for item in rama["enough_for"]
                     if item["product"][0] == self.drone.product_tmpl_id.id)
        self.assertEqual(frame["per_unit"], 1.0, "2 рами на партію 2")
        self.assertEqual(frame["units"], 3)

    # ------------------------------------------------------------------ 16. підлога
    def test_16_floor_packages_finds_the_unshelved(self):
        """floor_packages() бачить приймання і підлогу полиці, полиці - не бачить."""
        data = self.Api.floor_packages(self.company.id)
        self.assertEqual(set(data), {"company", "count", "rows"})
        self.assertEqual(data["count"], len(data["rows"]))
        for row in data["rows"]:
            self.assertEqual(set(row), FLOOR_ROW_KEYS)
            self.assertIn(row["source"], ("input", "floor", "production"))

        places = {(row["source"], row["location"][0], row["product"][0]): row
                  for row in data["rows"]}
        self.assertIn(("input", self.input.id, self.small.id), places)
        self.assertIn(("floor", self.floor.id, self.medium.id), places)
        self.assertNotIn(("floor", self.shelf_big.id, self.small.id), places,
                         "полиця нерозкладеним не є")

        on_floor = places[("floor", self.floor.id, self.medium.id)]
        self.assertEqual(on_floor["quantity"], 1.0)
        self.assertEqual(on_floor["slots"], 4.0, "одне середнє - чотири місця")
        self.assertFalse(on_floor["order"], "це не випуск з виробництва")
        self.assertEqual(data, self._json_safe(data))

    # ------------------------------------------------------------------ 17. складання
    def test_17_product_assembly_points_at_real_shelves(self):
        """Складальна карта - та сама, що ua_assembly(), але полиця з живого залишку."""
        card = self.Api.product_assembly(self.drone.product_tmpl_id.id)
        self.assertEqual(set(card), ASSEMBLY_KEYS)
        self.assertEqual(card["product"][0], self.drone.product_tmpl_id.id)
        self.assertFalse(card["drawing_svg"], "креслення не заводили")
        self.assertEqual(card["total_minutes"], 20.0)

        core = self.drone.product_tmpl_id.ua_assembly()
        self.assertEqual([group["name"] for group in card["operations"]],
                         [group["name"] for group in core["operations"]],
                         "групи операцій ті самі, що в ядрі")

        parts = {part["product_id"]: part
                 for group in card["operations"] for part in group["parts"]}
        for part in parts.values():
            self.assertEqual(set(part), PART_KEYS)
        self.assertEqual(parts[self.large.id]["qty"], 1.0, "2 рами на партію 2")
        self.assertEqual(parts[self.large.id]["bin_location"],
                         self.shelf_small.display_name,
                         "рами лежать на М2 - туди збирач і йде")
        self.assertEqual(parts[self.large.id]["bin_source"], "stock")
        self.assertEqual(parts[self.small.id]["bin_location"], self.shelf_big.display_name)

        assembly = next(group for group in card["operations"]
                        if group["name"] == "Збирання рами")
        self.assertEqual(assembly["workcenter"], self.workcenter.display_name)
        self.assertEqual(assembly["steps"], ["Розпакувати раму", "Поставити мотори"])
        self.assertEqual(assembly["checks"], ["Люфтів немає"])
        self.assertEqual(card, self._json_safe(card))

    # ------------------------------------------------------------------ 18. план опису
    def test_18_inventory_plan_wraps_the_model(self):
        """inventory_plan() не рахує свій план - це рядки ua.stock.inventory.plan()."""
        data = self.Api.inventory_plan(self.inventory.id)
        self.assertEqual(set(data), {"inventory", "plan", "crit", "can_apply"})
        rows = self.inventory.plan()
        self.assertEqual([row["text"] for row in data["plan"]],
                         [row["text"] for row in rows])
        self.assertEqual(data["crit"], sum(1 for row in rows if row["level"] == "crit"))
        self.assertFalse(data["can_apply"],
                         "опис у чернетці не проводиться - у плані є crit")
        self.assertEqual(data["inventory"]["client_ref"], "api-test-1")
        self.assertEqual(data["inventory"]["state"], "draft")
        self.assertEqual(data["inventory"]["lines"], 0)
        self.assertEqual(data["inventory"]["target"],
                         {"model": "ua.stock.inventory", "res_id": self.inventory.id})
        self.assertEqual(data, self._json_safe(data))

        # заповнений і переведений у підрахунок опис проводити вже можна
        self.inventory.action_fill()
        ready = self.Api.inventory_plan(self.inventory.id)
        self.assertEqual(ready["inventory"]["state"], "counting")
        self.assertTrue(ready["inventory"]["lines"])
        self.assertTrue(ready["can_apply"])
        self.assertEqual(ready["crit"], 0)

    # ------------------------------------------------------------------ 19. читання не пише
    def test_19_stock_reading_writes_nothing(self):
        """Жодне з пʼяти складських читань не пише - ні записом, ні SQL."""
        self.assert_reads_only([
            lambda: self.Api.warehouse_map(self.company.id),
            lambda: self.Api.stock_glance(self.company.id),
            lambda: self.Api.floor_packages(self.company.id),
            lambda: self.Api.product_assembly(self.drone.product_tmpl_id.id),
            lambda: self.Api.inventory_plan(self.inventory.id),
        ])

    # ------------------------------------------------------------------ 20. права
    def test_20_stock_reading_needs_stock_rights(self):
        """Без складських і виробничих груп - AccessError, а не порожній склад."""
        user = self._plain_user()
        api = self.env["ua.api"].with_user(user)
        with self.assertRaises(AccessError):
            api.stock_glance(self.company.id)          # stock.warehouse.orderpoint
        with self.assertRaises(AccessError):
            api.product_assembly(self.drone.product_tmpl_id.id)   # mrp.bom

    def test_21_unknown_ids_say_so(self):
        """Неіснуючий id - людський UserError, а не AttributeError з нутрощів."""
        with self.assertRaises(UserError):
            self.Api.product_assembly(0)
        with self.assertRaises(UserError):
            self.Api.inventory_plan(0)
