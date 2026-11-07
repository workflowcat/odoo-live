# -*- coding: utf-8 -*-
"""Експортний контроль: дозвіл пускає відвантаження за кордон і рахує залишок.

Виріб «БпЛА розвідувальний (тест)» з камерою - подвійного використання, позиція «9A012 (тест)».
На складі 30. Імпортер з Польщі. Без дозволу відвантаження 6 шт. не проводиться.
Дозвіл на 10 шт.: 6 проходять, дозвіл ставиться сам, залишок 4; ще 6 - відмова; 4 - проходять.
Українському клієнту, неконтрольований товар за кордон - без дозволу. Контрагент без країни - відмова.
Прострочений дозвіл не діє; два чинні - обирає людина. Нагадування і звіт.

Запуск: тег ua_export_control.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_export_control")
class TestUaExportControl(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        cls.poland = cls.env.ref("base.pl")
        Product = cls.env["product.product"]
        cls.uav = Product.create({
            "name": "БпЛА розвідувальний (тест)", "type": "consu", "is_storable": True,
            "ua_export_controlled": True, "ua_control_kind": "dual_use", "ua_control_ref": "9A012 (тест)"})
        cls.case = Product.create({"name": "Кейс транспортний (тест)", "type": "consu", "is_storable": True})
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.uav, cls.stock, 30)
        Quant._update_available_quantity(cls.case, cls.stock, 30)
        Partner = cls.env["res.partner"]
        cls.importer = Partner.create({"name": "Importer Sp. z o.o. (test)", "is_company": True,
                                       "country_id": cls.poland.id, "email": "orders@importer.example"})
        cls.domestic = Partner.create({"name": "ТОВ Замовник (тест)", "is_company": True, "country_id": ukraine.id})
        cls.nowhere = Partner.create({"name": "Контрагент без країни (тест)", "is_company": True})
        cls.today = fields.Date.context_today(cls.env.user)

    def _picking(self, partner, rows):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id, "partner_id": partner.id,
            "location_id": self.stock.id, "location_dest_id": self.customers.id,
            "move_ids": [(0, 0, {"product_id": product.id, "product_uom_qty": quantity,
                                 "location_id": self.stock.id, "location_dest_id": self.customers.id})
                         for product, quantity in rows]})
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        return picking

    def _permit(self, name, quantity=10.0, days=90, activate=True, **vals):
        permit = self.env["ua.export.permit"].create(dict({
            "name": name, "partner_id": self.importer.id, "country_id": self.poland.id,
            "date_issue": self.today - timedelta(days=5), "date_expiry": self.today + timedelta(days=days),
            "end_use": "Аерофотозйомка (тест)",
            "line_ids": [(0, 0, {"product_id": self.uav.id, "quantity": quantity})]}, **vals))
        if activate:
            permit.action_activate()
        return permit

    def test_01_permit_gates_export(self):
        first = self._picking(self.importer, [(self.uav, 6)])
        self.assertTrue(first.ua_export_needed)
        with self.assertRaises(UserError, msg="без дозволу за кордон не можна"):
            first.button_validate()
        self.assertNotEqual(first.state, "done")

        permit = self._permit("ДЕК-001 (тест)")
        first.button_validate()
        self.assertEqual(first.state, "done")
        self.assertEqual(first.ua_export_permit_id, permit, "дозвіл ставиться сам")
        line = permit.line_ids
        line.invalidate_recordset(["used_qty", "remaining_qty"])
        self.assertEqual((line.used_qty, line.remaining_qty), (6.0, 4.0))

        second = self._picking(self.importer, [(self.uav, 6)])
        with self.assertRaises(UserError, msg="за дозволом лишилось 4"):
            second.button_validate()
        third = self._picking(self.importer, [(self.uav, 4)])
        third.button_validate()
        self.assertEqual(third.state, "done")
        line.invalidate_recordset(["used_qty", "remaining_qty"])
        self.assertEqual((line.used_qty, line.remaining_qty), (10.0, 0.0))

        home = self._picking(self.domestic, [(self.uav, 2)])
        self.assertFalse(home.ua_export_needed)
        home.button_validate()
        self.assertEqual(home.state, "done")
        self.assertFalse(home.ua_export_permit_id, "в Україні дозвіл не потрібен")
        plain = self._picking(self.importer, [(self.case, 3)])
        plain.button_validate()
        self.assertEqual(plain.state, "done", "неконтрольований товар іде без дозволу")
        unknown = self._picking(self.nowhere, [(self.uav, 1)])
        with self.assertRaises(UserError, msg="без країни перевірити нема з чим"):
            unknown.button_validate()

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_export_control.report_ua_export_permit", permit.ids)[0].decode()
        for text in ("ЗВІТ ПРО ВИКОРИСТАННЯ ДОЗВОЛУ", "ДЕК-001 (тест)", "БпЛА розвідувальний (тест)",
                     "9A012 (тест)", "Importer Sp. z o.o. (test)", first.name, third.name, "Аерофотозйомка"):
            self.assertIn(text, html)
        self.assertNotIn(home.name, html)

    def test_02_expiry_choice_and_reminders(self):
        old = self._permit("ДЕК-000 (тест)", activate=False, date_issue=self.today - timedelta(days=200),
                           date_expiry=self.today - timedelta(days=1))
        with self.assertRaises(UserError, msg="строк минув"):
            old.action_activate()
        old.state = "active"
        picking = self._picking(self.importer, [(self.uav, 2)])
        with self.assertRaises(UserError, msg="прострочений дозвіл не діє"):
            picking.button_validate()
        picking.ua_export_permit_id = old
        with self.assertRaises(UserError):
            picking.button_validate()

        a = self._permit("ДЕК-002 (тест)", days=10)
        b = self._permit("ДЕК-003 (тест)", days=200)
        picking.ua_export_permit_id = False
        with self.assertRaises(UserError, msg="два чинні дозволи - обирає людина"):
            picking.button_validate()
        picking.ua_export_permit_id = b
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.ua_export_permit_id, b)

        Permit = self.env["ua.export.permit"]
        Permit._cron_reminders()
        Permit._cron_reminders()
        self.assertEqual(old.state, "expired")
        self.assertEqual(len(a.activity_ids), 1, "нагадування одне")
        self.assertIn("ДЕК-002 (тест)", a.activity_ids.summary)
        self.assertFalse(b.activity_ids, "до кінця строку ще далеко")
        a.action_close()
        self.assertEqual(a.state, "closed")
        self.assertFalse(a.activity_ids)

    def test_03_guards(self):
        with self.assertRaises(ValidationError):
            self._permit("ДЕК-X", activate=False, date_issue=self.today, date_expiry=self.today - timedelta(days=1))
        with self.assertRaises(ValidationError):
            self._permit("ДЕК-Y", quantity=0.0, activate=False)
        empty = self.env["ua.export.permit"].create({
            "name": "ДЕК-Z", "partner_id": self.importer.id, "country_id": self.poland.id,
            "date_expiry": self.today + timedelta(days=30)})
        with self.assertRaises(UserError, msg="без товарів"):
            empty.action_activate()
