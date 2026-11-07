# -*- coding: utf-8 -*-
"""Права доступу після аудиту безпеки 2026-10. Тег `ua_security`.

Кожен тест доводить одне правило з двох боків: той, кому не можна, дістає AccessError
(або не бачить запису), а той, чия це робота, і далі її робить. Демо-даних тести не
потребують: усе, що читають, створюють самі в транзакції.

  слід розрахунку (ua.explain.trace)   - лише через право на сам листок;
  журнал змін (ua.change.log)          - кадри і бухгалтерія, кожен свою ділянку;
  зведення ПДВ, касова книга           - пише бухгалтер;
  правила компанії                     - запис чужої компанії не видно;
  міст інтеграцій (bp.bridge)          - транспорт приватний, шлях лише /api/ на своєму хості;
  статус постачальника                 - «перевірено» ставить лише керівник;
  нарахування відпусток, звірка з ТЦК  - кадровик;
  довідка про доходи, П-2              - зарплата і кадри відповідно;
  анкета компанії                      - пише лише дозволені поля компанії;
  адреса банку, XML ДПС                - лише хости банків; сутності XML не розкриваються;
  скани документів працівника          - кадровик і сам працівник, прапорець OCA не відкриває чужі.
"""
import base64
import os
import tempfile
from unittest.mock import MagicMock, patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

YEAR, MONTH = 2026, 3


