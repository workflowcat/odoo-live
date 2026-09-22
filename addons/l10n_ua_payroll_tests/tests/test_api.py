# -*- coding: utf-8 -*-
"""Договір читання для інтерфейсу (модель `ua.api`). Тег `ua_api`.

Інтерфейс живе в іншому репозиторії і не може «швидко подивитися в код», коли
відповідь змінила форму. Тому тут перевіряється не текст документації, а сама
відповідь: склад ключів, збіг чисел із моделями, відсутність записів у базу і
права доступу.

Чотири групи:
  1-4  форма відповіді кожного з чотирьох методів;
  5-6  значення дорівнюють тому, що кажуть самі моделі (другого розрахунку немає);
  7    читання нічого не пише - ані нових записів, ані INSERT/UPDATE/DELETE;
  8-10 користувач без кадрових прав дістає AccessError, а не дані.
"""
import json
from datetime import date

from odoo.exceptions import AccessError
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
# Запис пізнається за ПЕРШИМ словом запиту: «... FOR UPDATE» у SELECT записом не є.
WRITE_SQL = ("insert into", "update ", "delete from", "truncate ")


@tagged("post_install", "-at_install", "ua_api")
class TestUaApi(TransactionCase):

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
        self.assertEqual(set(card["alerts"]), {"count", "docs_expiring", "military_needs_check"})
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
        """Жоден з чотирьох методів не створює записів і не робить INSERT/UPDATE/DELETE.

        Колишній scripts/readonly_check.py доводив те саме лічильниками pg_stat на
        стенді. Тут те саме рахується в транзакції: і кількість записів у базі, і
        сам SQL, який ядро встигло виконати."""
        self.env.flush_all()
        watched = ["hr.payslip", "hr.payslip.run", "account.move", "ua.change.log",
                   "ua.period.close", "ua.timesheet.sheet", "ua.staff.list",
                   "ua.report.run", "ua.employee.document", "ir.attachment"]
        before = {model: self.env[model].sudo().search_count([]) for model in watched}

        cursor = self.env.cr
        original = cursor.execute
        seen = []

        def spy(query, params=None, log_exceptions=True):
            seen.append(" ".join(str(query).split()).lower())
            return original(query, params, log_exceptions)

        cursor.execute = spy
        try:
            self.Api.month_summary(self.company.id, YEAR, MONTH)
            self.Api.documents_for_month(self.company.id, YEAR, MONTH)
            self.Api.employee_card(self.employee.id)
            self.Api.reporting_status(self.company.id, YEAR, MONTH)
        finally:
            cursor.execute = original

        writes = [query for query in seen if query.startswith(WRITE_SQL)]
        self.assertEqual(writes, [], "читання виконало запис: %s" % (writes[:1] or ""))

        self.env.flush_all()
        after = {model: self.env[model].sudo().search_count([]) for model in watched}
        self.assertEqual(before, after, "читання створило записи")

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
