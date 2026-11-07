# -*- coding: utf-8 -*-
"""Реєстрація кореспонденції.

    вхідний лист 2026-11-03                      -> Вх/2026/0001, завдання виконавцю на строк
    вихідний у відповідь                         -> Вих/2026/0001, вхідний виконано
    вхідний ДСК                                  -> Вх/2026/0001-ДСК (окрема нумерація)
    працівник без допуску                        -> ДСК не бачить і не реєструє
    вхідний 2027-01-05                           -> Вх/2027/0001 (номер з початку року)

Запуск: чиста база, тег ua_correspondence.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

GROUP = "l10n_ua_correspondence.group_ua_correspondence_"


@tagged("post_install", "-at_install", "ua_correspondence")
class TestUaCorrespondence(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Doc = cls.env["ua.correspondence"]
        cls.ministry = cls.env["res.partner"].create({"name": "Замовник: військова частина (тест)"})
        cls.supplier = cls.env["res.partner"].create({"name": "ТОВ Постачальник (тест)"})

        def user(login, group):
            return new_test_user(cls.env, login=login, groups=GROUP + group,
                                 company_id=cls.company.id,
                                 company_ids=[(6, 0, cls.company.ids)])

        cls.clerk = user("corr_clerk", "user")
        cls.engineer = user("corr_engineer", "user")
        cls.secret_clerk = user("corr_dsk", "restricted")
        cls.today = fields.Date.context_today(cls.Doc)

    def _incoming(self, user=None, **vals):
        values = {"direction": "in", "partner_id": self.ministry.id, "date": "2026-11-03",
                  "partner_ref": "123/4", "partner_date": "2026-11-01",
                  "subject": "Запит щодо строків поставки (тест)"}
        values.update(vals)
        return self.Doc.with_user(user or self.clerk).create(values)

    # --- 1. Номери ------------------------------------------------------------

    def test_01_numbers_per_direction_and_year(self):
        first = self._incoming()
        second = self._incoming()
        outgoing = self.Doc.with_user(self.clerk).create({
            "direction": "out", "partner_id": self.supplier.id, "date": "2026-11-03",
            "subject": "Претензія (тест)", "kind": "claim"})
        next_year = self._incoming(date="2027-01-05")
        self.assertEqual(first.name, "Вх/2026/0001")
        self.assertEqual(second.name, "Вх/2026/0002")
        self.assertEqual(outgoing.name, "Вих/2026/0001")
        self.assertEqual(next_year.name, "Вх/2027/0001", "номер з початку кожного року")
        self.assertEqual(first.user_id, self.clerk)
        self.assertEqual(first.state, "registered")

    def test_02_registered_document_is_not_deleted(self):
        doc = self._incoming()
        with self.assertRaises(UserError):
            doc.with_user(self.secret_clerk).unlink()
        doc.with_user(self.clerk).action_cancel()
        doc.with_user(self.secret_clerk).unlink()
        self.assertFalse(doc.exists())
        with self.assertRaises(UserError):
            self._incoming().with_user(self.clerk).write({"direction": "out"})

    # --- 2. Контроль виконання -------------------------------------------------

    def test_03_responsible_gets_task_with_deadline(self):
        due = self.today + timedelta(days=5)
        doc = self._incoming(responsible_id=self.engineer.id, date_due=due)
        todo = self.env.ref("mail.mail_activity_data_todo")
        activity = doc.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual((activity.user_id, activity.date_deadline, activity.activity_type_id),
                         (self.engineer, due, todo))
        later = due + timedelta(days=3)
        doc.with_user(self.clerk).date_due = later
        self.assertEqual(doc.activity_ids.date_deadline, later, "строк переноситься в завдання")
        self.assertEqual(len(doc.activity_ids), 1)
        doc.with_user(self.engineer).action_start()
        doc.with_user(self.engineer).action_done()
        self.assertEqual(doc.state, "done")
        self.assertEqual(doc.date_done, self.today)
        self.assertFalse(doc.activity_ids, "виконане завдання закривається")

    def test_04_overdue(self):
        late = self._incoming(date_due=self.today - timedelta(days=1))
        on_time = self._incoming(date_due=self.today + timedelta(days=1))
        closed = self._incoming(date_due=self.today - timedelta(days=2))
        closed.action_done()
        self.assertTrue(late.is_overdue)
        self.assertFalse(on_time.is_overdue)
        self.assertFalse(closed.is_overdue)
        mine = self.Doc.search([("id", "in", (late | on_time | closed).ids)])
        self.assertEqual(mine.filtered_domain([("is_overdue", "=", True)]), late)
        self.assertEqual(self.Doc.search([("id", "in", mine.ids), ("is_overdue", "=", True)]), late)
        self.assertEqual(self.Doc.search([("id", "in", mine.ids), ("is_overdue", "=", False)]),
                         on_time | closed)

    def test_05_reply_closes_incoming(self):
        incoming = self._incoming(needs_reply=True, responsible_id=self.engineer.id,
                                  date_due=self.today + timedelta(days=3))
        with self.assertRaises(UserError):
            incoming.with_user(self.engineer).action_done()  # ще без відповіді
        action = incoming.with_user(self.engineer).action_reply()
        defaults = {key[len("default_"):]: value for key, value in action["context"].items()}
        self.assertEqual(defaults["direction"], "out")
        self.assertEqual(defaults["partner_id"], self.ministry.id)
        self.assertIn("№ 123/4", defaults["subject"])
        reply = self.Doc.with_user(self.engineer).with_context(action["context"]).create({
            "signer_id": self.engineer.id})
        self.assertEqual(reply.direction, "out")
        self.assertTrue(reply.name.startswith("Вих/"))
        self.assertEqual(reply.reply_to_id, incoming)
        self.assertEqual(incoming.state, "done")
        self.assertEqual(incoming.reply_ids, reply)
        self.assertFalse(incoming.activity_ids)
        with self.assertRaises(ValidationError):
            self.Doc.create({"direction": "in", "partner_id": self.ministry.id,
                             "subject": "Не відповідь (тест)", "reply_to_id": incoming.id})

    # --- 3. ДСК -----------------------------------------------------------

    def test_06_restricted_numbering_and_access(self):
        open_doc = self._incoming()
        secret = self._incoming(user=self.secret_clerk, restricted=True,
                                subject="Технічне завдання ДСК (тест)")
        self.assertEqual(open_doc.name, "Вх/2026/0001")
        self.assertEqual(secret.name, "Вх/2026/0001-ДСК", "ДСК мають окрему нумерацію")

        visible = self.Doc.with_user(self.clerk).search([("id", "in", (open_doc | secret).ids)])
        self.assertEqual(visible, open_doc, "без допуску ДСК не видно")
        with self.assertRaises(AccessError):
            secret.with_user(self.clerk).read(["subject"])
        with self.assertRaises(AccessError):
            self._incoming(restricted=True)  # реєструє лише працівник з допуском
        self.assertEqual(self.Doc.with_user(self.secret_clerk).search(
            [("id", "in", (open_doc | secret).ids)]), open_doc | secret)

        with self.assertRaises(UserError):
            secret.with_user(self.secret_clerk).restricted = False  # гриф не знімають
        with self.assertRaises(ValidationError):
            secret.with_user(self.secret_clerk).responsible_id = self.engineer  # без допуску

    def test_07_reply_to_restricted_is_restricted(self):
        secret = self._incoming(user=self.secret_clerk, restricted=True, needs_reply=True)
        values = secret._reply_values()
        self.assertTrue(values["restricted"])
        reply = self.Doc.with_user(self.secret_clerk).create(values)
        self.assertTrue(reply.name.endswith("-ДСК"))
        self.assertEqual(secret.state, "done")
        values["restricted"] = False
        with self.assertRaises(ValidationError):
            self.Doc.with_user(self.secret_clerk).create(values)

    # --- 4. Журнал --------------------------------------------------------

    def test_08_register_rows_and_print(self):
        first = self._incoming(responsible_id=self.engineer.id, date_due="2026-11-10")
        self._incoming(date="2026-11-04", partner_id=self.supplier.id, partner_ref=False,
                       subject="Рахунок (тест)")
        self._incoming(user=self.secret_clerk, restricted=True, subject="ДСК (тест)")
        self._incoming(date="2026-12-01")
        rows = self.Doc.register_rows("in", "2026-11-01", "2026-11-30", company=self.company)
        self.assertEqual([r["name"] for r in rows], ["Вх/2026/0001", "Вх/2026/0002"])
        self.assertEqual(rows[0]["responsible"], self.engineer.name)
        self.assertEqual(rows[0]["partner_ref"], "123/4")
        secret_rows = self.Doc.with_user(self.secret_clerk).register_rows(
            "in", "2026-11-01", "2026-11-30", restricted=True, company=self.company)
        self.assertEqual([r["name"] for r in secret_rows], ["Вх/2026/0001-ДСК"])

        docs = self.Doc.search([("date", ">=", "2026-11-01"), ("date", "<=", "2026-11-30")])
        html, _kind = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_correspondence.report_ua_correspondence_register", docs.ids)
        text = html.decode() if isinstance(html, bytes) else html
        for expected in ("ЖУРНАЛ РЕЄСТРАЦІЇ ВХІДНИХ ДОКУМЕНТІВ", "Для службового користування",
                         first.name, "№ 123/4", self.engineer.name, "10.11.2026"):
            self.assertIn(expected, text)
