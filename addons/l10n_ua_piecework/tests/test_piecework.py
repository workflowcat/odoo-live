# -*- coding: utf-8 -*-
"""Виробіток: операції з розцінкою -> рядки за працівниками -> відрядна оплата в листку.

Складання дрона - розцінка 250 грн за виріб; пайка - без розцінки (в виробіток не йде).
Замовлення на 60 дронів: на складанні Анна працювала 120 хв, Богдан 60 хв. Отже Анні 40 шт.
(10 000 грн), Богдану 20 шт. (5 000 грн). Податки з відрядної оплати перевіряє еталонний
сценарій 31 (l10n_ua_payroll_tests); тут - лише що сума дійшла до листка рядком PIECE.

Запуск: чиста база, тег ua_piecework.
"""
from datetime import date, datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install", "ua_piecework")
class TestUaPiecework(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.calendar = cls.company.resource_calendar_id
        cls.loss = cls.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1)
        cls.workcenter = cls.env["mrp.workcenter"].create({"name": "Дільниця складання (тест)"})
        cls.drone = cls.env["product.product"].create({"name": "Дрон відрядний (тест)", "type": "consu"})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "operation_ids": [
                (0, 0, {"name": "Складання", "workcenter_id": cls.workcenter.id,
                        "time_cycle_manual": 30.0, "ua_piece_rate": 250.0, "sequence": 1}),
                (0, 0, {"name": "Пайка", "workcenter_id": cls.workcenter.id,
                        "time_cycle_manual": 10.0, "sequence": 2}),
            ]})
        cls.assembly = cls.bom.operation_ids.filtered(lambda o: o.name == "Складання")
        start = date(fields.Date.today().year, 1, 1)
        cls.anna = cls._worker("Анна Відрядна", "piece_anna", 20000.0, start)
        cls.bohdan = cls._worker("Богдан Відрядний", "piece_bohdan", 15000.0, start)

    @classmethod
    def _worker(cls, name, login, wage, start):
        user = new_test_user(cls.env, login=login, groups="mrp.group_mrp_user",
                             company_id=cls.company.id, company_ids=[(6, 0, cls.company.ids)])
        Employee = cls.env["hr.employee"]
        values = {"name": name, "user_id": user.id, "company_id": cls.company.id,
                  "resource_calendar_id": cls.calendar.id, "ua_main_job": True,
                  "ua_contract_kind": "employment", "ua_esv_category": "standard", "ua_index_off": True}
        employee = Employee.create({k: v for k, v in values.items() if k in Employee._fields})
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": wage, "date_version": start, "contract_date_start": start,
            "contract_date_end": False, "struct_id": cls.structure.id,
            "resource_calendar_id": cls.calendar.id})
        return employee

    def _mo(self, qty, logs):
        """Замовлення на qty дронів; logs - [(працівник, хвилини)] на складанні; обидві операції завершено."""
        production = self.env["mrp.production"].create({
            "product_id": self.drone.id, "product_qty": qty, "bom_id": self.bom.id})
        production.action_confirm()
        assembly = production.workorder_ids.filtered(lambda w: w.operation_id == self.assembly)
        now = datetime.now().replace(microsecond=0)
        for employee, minutes in logs:
            self.env["mrp.workcenter.productivity"].create({
                "workorder_id": assembly.id, "workcenter_id": self.workcenter.id,
                "loss_id": self.loss.id, "user_id": employee.user_id.id, "company_id": self.company.id,
                "date_start": now - timedelta(minutes=minutes + 5), "date_end": now - timedelta(minutes=5)})
        production.workorder_ids.button_finish()
        return production

    def _slip(self, employee, doc):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id, "date_from": doc.date_from, "date_to": doc.date_to,
            "struct_id": self.structure.id, "name": employee.name, "company_id": self.company.id})
        slip.onchange_employee()
        slip.compute_sheet()
        return slip

    @staticmethod
    def _totals(slip):
        return {line.code: round(line.total, 2) for line in slip.line_ids}

    def test_01_fill_confirm_and_payslip(self):
        self._mo(60.0, [(self.anna, 120.0), (self.bohdan, 60.0)])
        doc = self.env["ua.piecework"].create({})
        self.assertTrue(doc.name.startswith("ВР/"))
        anna_slip = self._slip(self.anna, doc)
        self.assertNotIn("PIECE", self._totals(anna_slip), "до затвердження відрядної оплати немає")

        doc.action_fill()
        self.assertEqual(doc.line_ids.operation_id, self.assembly, "пайка без розцінки не йде")
        rows = {line.employee_id: line for line in doc.line_ids}
        self.assertEqual((rows[self.anna].quantity, rows[self.anna].minutes, rows[self.anna].amount),
                         (40.0, 120.0, 10000.0))
        self.assertEqual((rows[self.bohdan].quantity, rows[self.bohdan].amount), (20.0, 5000.0))
        self.assertEqual(doc.amount_total, 15000.0)

        doc.action_confirm()
        self.assertEqual(doc.state, "confirmed")
        totals = self._totals(anna_slip)
        self.assertEqual(totals.get("PIECE"), 10000.0, "відкритий листок перерахувався")
        piece = anna_slip.line_ids.filtered(lambda l: l.code == "PIECE")
        self.assertEqual(piece.category_id.code, "BASIC", "відрядна оплата - основна зарплата")
        self.assertGreaterEqual(totals["GROSS"], totals["BASIC"] + totals["PIECE"])
        self.assertTrue(anna_slip.input_line_ids.filtered(lambda i: i.code == "PIECE").ua_piecework_auto)

        bohdan_slip = self._slip(self.bohdan, doc)
        self.assertEqual(self._totals(bohdan_slip).get("PIECE"), 5000.0, "листок, створений пізніше")

        # та сама операція вдруге в виробіток не потрапляє
        again = self.env["ua.piecework"].create({})
        with self.assertRaises(UserError):
            again.action_fill()

        # скасування прибирає суму з незакритих листків
        doc.action_cancel()
        self.assertNotIn("PIECE", self._totals(anna_slip))
        self.assertFalse(anna_slip.input_line_ids.filtered(lambda i: i.code == "PIECE" and i.amount))
        doc.action_draft()
        self.assertEqual(doc.state, "draft")

    def test_02_guards(self):
        self._mo(10.0, [])
        doc = self.env["ua.piecework"].create({})
        doc.action_fill()
        self.assertEqual(len(doc.line_ids), 1)
        self.assertFalse(doc.line_ids.employee_id, "часу немає - працівника вказують руками")
        self.assertEqual(doc.line_ids.quantity, 10.0)
        with self.assertRaises(UserError):
            doc.action_confirm()
        doc.line_ids.employee_id = self.anna

        slip = self._slip(self.anna, doc)
        slip.input_line_ids.filtered(lambda i: i.code == "PIECE").unlink()
        self.env["hr.payslip.input"].create({
            "payslip_id": slip.id, "contract_id": slip.contract_id.id, "code": "PIECE",
            "name": "Відрядна оплата вручну", "amount": 100.0})
        with self.assertRaises(UserError, msg="ручна сума і виробіток разом - подвійна оплата"):
            doc.action_confirm()
        slip.input_line_ids.filtered(lambda i: i.code == "PIECE").unlink()
        doc.action_confirm()
        self.assertEqual(self._totals(slip).get("PIECE"), 2500.0)
        with self.assertRaises(UserError):
            doc.line_ids.quantity = 12.0

        slip.write({"state": "done"})
        with self.assertRaises(UserError, msg="листок проведено - виробіток не скасовують"):
            doc.action_cancel()
        with self.assertRaises(UserError):
            doc.unlink()

    def test_03_print(self):
        self._mo(60.0, [(self.anna, 120.0), (self.bohdan, 60.0)])
        doc = self.env["ua.piecework"].create({})
        doc.action_fill()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_piecework.report_ua_piecework", doc.ids)[0].decode()
        for text in ("НАРЯД НА ВІДРЯДНУ РОБОТУ", doc.name, "Анна Відрядна", "Богдан Відрядний",
                     "10 000,00", "15 000,00", "Складання"):
            self.assertIn(text, html)
