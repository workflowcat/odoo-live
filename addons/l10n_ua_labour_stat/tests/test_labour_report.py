# -*- coding: utf-8 -*-
"""Звіт із праці 1-ПВ: хто в якому рядку і що до фонду не входить.

Вересень 2026: дві штатні людини (жінка з липня, чоловік з лікарняним), зовнішній сумісник,
виконавець за договором ЦПХ і мобілізований працівник. Суми листків тримають еталонні сценарії;
тут - що лікарняні поза фондом, мобілізований у фонді всіх, але не штатних і не в середньообліковій,
сумісник і ЦПХ - лише у фонді всіх, а квартальний звіт рахує рух кадрів за підставою звільнення.

Запуск: чиста база, тег ua_labour_stat.
"""
from datetime import date

from odoo.tests import TransactionCase, tagged

YEAR = 2026
SEP_START, SEP_END = date(YEAR, 9, 1), date(YEAR, 9, 30)


@tagged("post_install", "-at_install", "ua_labour_stat")
class TestUaLabourReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.calendar = cls.company.resource_calendar_id
        cls.rnokpp = 3000000500
        cls.Report = cls.env["ua.labour.report"]

    def _people(self):
        cls = type(self)
        self.woman = cls._employee("Штатна (тест)", 20000.0, start=date(YEAR, 7, 1), sex="female")
        self.man = cls._employee("Штатний з лікарняним (тест)", 30000.0, sex="male")
        self.external = cls._employee("Зовнішній сумісник (тест)", 10000.0, ua_main_job=False)
        self.civil = cls._employee("Виконавець ЦПХ (тест)", 0.0, ua_contract_kind="gph", ua_main_job=False)
        self.soldier = cls._employee("Мобілізований (тест)", 25000.0)

    def _report(self, kind, year, period):
        """Звіт і цифри до тестових людей (база)."""
        report = self.Report.create({"company_id": self.company.id, "kind": kind, "year": year, "period": period})
        base = report._compute_month() if kind == "month" else report._compute_quarter()
        return report, base

    def _refill(self, report):
        """Табелі періоду створено ще для бази: заповнити заново, з тестовими людьми."""
        self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company.id), ("department_id", "=", False), ("year", "=", report.year),
            ("month", "in", [d.month for d in report._month_starts()])]).action_refill()

    @classmethod
    def _employee(cls, name, wage, start=date(YEAR, 1, 1), end=None, **values):
        cls.rnokpp += 1
        vals = {"name": name, "company_id": cls.company.id, "ua_contract_kind": "employment", "ua_main_job": True,
                "ua_rnokpp": str(cls.rnokpp), "resource_calendar_id": cls.calendar.id}
        vals.update(values)
        employee = cls.env["hr.employee"].create(vals)
        version = {"wage": wage, "date_version": start, "contract_date_start": start,
                   "struct_id": cls.structure.id, "resource_calendar_id": cls.calendar.id}
        if end:
            version["contract_date_end"] = end
        employee.version_id.with_context(sync_contract_dates=True).write(version)
        return employee

    def _leave(self, employee, code, date_from, date_to):
        leave_type = self.env["hr.leave.type"].search([("work_entry_type_id.code", "=", code)], limit=1)
        self.assertTrue(leave_type, "немає виду відсутності %s" % code)
        leave = self.env["hr.leave"].with_context(leave_skip_state_check=True, mail_notrack=True).create({
            "employee_id": employee.id, "holiday_status_id": leave_type.id,
            "request_date_from": date_from, "request_date_to": date_to})
        leave.sudo().action_approve()
        return leave

    def _slip(self, employee, date_from=SEP_START, date_to=SEP_END, gph=0.0):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id, "date_from": date_from, "date_to": date_to,
            "struct_id": self.structure.id, "name": employee.name, "company_id": self.company.id})
        slip.onchange_employee()
        if gph:
            self.env["hr.payslip.input"].create({"payslip_id": slip.id, "contract_id": slip.contract_id.id,
                                                 "code": "GPH", "name": "Винагорода ЦПХ", "amount": gph})
        slip.compute_sheet()
        slip.write({"state": "done"})   # без проводки: звіту потрібен лише стан листка
        return slip

    @staticmethod
    def _sum(slips, codes):
        return sum(slips.line_ids.filtered(lambda line: line.code in codes).mapped("total"))

    def _september(self):
        self._people()
        self._leave(self.man, "SICK", date(YEAR, 9, 14), date(YEAR, 9, 18))
        self._leave(self.soldier, "MIL", date(YEAR, 8, 10), date(YEAR, 12, 31))
        slips = {key: self._slip(emp) for key, emp in
                 (("woman", self.woman), ("man", self.man), ("external", self.external), ("soldier", self.soldier))}
        slips["civil"] = self._slip(self.civil, gph=8000.0)
        return slips

    # ---- місячна ---------------------------------------------------------------------------
    def test_month_rows(self):
        report, base = self._report("month", YEAR, 9)
        slips = self._september()
        sick = ("SICK_EMP", "SICK_PFU")
        self.assertTrue(self._sum(slips["man"], sick), "у листку є лікарняні")
        staff = slips["woman"] | slips["man"]
        staff_fund = self._sum(staff, ("GROSS",)) - self._sum(staff, sick)
        all_fund = staff_fund + self._sum(slips["external"] | slips["civil"] | slips["soldier"], ("GROSS",))

        self.assertEqual((report.date_from, report.date_to), (SEP_START, SEP_END))
        self._refill(report)
        report.action_compute()
        self.assertAlmostEqual(report.r1070 - base["r1070"], staff_fund / 1000.0, delta=0.11,
                               msg="фонд штатних: без лікарняних, сумісника, ЦПХ і мобілізованого")
        self.assertAlmostEqual(report.r1020 - base["r1020"], all_fund / 1000.0, delta=0.11,
                               msg="фонд усіх: штатні, сумісник, ЦПХ")
        self.assertGreater(report.r1020, report.r1070)
        self.assertEqual(report.r1040 - base["r1040"], 2, "мобілізований і зовнішній сумісник - поза середньообліковою")
        sheet = self.env["ua.timesheet.sheet"]._ua_ensure_for(self.company, YEAR, 9)
        hours = sum(sheet.line_ids.filtered(lambda l: l.employee_id in (self.woman | self.man)).mapped("hours"))
        self.assertAlmostEqual(report.r1060 - base["r1060"], hours, delta=1, msg="людино-години штатних з табеля")
        self.assertGreater(report.r1030, 0.0)
        self.assertLessEqual(report.r1030, round(report.r1020 * 0.18, 1) + 0.1, "ПДФО не більше 18 % фонду")
        texts = " ".join(check["text"] for check in report._checks())
        self.assertNotIn("більший за фонд", texts)

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_labour_stat.action_report_ua_labour", report.ids)[0].decode()
        self.assertIn("1070", html)
        self.assertIn("Середньооблікова кількість штатних працівників", html)

    def test_rule_class_moves_amounts(self):
        basic = self.env["hr.salary.rule"].search([("code", "=", "BASIC")])
        basic.ua_pv_class = "none"
        report, base = self._report("month", YEAR, 9)
        slips = self._september()
        self._refill(report)
        report.action_compute()
        without_basic = (self._sum(slips["woman"] | slips["man"], ("GROSS",))
                         - self._sum(slips["woman"] | slips["man"], ("SICK_EMP", "SICK_PFU", "BASIC")))
        self.assertAlmostEqual(report.r1070 - base["r1070"], without_basic / 1000.0, delta=0.11,
                               msg="клас правила в картці правила керує рядком")

    # ---- квартальна ---------------------------------------------------------------------
    def test_quarter_moves_and_fund(self):
        report, base = self._report("quarter", YEAR, 3)
        organisation = self._employee("Скорочений (тест)", 15000.0, end=date(YEAR, 8, 31))
        organisation.version_id.ua_dismissal_basis = "п. 1 ст. 40 КЗпП"
        left = self._employee("Пішов за власним бажанням (тест)", 15000.0, end=date(YEAR, 7, 15))
        left.version_id.ua_dismissal_basis = "ст. 38 КЗпП"
        slips = self._september()
        for month in (7, 8):
            self._slip(self.civil, date(YEAR, month, 1), date(YEAR, month, 31), gph=8000.0)
            self._slip(self.external, date(YEAR, month, 1), date(YEAR, month, 31))

        self.assertEqual((report.date_from, report.date_to), (date(YEAR, 7, 1), SEP_END))
        self._refill(report)
        report.action_compute()

        def delta(field):
            return report[field] - base[field]
        self.assertEqual(delta("r3020"), 1, "прийнято з липня")
        self.assertEqual((delta("r3040"), delta("r3050"), delta("r3060")), (2, 1, 1),
                         "звільнено двоє: скорочення (п. 1 ст. 40) і власне бажання (ст. 38)")
        self.assertEqual(delta("r3070"), 3, "на кінець кварталу: дві штатні людини і мобілізований")
        self.assertEqual(report.r3080, 0, "неповний час - лише в IV кварталі")
        self.assertAlmostEqual(report.r5010, report.r5020 + report.r5030 + report.r5060, delta=0.05)
        self.assertGreater(delta("r5020"), 0.0)
        self.assertEqual(delta("r7010_1"), 1, "одна жінка в середньообліковій")
        self.assertAlmostEqual(delta("r7010_2"), self._sum(slips["woman"], ("GROSS",)) / 1000.0, delta=0.11)
        self.assertEqual(delta("r7040_1"), 1, "один виконавець ЦПХ щомісяця")
        self.assertAlmostEqual(delta("r7040_2"), 24.0, delta=0.11, msg="3 × 8 000 грн")
        self.assertEqual(delta("r7030_1"), 1, "зовнішній сумісник щомісяця")

    def test_year_end_part_time_and_agreements(self):
        previous = self.Report.create({"company_id": self.company.id, "kind": "quarter", "year": YEAR - 1,
                                       "period": 4, "r8010": 1, "r8020": 7, "r8030": 8000.0})
        report, base = self._report("quarter", YEAR, 4)
        part = self._employee("Пів ставки (тест)", 10000.0)
        part.ua_fte = "0.5"
        self._refill(report)
        report.action_compute()
        self.assertEqual(report.r3080 - base["r3080"], 1, "на 31 грудня одна людина на неповній ставці")
        self.assertEqual((report.r8010, report.r8020, report.r8030), (1, 7, 8000.0),
                         "колективний договір - з минулорічного звіту")
        self.assertTrue(previous)
