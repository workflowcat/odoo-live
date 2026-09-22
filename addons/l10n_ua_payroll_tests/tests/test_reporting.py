# -*- coding: utf-8 -*-
"""Звітний прогін (l10n_ua_reporting) на стандартних список/форма, без OWL-екрана.

Порт логіки з scripts/reporting_check.py (339 рядків), яка раніше зверталася до
get_screen_data() на живому стенді: тут усе будується в транзакції тесту через ORM.
Не портовано: форму словника get_screen_data() (знято з полиці разом з OWL-екраном),
HTTP-перевірку збірки web.assets_backend.js (це був OWL-бандл, якого більше немає) і
реальну XML/PDF генерацію (action_generate() для j05/pfu кличе повноцінний майстер
звітності, який будує суми з проведених листків - те саме, що еталонні сценарії
test_golden.py піднімають ~80 рядками плану рахунків/структури нарахування; дублювати
це заради одного тесту генерації - поза межами цього шматка). Натомість дуже докладно
покрито життєвий цикл прогону: перевірки (_common_checks/_checks_j30), стани,
коригування, унікальність періоду і те, що ua.report.check не редагується з UI -
це і є "логіка", яку скрипт насправді перевіряв за межами самого рендеру файлів.

"Дедлайни" зі шматка завдання: ні в ua_report_run.py, ні в reporting_check.py немає
поля чи перевірки дедлайну (є лише notice_deadline на іншій моделі, ua.pfu.claim -
не тут). Портувати нема чого; поле не вигадувалося."""
from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged("post_install", "-at_install", "ua_reporting")
class TestUaReportRun(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Run = cls.env["ua.report.run"]
        cls.Check = cls.env["ua.report.check"]
        cls.calendar = cls.company.resource_calendar_id

    def _employee(self, name, **values):
        vals = {"name": name, "company_id": self.company.id, "ua_contract_kind": "employment"}
        if self.calendar:
            vals["resource_calendar_id"] = self.calendar.id
        vals.update(values)
        return self.env["hr.employee"].create(vals)

    def _user(self, group_xmlids):
        import uuid
        login = "ua_reporting_test_%s" % uuid.uuid4().hex[:10]
        groups = [self.env.ref(xmlid).id for xmlid in group_xmlids]
        return self.env["res.users"].create({
            "name": "Тестовий користувач", "login": login, "email": "%s@example.com" % login,
            "group_ids": [(6, 0, groups)],
        })

    # ------------------------------------------------------------------ 1. каталог звітів
    def test_report_catalog_matches_period_types(self):
        from odoo.addons.l10n_ua_reporting.models.ua_report_run import PERIOD_TYPE, REPORTS
        self.assertGreaterEqual(len(REPORTS), 6, "звітів у каталозі")
        codes = {code for code, _name in REPORTS}
        self.assertEqual(codes, set(PERIOD_TYPE.keys()), "кожен звіт каталогу має тип періоду")
        self.assertIn("j05", codes)
        self.assertIn("pfu", codes)

    # ------------------------------------------------------------------ 2. views
    def test_views_load(self):
        views = self.Run.get_views([(False, "form"), (False, "list")])
        self.assertIn("form", views["views"])
        self.assertIn("list", views["views"])

    # ------------------------------------------------------------------ 3. ensure_run / унікальність
    def test_ensure_run_is_idempotent(self):
        before = self.Run.search_count([("report_code", "=", "j05"), ("year", "=", 2026), ("month", "=", 8)])
        run_id = self.Run.ensure_run(report_code="j05", year=2026, month=8)
        again_id = self.Run.ensure_run(report_code="j05", year=2026, month=8)
        after = self.Run.search_count([("report_code", "=", "j05"), ("year", "=", 2026), ("month", "=", 8)])
        self.assertEqual(run_id, again_id, "повторний виклик відкриває наявний прогін, не дублює")
        self.assertEqual(after, before + 1, "рівно один запис створено")

    def test_period_uniqueness_constraint(self):
        self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 8})
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 8})

    def test_period_key_and_name_for_j05_month(self):
        run = self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 8})
        self.assertEqual(run.period_key, "2026-08")
        self.assertTrue(run.name, "прогін має назву")
        self.assertIn("2026", run.period_key)

    # ------------------------------------------------------------------ 4. перевірки: _common_checks
    def test_common_checks_flag_missing_rnokpp_and_company_data(self):
        self.company.write({"company_registry": False, "ua_sti_code": False, "ua_director_name": False})
        self._employee("Без РНОКПП")
        run = self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 8})
        run.action_refresh()
        self.assertEqual(run.state, "draft", "є помилки - прогін лишається чернеткою")

        rnokpp = run.check_ids.filtered(lambda c: c.code == "rnokpp")
        self.assertTrue(rnokpp)
        self.assertEqual(rnokpp.level, "error")
        self.assertGreaterEqual(int(rnokpp.value), 1)

        signers = run.check_ids.filtered(lambda c: c.code == "company_signers")
        self.assertTrue(signers)
        self.assertEqual(signers.level, "error")
        self.assertIn("ЄДРПОУ", signers.detail)

        # усі рядки перевірки мають лише рівні ok/warn/error і ціль, що резолвиться
        for check in run.check_ids:
            self.assertIn(check.level, ("ok", "warn", "error"))
            self.assertTrue(check.target_model, "рядок %s без цілі" % check.code)

    def test_common_checks_ok_when_company_data_complete(self):
        self.company.write({
            "company_registry": "12345678", "ua_sti_code": "1234", "ua_director_name": "Директор Директорович",
        })
        run = self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 8})
        run.action_refresh()
        signers = run.check_ids.filtered(lambda c: c.code == "company_signers")
        self.assertEqual(signers.level, "ok")

    # ------------------------------------------------------------------ 5. перевірки: j30
    def test_checks_j30_flags_hire_without_order_then_ok_with_order(self):
        start = date(2026, 5, 10)
        employee = self._employee("Прийнята Особа")
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 20000, "date_version": start, "contract_date_start": start, "contract_date_end": False,
        })
        run = self.Run.create({"report_code": "j30", "company_id": self.company.id, "year": 2026, "month": 5})
        run.action_refresh()
        orders_check = run.check_ids.filtered(lambda c: c.code == "j30_orders")
        self.assertTrue(orders_check)
        self.assertEqual(orders_check.level, "error", "прийняття без наказу - помилка")

        self.env["ua.hr.order"].create({
            "order_type": "hire", "employee_id": employee.id, "company_id": self.company.id,
            "date": start, "date_from": start, "state": "posted",
        })
        run.action_refresh()
        orders_check = run.check_ids.filtered(lambda c: c.code == "j30_orders")
        self.assertEqual(orders_check.level, "ok", "тепер наказ є - перевірка ок")

    # ------------------------------------------------------------------ 6. дії: generate / mark_submitted / reset
    def test_action_generate_blocks_when_checks_have_errors(self):
        self.company.write({"company_registry": False, "ua_sti_code": False, "ua_director_name": False})
        run = self.Run.create({"report_code": "staff", "company_id": self.company.id, "year": 2026, "date": date(2026, 8, 31)})
        with self.assertRaises(UserError):
            run.action_generate()
        self.assertNotEqual(run.state, "generated")

    def test_action_mark_submitted_requires_generated_state(self):
        run = self.Run.create({"report_code": "pfu", "company_id": self.company.id, "year": 2026, "month": 8})
        with self.assertRaises(UserError):
            run.action_mark_submitted()
        run.write({"state": "generated"})
        run.action_mark_submitted()
        self.assertEqual(run.state, "submitted")
        self.assertTrue(run.submitted_date)
        self.assertEqual(run.submitted_by, self.env.user)

    def test_action_reset_returns_to_draft(self):
        run = self.Run.create({"report_code": "pfu", "company_id": self.company.id, "year": 2026, "month": 8})
        run.write({"state": "generated"})
        run.action_reset()
        self.assertEqual(run.state, "draft")

    # ------------------------------------------------------------------ 7. коригування (action_create_correction)
    def test_create_correction_only_for_j05_and_generated_or_submitted(self):
        pfu_run = self.Run.create({"report_code": "pfu", "company_id": self.company.id, "year": 2026, "month": 8})
        pfu_run.write({"state": "generated"})
        with self.assertRaises(UserError):
            pfu_run.action_create_correction()

        j05_run = self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 9})
        with self.assertRaises(UserError):
            j05_run.action_create_correction()  # ще чернетка - коригувати нема чого

    def test_create_correction_kind_and_sequence(self):
        j05_run = self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 9})
        j05_run.write({"state": "generated"})
        with self.assertRaises(UserError):
            j05_run.action_create_correction(kind="HZ")  # недійсний тип коригування

        first = j05_run.action_create_correction("HZU")
        self.assertEqual(first.base_run_id, j05_run)
        self.assertEqual(first.correction_no, 1)
        self.assertEqual(first.doc_kind, "HZU")
        self.assertEqual(first.report_code, "j05")
        self.assertNotEqual(first.period_key, j05_run.period_key, "коригування має інший ключ періоду")

        second = j05_run.action_create_correction("HZN")
        self.assertEqual(second.correction_no, 2, "номер коригування наскрізний по базовому прогону")
        self.assertEqual(second.doc_kind, "HZN")
        self.assertEqual(second.base_run_id, j05_run, "база лишається тим самим поданим прогоном")

    # ------------------------------------------------------------------ 8. ua.report.check не редагується з UI
    def test_report_check_is_read_only_for_regular_users(self):
        run = self.Run.create({"report_code": "j05", "company_id": self.company.id, "year": 2026, "month": 8})
        user = self._user(["base.group_user", "hr.group_hr_user"])
        with self.assertRaises(AccessError):
            self.Check.with_user(user).create({"run_id": run.id, "code": "x", "title": "x", "level": "ok"})

        check = self.Check.sudo().create({"run_id": run.id, "code": "y", "title": "y", "level": "ok"})
        with self.assertRaises(AccessError):
            check.with_user(user).write({"title": "змінено"})
        with self.assertRaises(AccessError):
            check.with_user(user).unlink()
