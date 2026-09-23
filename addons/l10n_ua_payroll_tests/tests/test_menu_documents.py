# -*- coding: utf-8 -*-
"""Документи, що виросли з меню-діалогів. Тег `ua_documents`.

Рішення Andrii від 2026-09-22: пункт меню відкриває сторінку, діалог буває лише з
кнопки, а річ із періодом і рядками - документ зі своїм списком. Три майстри стали
документами: довідка про доходи, перевірка документів, зведення ПДВ за період.

Для кожного доводимо те саме, що й для решти документів місяця: `ua_compose()` складає
запис із рядками, `_checks()` дає рядки перевірок, друк рендериться.
"""
from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

YEAR, MONTH = 2026, 3


@tagged("post_install", "-at_install", "ua_documents")
class TestMenuDocuments(TransactionCase):

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
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.employee = cls.env["hr.employee"].create({
            "name": "Довідкова Оксана", "company_id": cls.company.id,
            "ua_rnokpp": "3111111111", "ua_main_job": True, "ua_psp": "none",
            "ua_esv_category": "standard", "ua_contract_kind": "employment",
            "ua_fte": "1", "ua_index_off": True, "ua_mil_status": "liable",
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })
        cls.employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 21000.0, "contract_date_start": "2025-01-01", "date_version": "2025-01-01",
            "struct_id": cls.structure.id,
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })

    def _render(self, report_xmlid, record):
        report = self.env.ref(report_xmlid)
        html, _kind = report._render_qweb_html(report.report_name, record.ids)
        return html

    def _posted_payslip(self):
        """Один проведений листок за березень: довідці про доходи потрібні саме такі."""
        slip = self.env["hr.payslip"].create({
            "employee_id": self.employee.id,
            "date_from": date(YEAR, MONTH, 1),
            "date_to": date(YEAR, MONTH, 31),
            "struct_id": self.structure.id,
            "name": self.employee.name,
            "company_id": self.company.id,
        })
        slip.onchange_employee()
        slip.compute_sheet()
        slip.action_payslip_done()
        self.assertEqual(slip.state, "done")
        self.assertTrue(slip.line_ids, "листок порахований")
        return slip

    # ------------------------------------------------------------------ довідка про доходи
    def test_01_income_certificate_is_a_document(self):
        """ua.income.certificate: ua_compose складає, _checks() дає рядки, друк рендериться."""
        self._posted_payslip()
        doc = self.env["ua.income.certificate"].ua_compose(
            self.company, YEAR, MONTH, employee=self.employee)

        self.assertEqual(doc.employee_id, self.employee)
        self.assertEqual(doc.state, "draft")
        self.assertTrue(doc.line_ids, "рядки довідки заповнені з проведених листків")
        self.assertGreater(doc.total_gross, 0.0, "нарахування за місяць більші за нуль")

        rows = doc._checks()
        self.assertTrue(rows, "перевірки дають рядки")
        self.assertTrue(all("level" in row and "text" in row for row in rows))

        doc.action_confirm()
        self.assertEqual(doc.state, "issued")
        self.assertTrue(doc.number, "видана довідка має номер із послідовності")

        html = self._render("l10n_ua_payroll_reports.action_report_ua_income_certificate", doc)
        self.assertIn(b"\xd0\x94\xd0\x9e\xd0\x92\xd0\x86\xd0\x94\xd0\x9a\xd0\x90", html)

    def test_02_income_certificate_list_is_the_register(self):
        """Список довідок і є реєстром: окремої моделі реєстру більше немає."""
        self.assertNotIn("ua.income.certificate.register", self.env)
        self.assertNotIn("ua.income.certificate.wizard", self.env)
        action = self.env.ref("l10n_ua_payroll_reports.action_ua_income_certificate")
        self.assertEqual(action.res_model, "ua.income.certificate")
        self.assertNotEqual(action.target, "new", "пункт меню відкриває сторінку")

    # ------------------------------------------------------------------ перевірка документів
    def test_03_doc_check_is_a_document(self):
        """ua.hr.doc.check: ua_compose складає, _checks() дає рядки, друк рендериться."""
        doc = self.env["ua.hr.doc.check"].ua_compose(self.company)

        self.assertEqual(doc.state, "draft")
        self.assertTrue(doc.line_ids, "рядки - працівник на кожну вимогу довідника")
        self.assertGreaterEqual(doc.employee_count, 1)
        self.assertIn(self.employee, doc.line_ids.mapped("employee_id"))

        rows = doc._checks()
        self.assertTrue(rows)
        self.assertTrue(all("level" in row and "text" in row for row in rows))

        doc.action_confirm()
        self.assertEqual(doc.state, "confirmed")

        matrix = doc.matrix()
        self.assertTrue(matrix["employees"] and matrix["requirements"])

        html = self._render("l10n_ua_hr_orders.action_report_ua_hr_doc_pack", doc)
        self.assertIn(self.employee.name.encode(), html)

    def test_04_doc_pack_wizard_is_gone(self):
        """Майстра «Перевірка документів» більше немає, а меню веде на список документів."""
        self.assertNotIn("ua.hr.doc.pack.wizard", self.env)
        action = self.env.ref("l10n_ua_hr_orders.action_ua_hr_doc_check")
        self.assertEqual(action.res_model, "ua.hr.doc.check")
        self.assertNotEqual(action.target, "new")

    # ------------------------------------------------------------------ журнал реєстрації
    def test_05_order_register_is_a_list_of_orders(self):
        """Журнал реєстрації - той самий перелік наказів, а не окремий документ-знімок."""
        self.assertNotIn("ua.hr.order.register.wizard", self.env)
        action = self.env.ref("l10n_ua_hr_orders.action_ua_hr_order_register")
        self.assertEqual(action.res_model, "ua.hr.order")
        self.assertNotEqual(action.target, "new")
        report = self.env.ref("l10n_ua_hr_orders.action_report_ua_hr_order_register")
        self.assertEqual(report.model, "ua.hr.order")

    # ------------------------------------------------------------------ зведення ПДВ
    def test_06_vat_period_is_a_record(self):
        """ua.vat.period: запис на період зі своїм списком, а не разовий розрахунок."""
        self.assertNotIn("ua.vat.cabinet", self.env)
        period = self.env["ua.vat.period"].ua_compose(self.company, YEAR, MONTH)
        self.assertTrue(period.id and period.name)
        self.assertEqual(period.date_from, date(YEAR, MONTH, 1))
        self.assertEqual(period.date_to, date(YEAR, MONTH, 31))
        self.assertTrue(period.problems, "рядок «що не доробили» заповнений завжди")
        self.assertEqual(period.read(["name"])[0]["name"], period.name,
                         "запис читається з бази, а не живе в пам'яті")

    # ------------------------------------------------------------------ військовий облік
    def test_07_military_documents_compose_without_wizards(self):
        """Майстрів військового обліку немає; ua_compose складає документи сам."""
        for model in ("ua.military.list.wizard", "ua.military.notice.wizard",
                      "ua.military.reserved.wizard", "ua.staff.list.wizard",
                      "ua.timesheet.wizard", "ua.payroll.advance.wizard",
                      "ua.bank.ops.wizard", "ua.vat.cabinet"):
            self.assertNotIn(model, self.env, "%s видалено" % model)

        self.employee.write({"ua_mil_tcc": "Львівський міський ТЦК та СП"})
        docs = self.env["ua.military.list"].ua_compose(self.company, YEAR, MONTH)
        self.assertTrue(docs, "без ТЦК складається по одному списку на кожен ТЦК")
        self.assertTrue(docs[0].line_ids)
        self.assertTrue(docs[0]._checks())

        notice = self.env["ua.military.notice"].ua_compose(self.company, YEAR, MONTH)
        self.assertEqual(notice.date_from, date(YEAR, MONTH, 1))
        self.assertTrue(notice._checks())
