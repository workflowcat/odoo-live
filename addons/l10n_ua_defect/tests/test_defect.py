# -*- coding: utf-8 -*-
"""Акти про брак на замовленні з 5 дронів.

Матеріали на одиницю: рама 800, мотори 4 x 150, польотний контролер 600 = 2 000.
1. Невиправний брак 2 шт.: собівартість 4 000 (Дт 24 Кт 231); відходи 500 (Дт 209 Кт 24); з
   винного складальника 700 (Дт 375 Кт 24); втрати 2 800 у собівартість (Дт 231 Кт 24).
2. Виправний брак 3 шт. через плату постачальника: перепаювання 450 (Кт 231), нові роз'єми 150
   (Кт 201), претензія постачальнику 600 (Дт 374 Кт 24); втрат немає.
Рахунок 24 після обох актів - нуль.

Запуск: тег ua_defect.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "ua_defect")
class TestUaDefect(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Product = cls.env["product.product"]

        def product(name, price):
            return Product.create({"name": name, "type": "consu", "standard_price": price})
        cls.frame = product("Рама (тест браку)", 800)
        cls.motor = product("Мотор (тест браку)", 150)
        cls.fc = product("Польотний контролер (тест браку)", 600)
        cls.drone = product("Дрон розвідувальний з камерою (тест браку)", 0)
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0, "bom_line_ids": [
                (0, 0, {"product_id": cls.frame.id, "product_qty": 1}),
                (0, 0, {"product_id": cls.motor.id, "product_qty": 4}),
                (0, 0, {"product_id": cls.fc.id, "product_qty": 1})]})
        cls.production = cls.env["mrp.production"].create(
            {"product_id": cls.drone.id, "product_qty": 5, "bom_id": cls.bom.id})
        cls.production.action_confirm()
        cls.worker = cls.env["hr.employee"].create({"name": "Складальник Тарас (тест браку)"})
        cls.supplier = cls.env["res.partner"].create({"name": "ТОВ Плати (тест браку)"})
        cls.Act = cls.env["ua.defect.act"]

    def _acc(self, code):
        return self.Act._ua_default_account((code,))

    def _balance(self, move, code):
        return sum(move.line_ids.filtered(lambda l: l.account_id.code.startswith(code)).mapped("balance"))

    def test_01_final_defect(self):
        self.assertEqual(self.production.ua_defect_unit_cost(), 2000)
        context = self.production.action_ua_defect_act()["context"]
        act = self.Act.with_context(context).create({
            "date": date(2026, 3, 10), "qty": 2, "kind": "final", "cause": "worker",
            "description": "Перетягнуто кріплення моторів, тріщини рами (тест)",
            "salvage_amount": 500, "culprit_amount": 700})
        self.assertEqual((act.production_id, act.product_id, act.unit_cost), (self.production, self.drone, 2000))
        self.assertEqual((act.cost_amount, act.total_amount, act.loss_amount), (4000, 4000, 2800))
        self.assertTrue(act.name.startswith("АБ/"))
        with self.assertRaises(UserError, msg="без винної особи"):
            act.action_post()
        act.culprit_id = self.worker
        act.action_post()
        move = act.move_id
        self.assertEqual(move.state, "posted")
        self.assertAlmostEqual(self._balance(move, "24"), 0.0)
        self.assertAlmostEqual(self._balance(move, "209"), 500)
        self.assertAlmostEqual(self._balance(move, "375"), 700)
        self.assertAlmostEqual(self._balance(move, "231"), -4000 + 2800)
        culprit_line = move.line_ids.filtered(lambda l: l.account_id.code.startswith("375"))
        self.assertEqual(culprit_line.partner_id, self.worker.work_contact_id)
        self.assertEqual(self.production.ua_defect_count, 1)

        html = self.env["ir.actions.report"]._render_qweb_html("l10n_ua_defect.report_ua_defect", act.ids)[0].decode()
        self.assertIn("АКТ ПРО БРАК", html)
        self.assertIn("2800.00", html)

        act.action_draft()
        self.assertEqual(act.state, "draft")
        self.assertTrue(move.reversal_move_ids)

    def test_02_fixable_defect_supplier_claim(self):
        act = self.Act.create({
            "date": date(2026, 3, 12), "product_id": self.drone.id, "qty": 3, "kind": "fixable",
            "cause": "material", "supplier_id": self.supplier.id, "supplier_amount": 600,
            "description": "Холодна пайка роз'ємів плати живлення (тест)",
            "fix_line_ids": [(0, 0, {"name": "Перепаювання", "amount": 450}),
                             (0, 0, {"name": "Нові роз'єми", "account_id": self._acc("201").id, "amount": 150})]})
        self.assertEqual((act.cost_amount, act.fix_amount, act.loss_amount), (0, 600, 0))
        act.action_post()
        move = act.move_id
        self.assertAlmostEqual(self._balance(move, "24"), 0.0)
        self.assertAlmostEqual(self._balance(move, "374"), 600)
        self.assertAlmostEqual(self._balance(move, "201"), -150)
        self.assertAlmostEqual(self._balance(move, "231"), -450)
        claim = move.line_ids.filtered(lambda l: l.account_id.code.startswith("374"))
        self.assertEqual(claim.partner_id, self.supplier)

    def test_03_refunds_over_total(self):
        act = self.Act.create({
            "date": date(2026, 3, 15), "product_id": self.drone.id, "qty": 1, "kind": "final",
            "unit_cost": 2000, "cause": "equipment", "description": "Збій стенду (тест)",
            "salvage_amount": 1500, "culprit_amount": 600, "culprit_id": self.worker.id})
        with self.assertRaises(UserError):
            act.action_post()
        act.loss_to = "expense"
        act.culprit_amount = 0
        act.action_post()
        self.assertAlmostEqual(self._balance(act.move_id, "949"), 500)
