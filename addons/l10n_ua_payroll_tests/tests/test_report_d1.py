# -*- coding: utf-8 -*-
"""Д1 об'єднаної звітності: ознаки з договору, мобілізовані без листка, коригування за минулий
місяць і правка рядків перед формуванням файлів.

Графи Д1 за бланком: 21 - основне місце роботи, 22 - неповний час, 23 - спецстаж, 24 - нове
робоче місце, 25 - ознака рядка (0 - ввести, 1 - вилучити), 26 - нефіксований робочий час.
Суми тут не перевіряються: їх тримають еталонні сценарії. Тут - які рядки і з якими графами
лягають у файл.

Запуск: чиста база, тег ua_reporting.
"""
import base64
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_payroll_reports.wizards.ua_report_wizard import D1_COLS, D6_COLS

YEAR, MONTH = 2026, 10
OCT_START, OCT_END = date(YEAR, 10, 1), date(YEAR, 10, 31)
SEP_START, SEP_END = date(YEAR, 9, 1), date(YEAR, 9, 30)


@tagged("post_install", "-at_install", "ua_reporting")
class TestUaReportD1(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({"company_registry": "12345678", "ua_sti_code": "2650",
                           "ua_director_rnokpp": "3000000001", "ua_director_name": "Директор Тестовий"})
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.calendar = cls.company.resource_calendar_id
        cls.rnokpp = 3000000100

    @classmethod
    def _employee(cls, name, wage=20000.0, **values):
        cls.rnokpp += 1
        vals = {"name": name, "company_id": cls.company.id, "ua_contract_kind": "employment", "ua_main_job": True,
                "ua_rnokpp": str(cls.rnokpp), "resource_calendar_id": cls.calendar.id}
        vals.update(values)
        employee = cls.env["hr.employee"].create(vals)
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": wage, "date_version": date(YEAR, 1, 1), "contract_date_start": date(YEAR, 1, 1),
            "struct_id": cls.structure.id, "resource_calendar_id": cls.calendar.id})
        return employee

    def _leave(self, employee, code, date_from, date_to):
        leave_type = self.env["hr.leave.type"].search([("work_entry_type_id.code", "=", code)], limit=1)
        self.assertTrue(leave_type, "немає виду відсутності %s" % code)
        leave = self.env["hr.leave"].with_context(leave_skip_state_check=True, mail_notrack=True).create({
            "employee_id": employee.id, "holiday_status_id": leave_type.id,
            "request_date_from": date_from, "request_date_to": date_to})
        leave.sudo().action_approve()
        return leave

    def _done_slip(self, employee, date_from=OCT_START, date_to=OCT_END, **values):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id, "date_from": date_from, "date_to": date_to,
            "struct_id": self.structure.id, "name": employee.name, "company_id": self.company.id})
        slip.onchange_employee()
        slip.compute_sheet()
        slip.write(dict(values, state="done"))   # без проводки: звітності потрібен лише стан листка
        return slip

    def _wizard(self, month=MONTH):
        return self.env["ua.payroll.report.wizard"].create({"company_id": self.company.id, "year": YEAR, "month": month})

    def _params(self, wizard):
        return self.env["ua.payroll.param"].get_all(wizard._period()[1], self.company)

    @staticmethod
    def _rows_of(rows, employee):
        return [row for row in rows if row.get("employee_id") == employee.id]

    def test_marks_from_contract_version(self):
        welder = self._employee("Зварник (тест)")
        welder.version_id.write({"ua_special_seniority": True, "ua_special_seniority_code": "ЗП1",
                                 "ua_new_workplace": True, "ua_unfixed_hours": True})
        slip = self._done_slip(welder)
        wizard = self._wizard()
        rows, _person = wizard._person_rows(slip, self._params(wizard))
        main = rows[0]
        self.assertEqual((main["G21"], main["G23"], main["G24"], main["G26"]), ("1", "1", "1", "1"))
        text = wizard._text_row(main, D1_COLS)
        self.assertEqual(text["G25"], "0", "графа 25 - ознака рядка: 0, рядок на введення")
        self.assertEqual(text["G26"], "1", "графа 26 - нефіксований робочий час, не ознака рядка")

        welder.version_id.ua_new_workplace_until = date(YEAR, 9, 30)
        rows, _person = wizard._person_rows(slip, self._params(wizard))
        self.assertEqual(rows[0]["G24"], "0", "строк нового робочого місця минув до звітного місяця")

    def test_mobilised_without_slip_in_d1_not_in_4df(self):
        worker = self._employee("Працює (тест)")
        self._done_slip(worker)
        soldier = self._employee("На військовій службі (тест)")
        self._leave(soldier, "MIL", date(YEAR, 8, 10), date(YEAR, 12, 31))
        wizard = self._wizard()
        persons, rows, _params = wizard._collect()
        soldier_rows = self._rows_of(rows, soldier)
        self.assertEqual(len(soldier_rows), 1, "людина на військовій службі є в Д1 одним рядком")
        row = soldier_rows[0]
        self.assertEqual(row["G8"], "1")
        self.assertEqual(row["G14"], 31, "графа 14 - усі календарні дні трудових відносин")
        self.assertIsNone(row["G13"], "дні служби - не відпустка без збереження зарплати")
        self.assertEqual((row["G16"], row["G17"], row["G20"]), (0.0, 0.0, 0.0))
        self.assertFalse(self._rows_of(wizard._4df_rows(persons), soldier), "доходу не було: у 4ДФ людини немає")
        self.assertTrue(self._rows_of(wizard._4df_rows(persons), worker))

        X = self.env["ua.dps.xml"]
        _name, data = X.build(self.company, "J05", "101", "11", 1, MONTH, YEAR, wizard._build_d1(rows),
                              c_doc_cnt=1, c_doc_stan=1, fill_date=date(YEAR, 11, 10))
        self.assertFalse(X.validate(data, "J0510111"), "Д1 з рядком без сум відповідає схемі")

    def test_mobilised_slip_without_pay_has_no_minimum(self):
        soldier = self._employee("Служить весь місяць (тест)")
        self._leave(soldier, "MIL", date(YEAR, 8, 10), date(YEAR, 12, 31))
        slip = self._done_slip(soldier)
        lines = {line.code: line.total for line in slip.line_ids}
        self.assertFalse(lines.get("GROSS"), "за місяць служби нічого не нараховано")
        self.assertFalse(lines.get("ESV"), "без нарахувань мінімального ЄСВ немає")
        wizard = self._wizard()
        rows, _person = wizard._person_rows(slip, self._params(wizard))
        self.assertIsNone(rows[0]["G18"], "різниці до мінімальної зарплати теж немає")

    def test_late_sick_note_goes_to_its_month(self):
        nurse = self._employee("Лікарняний за вересень (тест)")
        self._leave(nurse, "SICK", date(YEAR, 9, 14), date(YEAR, 9, 18))
        late = self._done_slip(nurse, SEP_START, SEP_END, ua_report_month=date(YEAR, 10, 15))
        self.assertEqual(late.ua_report_month, OCT_START, "місяць звітності - перше число")
        october = self._done_slip(nurse)

        self.assertIn(late, self._wizard()._payslips(), "коригування звітують у жовтні")
        self.assertNotIn(late, self._wizard(9)._payslips(), "у вересні його вже немає")

        _persons, rows, _params = self._wizard()._collect()
        mine = self._rows_of(rows, nurse)
        sick = [row for row in mine if row["G8"] == "29"]
        self.assertEqual(len(sick), 1)
        self.assertEqual((sick[0]["G101"], sick[0]["G102"], sick[0]["G9"]), (9, YEAR, "13"),
                         "лікарняні за вересень - рядком за вересень з кодом типу нарахувань 13")
        main = [row for row in mine if row["G8"] == "1"]
        self.assertEqual(len(main), 1, "два листки місяця - один рядок категорії 1")
        self.assertEqual(main[0]["G101"], MONTH)
        salaries = sum(slip.line_ids.filtered(lambda line: line.code == "GROSS").total for slip in (late, october))
        sick_total = sum(late.line_ids.filtered(lambda line: line.code in ("SICK_EMP", "SICK_PFU")).mapped("total"))
        self.assertAlmostEqual(main[0]["G16"], round(salaries - sick_total, 2), places=2)

        with self.assertRaises(ValidationError):
            late.ua_report_month = date(YEAR, 8, 1)

    def test_vacation_into_next_month_ktn_10(self):
        """Відпустка 26 жовтня - 8 листопада: жовтневий листок платить усі 14 днів (ст. 21 ЗУ «Про
        відпустки»), Д1 жовтня має рядки КТН 10 за жовтень і за листопад, листопадовий листок ці дні
        вже не оплачує."""
        rested = self._employee("Відпустка через місяць (тест)")
        rested.sudo()._ua_ensure_leave_allocations()   # без нарахування днів hr_holidays відпустку не проведе
        self._leave(rested, "VAC", date(YEAR, 10, 26), date(YEAR, 11, 8))
        october = self._done_slip(rested)
        october._ua_store_vac_ahead()
        self.assertEqual(october.ua_vac_ahead["%d-11" % YEAR]["days"], 8)
        lines = {line.code: line.total for line in october.line_ids}
        day = october._ua_average_day()
        self.assertAlmostEqual(lines["VAC"], round(14 * day, 2), places=2, msg="жовтень оплачує всі 14 днів")

        wizard = self._wizard()
        rows, _person = wizard._person_rows(october, self._params(wizard))
        vacation = [row for row in rows if row["G9"] == "10"]
        self.assertEqual([(row["G101"], row["G102"]) for row in vacation], [(10, YEAR), (11, YEAR)])
        self.assertAlmostEqual(vacation[1]["G16"], round(8 * day, 2), places=2)
        self.assertAlmostEqual(sum(row["G16"] for row in rows), lines["GROSS"], places=2,
                               msg="рядки Д1 разом - усе нараховане за листок")
        self.assertAlmostEqual(sum(row["G20"] for row in rows), lines["ESV"], places=2)
        self.assertTrue(all(row["G14"] is None for row in vacation), "дні трудових відносин - лише в основному рядку")
        X = self.env["ua.dps.xml"]
        _name, data = X.build(self.company, "J05", "101", "11", 1, MONTH, YEAR, wizard._build_d1(rows),
                              c_doc_cnt=1, c_doc_stan=1, fill_date=date(YEAR, 11, 10))
        self.assertFalse(X.validate(data, "J0510111"), "Д1 з рядками КТН 10 відповідає схемі")

        november = self._done_slip(rested, date(YEAR, 11, 1), date(YEAR, 11, 30))
        self.assertFalse(november.line_ids.filtered(lambda line: line.code == "VAC"),
                         "дні листопада вже оплатив жовтневий листок")

    def test_special_seniority_d6(self):
        """Д6: людина зі спецстажем - рядок з кодом підстави, днями періоду без відпустки без
        збереження зарплати і нормою в календарних днях; без коду підстави рядка немає."""
        doctor = self._employee("Лікар (тест)")
        doctor.version_id.write({"ua_special_seniority": True, "ua_special_seniority_code": "ЗПЗ055Е2",
                                 "ua_special_attest_number": "17-к", "ua_special_attest_date": date(2024, 3, 1)})
        self._leave(doctor, "UNPAID", date(YEAR, 10, 13), date(YEAR, 10, 15))
        no_code = self._employee("Спецстаж без коду (тест)")
        no_code.version_id.ua_special_seniority = True
        plain = self._employee("Без спецстажу (тест)")
        wizard = self._wizard()
        rows = wizard._d6_rows()
        self.assertEqual([row["employee_id"] for row in rows], [doctor.id], "у Д6 - лише люди з кодом підстави")
        row = rows[0]
        self.assertEqual((row["G7S"], row["G9"], row["G10"], row["G11"], row["G131"]), ("ЗПЗ055Е2", 1, 31, 28, 31))
        self.assertEqual(row["G14S"], "17-к")
        self.assertNotIn(plain.id, [r["employee_id"] for r in rows])
        text = wizard._text_row(row, D6_COLS)
        self.assertEqual((text["G81S"], text["G17"], text["G15D"]), (doctor._ua_name_parts()[0], "0", "01032024"))
        X = self.env["ua.dps.xml"]
        _name, data = X.build(self.company, "J05", "106", "11", 1, MONTH, YEAR, wizard._build_d6(rows),
                              c_doc_cnt=1, c_doc_stan=1, fill_date=date(YEAR, 11, 10))
        self.assertFalse(X.validate(data, "J0510611"), "Д6 відповідає схемі")

    def test_edited_rows_go_to_files(self):
        worker = self._employee("Рядок поправлено (тест)")
        self._done_slip(worker)
        wizard = self._wizard()
        wizard.action_collect()
        self.assertTrue(wizard.lines_edited)
        line = wizard.d1_line_ids.filtered(lambda r: r.employee_id == worker)
        self.assertEqual(len(line), 1)
        self.assertTrue(wizard.df_line_ids.filtered(lambda r: r.employee_id == worker))
        line.write({"g24": "1", "g16": line.g16 + 100.0})

        wizard.action_generate()
        d1_file = wizard.result_ids.filtered(lambda a: "J0510111" in (a.name or ""))
        self.assertEqual(len(d1_file), 1)
        rows = wizard._rows_from_xml(base64.b64decode(d1_file.datas), D1_COLS)
        mine = [row for row in rows if row["G7S"] == worker.ua_rnokpp]
        self.assertEqual(mine[0]["G24"], "1", "правка ознаки дійшла до файлу")
        self.assertIn("поправлених вручну", wizard.log)
        self.assertIn("Увага", wizard.log, "сума графи 16 розійшлася з листками - про це сказано")

        wizard.action_drop_lines()
        self.assertFalse(wizard.lines_edited)
        self.assertFalse(wizard.d1_line_ids)
