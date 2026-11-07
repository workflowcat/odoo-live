# -*- coding: utf-8 -*-
"""Рекламації.

Дрон-розвідник ДР-0001 за контрактом ОК-7/2026, акт приймання 2026-03-10, гарантія 12 місяців
-> гарантія до 2027-03-10. Контракт: відповісти за 5 днів, усунути за 20.
Рекламаційний акт РА-15 надійшов 2026-11-02, відмова 2026-11-01:
відповісти до 2026-11-07, усунути до 2026-11-22, у гарантії.

Запуск: чиста база, тег ua_claim.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

RECEIVED = date(2026, 11, 2)


@tagged("post_install", "-at_install", "ua_claim")
class TestUaClaim(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.customer = cls.env["res.partner"].create({"name": "Військова частина А0000 (тест)"})
        cls.supplier = cls.env["res.partner"].create({"name": "Постачальник камер (тест)"})
        cls.contract = cls.env["ua.contract"].create({
            "name": "ОК-7/2026 (тест)", "date": date(2026, 2, 1), "partner_id": cls.customer.id,
            "ua_defense": True, "ua_claim_response_days": 5, "ua_claim_fix_days": 20})
        product = cls.env["product.product"]
        cls.drone = product.create({"name": "Дрон-розвідник (тест)", "is_storable": True,
                                    "tracking": "serial", "ua_warranty_months": 12})
        cls.camera = product.create({"name": "Камера (тест)", "is_storable": True,
                                     "tracking": "serial"})

        def lot(name, item):
            return cls.env["stock.lot"].create({"name": name, "product_id": item.id,
                                                "company_id": cls.company.id})

        cls.lot, cls.spare = lot("ДР-0001", cls.drone), lot("ДР-0002", cls.drone)
        cls.camera_lot, cls.camera_lot2 = lot("КМ-0001", cls.camera), lot("КМ-0002", cls.camera)
        acceptance = cls.env["ua.defense.acceptance"].create({
            "contract_id": cls.contract.id, "date": date(2026, 3, 10)})
        (cls.lot | cls.spare).write({"ua_acceptance_id": acceptance.id,
                                     "ua_contract_id": cls.contract.id})

        def user(login, groups):
            return new_test_user(cls.env, login=login, groups=groups, company_id=cls.company.id,
                                 company_ids=[(6, 0, cls.company.ids)])

        cls.engineer = user("claim_engineer", "l10n_ua_claim.group_ua_claim_user,"
                                              "l10n_ua_eco.group_ua_eco_user")
        cls.head = user("claim_head", "l10n_ua_claim.group_ua_claim_manager")
        cls.today = fields.Date.context_today(cls.env["ua.claim"])

    def _claim(self, **vals):
        values = {"lot_id": self.lot.id, "date_received": RECEIVED,
                  "date_failure": RECEIVED - timedelta(days=1), "partner_ref": "РА-15",
                  "symptom": "Немає відеосигналу з камери після 12 вильотів (тест)",
                  "operating_hours": 6.5}
        values.update(vals)
        return self.env["ua.claim"].with_user(self.engineer).create(values)

    def _decide(self, claim, **vals):
        claim.with_user(self.head).write(vals)
        claim.with_user(self.head).action_decide()

    # --- 1. Реєстрація ---------------------------------------------------

    def test_01_register_takes_contract_warranty_and_deadlines(self):
        claim = self._claim()
        self.assertTrue(claim.name.startswith("РК/2026/"))
        self.assertEqual((claim.contract_id, claim.partner_id, claim.product_id),
                         (self.contract, self.customer, self.drone))
        self.assertEqual((claim.warranty_start, claim.warranty_end, claim.in_warranty),
                         (date(2026, 3, 10), date(2027, 3, 10), True))
        self.assertEqual((claim.date_response_due, claim.date_due),
                         (date(2026, 11, 7), date(2026, 11, 22)))
        activity = claim.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual((activity.user_id, activity.date_deadline),
                         (self.engineer, date(2026, 11, 7)))
        claim.action_respond()
        self.assertEqual(claim.date_responded, self.today)
        self.assertEqual(claim.activity_ids.date_deadline, date(2026, 11, 22),
                         "після відповіді нагадування - на строк усунення")
        self.assertEqual(self.lot.with_user(self.engineer).ua_claim_count, 1)

    # --- 2. Повний цикл --------------------------------------------------

    def test_02_component_defect_full_cycle(self):
        claim = self._claim()
        claim.action_start()
        self.assertEqual(claim.state, "investigation")
        claim.write({"cause": "component", "component_lot_id": self.camera_lot.id,
                     "supplier_id": self.supplier.id, "decision": "component",
                     "root_cause": "Обрив шлейфа камери (тест)"})
        with self.assertRaises(AccessError):
            claim.action_decide()  # працівник рішень не приймає
        claim.with_user(self.head).action_decide()
        self.assertEqual(claim.state, "decided")
        self.assertEqual(claim.date_responded, self.today, "рішення - теж відповідь замовнику")
        claim.action_close()
        self.assertEqual((claim.state, claim.date_closed), ("closed", self.today))
        self.assertFalse(claim.activity_ids)

        report = self.env["ir.actions.report"]
        html, _kind = report._render_qweb_html("l10n_ua_claim.report_ua_claim", claim.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("ВИСНОВОК ЗА РЕКЛАМАЦІЄЮ", claim.name, "ДР-0001", "РА-15",
                         "Дефект покупного комплектуючого", "КМ-0001", "Постачальник камер (тест)",
                         "Заміна складової", "відмова в гарантійний строк", "10.03.2027"):
            self.assertIn(expected, text)
        html, _kind = report._render_qweb_html(
            "l10n_ua_defense.report_ua_product_passport", self.lot.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("Рекламації", claim.name, "Немає відеосигналу",
                         "Дефект покупного комплектуючого", "Закрито"):
            self.assertIn(expected, text)

    # --- 3. Правила рішення ------------------------------------------------

    def test_03_decision_rules(self):
        claim = self._claim()
        claim.action_start()
        with self.assertRaises(UserError):
            claim.with_user(self.head).action_decide()  # без причини і рішення
        with self.assertRaises(UserError):
            self._decide(claim, cause="manufacturing", decision="reject",
                         decision_note="Не визнаємо (тест)")  # власний дефект у гарантії
        with self.assertRaises(UserError):
            self._decide(claim, cause="operation", decision="reject", decision_note=False)
        self._decide(claim, cause="operation", decision="reject",
                     decision_note="Виріб працював під дощем без захисного кожуха (тест)")
        self.assertEqual(claim.state, "decided")

        late = self._claim(date_received=date(2027, 4, 2), date_failure=date(2027, 4, 1))
        self.assertFalse(late.in_warranty)
        late.action_start()
        with self.assertRaises(UserError):
            self._decide(late, cause="manufacturing", decision="repair")
        self._decide(late, cause="manufacturing", decision="repair",
                     decision_note="Платний ремонт за окремим рахунком (тест)")
        self.assertEqual(late.state, "decided")

    def test_04_replacement(self):
        claim = self._claim()
        claim.action_start()
        self._decide(claim, cause="manufacturing", decision="replace")
        with self.assertRaises(UserError):
            claim.action_close()  # без виробу на заміну
        with self.assertRaises(ValidationError):
            claim.replacement_lot_id = self.lot
        with self.assertRaises(ValidationError):
            claim.replacement_lot_id = self.camera_lot  # інший виріб
        claim.replacement_lot_id = self.spare
        claim.action_close()
        self.assertEqual(claim.state, "closed")
        with self.assertRaises(AccessError):
            claim.action_reopen()
        claim.with_user(self.head).action_reopen()
        self.assertEqual((claim.state, claim.date_closed), ("investigation", False))

    # --- 4. Прострочення ----------------------------------------------------

    def test_05_overdue(self):
        Claim = self.env["ua.claim"]
        no_answer = self._claim(date_received=self.today - timedelta(days=10),
                                date_failure=self.today - timedelta(days=11))
        answered = self._claim(date_received=self.today - timedelta(days=10),
                               date_failure=self.today - timedelta(days=11))
        answered.action_respond()
        not_fixed = self._claim(date_received=self.today - timedelta(days=30),
                                date_failure=self.today - timedelta(days=31))
        not_fixed.action_respond()
        closed = self._claim(date_received=self.today - timedelta(days=30),
                             date_failure=self.today - timedelta(days=31))
        closed.action_start()
        self._decide(closed, cause="not_confirmed", decision="reject",
                     decision_note="Несправність не відтворилась на стенді (тест)")
        closed.action_close()
        claims = no_answer | answered | not_fixed | closed
        self.assertEqual(claims.filtered("is_overdue"), no_answer | not_fixed)
        self.assertEqual(Claim.search([("id", "in", claims.ids), ("is_overdue", "=", True)]),
                         no_answer | not_fixed)
        self.assertEqual(Claim.search([("id", "in", claims.ids), ("is_overdue", "=", False)]),
                         answered | closed)

    # --- 5. Конструкторська причина -> повідомлення про зміну ---------------------

    def test_06_design_cause_opens_change_notice(self):
        claim = self._claim()
        claim.action_start()
        claim.cause = "manufacturing"
        with self.assertRaises(UserError):
            claim.action_create_eco()
        claim.write({"cause": "design", "root_cause": "Кріплення камери не витримує вібрації (тест)"})
        with self.assertRaises(UserError):
            claim.action_create_eco()  # у виробу немає специфікації
        self.env["mrp.bom"].create({
            "product_tmpl_id": self.drone.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": self.camera.id, "product_qty": 1.0})]})
        action = claim.action_create_eco()
        eco = claim.eco_id
        self.assertEqual(action["res_id"], eco.id)
        self.assertEqual((eco.reason, eco.product_tmpl_id, eco.state),
                         ("defect", self.drone.product_tmpl_id, "draft"))
        self.assertIn(claim.name, eco.description)
        self.assertIn("вібрації", eco.description)
        claim.action_create_eco()
        self.assertEqual(self.env["ua.eco"].search_count([("product_tmpl_id", "=",
                                                           self.drone.product_tmpl_id.id)]), 1)

    # --- 6. Подібні рекламації і перевірки --------------------------------------

    def test_07_repeats_and_checks(self):
        first = self._claim(component_lot_id=self.camera_lot.id)
        second = self._claim(lot_id=self.spare.id, component_lot_id=self.camera_lot2.id)
        other = self._claim(lot_id=self.spare.id, cause="transport")
        self.assertEqual((first.repeat_count, second.repeat_count, other.repeat_count), (1, 1, 0))
        with self.assertRaises(ValidationError):
            self._claim(date_failure=RECEIVED + timedelta(days=1))
        with self.assertRaises(ValidationError):
            self._claim(component_lot_id=self.lot.id)
        with self.assertRaises(UserError):
            first.with_user(self.head).unlink()
        first.action_cancel()
        self.assertFalse(first.activity_ids)
        first.with_user(self.head).unlink()
        second.invalidate_recordset(["repeat_count"])
        self.assertEqual(second.repeat_count, 0)
