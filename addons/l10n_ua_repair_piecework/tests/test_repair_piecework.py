# -*- coding: utf-8 -*-
"""Відрядна оплата за ремонти: робота ремонту -> рядок виробітку -> план і факт.

Ремонт дрона: Анна двічі міняє мотор (розцінка 150 грн, норма 20 хв) - 300 грн і 40 нормо-хвилин;
діагностика Богдана без розцінки у виробіток не йде. Поки ремонт не завершено, виробіток його не
бачить; завершений ремонт іде в один виробіток, і робота в ньому не змінюється.

Запуск: чиста база, тег ua_repair_piecework.
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_repair_piecework")
class TestUaRepairPiecework(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Employee = cls.env["hr.employee"]
        cls.anna = Employee.create({"name": "Анна Ремонтна (тест)", "company_id": cls.company.id})
        cls.bohdan = Employee.create({"name": "Богдан Ремонтний (тест)", "company_id": cls.company.id})
        Operation = cls.env["ua.repair.operation"]
        cls.motor = Operation.create({"name": "Заміна мотора (тест)", "rate": 150.0, "minutes": 20.0})
        cls.check = Operation.create({"name": "Діагностика (тест)", "rate": 0.0, "minutes": 15.0})
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)

    def _repair(self):
        return self.env["repair.order"].create({
            "picking_type_id": self.warehouse.repair_type_id.id,
            "ua_labour_ids": [(0, 0, {"employee_id": self.anna.id, "operation_id": self.motor.id, "quantity": 2.0}),
                              (0, 0, {"employee_id": self.bohdan.id, "operation_id": self.check.id})]})

    @staticmethod
    def _finish(repair):
        repair.action_validate()
        repair.action_repair_start()
        repair.action_repair_end()

    def test_01_repair_to_piecework(self):
        repair = self._repair()
        motor = repair.ua_labour_ids.filtered(lambda l: l.operation_id == self.motor)
        self.assertEqual((motor.rate, motor.amount), (150.0, 300.0), "розцінка з довідника")
        self.assertEqual(repair.ua_labour_amount, 300.0)

        doc = self.env["ua.piecework"].create({})
        with self.assertRaises(UserError, msg="незавершений ремонт у виробіток не йде"):
            doc.action_fill()

        self._finish(repair)
        self.assertEqual(repair.state, "done")
        self.assertEqual(repair.ua_date_done, fields.Date.context_today(repair))

        doc.action_fill()
        line = doc.line_ids
        self.assertEqual(len(line), 1, "діагностика без розцінки - не в виробітку")
        self.assertEqual((line.employee_id, line.quantity, line.rate, line.amount),
                         (self.anna, 2.0, 150.0, 300.0))
        self.assertEqual(line.repair_id, repair)
        self.assertEqual(line._ua_doc_name(), repair.name)
        self.assertEqual(line._ua_work_name(), self.motor.name)
        self.assertAlmostEqual(line._ua_norm_minutes(), 40.0)
        self.assertTrue(motor.in_piecework)
        with self.assertRaises(UserError, msg="робота у виробітку не змінюється"):
            motor.quantity = 3.0

        doc.action_fill()
        self.assertEqual(len(doc.line_ids), 1, "«Перезаповнити» не дублює рядок")
        other = self.env["ua.piecework"].create({})
        with self.assertRaises(UserError, msg="робота йде лише в один виробіток"):
            other.action_fill()

        doc.action_confirm()
        plan = self.env["ua.piecework.plan"].create({"month": doc.date_to})
        plan.action_compute()
        anna = plan.line_ids.filtered(lambda l: l.employee_id == self.anna)
        self.assertEqual(anna.fact_amount, 300.0)
        self.assertAlmostEqual(anna.fact_norm_hours, 40.0 / 60.0, places=2)

        doc.action_cancel()
        self.assertFalse(motor.in_piecework, "скасований виробіток звільняє роботу")
        other.action_fill()
        self.assertEqual(other.line_ids.repair_labour_id, motor)

    def test_02_print(self):
        repair = self._repair()
        self._finish(repair)
        doc = self.env["ua.piecework"].create({})
        doc.action_fill()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_piecework.report_ua_piecework", doc.ids)[0].decode()
        self.assertIn(repair.name, html)
        self.assertIn(self.motor.name, html)
