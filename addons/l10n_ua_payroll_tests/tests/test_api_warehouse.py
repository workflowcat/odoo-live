# -*- coding: utf-8 -*-
"""Договір `ua.api`, склад: партія і категорія на підлозі, пошук і сторінки залишків,
зони на плані, перевірки запису, картка наряду. Тег `ua_api`.

Запити інтерфейсу 2026-09-22-012, -013, -016, 2026-09-22-015 і 2026-09-23-002.
Очікування пораховані руками, арифметика в коментарі поруч.
"""
import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from .test_api import NoWriteMixin


@tagged("post_install", "-at_install", "ua_api")
class TestUaApiWarehouse(NoWriteMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Api = cls.env["ua.api"]
        cls.Quant = cls.env["stock.quant"]
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], order="sequence, id", limit=1)
        cls.stock = cls.warehouse.lot_stock_id

        Location = cls.env["stock.location"]
        cls.cabinet = Location.create({
            "name": "Шафа АКБ", "usage": "internal", "location_id": cls.stock.id,
            "company_id": cls.company.id, "ua_capacity": 30, "ua_purpose": "hazard",
            "ua_plan_x": 1, "ua_plan_y": 2, "ua_plan_w": 3, "ua_plan_h": 4})
        cls.floor = Location.create({
            "name": "Підлога", "usage": "internal", "location_id": cls.cabinet.id,
            "company_id": cls.company.id, "ua_plan_w": 5})   # висоти нема - не намальовано

        cls.category = cls.env["product.category"].create({"name": "АКБ"})
        Product = cls.env["product.product"]
        cls.battery = Product.create({
            "name": "Акумулятор 6S", "is_storable": True, "default_code": "AKB-6S",
            "categ_id": cls.category.id, "ua_size": "m", "tracking": "lot"})
        cls.lot = cls.env["stock.lot"].create({
            "name": "АКБ-2607", "product_id": cls.battery.id, "company_id": cls.company.id})
        # 3 АКБ з партією на підлозі шафи: 3 × M (4 місця) = 12 місць
        cls.Quant._update_available_quantity(cls.battery, cls.floor, 3, lot_id=cls.lot)

        # сім гвинтів різних кодів по одному на шафі - для пошуку і сторінок
        cls.screws = Product.create([{
            "name": "Гвинт М%d" % size, "is_storable": True, "default_code": "GV-%d" % size,
            "categ_id": cls.category.id} for size in range(2, 9)])
        for screw in cls.screws:
            cls.Quant._update_available_quantity(screw, cls.cabinet, 1)

    def _json_safe(self, payload):
        return json.loads(json.dumps(payload))

    # ------------------------------------------------------------------ 012, 016: підлога
    def test_01_floor_row_carries_lot_category_and_the_size_of_the_product(self):
        """Рядок підлоги: партія залишку, категорія товару і габарит із самого товару."""
        data = self.Api.floor_packages(self.company.id)
        row = next(row for row in data["rows"]
                   if row["source"] == "floor" and row["product"][0] == self.battery.id)
        self.assertEqual(row["lot"], [self.lot.id, "АКБ-2607"])
        self.assertEqual(row["category"], [self.category.id, "АКБ"])
        # 016: габарит - те саме поле, що рахує ua_capacity_used, а не замовчування
        self.assertEqual(row["size"], "m")
        self.assertEqual(row["size"], self.battery.product_tmpl_id.ua_size)
        self.assertEqual(row["per_unit"], 4, "M - чотири місця на штуку")
        self.assertEqual(row["slots"], 12.0, "3 штуки × 4 місця")
        self.assertEqual(self.floor.ua_capacity_used, 12, "ядро рахує так само")
        self.assertEqual(data, self._json_safe(data))

    # ------------------------------------------------------------------ 013: пошук і сторінки
    def test_02_glance_query_by_code_or_name(self):
        """query шукає частину коду або назви, без регістру."""
        by_code = self.Api.stock_glance(self.company.id, query="gv-5")
        self.assertEqual([row["code"] for row in by_code["rows"]], ["GV-5"])
        self.assertEqual(by_code["total"], 1)
        by_name = self.Api.stock_glance(self.company.id, query="акумулятор")
        self.assertEqual({row["product"][0] for row in by_name["rows"]}, {self.battery.id})
        self.assertEqual(self.Api.stock_glance(self.company.id, query="немає-такого")["rows"],
                         [])

    def test_03_glance_pages_walk_the_whole_list(self):
        """offset/limit проходять увесь перелік без дірок і повторів."""
        everything = self.Api.stock_glance(self.company.id, query="GV-")
        self.assertEqual(everything["total"], 7, "сім гвинтів по одному залишку")
        self.assertFalse(everything["truncated"])

        first = self.Api.stock_glance(self.company.id, query="GV-", limit=3)
        self.assertEqual((first["offset"], first["limit"], first["count"]), (0, 3, 3))
        self.assertTrue(first["truncated"], "0 + 3 < 7 - є ще сторінка")
        seen, offset = [], 0
        while True:
            page = self.Api.stock_glance(self.company.id, query="GV-", offset=offset, limit=3)
            seen += [row["target"]["res_id"] for row in page["rows"]]
            if not page["truncated"]:
                break
            offset += page["count"]
        self.assertEqual(offset, 6, "сторінки 0, 3, 6")
        self.assertEqual(seen, [row["target"]["res_id"] for row in everything["rows"]])

        clamped = self.Api.stock_glance(self.company.id, limit=100000)
        self.assertEqual(clamped["limit"], 500, "більше за 500 на сторінку не віддаємо")

    # ------------------------------------------------------------------ 002: зони на плані
    def test_04_map_zone_purpose_and_plan(self):
        """Призначення зони і прямокутник на плані - з полів локації."""
        data = self.Api.warehouse_map(self.company.id)
        rows = {row["id"]: row for row in data["locations"]}
        cabinet = rows[self.cabinet.id]
        self.assertEqual(cabinet["purpose"], "hazard")
        self.assertEqual(cabinet["purpose_label"], "Небезпечні вантажі")
        self.assertEqual(cabinet["plan"], {"x": 1, "y": 2, "w": 3, "h": 4})
        self.assertFalse(rows[self.floor.id]["plan"], "висота нуль - на плані не намальовано")
        self.assertFalse(rows[self.floor.id]["purpose"])
        self.assertEqual(data, self._json_safe(data))

    # ------------------------------------------------------------------ 015: перевірки запису
    def test_05_record_checks_is_the_mixin(self):
        """record_checks() віддає рівно _checks_summary() документа."""
        document = self.env["ua.military.list"].create({
            "company_id": self.company.id, "tcc": "Львівський міський ТЦК та СП"})
        data = self.Api.record_checks("ua.military.list", document.id)
        summary = document._checks_summary()
        self.assertTrue(data["has_checks"])
        self.assertEqual((data["model"], data["res_id"]), ("ua.military.list", document.id))
        self.assertEqual(data["level"], summary["level"])
        self.assertEqual((data["errors"], data["warns"]), (summary["errors"], summary["warns"]))
        self.assertEqual([row["text"] for row in data["checks"]],
                         [row["text"] for row in summary["checks"]])
        for row in data["checks"]:
            self.assertEqual(set(row), {"level", "text", "fact", "target"})
        self.assertEqual(data, self._json_safe(data))

        plain = self.Api.record_checks("res.partner", self.company.partner_id.id)
        self.assertFalse(plain["has_checks"])
        self.assertEqual((plain["level"], plain["checks"]), ("ok", []))

        with self.assertRaises(UserError):
            self.Api.record_checks("no.such.model", 1)
        with self.assertRaises(UserError):
            self.Api.record_checks("ua.military.list", 0)

    def test_06_record_checks_respects_company_rules(self):
        """Опис іншої компанії не читається ні через record_checks, ні напряму."""
        other = self.env["res.company"].create({"name": "Інша компанія"})
        other_stock = self.env["stock.warehouse"].search(
            [("company_id", "=", other.id)], limit=1).lot_stock_id \
            or self.env["stock.location"].create({
                "name": "Склад іншої", "usage": "internal", "company_id": other.id})
        foreign = self.env["ua.stock.inventory"].create({
            "company_id": other.id, "location_id": other_stock.id})
        user = self.env["res.users"].create({
            "name": "Комірник", "login": "ua_api_keeper_one_company",
            "company_id": self.company.id, "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [self.env.ref("stock.group_stock_user").id])]})
        with self.assertRaises(AccessError):
            self.env["ua.api"].with_user(user).record_checks("ua.stock.inventory", foreign.id)
        self.assertFalse(self.env["ua.stock.inventory"].with_user(user).search(
            [("id", "=", foreign.id)]), "правило компанії ховає чужий опис")

    # ------------------------------------------------------------------ 002: картка наряду
    def _order(self):
        drone = self.env["product.product"].create({
            "name": "Дрон Шершень", "is_storable": True, "default_code": "SH-7"})
        workcenter = self.env["mrp.workcenter"].create({
            "name": "Пайка", "company_id": self.company.id})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": drone.product_tmpl_id.id, "product_qty": 2.0,
            "company_id": self.company.id,
            "bom_line_ids": [
                (0, 0, {"product_id": self.battery.id, "product_qty": 2.0, "sequence": 1}),
                (0, 0, {"product_id": self.screws[0].id, "product_qty": 8.0, "sequence": 2}),
            ],
            "operation_ids": [(0, 0, {
                "name": "Пайка силової частини", "workcenter_id": workcenter.id,
                "time_cycle_manual": 40.0,
                "ua_steps": "Залудити майданчики\nПрипаяти фази",
                "ua_checks": "Опір між фазами однаковий\nКЗ на корпус немає"})],
        })
        bom.bom_line_ids[0].operation_id = bom.operation_ids[0].id
        order = self.env["mrp.production"].create({
            "product_id": drone.id, "product_qty": 1, "bom_id": bom.id,
            "company_id": self.company.id})
        order.action_confirm()
        return order

    def test_07_workorder_card_and_answers(self):
        """Картка наряду: кроки, пункти перевірки з відповідями, комплектуючі операції."""
        order = self._order()
        workorder = order.workorder_ids
        self.assertEqual(len(workorder), 1, "одна операція - один наряд")

        card = self.Api.workorder_card(workorder.id)
        self.assertEqual(set(card), {"workorder", "steps", "checks", "open", "failed", "parts"})
        self.assertEqual(card["steps"], ["Залудити майданчики", "Припаяти фази"])
        self.assertEqual([row["text"] for row in card["checks"]],
                         ["Опір між фазами однаковий", "КЗ на корпус немає"])
        self.assertEqual((card["open"], card["failed"]), (2, 0))
        # АКБ прив'язані до операції: 2 на партію 2 - одна на виріб; гвинти - ні
        self.assertEqual([(part["code"], part["qty"]) for part in card["parts"]],
                         [("AKB-6S", 1.0)])
        self.assertEqual(card["workorder"]["target"],
                         {"model": "mrp.workorder", "res_id": workorder.id})
        self.assertEqual(card, self._json_safe(card))
        self.assert_reads_only([lambda: self.Api.workorder_card(workorder.id)])

        workorder.button_start()
        workorder.ua_answer_check(2, "fail", "коротке на раму")
        rows = workorder.ua_answer_check(2, "ok")     # повторна відповідь оновлює першу
        self.assertEqual(len(workorder.ua_check_ids), 1)
        self.assertEqual(rows[1]["result"], "ok")
        self.assertEqual(rows[1]["user"][0], self.env.user.id)
        workorder.ua_answer_check(1, "fail")
        card = self.Api.workorder_card(workorder.id)
        self.assertEqual((card["open"], card["failed"]), (0, 1))
        self.assertEqual(card["workorder"]["state"], "progress")

        with self.assertRaises(UserError):
            workorder.ua_answer_check(3, "ok")          # пунктів лише два
        with self.assertRaises(UserError):
            workorder.ua_answer_check(1, "maybe")
        workorder.button_finish()
        with self.assertRaises(UserError):
            workorder.ua_answer_check(1, "ok")          # закритий наряд не приймає

    def test_08_unknown_workorder_says_so(self):
        with self.assertRaises(UserError):
            self.Api.workorder_card(0)
