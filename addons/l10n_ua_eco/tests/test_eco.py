# -*- coding: utf-8 -*-
"""Конструкторські зміни.

Дрон-розвідник, специфікація зм. 0: камера v1 x1, рама x1, гвинти M3 x4.
ПЗ «заміна комплектуючих»: камера v1 -> камера v2, гвинти 4 -> 6, додати антену x1.
Після застосування - специфікація зм. 1: камера v2 x1, рама x1, гвинти x6, антена x1;
стара - в архіві; нове замовлення на виробництво бере зм. 1.

Запуск: чиста база, тег ua_eco.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

GROUP = "l10n_ua_eco.group_ua_eco_"


@tagged("post_install", "-at_install", "ua_eco")
class TestUaEco(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        product = cls.env["product.product"]
        cls.drone = product.create({"name": "Дрон-розвідник (тест)", "type": "consu"})
        cls.camera_v1 = product.create({"name": "Камера v1 (тест)", "type": "consu"})
        cls.camera_v2 = product.create({"name": "Камера v2 (тест)", "type": "consu"})
        cls.frame = product.create({"name": "Рама (тест)", "type": "consu"})
        cls.screw = product.create({"name": "Гвинт M3 (тест)", "type": "consu"})
        cls.antenna = product.create({"name": "Антена (тест)", "type": "consu"})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.drone.product_tmpl_id.id, "product_qty": 1.0,
            "code": "ДР-1", "company_id": cls.company.id,
            "bom_line_ids": [(0, 0, {"product_id": p.id, "product_qty": q})
                             for p, q in ((cls.camera_v1, 1.0), (cls.frame, 1.0),
                                          (cls.screw, 4.0))]})

        def user(login, groups):
            return new_test_user(cls.env, login=login, groups=groups, company_id=cls.company.id,
                                 company_ids=[(6, 0, cls.company.ids)])

        cls.designer = user("eco_designer", GROUP + "user")
        cls.technologist = user("eco_tech", GROUP + "technology")
        cls.inspector = user("eco_qc", GROUP + "quality")
        cls.officer = user("eco_mil", GROUP + "military")
        cls.today = fields.Date.context_today(cls.env["ua.eco"])

    def _eco(self, **vals):
        values = {
            "product_tmpl_id": self.drone.product_tmpl_id.id, "reason": "supply",
            "description": "Камера v1 знята з виробництва постачальником (тест)",
            "line_ids": [
                (0, 0, {"action": "replace", "product_id": self.camera_v1.id,
                        "new_product_id": self.camera_v2.id, "new_qty": 1.0}),
                (0, 0, {"action": "qty", "product_id": self.screw.id, "new_qty": 6.0}),
                (0, 0, {"action": "add", "new_product_id": self.antenna.id, "new_qty": 1.0}),
            ]}
        values.update(vals)
        return self.env["ua.eco"].with_user(self.designer).create(values)

    def _approve(self, eco, *users):
        for approver in users:
            eco.with_user(approver).action_approve()

    @staticmethod
    def _components(bom):
        return {(line.product_id, line.product_qty) for line in bom.bom_line_ids}

    # --- 1. Повний цикл ---------------------------------------------------

    def test_01_full_cycle(self):
        eco = self._eco()
        self.assertTrue(eco.name.startswith("ПЗ/"))
        self.assertEqual(eco.bom_id, self.bom, "чинна специфікація знаходиться сама")
        self.assertFalse(eco.need_military)
        self.assertEqual(eco.roles_required, "Технолог, ВТК")
        rows = eco.diff_rows()
        self.assertEqual([(r["action"], r["product"], r["old_qty"], r["new_product"], r["new_qty"])
                          for r in rows],
                         [("replace", "Камера v1 (тест)", 1.0, "Камера v2 (тест)", 1.0),
                          ("qty", "Гвинт M3 (тест)", 4.0, "Гвинт M3 (тест)", 6.0),
                          ("add", "", 0.0, "Антена (тест)", 1.0)])

        eco.with_user(self.designer).action_submit()
        self.assertEqual(eco.state, "review")
        self.assertFalse(eco.with_user(self.designer).can_approve, "автор не погоджує")
        with self.assertRaises(UserError):
            eco.with_user(self.designer).action_approve()
        self._approve(eco, self.inspector)
        self.assertEqual(eco.state, "review")
        self.assertEqual(eco.roles_pending, "Технолог")
        with self.assertRaises(UserError):
            eco.with_user(self.inspector).action_approve()  # ВТК уже погодив
        self._approve(eco, self.technologist)
        self.assertEqual(eco.state, "approved")

        eco.with_user(self.designer).action_apply()
        self.assertEqual(eco.state, "applied")
        new = eco.new_bom_id
        self.assertTrue(new.active)
        self.assertFalse(self.bom.active, "стара ревізія - в архіві")
        self.assertEqual((new.ua_revision, new.ua_eco_id, new.ua_previous_bom_id),
                         (1, eco, self.bom))
        self.assertEqual(self.bom.ua_successor_eco_id, eco)
        self.assertEqual(self._components(new), {(self.camera_v2, 1.0), (self.frame, 1.0),
                                                 (self.screw, 6.0), (self.antenna, 1.0)})
        self.assertEqual(self._components(self.bom), {(self.camera_v1, 1.0), (self.frame, 1.0),
                                                      (self.screw, 4.0)}, "стара не змінилась")
        self.assertIn("зм. 1", new.display_name)

        found = self.env["mrp.bom"]._bom_find(self.drone)[self.drone]
        self.assertEqual(found, new)
        production = self.env["mrp.production"].create({
            "product_id": self.drone.id, "product_qty": 1.0, "company_id": self.company.id})
        self.assertEqual(production.bom_id, new)
        self.assertEqual(production.ua_bom_revision, 1)

    # --- 2. Військове представництво ------------------------------------------

    def test_02_military_representative_for_contract_products(self):
        customer = self.env["res.partner"].create({"name": "Військова частина А0000 (тест)"})
        contract = self.env["ua.contract"].create({
            "name": "ОК-1/2026 (тест)", "partner_id": customer.id, "kind": "sale",
            "ua_defense": True, "date": "2026-11-01"})
        self.env["mrp.production"].create({
            "product_id": self.drone.id, "product_qty": 1.0, "company_id": self.company.id,
            "ua_contract_id": contract.id})
        eco = self._eco()
        self.assertTrue(eco.need_military, "виріб робили за оборонним контрактом")
        self.assertEqual(eco.roles_required, "Технолог, ВТК, Військове представництво")
        eco.with_user(self.designer).action_submit()
        self._approve(eco, self.technologist, self.inspector)
        self.assertEqual(eco.state, "review", "без військового представництва не погоджено")
        self.assertTrue(eco.with_user(self.officer).can_approve)
        self._approve(eco, self.officer)
        self.assertEqual(eco.state, "approved")
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_eco.report_ua_eco", eco.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("ПОВІДОМЛЕННЯ ПРО ЗМІНУ", eco.name, "Дрон-розвідник (тест)",
                         "зм. 0", "зм. 1", "Камера v2 (тест)", "Військове представництво",
                         self.officer.name):
            self.assertIn(expected, text)

    # --- 3. Відхилення і нове подання ------------------------------------------

    def test_03_reject_and_resubmit(self):
        eco = self._eco()
        eco.with_user(self.designer).action_submit()
        self._approve(eco, self.technologist)
        with self.assertRaises(UserError):
            eco.with_user(self.inspector).action_reject()  # без причини
        eco.with_user(self.inspector).reject_reason = "Немає протоколу випробувань камери v2"
        eco.with_user(self.inspector).action_reject()
        self.assertEqual(eco.state, "rejected")
        eco.with_user(self.designer).action_submit()
        self.assertEqual(eco.approval_round, 2)
        self.assertEqual(eco.roles_pending, "Технолог, ВТК",
                         "погодження першого подання не переходять у друге")
        self._approve(eco, self.technologist, self.inspector)
        self.assertEqual(eco.state, "approved")
        self.assertEqual(eco.approval_ids.mapped("submission"), [1, 1, 2, 2])

    # --- 4. Дата набрання чинності --------------------------------------------

    def test_04_effective_date_and_scheduler(self):
        eco = self._eco(effective_date=self.today + timedelta(days=3))
        eco.with_user(self.designer).action_submit()
        self._approve(eco, self.technologist, self.inspector)
        with self.assertRaises(UserError):
            eco.action_apply()
        self.env["ua.eco"]._cron_apply_due()
        self.assertEqual(eco.state, "approved", "дата ще не настала")
        eco.effective_date = self.today
        self.env["ua.eco"]._cron_apply_due()
        self.assertEqual(eco.state, "applied")
        self.assertEqual(eco.date_applied, self.today)

    def test_05_second_change_from_stale_revision_is_refused(self):
        first, second = self._eco(), self._eco(description="Паралельна зміна (тест)")
        for eco in (first, second):
            eco.with_user(self.designer).action_submit()
            self._approve(eco, self.technologist, self.inspector)
        first.action_apply()
        with self.assertRaises(UserError):
            second.action_apply()
        self.assertEqual(second.state, "approved")
        self.assertEqual(self.env["mrp.bom"].search_count([
            ("product_tmpl_id", "=", self.drone.product_tmpl_id.id), ("active", "=", True)]), 1)

    # --- 5. Рядки -------------------------------------------------------

    def test_06_lines_are_checked(self):
        with self.assertRaises(ValidationError):
            self._eco(line_ids=[(0, 0, {"action": "add", "new_product_id": self.antenna.id,
                                        "new_qty": 0.0})])
        stranger = self._eco(line_ids=[(0, 0, {"action": "remove", "product_id": self.antenna.id})])
        with self.assertRaises(UserError):
            stranger.with_user(self.designer).action_submit()  # антени немає в специфікації
        empty = self._eco(line_ids=[])
        with self.assertRaises(UserError):
            empty.with_user(self.designer).action_submit()

    def test_07_remove_and_add_existing(self):
        eco = self._eco(line_ids=[
            (0, 0, {"action": "remove", "product_id": self.camera_v1.id}),
            (0, 0, {"action": "add", "new_product_id": self.screw.id, "new_qty": 2.0}),
        ])
        eco.with_user(self.designer).action_submit()
        self._approve(eco, self.technologist, self.inspector)
        eco.action_apply()
        self.assertEqual(self._components(eco.new_bom_id), {(self.frame, 1.0), (self.screw, 6.0)})

    def test_08_guards(self):
        eco = self._eco()
        eco.with_user(self.designer).action_submit()
        with self.assertRaises(UserError):
            eco.unlink()
        with self.assertRaises(UserError):
            eco.action_apply()  # ще не погоджено
        eco.action_cancel()
        eco.action_draft()
        self.assertEqual(eco.state, "draft")
        eco.unlink()