@tagged("post_install", "-at_install", "ua_security")
class TestUaSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other = cls.env["res.company"].create({"name": "Інша компанія (тест прав)"})
        cls.plain = cls._user("plain", [])
        cls.hr = cls._user("hr", ["hr.group_hr_user"])
        cls.accountant = cls._user("acc", ["account.group_account_user"])
        cls.payroll = cls._user("payroll", ["payroll.group_payroll_manager"])
        cls.employee = cls.env["hr.employee"].create({
            "name": "Правова Олена", "company_id": cls.company.id})

    # ------------------------------------------------------------------ службове
    @classmethod
    def _user(cls, key, group_xmlids):
        """Внутрішній користувач однієї компанії з переліченими групами."""
        groups = [cls.env.ref("base.group_user").id] + [cls.env.ref(x).id for x in group_xmlids]
        return cls.env["res.users"].create({
            "name": "Тест прав %s" % key, "login": "ua_security_%s" % key,
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, groups)],
        })

    def _log(self, area, company=None, name="Запис"):
        return self.env["ua.change.log"].sudo().with_context(ua_no_log=True).create({
            "company_id": (company or self.company).id, "area": area, "operation": "write",
            "model_name": "hr.employee", "res_id": self.employee.id, "res_name": name,
            "what": "Оклад", "old_value": "20000", "new_value": "25000",
            "year": YEAR, "month": MONTH,
        })

    def _slip(self):
        """Листок місяця тим самим шляхом, що й у test_api: табель, пакет, розрахунок."""
        company = self.company
        ukraine = self.env.ref("base.ua")
        if company.country_id != ukraine:
            company.country_id = ukraine
        if company.chart_template != "ua_psbo":
            self.env["account.chart.template"].try_loading("ua_psbo", company, install_demo=False)
        company.invalidate_recordset()
        structure = self.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        employee = self.env["hr.employee"].create({
            "name": "Листкова Ірина", "company_id": company.id,
            "ua_rnokpp": "3555555555", "ua_main_job": True, "ua_psp": "none",
            "ua_esv_category": "standard", "ua_contract_kind": "employment",
            "ua_fte": "1", "ua_index_off": True,
            "resource_calendar_id": company.resource_calendar_id.id,
        })
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 21000.0, "contract_date_start": "2025-01-01",
            "struct_id": structure.id,
            "resource_calendar_id": company.resource_calendar_id.id,
        })
        self.env["hr.payslip.run"].ua_prepare_month(company, YEAR, MONTH)
        slip = self.env["hr.payslip"].search([("employee_id", "=", employee.id)], limit=1)
        self.assertTrue(slip, "підготовка місяця створила листок")
        return slip

    # ------------------------------------------------------------------ 1. слід розрахунку
    def test_01_trace_is_not_readable_by_plain_user(self):
        Trace = self.env["ua.explain.trace"]
        Trace.sudo().create({"model_name": "hr.payslip", "res_id": 0, "payload": "{}",
                             "company_id": self.company.id})
        with self.assertRaises(AccessError):
            Trace.with_user(self.plain).search([])
        with self.assertRaises(AccessError):
            Trace.with_user(self.hr).search([])
        self.assertTrue(Trace.with_user(self.payroll).search([]), "керівник зарплати читає слід")

    def test_02_explain_checks_access_to_the_payslip(self):
        slip = self._slip()
        self.env["ua.explain.trace"].sudo().create({
            "model_name": "hr.payslip", "res_id": slip.id, "company_id": self.company.id,
            "payload": '{"steps": [], "totals": {"gross": 21000.0}}'})
        Explain = self.env["ua.explain"]
        for user in (self.plain, self.hr, self.accountant):
            with self.assertRaises(AccessError, msg=user.login):
                Explain.with_user(user).explain("hr.payslip", slip.id, when="frozen")
            with self.assertRaises(AccessError, msg=user.login):
                Explain.with_user(user).explain("hr.payslip", slip.id, when="now")
        answer = Explain.with_user(self.payroll).explain("hr.payslip", slip.id, when="frozen")
        self.assertEqual(answer["state"], "committed")
        self.assertEqual(answer["totals"]["gross"], 21000.0)
        # запису вже немає - слід бачить лише той, хто читає сліди напряму
        with self.assertRaises(AccessError):
            Explain.with_user(self.plain).explain("hr.payslip", 0, when="frozen")
        with self.assertRaises(UserError):
            Explain.with_user(self.payroll).explain("no.such.model", 1)

    def test_03_trace_company_rule(self):
        Trace = self.env["ua.explain.trace"]
        foreign = Trace.sudo().create({"model_name": "hr.payslip", "res_id": 0, "payload": "{}",
                                       "company_id": self.other.id})
        self.assertFalse(Trace.with_user(self.payroll).search([("id", "=", foreign.id)]))

    # ------------------------------------------------------------------ 2. журнал змін
    def test_04_change_log_roles(self):
        Log = self.env["ua.change.log"]
        hr_row, pay_row, acc_row = self._log("hr"), self._log("payroll"), self._log("account")
        foreign = self._log("hr", company=self.other)
        mine = [("id", "in", (hr_row | pay_row | acc_row | foreign).ids)]

        with self.assertRaises(AccessError):
            Log.with_user(self.plain).search(mine)
        with self.assertRaises(AccessError):
            Log.with_user(self.plain).count_new(self.company, YEAR, MONTH)

        self.assertEqual(Log.with_user(self.hr).search(mine), hr_row,
                         "кадровик бачить кадри, але не зарплату, облік і чужу компанію")
        self.assertEqual(Log.with_user(self.payroll).search(mine), hr_row | pay_row,
                         "розрахунок зарплати бачить кадри і зарплату")
        self.assertEqual(Log.with_user(self.accountant).search(mine), hr_row | pay_row | acc_row,
                         "бухгалтер бачить усі ділянки своєї компанії")

        # бухгалтер і далі приймає зміни перед закриттям місяця
        pay_row.with_user(self.accountant).action_accept()
        self.assertEqual(pay_row.state, "accepted")
        with self.assertRaises(AccessError):
            pay_row.with_user(self.hr).action_reset()

    # ------------------------------------------------------------------ 3. ПДВ і каса
    def test_05_vat_period_writes_belong_to_accountant(self):
        Period = self.env["ua.vat.period"]
        vals = {"company_id": self.company.id, "date_from": "2019-01-01", "date_to": "2019-01-31"}
        period = Period.sudo().create(vals)
        for user in (self.plain, self.hr):
            with self.assertRaises(AccessError):
                Period.with_user(user).create(dict(vals, date_from="2019-02-01", date_to="2019-02-28"))
            for operation in ("read", "write", "unlink"):
                with self.assertRaises(AccessError, msg="%s %s" % (user.login, operation)):
                    period.with_user(user).check_access(operation)
        mine = Period.with_user(self.accountant).create(
            dict(vals, date_from="2019-03-01", date_to="2019-03-31"))
        self.assertTrue(mine)
        for operation in ("read", "write", "unlink"):
            period.with_user(self.accountant).check_access(operation)

    def test_06_vat_period_company_rule(self):
        Period = self.env["ua.vat.period"]
        foreign = Period.sudo().create({
            "company_id": self.other.id, "date_from": "2019-01-01", "date_to": "2019-01-31"})
        self.assertFalse(Period.with_user(self.accountant).search([("id", "=", foreign.id)]),
                         "правило компанії ховає чуже зведення")
        with self.assertRaises(AccessError):
            foreign.with_user(self.accountant).check_access("read")
        with self.assertRaises(AccessError):
            Period.with_user(self.accountant).create({
                "company_id": self.other.id, "date_from": "2019-04-01", "date_to": "2019-04-30"})

    def test_07_cash_book_writes_belong_to_accountant(self):
        for model in ("ua.cash.book", "ua.cash.book.line", "ua.cash.book.entry"):
            for operation in ("read", "write", "create", "unlink"):
                with self.assertRaises(AccessError, msg="%s %s" % (model, operation)):
                    self.env[model].with_user(self.plain).check_access(operation)
                self.env[model].with_user(self.accountant).check_access(operation)

    def test_08_tax_registers_are_closed_for_plain_user(self):
        """Реєстри бухгалтера: не кожен працівник читає декларації і книгу доходів."""
        models = ["ua.vat.compensation", "ua.advance.report", "ua.cost.calculation",
                  "ua.zvv.allocation", "ua.bank.connect", "ua.fop.income", "ua.fop.quarter",
                  "ua.profit.declaration"]
        for model in models:
            if model not in self.env:
                continue        # модуль не встановлено на цій базі
            with self.assertRaises(AccessError, msg=model):
                self.env[model].with_user(self.plain).check_access("read")
            self.env[model].with_user(self.accountant).check_access("read")
        if "ua.fop.income" in self.env:
            with self.assertRaises(AccessError):
                self.env["ua.fop.income"].with_user(self.plain).action_sync()

    # ------------------------------------------------------------------ 4. міст інтеграцій
    def test_09_bridge_transport_is_private_and_pinned(self):
        Bridge = self.env["bp.bridge"]
        self.assertFalse(hasattr(Bridge, "call"), "публічного транспорту більше немає")
        try:
            from odoo.service.model import get_public_method
        except ImportError:         # інша версія ядра: досить того, що ім'я з підкресленням
            get_public_method = None
        if get_public_method:
            with self.assertRaises(Exception):
                get_public_method(Bridge.with_user(self.plain), "_call")

        env = {"BP_BRIDGE_URL": "https://bridge.example", "BP_BRIDGE_TOKEN": "secret-token"}
        bad = [".evil.example/api/x", "@evil.example/api/x", "//evil.example/api/x",
               ":8443/api/x", "/kyc/subjects", "/api/../admin", "/api/x?token=1",
               "/api/odb/screen/1\r\nX-Evil: 1", "", None]
        with patch.dict(os.environ, env), \
                patch("odoo.addons.bp_bridge.models.bridge.requests.request") as request:
            for path in bad:
                with self.assertRaises(UserError, msg=repr(path)):
                    Bridge._call("GET", path)
            with self.assertRaises(UserError):
                Bridge._call("DELETE", "/api/kyc/subjects/1")
            request.assert_not_called()

            request.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
            status, data = Bridge._call("GET", "/api/odb/screen/12345678")
            self.assertEqual((status, data), (200, {"ok": True}))
            args, kwargs = request.call_args
            self.assertEqual(args[:2], ("GET", "https://bridge.example/api/odb/screen/12345678"))
            self.assertIs(kwargs.get("allow_redirects"), False)

    # ------------------------------------------------------------------ 5. статус постачальника
    def test_10_supplier_status_needs_manager(self):
        partner_group = "base.group_partner_manager"
        clerk = self._user("clerk", [partner_group, "purchase.group_purchase_user"])
        manager = self._user("buyer_manager", [partner_group, "purchase.group_purchase_manager"])
        Partner = self.env["res.partner"]
        partner = Partner.create({"name": "ТОВ «Тест постач»", "bp_supplier_status": "unverified"})

        with self.assertRaises(AccessError):
            partner.with_user(clerk).write({"bp_supplier_status": "verified"})
        with self.assertRaises(AccessError):
            partner.with_user(clerk).write({"bp_supplier_status": False})
        with self.assertRaises(AccessError):
            partner.with_user(clerk).write({"bp_verified_by": clerk.id})
        with self.assertRaises(AccessError):
            partner.with_user(clerk).action_bp_mark_verified()
        with self.assertRaises(AccessError):
            Partner.with_user(clerk).create({"name": "Одразу перевірений",
                                             "bp_supplier_status": "verified"})
        self.assertEqual(partner.bp_supplier_status, "unverified")
        # звичайна робота з карткою не зачеплена
        partner.with_user(clerk).write({"comment": "уточнити реквізити"})
        self.assertTrue(Partner.with_user(clerk).create({"name": "Звичайний контакт"}))

        partner.with_user(manager).action_bp_mark_verified()
        self.assertEqual(partner.bp_supplier_status, "verified")
        self.assertEqual(partner.bp_verified_by, manager)
        # повернути «не перевірено» може кожен, хто редагує картку: це лише посилює контроль
        partner.with_user(clerk).action_bp_mark_unverified()
        self.assertEqual(partner.bp_supplier_status, "unverified")
        partner.with_user(manager).write({"bp_supplier_status": "verified"})
        self.assertEqual(partner.bp_supplier_status, "verified")

    # ------------------------------------------------------------------ 6. кадри
    def test_11_leave_allocations_need_hr(self):
        employee = self.employee
        for user in (self.plain, self.accountant):
            with self.assertRaises(AccessError):
                employee.with_user(user).ua_ensure_leave_allocations()
            with self.assertRaises(AccessError):
                employee.with_user(user).ua_ensure_allocations(YEAR + 5)
        self.assertTrue(employee.with_user(self.hr).ua_ensure_leave_allocations())
        self.assertTrue(employee.with_user(self.hr).ua_ensure_allocations(YEAR))

    def test_12_military_check_needs_hr(self):
        employee = self.employee
        with self.assertRaises(AccessError):
            employee.with_user(self.plain).ua_mil_register_check()
        with self.assertRaises(AccessError):
            employee.with_user(self.plain).action_ua_mil_register_check()
        self.assertFalse(employee.ua_mil_last_check)
        self.assertFalse(self.env["ua.military.event"].search([("employee_id", "=", employee.id)]))

        day = employee.with_user(self.hr).ua_mil_register_check()
        self.assertEqual(employee.ua_mil_last_check, day)
        self.assertEqual(len(self.env["ua.military.event"].search(
            [("employee_id", "=", employee.id), ("kind", "=", "check")])), 1)

        with self.assertRaises(AccessError):
            self.env["ua.military.list"].with_user(self.hr).action_create_all_tcc(self.other.id)

    def test_13_income_certificate_needs_payroll(self):
        Certificate = self.env["ua.income.certificate"]
        for user in (self.plain, self.hr, self.accountant):
            with self.assertRaises(AccessError, msg=user.login):
                Certificate.with_user(user).check_access("read")
        Certificate.with_user(self.payroll).check_access("create")
        with self.assertRaises(UserError):
            Certificate.with_user(self.payroll).ua_compose(self.other.id, YEAR, MONTH,
                                                           employee=self.employee.id)

    def test_14_p2_report_needs_hr(self):
        Report = self.env["report.l10n_ua_hr_card.report_ua_p2"]
        for user in (self.plain, self.accountant):
            with self.assertRaises(AccessError, msg=user.login):
                Report.with_user(user)._get_report_values(self.employee.ids)
        values = Report.with_user(self.hr)._get_report_values(self.employee.ids)
        self.assertEqual(values["docs"].ids, self.employee.ids)
        action = self.env.ref("l10n_ua_hr_card.action_report_ua_p2")
        self.assertIn(self.env.ref("hr.group_hr_user"), action.group_ids)

    def test_15_hr_documents_company_rule(self):
        """Кадровик однієї компанії не бачить списків і подій іншої."""
        foreign_employee = self.env["hr.employee"].create({
            "name": "Чужа Марія", "company_id": self.other.id})
        foreign_list = self.env["ua.military.reserved"].sudo().create({
            "company_id": self.other.id, "date": "2026-03-31"})
        foreign_event = self.env["ua.military.event"].sudo().create({
            "employee_id": foreign_employee.id, "date": "2026-03-01", "kind": "check",
            "note": "чужа звірка"})
        own_event = self.env["ua.military.event"].sudo().create({
            "employee_id": self.employee.id, "date": "2026-03-01", "kind": "check",
            "note": "своя звірка"})
        Reserved = self.env["ua.military.reserved"].with_user(self.hr)
        Event = self.env["ua.military.event"].with_user(self.hr)
        self.assertFalse(Reserved.search([("id", "=", foreign_list.id)]))
        self.assertEqual(Event.search([("id", "in", (foreign_event | own_event).ids)]), own_event)
        with self.assertRaises(AccessError):
            Reserved.create({"company_id": self.other.id, "date": "2026-03-31"})

    # ------------------------------------------------------------------ 7. анкета компанії
    def test_16_setup_profile_applies_only_known_company_fields(self):
        Question = self.env["ua.setup.question"]
        iban = Question.create({
            "code": "SEC_IBAN", "section": "Тест прав", "name": "Рахунок бюджету ПДФО",
            "target": "company.ua_iban_pdfo", "is_setting": True})
        director = Question.search([("target", "=", "company.ua_director_name")], limit=1) \
            or Question.create({"code": "SEC_DIRECTOR", "section": "Тест прав", "name": "Керівник",
                                "target": "company.ua_director_name", "is_setting": True})
        self.company.write({"ua_iban_pdfo": False, "ua_director_name": "Старий Керівник"})
        profile = self.env["ua.setup.profile"].profile_for(self.company)
        Answer = self.env["ua.setup.answer"]
        for question, value in ((iban, "UA000000000000000000000000001"), (director, "Новий Керівник")):
            answer = Answer.search([("profile_id", "=", profile.id),
                                    ("question_id", "=", question.id)], limit=1)
            vals = {"value": value, "state": "confirmed", "source": "accountant"}
            if answer:
                answer.write(vals)
            else:
                Answer.create(dict(vals, profile_id=profile.id, question_id=question.id))
        profile.invalidate_recordset()
        fields_to_apply = {row["field"] for row in profile.preview_apply()}
        self.assertIn("ua_director_name", fields_to_apply)
        self.assertNotIn("ua_iban_pdfo", fields_to_apply, "поле поза переліком анкета не чіпає")
        profile.action_apply()
        self.assertEqual(self.company.ua_director_name, "Новий Керівник")
        self.assertFalse(self.company.ua_iban_pdfo)

    # ------------------------------------------------------------------ 8. мережа і файли
    def test_17_bank_api_host_is_pinned(self):
        from odoo.addons.l10n_ua_bank_online.models import online_bank_statement_provider as mod
        for url in ("https://acp.privatbank.ua/api/statements/transactions?acc=1",
                    "https://api.monobank.ua/personal/client-info"):
            self.assertTrue(mod._ua_bank_url_ok(url), url)
        for url in ("http://acp.privatbank.ua/api", "https://evil.example/api",
                    "https://acp.privatbank.ua@evil.example/api", "https://acp.privatbank.ua.evil.example/",
                    "https://169.254.169.254/latest/meta-data", "file:///etc/passwd",
                    "https://api.monobank.ua:8443/personal"):
            self.assertFalse(mod._ua_bank_url_ok(url), url)
        Provider = self.env["online.bank.statement.provider"]
        with patch.object(mod, "build_opener") as opener:
            with self.assertRaises(UserError):
                Provider._ua_fetch("https://evil.example/api/statements", {"token": "t"})
            opener.assert_not_called()

    def test_18_dps_xml_parser_does_not_expand_entities(self):
        from odoo.addons.l10n_ua_payroll_reports.models.ua_dps_xml import safe_fromstring
        from lxml import etree
        marker = "UA-SECURITY-MARKER-7391"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write(marker)
            path = handle.name
        try:
            data = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file://%s">]>'
                    '<d><T1RXXXXG02S ROWNUM="1">&x;</T1RXXXXG02S></d>' % path).encode()
            root = safe_fromstring(data)
            self.assertNotIn(marker, etree.tostring(root, encoding="unicode"))
            self.assertNotIn(marker, "".join(root.itertext()))
        finally:
            os.unlink(path)
        plain = safe_fromstring(b'<d><T1RXXXXG02S ROWNUM="1">12</T1RXXXXG02S></d>')
        self.assertEqual(plain[0].text, "12")

    # ------------------------------------------------------------------ 10. скани документів
    def test_19_employee_scans_stay_with_hr_and_owner(self):
        """Скан на картці працівника (res_model hr.employee): колега без прав кадровика не читає
        його ні прямо, ні з прапорцем OCA search_attachments_from_hr_employee; власник і кадровик читають."""
        scan = self.env["ir.attachment"].create({
            "name": "passport.pdf", "res_model": "hr.employee", "res_id": self.employee.id,
            "datas": base64.b64encode(b"UA-SECURITY-SCAN")})
        for ctx in ({}, {"search_attachments_from_hr_employee": True}):
            with self.assertRaises(AccessError, msg="контекст %s" % ctx):
                scan.with_user(self.plain).with_context(**ctx).read(["datas"])
        mine = self.env["hr.employee"].create({
            "name": "Власна Оксана", "company_id": self.company.id, "user_id": self.plain.id})
        own_scan = self.env["ir.attachment"].create({
            "name": "own.pdf", "res_model": "hr.employee", "res_id": mine.id,
            "datas": base64.b64encode(b"OWN")})
        own = own_scan.with_user(self.plain).with_context(search_attachments_from_hr_employee=True)
        self.assertTrue(own.read(["datas"])[0]["datas"])
        self.assertTrue(scan.with_user(self.hr).read(["datas"])[0]["datas"])
