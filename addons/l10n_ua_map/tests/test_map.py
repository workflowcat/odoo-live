# -*- coding: utf-8 -*-
"""Карта системи (`ua.api.system_map`). Тег `ua_map`.

Що доводимо:
  1. Файл карти цілий: стани лише done/part/gap, ключі не повторюються, у кожної
     ділянки є пункти, у пункту з дією є модель.
  2. Карта відповідає встановленій системі: для кожного пункту, чиї модулі є,
     модель існує, дія знаходиться, а домени читаються без помилок. Усі розбіжності
     збираються в один список - щоб одна перевірка показала все.
  3. Числа - ті самі, що дає пошук по моделі, у межах компанії.
  4. Нічого не пише.
  5. Користувач без прав отримує карту без чисел там, куди йому не можна, а не помилку.
"""
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

STATUSES = {"done", "part", "gap"}
TOP_KEYS = {"company", "today", "statuses", "summary", "areas", "attention"}
AREA_KEYS = {"key", "title", "icon", "summary", "items"}
ITEM_KEYS = {"key", "title", "status", "status_label", "note", "modules", "missing",
             "installed", "model", "access", "count", "open", "open_label", "attention",
             "target", "open_target"}
STRIP_KEYS = {"area", "area_title", "item", "title", "label", "count", "target"}
WRITE_SQL = ("insert into", "update ", "delete from", "truncate ")


