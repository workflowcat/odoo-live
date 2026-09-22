# -*- coding: utf-8 -*-
"""Журнал змін на OCA auditlog: що бачить бухгалтер у черзі і що її не засмічує.

Зміни ловить `auditlog` за правилами з l10n_ua_changes/data/auditlog_rules.xml,
рядок черги робить перекладач у l10n_ua_changes/models/ua_change_source.py.
Тести перевіряють саме договір черги: одна ділова зміна - один рядок із тими
самими словами, решта - тиша.

Тег `ua_changes`. Тести post_install: правила auditlog підмінюють методи ORM
наприкінці завантаження реєстру, до того жодного рядка не буде.
"""
from datetime import date, timedelta

from odoo import SUPERUSER_ID, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_changes")
class TestChangeQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Log = cls.env["ua.change.log"]
        cls.employee = cls.env["hr.employee"].create({
            "name": "Журнал: Петренко Петро",
            "company_id": cls.company.id,
        })
        cls.version = cls.employee.version_id

    # ------------------------------------------------------------------ хелпери
    def rows_for(self, record, **extra):
        domain = [("model_name", "=", record._name), ("res_id", "=", record.id)]
        domain += [(key, "=", value) for key, value in extra.items()]
        return self.Log.search(domain, order="id desc")

    # ------------------------------------------------------------------ тести
    def test_wage_change_is_one_queue_row(self):
        """Оклад у версії контракту - один рядок, «було → стало» і різниця в гривнях."""
        self.version.wage = 20000.0
        before = self.rows_for(self.version)
        self.version.wage = 25000.0
        rows = self.rows_for(self.version) - before
        self.assertEqual(len(rows), 1, "одна зміна окладу - один рядок черги")
        row = rows[0]
        self.assertEqual(row.what, "Оклад")
        self.assertEqual(row.old_value, "20000.00")
        self.assertEqual(row.new_value, "25000.00")
        self.assertAlmostEqual(row.amount, 5000.0, places=2)
        self.assertEqual(row.area, "hr")
        self.assertEqual(row.operation, "write")
        self.assertEqual(row.state, "new")
        self.assertEqual(row.res_name, self.employee.name)
        self.assertTrue(row.auditlog_log_id, "рядок черги веде до запису аудиту")

    def test_field_outside_whitelist_is_not_logged(self):
        """Поле поза білим списком правила черги не бачить - і auditlog теж."""
        before = self.rows_for(self.employee)
        self.employee.write({"work_phone": "+380 44 000 00 00"})
        self.assertEqual(self.rows_for(self.employee) - before, self.Log.browse(),
                         "робочий телефон - не ділова зміна")

    def test_accept_and_undo_within_window(self):
        """«Прийняти всі зміни» і чесний відкат у вікні скасування."""
        self.employee.write({"ua_rnokpp": "1234567890"})
        row = self.rows_for(self.employee, what="РНОКПП")[0]
        year, month = row.year, row.month
        accepted = self.Log.accept_period(year, month)
        self.assertGreaterEqual(accepted, 1)
        row.invalidate_recordset()
        self.assertEqual(row.state, "accepted")
        self.assertTrue(row.accepted_user_id and row.accepted_date)

        returned = self.Log.undo_accept_period(year, month)
        self.assertGreaterEqual(returned, 1)
        row.invalidate_recordset()
        self.assertEqual(row.state, "new", "відкат повертає рядок на перегляд")
        self.assertFalse(row.accepted_user_id)

        # поза вікном відкат нічого не чіпає: рядок, прийнятий хвилину тому, лишається
        self.Log.accept_period(year, month)
        row.invalidate_recordset()
        row.sudo().write({"accepted_date": fields.Datetime.now() - timedelta(minutes=1)})
        self.assertEqual(self.Log.undo_accept_period(year, month, seconds=25), 0)
        row.invalidate_recordset()
        self.assertEqual(row.state, "accepted")

    def test_new_change_blocks_period_close(self):
        """Непереглянута зміна - перешкода закриттю; після прийняття її немає."""
        self.employee.write({"ua_fte": "0.5"})
        row = self.rows_for(self.employee, what="Ставка")[0]
        year, month = row.year, row.month
        blockers = self.env["ua.period.close"].blocker_rows(self.company, year, month)
        changes = [item for item in blockers if item["key"] == "changes"]
        self.assertTrue(changes, "непереглянута зміна блокує місяць")
        self.assertIn("непереглянутих змін", changes[0]["text"])
        self.assertEqual(changes[0]["target"]["model"], "ua.change.log")

        self.Log.accept_period(year, month)
        left = self.env["ua.period.close"].blocker_rows(self.company, year, month)
        self.assertFalse([item for item in left if item["key"] == "changes"],
                         "прийняті зміни більше не заважають")

    def test_unlink_is_logged(self):
        """Видалення ділового запису лишає слід, хоч самого запису вже немає."""
        param = self.env["ua.payroll.param"].create({
            "key": "ua_changes_test",
            "name": "Параметр перевірки",
            "value": 1.0,
            "valid_from": date(2026, 1, 1),
        })
        param_id = param.id
        param.unlink()
        rows = self.Log.search([("model_name", "=", "ua.payroll.param"),
                                ("res_id", "=", param_id), ("operation", "=", "unlink")])
        self.assertEqual(len(rows), 1, "видалення параметра - рядок черги")
        self.assertEqual(rows.area, "setup")

    def test_ua_no_log_suppresses_the_queue(self):
        """Заміна контексту ua_no_log: скрипт пише, черга мовчить, аудит лишається."""
        Audit = self.env["auditlog.log"].sudo()
        audit_before = Audit.search_count([("model_model", "=", "hr.version")])
        before = self.rows_for(self.version)
        self.version.with_context(ua_no_log=True).write({"wage": 31234.0})
        self.assertEqual(self.rows_for(self.version) - before, self.Log.browse(),
                         "під ua_no_log черга бухгалтера не росте")
        self.assertGreater(Audit.search_count([("model_model", "=", "hr.version")]), audit_before,
                           "аудит пише завжди - ховаємо лише чергу")

    def test_system_user_cron_write_not_shown(self):
        """Службовий користувач: технічне поле в чергу не йде, ділове - йде.

        Правило одне для всіх авторів: у чергу потрапляє тільки поле з білого
        списку. Крон, який пересуває технічну мітку, черги не торкається; крон,
        який змінив оклад, у черзі видно - і це навмисно."""
        system = self.env["hr.version"].with_user(SUPERUSER_ID).browse(self.version.id)
        before = self.rows_for(self.version)
        system.write({"date_version": date(2026, 2, 1)})
        self.assertEqual(self.rows_for(self.version) - before, self.Log.browse(),
                         "технічна правка службового користувача в чергу не йде")
        system.write({"wage": 41000.0})
        rows = self.rows_for(self.version) - before
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.user_id.id, SUPERUSER_ID)
        self.assertEqual(rows.what, "Оклад")

    def test_period_follows_the_document(self):
        """Рядок належить періоду документа, а не дню правки: табель за свій місяць."""
        sheet = self.env["ua.timesheet.sheet"].create({
            "company_id": self.company.id, "year": 2026, "month": 3,
        })
        line = self.env["ua.timesheet.line"].create({
            "sheet_id": sheet.id, "employee_id": self.employee.id, "days_worked": 20.0,
        })
        line.write({"days_worked": 19.0})
        row = self.rows_for(line)[0]
        self.assertEqual((row.year, row.month), (2026, 3))
        self.assertEqual(row.area, "time")
        self.assertEqual(row.what, "Відпрацьовано днів")
        self.assertEqual(row.old_value, "20.00")
        self.assertEqual(row.new_value, "19.00")
        self.assertAlmostEqual(row.amount, -1.0, places=2)
        self.assertEqual(row.res_name, self.employee.name)

    def test_translator_words_for_three_common_kinds(self):
        """Три найчастіші види змін називаються так само, як і до переходу на auditlog."""
        # 1. сума: різниця в гривнях і дві копійки
        self.version.wage = 10000.0
        self.version.wage = 10500.5
        money = self.rows_for(self.version, what="Оклад")[0]
        self.assertEqual((money.old_value, money.new_value), ("10000.00", "10500.50"))
        self.assertAlmostEqual(money.amount, 500.5, places=2)

        # 2. дата: як її бачить людина в картці
        self.employee.write({"departure_date": date(2026, 5, 31)})
        day = self.rows_for(self.employee, what="Дата звільнення")[0]
        self.assertEqual(day.new_value, "2026-05-31")
        self.assertEqual(day.amount, 0.0)

        # 3. зв'язок: назва запису, а не його номер
        structure = self.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        self.assertTrue(structure, "немає структури UA_SALARY")
        self.version.write({"struct_id": structure.id})
        link = self.rows_for(self.version, what="Структура нарахування")[0]
        self.assertEqual(link.new_value, structure.display_name)

    def test_payslip_intermediate_states_stay_out(self):
        """Проміжні стани розрахунку в чергу не йдуть, проведення і скасування - йдуть."""
        rule = self.env["auditlog.rule"].sudo().search([("model_model", "=", "hr.payslip")], limit=1)
        self.assertTrue(rule, "немає правила auditlog на hr.payslip")
        self.assertEqual(rule.ua_area, "payroll")
        self.assertEqual(rule.ua_period_date, "date_from")
        self.assertIn("state", rule.ua_field_ids.mapped("field_name"))
        from odoo.addons.l10n_ua_changes.models.ua_change_source import SPECIAL
        keep = SPECIAL["hr.payslip"]["keep"]
        self.assertFalse(keep("state", "draft", "verify"), "чернетка → перевірено в чергу не йде")
        self.assertTrue(keep("state", "verify", "done"), "проведення - ділова подія")
        self.assertTrue(keep("state", "done", "cancel"), "скасування - ділова подія")
