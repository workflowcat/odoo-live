# -*- coding: utf-8 -*-
"""Метрологія: строк придатності з повірок, ВТК лише придатними засобами, нагадування.

Штангенциркуль (повірка, інтервал 12 міс.) повірено 100 днів тому - придатний.
Мікрометр (калібрування, 12 міс.) калібровано 400 днів тому - строк минув.
Операція «Контроль розмірів» має два пункти і міряє штангенциркулем.

Запуск: чиста база, тег ua_metrology.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_metrology")
class TestUaMetrology(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)
        Equipment = cls.env["maintenance.equipment"]
        cls.caliper = Equipment.create({
            "name": "Штангенциркуль ШЦ-I-150 (тест)", "serial_no": "1234", "ua_measuring": True,
            "ua_regulated": True, "ua_interval_months": 12, "ua_measure_range": "0-150 мм",
            "ua_accuracy": "0,05 мм"})
        cls.micrometer = Equipment.create({
            "name": "Мікрометр МК-25 (тест)", "serial_no": "77", "ua_measuring": True,
            "ua_interval_months": 12})
        cls.lab = cls.env["res.partner"].create({"name": "Метрологічний центр (тест)", "is_company": True})
        cls._verify(cls.caliper, cls.today - timedelta(days=100))
        cls._verify(cls.micrometer, cls.today - timedelta(days=400))

        cls.workcenter = cls.env["mrp.workcenter"].create({"name": "ВТК (тест)"})
        cls.frame = cls.env["product.product"].create({"name": "Рама з контролем (тест)", "type": "consu"})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.frame.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
            "operation_ids": [(0, 0, {
                "name": "Контроль розмірів", "workcenter_id": cls.workcenter.id, "time_cycle_manual": 5.0,
                "ua_checks": "Колісна база 250 мм\nТовщина пластини 3 мм",
                "ua_instrument_ids": [(6, 0, cls.caliper.ids)]})]})
        cls.operation = cls.bom.operation_ids

    @classmethod
    def _verify(cls, equipment, day, result="passed", **extra):
        return cls.env["ua.metrology.verification"].create(dict({
            "equipment_id": equipment.id, "date": day, "result": result, "provider_id": cls.lab.id,
            "certificate": "СП-%s-%s" % (equipment.serial_no, day.strftime("%Y%m%d"))}, **extra))

    def _workorder(self):
        production = self.env["mrp.production"].create({
            "product_id": self.frame.id, "product_qty": 1.0, "bom_id": self.bom.id})
        production.action_confirm()
        return production.workorder_ids

    def test_01_validity_from_verifications(self):
        verification = self.caliper.ua_verification_ids
        self.assertEqual(verification.kind, "verification", "регульований засіб - повірка")
        self.assertEqual(self.micrometer.ua_verification_ids.kind, "calibration")
        expected = self.today - timedelta(days=100) + relativedelta(months=12) - timedelta(days=1)
        self.assertEqual(self.caliper.ua_valid_until, expected)
        self.assertEqual(self.caliper.ua_metrology_state, "valid")
        self.assertEqual(self.micrometer.ua_metrology_state, "overdue")
        self.assertIn("строк минув", self.micrometer.ua_unfit_reason())
        self.assertIn("№ 1234, повірка до", self.caliper.ua_label())

        self._verify(self.caliper, self.today, result="failed")
        self.assertEqual(self.caliper.ua_metrology_state, "unfit")
        self.assertFalse(self.caliper.ua_valid_until)
        self._verify(self.caliper, self.today, result="passed", certificate="СП-нове")
        self.assertEqual(self.caliper.ua_metrology_state, "valid", "нова повірка повертає придатність")

        self.caliper.ua_conserved = True
        self.assertEqual(self.caliper.ua_metrology_state, "conserved")
        self.assertIn("законсервовано", self.caliper.ua_unfit_reason())

        with self.assertRaises(ValidationError):
            self._verify(self.micrometer, self.today, valid_until=self.today - timedelta(days=1))

    def test_02_quality_answers_need_fit_instruments(self):
        workorder = self._workorder()
        rows = workorder.ua_answer_check(1, "ok")
        self.assertIn("Штангенциркуль ШЦ-I-150 (тест) № 1234, повірка до", rows[0]["instruments"])
        answer = workorder.ua_check_ids.filtered(lambda c: c.sequence == 1)
        self.assertEqual(answer.ua_instrument_ids, self.caliper)

        self.operation.ua_instrument_ids = [(4, self.micrometer.id)]
        with self.assertRaises(UserError, msg="мікрометр прострочено"):
            workorder.ua_answer_check(2, "ok")
        rows = workorder.ua_answer_check(2, "fail", "товщина 2,6 мм")
        self.assertEqual(rows[1]["result"], "fail", "брак записується будь-яким засобом")
        self.assertIn("Мікрометр", rows[1]["instruments"])

        self._verify(self.micrometer, self.today)
        rows = workorder.ua_answer_check(2, "ok", "після доопрацювання")
        self.assertEqual(rows[1]["result"], "ok")
        self.assertIn("калібрування до", rows[1]["instruments"])
        self.assertEqual(rows[0]["instruments"].count("Штангенциркуль"), 1,
                         "попередня відповідь лишає свій знімок")

    def test_03_reminders_and_schedule(self):
        soon = self.env["maintenance.equipment"].create({
            "name": "Динамометричний ключ (тест)", "serial_no": "D-5", "ua_measuring": True,
            "ua_interval_months": 12, "ua_notify_days": 30})
        self._verify(soon, self.today - relativedelta(months=12) + timedelta(days=11))
        self.assertEqual(soon.ua_metrology_state, "due_soon")

        Equipment = self.env["maintenance.equipment"]
        Equipment._ua_cron_metrology()
        self.assertEqual(len(soon.activity_ids), 1)
        self.assertEqual(len(self.micrometer.activity_ids), 1, "прострочений - не застосовувати")
        self.assertIn("не застосовувати", self.micrometer.activity_ids.summary)
        self.assertFalse(self.caliper.activity_ids)
        Equipment._ua_cron_metrology()
        self.assertEqual(len(soon.activity_ids), 1, "повтор не ставимо")

        overdue = Equipment.search([("id", "in", (self.caliper | self.micrometer | soon).ids),
                                    ("ua_valid_until", "<", self.today)])
        self.assertEqual(overdue, self.micrometer)

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_metrology.report_ua_metrology_schedule", (self.caliper | self.micrometer | soon).ids)[0]
        text = html.decode()
        for expected in ("ГРАФІК ПОВІРКИ ТА КАЛІБРУВАННЯ", "Штангенциркуль ШЦ-I-150 (тест)", "1234",
                         "0-150 мм; 0,05 мм", "повірка", "калібрування", "Динамометричний ключ (тест)"):
            self.assertIn(expected, text)