@tagged("post_install", "-at_install", "ua_map")
class TestUaMap(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Api = cls.env["ua.api"]
        cls.company = cls.env.company
        cls.spec = cls.Api._ua_map_spec()

    def _items(self, payload):
        return {item["key"]: item for area in payload["areas"] for item in area["items"]}

    # ------------------------------------------------------------------ 1. файл
    def test_01_file_is_whole(self):
        keys = []
        for area in self.spec["areas"]:
            self.assertTrue(area["items"], area["key"])
            for item in area["items"]:
                keys.append(item["key"])
                self.assertIn(item["status"], STATUSES, item["key"])
                if item.get("action") or item.get("attention"):
                    self.assertTrue(item.get("model"), item["key"])
                if item["status"] != "gap" and item.get("model"):
                    self.assertTrue(item.get("modules"), item["key"])
        self.assertEqual(len(keys), len(set(keys)), "ключі пунктів повторюються")
        area_keys = [area["key"] for area in self.spec["areas"]]
        self.assertEqual(len(area_keys), 12)
        self.assertEqual(len(area_keys), len(set(area_keys)))

    # ------------------------------------------------------------------ 2. відповідність системі
    def test_02_map_matches_installed_system(self):
        installed = self.Api._ua_map_installed()
        self.assertIn("l10n_ua_map", installed)
        self.assertIn("l10n_ua_api", installed)
        today = fields.Date.context_today(self.Api)
        problems = []
        for area in self.spec["areas"]:
            for item in area["items"]:
                if any(name not in installed for name in item.get("modules") or []):
                    continue
                model = item.get("model")
                if not model:
                    continue
                if model not in self.env:
                    problems.append("%s: моделі %s немає" % (item["key"], model))
                    continue
                action = item.get("action")
                if action and not self.env["ir.model.data"]._xmlid_to_res_id(
                        action, raise_if_not_found=False):
                    problems.append("%s: дії %s немає" % (item["key"], action))
                watch = item.get("attention") or {}
                checks = [(model, item.get("domain")), (model, item.get("open"))]
                if watch and not any(name not in installed for name in watch.get("modules") or []):
                    checks.append((watch.get("model") or model, watch.get("domain")))
                for where, domain in checks:
                    if not domain:
                        continue
                    if where not in self.env:
                        problems.append("%s: моделі %s немає" % (item["key"], where))
                        continue
                    try:
                        self.env[where].search_count(
                            self.Api._ua_map_domain(domain, today, self.company))
                    except Exception as error:  # noqa: BLE001 - збираємо всі розбіжності
                        problems.append("%s: домен %s на %s: %s" % (item["key"], domain, where, error))
        self.assertEqual(problems, [], "\n".join(problems))

    # ------------------------------------------------------------------ 3. форма і числа
    def test_03_shape_and_counts(self):
        payload = self.Api.system_map(self.company.id)
        self.assertEqual(json.loads(json.dumps(payload)), payload, "лише прості типи")
        self.assertEqual(set(payload), TOP_KEYS)
        self.assertEqual(payload["today"], fields.Date.to_string(fields.Date.context_today(self.Api)))
        self.assertEqual([area["key"] for area in payload["areas"]],
                         [area["key"] for area in self.spec["areas"]])
        for area in payload["areas"]:
            self.assertEqual(set(area), AREA_KEYS)
            for item in area["items"]:
                self.assertEqual(set(item), ITEM_KEYS, item["key"])
                self.assertEqual(item["status_label"], payload["statuses"][item["status"]])
        for row in payload["attention"]:
            self.assertEqual(set(row), STRIP_KEYS)
            self.assertGreater(row["count"], 0)
        counts = [row["count"] for row in payload["attention"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

        summary = payload["summary"]
        self.assertEqual(summary["items"], sum(len(a["items"]) for a in self.spec["areas"]))
        self.assertEqual(summary["items"], summary["done"] + summary["part"] + summary["gap"])
        self.assertEqual(summary["attention"], sum(counts))

        items = self._items(payload)
        employees = items["employees"]
        self.assertTrue(employees["installed"])
        self.assertEqual(employees["count"], self.env["hr.employee"].search_count(
            [("company_id", "in", [self.company.id, False])]))
        self.assertEqual(employees["target"], {"xmlid": "hr.open_view_employee_list_my"})
        gap = items["marketplace"]
        self.assertEqual((gap["status"], gap["model"], gap["count"], gap["target"]),
                         ("gap", False, False, False))

    def test_04_attention_follows_records(self):
        """Документ, що спливає за 10 днів, піднімає лічильник «Потребує уваги» на один."""
        before = self._items(self.Api.system_map())["employees"]["attention"]["count"]
        employee = self.env["hr.employee"].create({"name": "Карта Тест", "company_id": self.company.id})
        today = fields.Date.context_today(self.Api)
        self.env["ua.employee.document"].create({
            "employee_id": employee.id, "name": "Медична довідка",
            "valid_until": today + timedelta(days=10)})
        self.env["ua.employee.document"].create({
            "employee_id": employee.id, "name": "Паспорт",
            "valid_until": today + timedelta(days=400)})
        payload = self.Api.system_map()
        row = self._items(payload)["employees"]["attention"]
        self.assertEqual(row["count"], before + 1)
        self.assertEqual(row["target"]["model"], "ua.employee.document")
        strip = [r for r in payload["attention"] if r["item"] == "employees"]
        self.assertEqual(strip[0]["count"], before + 1)
        self.assertEqual(strip[0]["area"], "people")

    # ------------------------------------------------------------------ 4. лише читання
    def test_05_reads_only(self):
        self.env.flush_all()
        cursor = self.env.cr
        original = cursor.execute
        seen = []

        def spy(query, params=None, log_exceptions=True):
            seen.append(" ".join(str(query).split()).lower())
            return original(query, params, log_exceptions)

        cursor.execute = spy
        try:
            self.Api.system_map(self.company.id)
        finally:
            cursor.execute = original
        writes = [query for query in seen if query.startswith(WRITE_SQL)]
        self.assertEqual(writes, [], "карта виконала запис: %s" % (writes[:1] or ""))

    # ------------------------------------------------------------------ 5. права
    def test_06_plain_user_sees_map_without_closed_numbers(self):
        user = self.env["res.users"].create({
            "name": "Карта без прав", "login": "ua_map_no_rights",
            "company_id": self.company.id, "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        payload = self.Api.with_user(user).system_map()
        closed = 0
        for item in self._items(payload).values():
            if not item["model"] or not item["installed"]:
                continue
            if not self.env[item["model"]].with_user(user).has_access("read"):
                closed += 1
                self.assertFalse(item["access"], item["key"])
                self.assertIs(item["count"], False, item["key"])
                self.assertIs(item["open"], False, item["key"])
        self.assertTrue(closed, "у простого користувача мали б бути закриті пункти")
        military = self._items(payload)["military"]
        self.assertIs(military["attention"], False, "звірка військового обліку - лише кадровикам")
