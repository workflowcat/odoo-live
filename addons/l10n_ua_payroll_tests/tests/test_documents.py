# -*- coding: utf-8 -*-
"""Документи працівника на вкладеннях картки (OCA hr_employee_document). Тег `ua_documents`.

Перевіряємо головне, заради чого скан переїхав: файл лежить одним вкладенням на картці
працівника, те саме сховище показує кнопка «Документи» OCA, і воно не роздвоюється - при
перейменуванні, заміні файлу, переведенні на іншого працівника й видаленні документа
вкладення їде слідом. Український опис (тип, строк, підпис, наказ) лишається нашим.
"""
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
PNG2 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"1" * 128)


@tagged("post_install", "-at_install", "ua_documents")
class TestUaEmployeeDocuments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Document = cls.env["ua.employee.document"]
        cls.Attachment = cls.env["ir.attachment"]

    def _employee(self, name="Документова Ольга"):
        return self.env["hr.employee"].create({"name": name, "company_id": self.company.id})

    def _document(self, employee, **values):
        vals = {"employee_id": employee.id, "type": "passport", "name": "Паспорт"}
        vals.update(values)
        return self.Document.create(vals)

    def _employee_attachments(self, employee):
        return self.Attachment.sudo().search([
            ("res_model", "=", "hr.employee"), ("res_id", "=", employee.id)])

    # ------------------------------------------------------------------ 1. одне сховище
    def test_01_scan_is_an_attachment_on_the_employee(self):
        """Скан лягає вкладенням картки працівника, а не вкладенням самої моделі документа."""
        employee = self._employee()
        doc = self._document(employee, file=PNG, filename="pasport.png")

        self.assertTrue(doc.attachment_id, "документ тримає своє вкладення")
        attachment = doc.attachment_id.sudo()
        self.assertEqual(attachment.res_model, "hr.employee")
        self.assertEqual(attachment.res_id, employee.id)
        self.assertFalse(attachment.res_field, "це самостійне вкладення, а не поле-файл")
        self.assertEqual(attachment.name, "pasport.png")
        self.assertEqual(doc.file, PNG, "файл читається назад без втрат")
        self.assertFalse(self.Attachment.sudo().search_count([
            ("res_model", "=", "ua.employee.document")]),
            "вкладень на самій моделі документа більше немає")

    # ------------------------------------------------------------------ 2. лічильник OCA
    def test_02_oca_document_count_sees_our_scans(self):
        """Кнопка «Документи» OCA рахує саме наші скани - сховище одне."""
        employee = self._employee()
        self.assertEqual(employee.document_count, 0)
        self._document(employee, file=PNG, filename="pasport.png")
        self._document(employee, type="diploma", name="Диплом", file=PNG2, filename="diplom.png")
        employee.invalidate_recordset(["document_count"])
        self.assertEqual(employee.document_count, 2)
        self.assertEqual(len(self._employee_attachments(employee)), 2)

        action = employee.action_get_attachment_tree_view()
        self.assertEqual(self.Attachment.sudo().search(action["domain"]),
                         self._employee_attachments(employee),
                         "кнопка OCA відкриває рівно ті вкладення, що їх створили документи")

    # ------------------------------------------------------------------ 3. без файлу
    def test_03_document_without_a_scan_has_no_attachment(self):
        """Документ на підпис без сканованої копії не створює порожнього вкладення."""
        employee = self._employee()
        doc = self._document(employee, type="statement", name="Заява", state="to_sign")
        self.assertFalse(doc.attachment_id)
        self.assertFalse(doc.file)
        employee.invalidate_recordset(["document_count"])
        self.assertEqual(employee.document_count, 0)

    # ------------------------------------------------------------------ 4. заміна і зняття
    def test_04_replacing_and_clearing_the_scan_keeps_one_record(self):
        """Заміна файлу не плодить вкладень, зняття - прибирає його."""
        employee = self._employee()
        doc = self._document(employee, file=PNG, filename="pasport.png")
        first = doc.attachment_id

        doc.file = PNG2
        self.assertEqual(doc.attachment_id, first, "те саме вкладення, новий вміст")
        self.assertEqual(doc.file, PNG2)
        self.assertEqual(len(self._employee_attachments(employee)), 1)

        doc.file = False
        self.assertFalse(doc.attachment_id)
        self.assertFalse(first.exists(), "знятий файл не лишає сирітського вкладення")
        self.assertEqual(len(self._employee_attachments(employee)), 0)

    # ------------------------------------------------------------------ 5. перейменування
    def test_05_renaming_and_moving_follows_the_attachment(self):
        """Перейменований документ перейменовує вкладення; переведений - переносить його."""
        employee = self._employee()
        other = self._employee("Другий Працівник")
        doc = self._document(employee, file=PNG, filename="pasport.png")

        doc.filename = "pasport-new.png"
        self.assertEqual(doc.attachment_id.sudo().name, "pasport-new.png")

        doc.employee_id = other
        attachment = doc.attachment_id.sudo()
        self.assertEqual(attachment.res_id, other.id)
        employee.invalidate_recordset(["document_count"])
        other.invalidate_recordset(["document_count"])
        self.assertEqual(employee.document_count, 0)
        self.assertEqual(other.document_count, 1)

    # ------------------------------------------------------------------ 6. видалення
    def test_06_deleting_the_document_deletes_the_scan(self):
        """Видалений документ забирає з собою вкладення - картка не збирає сміття."""
        employee = self._employee()
        doc = self._document(employee, file=PNG, filename="pasport.png")
        attachment = doc.attachment_id
        doc.unlink()
        self.assertFalse(attachment.exists())
        self.assertEqual(len(self._employee_attachments(employee)), 0)

    # ------------------------------------------------------------------ 7. строк дії
    def test_07_expiry_state_is_ours(self):
        """Строк дії - наш: діє, спливає за 30 днів, прострочений. Upstream такого не має."""
        from datetime import timedelta

        from odoo import fields as odoo_fields
        employee = self._employee()
        today = odoo_fields.Date.context_today(self.Document)
        cases = {
            False: "ok",
            today + timedelta(days=90): "ok",
            today + timedelta(days=10): "warning",
            today - timedelta(days=1): "expired",
        }
        for valid_until, expected in cases.items():
            doc = self._document(employee, valid_until=valid_until)
            self.assertEqual(doc.ua_doc_state, expected,
                             "строк %s -> %s" % (valid_until, expected))
        employee.invalidate_recordset(["ua_docs_expiring"])
        self.assertEqual(employee.ua_docs_expiring, 1, "у вікно 30 днів потрапляє один документ")

    # ------------------------------------------------------------------ 8. підпис
    def test_08_sign_state_is_ours(self):
        """Стан підпису - наш: на підпис -> підписано і чесний відкат."""
        employee = self._employee()
        doc = self._document(employee, type="nda", name="NDA", state="to_sign")
        result = doc.action_mark_signed()
        self.assertEqual(doc.state, "signed")
        self.assertTrue(doc.signed_date)
        self.assertEqual(result["done"][0]["target"],
                         {"res_model": "ua.employee.document", "res_id": doc.id})

        doc.action_unmark_signed()
        self.assertEqual(doc.state, "to_sign")
        self.assertFalse(doc.signed_date)
        with self.assertRaises(UserError):
            doc.action_unmark_signed()

    # ------------------------------------------------------------------ 9. типи і друк
    def test_09_ukrainian_types_and_reprint_link_are_ours(self):
        """Український перелік типів і посилання на звіт для передруку лишаються нашими."""
        types = dict(self.Document._fields["type"]._description_selection(self.env))
        for key in ("passport", "rnokpp", "labor_book", "military_id", "order", "consent",
                    "safety_briefing", "inventory"):
            self.assertIn(key, types, "тип %s має бути в переліку" % key)
        self.assertEqual(types["labor_book"], "Трудова книжка")

        employee = self._employee()
        doc = self._document(employee, type="order", name="Наказ")
        with self.assertRaises(UserError):
            doc.action_print()
        doc.write({"report_xmlid": "l10n_ua_hr_orders.report_ua_hr_order",
                   "res_model": "ua.hr.order", "res_id": 1})
        action = doc.action_print()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("/ua/print", action["url"])
