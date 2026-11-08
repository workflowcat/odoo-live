# -*- coding: utf-8 -*-
"""Періодичні і типові випробування: коли приймання дозволене, а коли стоїть.

БпЛА (тест): періодичні раз на 6 місяців, перші - до сьогодні + 10 днів.
- Поки перших не було і строк не настав - акт затверджується; після строку - ні.
- Протокол «витримано» сьогодні - діє 6 місяців; через 7 місяців акт не проходить.
- «Не витримано» завтра - приймання стоїть; повторні «витримано» - знову можна.
- Рядки «на доопрацювання» не перевіряються.
- Зміна конструкції з типовими випробуваннями - акт стоїть, протокол типових знімає заборону.
- Нагадування про строк, друк протоколу, захист від порожніх зразків і видалення.

Запуск: тег ua_product_tests.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_product_tests")
class TestUaProductTests(TransactionCase):

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
        cls.today = fields.Date.context_today(cls.env.user)
        Product = cls.env["product.product"]
        cls.drone = Product.create({
            "name": "БпЛА розвідувальний (тест)", "type": "consu", "is_storable": True, "tracking": "serial",
            "ua_periodic_months": 6, "ua_periodic_first_due": cls.today + timedelta(days=10),
            "ua_test_program": "ПМ 01-2026 (тест)"})
        cls.frame = Product.create({"name": "Рама (тест)", "type": "consu"})
        cls.lots = cls.env["stock.lot"].create([{"name": "SN-%03d (тест)" % n, "product_id": cls.drone.id}
                                                for n in range(1, 4)])
        customer = cls.env["res.partner"].create({"name": "Державний замовник (тест)", "is_company": True})
        cls.contract = cls.env["ua.contract"].create({"name": "ОК-1/2026 (тест)", "partner_id": customer.id,
                                                      "ua_defense": True})

    def _act(self, day, product=None, result="accepted"):
        return self.env["ua.defense.acceptance"].create({
            "contract_id": self.contract.id, "date": day, "representative": "Представник (тест)",
            "line_ids": [(0, 0, {"product_id": (product or self.drone).id, "quantity": 1.0, "result": result})]})

    def _protocol(self, name, day, result="passed", kind="periodic", lots=None, product=None):
        test = self.env["ua.product.test"].create({
            "name": name, "product_tmpl_id": (product or self.drone).product_tmpl_id.id, "kind": kind,
            "date": day, "result": result, "lot_ids": [(6, 0, (lots or self.lots[:1]).ids)],
            "representative": "Представник замовника (тест)", "place": "Полігон (тест)"})
        test.action_done()
        return test

    def test_01_periodic_tests_gate_acceptance(self):
        template = self.drone.product_tmpl_id
        self._act(self.today).action_done()
        late = self._act(self.today + timedelta(days=20))
        with self.assertRaises(UserError, msg="перші періодичні прострочені"):
            late.action_done()

        first = self._protocol("ПВ-1 (тест)", self.today)
        self.assertEqual(first.program, "ПМ 01-2026 (тест)")
        self.assertEqual(first.valid_until, self.today + relativedelta(months=6) - timedelta(days=1))
        self.assertEqual(template.ua_periodic_valid_until, first.valid_until)
        late.action_done()
        self.assertEqual(late.state, "done")
        with self.assertRaises(UserError, msg="строк періодичних минув"):
            self._act(self.today + relativedelta(months=7)).action_done()

        failed = self._protocol("ПВ-2 (тест)", self.today + timedelta(days=1), result="failed", lots=self.lots[1:2])
        self.assertFalse(failed.valid_until)
        self.assertFalse(template.ua_periodic_valid_until)
        stopped = self._act(self.today + timedelta(days=2))
        with self.assertRaises(UserError, msg="не витримано - приймання стоїть"):
            stopped.action_done()
        self.assertIn("не витримано", template.ua_test_status(self.today + timedelta(days=2)))
        self._act(self.today + timedelta(days=2), result="rework").action_done()

        self._protocol("ПВ-3 (тест)", self.today + timedelta(days=3), lots=self.lots[2:])
        stopped.action_done()
        self.assertEqual(stopped.state, "done")
        self._act(self.today, product=self.frame).action_done()

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_product_tests.report_ua_product_test", failed.ids)[0].decode()
        for text in ("ПРОТОКОЛ ВИПРОБУВАНЬ", "ПВ-2 (тест)", "Періодичні", "SN-002 (тест)", "не витримано",
                     "ПМ 01-2026 (тест)", "Полігон (тест)", "Приймання і відвантаження виробів призупинено"):
            self.assertIn(text, html)

    def test_02_type_tests_after_design_change(self):
        self._protocol("ПВ-1 (тест)", self.today)
        bom = self.env["mrp.bom"].create({"product_tmpl_id": self.drone.product_tmpl_id.id, "product_qty": 1.0,
                                          "bom_line_ids": [(0, 0, {"product_id": self.frame.id, "product_qty": 1.0})]})
        eco = self.env["ua.eco"].create({"product_tmpl_id": self.drone.product_tmpl_id.id, "bom_id": bom.id,
                                         "description": "Нова рама (тест)", "ua_type_test": True})
        eco._ua_request_type_test()
        template = self.drone.product_tmpl_id
        self.assertTrue(template.ua_type_test_required)
        self.assertIn(eco.name, template.ua_type_test_reason)
        act = self._act(self.today)
        with self.assertRaises(UserError, msg="чекає типових випробувань"):
            act.action_done()
        periodic = self._protocol("ПВ-2 (тест)", self.today)
        self.assertTrue(template.ua_type_test_required, "періодичні не замінюють типові")
        self._protocol("ТВ-1 (тест)", self.today, kind="type", lots=self.lots[1:2])
        self.assertFalse(template.ua_type_test_required)
        act.action_done()
        self.assertEqual(act.state, "done")
        self.assertTrue(periodic.valid_until)

    def test_03_reminders_and_guards(self):
        sensor = self.env["product.product"].create({"name": "Датчик (тест)", "type": "consu",
                                                     "ua_periodic_months": 1})
        lot = self.env["stock.lot"].create({"name": "D-1 (тест)", "product_id": sensor.id})
        self._protocol("ПВ-Д (тест)", self.today - timedelta(days=20), product=sensor, lots=lot)
        Template = self.env["product.template"]
        Template._ua_cron_periodic_tests()
        Template._ua_cron_periodic_tests()
        self.assertEqual(len(sensor.product_tmpl_id.activity_ids), 1, "нагадування одне")
        self.assertEqual(len(self.drone.product_tmpl_id.activity_ids), 1, "перші періодичні - за 10 днів")

        empty = self.env["ua.product.test"].create({"name": "ПВ-X", "product_tmpl_id": sensor.product_tmpl_id.id})
        with self.assertRaises(UserError, msg="без зразків"):
            empty.action_done()
        done = sensor.product_tmpl_id.ua_test_ids.filtered(lambda t: t.state == "done")
        with self.assertRaises(UserError):
            done.unlink()
