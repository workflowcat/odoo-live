# -*- coding: utf-8 -*-
"""Анкета компанії (l10n_ua_setup) на стандартній формі, без OWL-екрана.

Порт логіки з scripts/setup_check.py (170 рядків), яка раніше зверталася до
ua.setup.profile.screen()/get_screen_data()/set_answer()/run() на живому стенді:
тут усе будується в транзакції тесту через ORM-виклики тих самих методів моделі
(profile_for, action_fill, action_propose, action_confirm, action_activate,
action_apply). Не портовано: розбір словника screen() на розділи/кнопки й set_answer()
з рядка id - це була форма самого OWL-екрана (знятого з полиці), а не логіка анкети;
дію "apply" екран викликав через run("apply"), тут кличемо ту саму дію напряму -
action_apply()."""
import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_setup")
class TestUaSetupProfile(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Profile = cls.env["ua.setup.profile"]
        cls.Question = cls.env["ua.setup.question"]
        cls.Answer = cls.env["ua.setup.answer"]
        cls.question_count = cls.Question.search_count([])

    def _user(self, group_xmlids):
        login = "ua_setup_test_%s" % uuid.uuid4().hex[:10]
        groups = [self.env.ref(xmlid).id for xmlid in group_xmlids]
        return self.env["res.users"].create({
            "name": "Тестовий користувач", "login": login, "email": "%s@example.com" % login,
            "group_ids": [(6, 0, groups)],
        })

    # ------------------------------------------------------------------ 1. каталог питань
    def test_question_catalog_loaded_from_source_document(self):
        questions = self.Question.search_read([], ["code", "section", "name", "required", "kind", "options"])
        self.assertGreaterEqual(len(questions), 60, "питань у каталозі")
        sections = {q["section"] for q in questions}
        self.assertGreaterEqual(len(sections), 10, "розділів анкети")
        required = [q for q in questions if q["required"]]
        self.assertGreaterEqual(len(required), 5, "обов'язкових питань")
        self.assertTrue(any(q["options"] for q in questions), "варіанти відповіді збережені")
        self.assertTrue(any("ЄДРПОУ" in q["name"] for q in questions))
        self.assertTrue(any("бронювання" in q["name"] for q in questions),
                        "текст питань узятий з анкети бухгалтера, не переписаний")

    # ------------------------------------------------------------------ 2. views
    def test_views_load(self):
        views = self.Profile.get_views([(False, "form"), (False, "list")])
        self.assertIn("form", views["views"])
        self.assertIn("list", views["views"])

    # ------------------------------------------------------------------ 3. profile_for / action_fill
    def test_profile_for_is_idempotent_per_company(self):
        profile = self.Profile.profile_for(self.company)
        self.assertTrue(profile)
        self.assertEqual(profile.total_count, self.question_count, "заповнюється каталогом одразу")
        again = self.Profile.profile_for(self.company)
        self.assertEqual(again, profile, "повторний виклик відкриває наявну анкету, не дублює")
        self.assertEqual(self.Profile.search_count([("company_id", "=", self.company.id)]), 1)

    def test_action_fill_creates_one_answer_per_question_and_is_idempotent(self):
        profile = self.Profile.create({"company_id": self.company.id})
        profile.action_fill()
        self.assertEqual(len(profile.answer_ids), self.question_count)
        profile.action_fill()
        self.assertEqual(len(profile.answer_ids), self.question_count, "повторний виклик не плодить рядків")

    def test_pull_known_supplies_answers_from_company_fields(self):
        self.company.write({"company_registry": "87654321", "ua_director_name": "Директорка Директорівна"})
        profile = self.Profile.profile_for(self.company)
        registry_answer = profile.answer_ids.filtered(lambda a: a.question_id.name == "Який ЄДРПОУ компанії?")
        self.assertTrue(registry_answer)
        self.assertEqual(registry_answer.value, "87654321")
        self.assertEqual(registry_answer.state, "supplied")
        self.assertEqual(registry_answer.source, "system")
        director_answer = profile.answer_ids.filtered(lambda a: a.question_id.name == "Хто директор / підписант компанії?")
        self.assertEqual(director_answer.value, "Директорка Директорівна")
        self.assertEqual(director_answer.state, "supplied")

    # ------------------------------------------------------------------ 4. action_propose
    def test_action_propose_requires_description(self):
        profile = self.Profile.profile_for(self.company)
        with self.assertRaises(UserError):
            profile.action_propose()

    def test_action_propose_fills_from_description_and_keeps_confirmed(self):
        profile = self.Profile.profile_for(self.company)
        legal_form = profile.answer_ids.filtered(lambda a: a.question_id.name == "Яка організаційно-правова форма компанії?")
        self.assertTrue(legal_form)
        legal_form.write({"value": "ФОП", "state": "confirmed", "source": "accountant"})

        profile.description = ("Українське ТОВ, меблі, 20 працівників, більшість на окладі, "
                               "двоє на пів ставки, розрахунки в гривні, один банк для зарплати")
        profile.action_propose()

        proposed = profile.answer_ids.filtered(lambda a: a.state == "proposed")
        self.assertGreaterEqual(len(proposed), 4, "опис компанії дає кілька пропозицій")
        self.assertTrue(all(a.source == "description" for a in proposed))
        self.assertEqual(legal_form.value, "ФОП", "уже підтверджену відповідь пропозиція не чіпає")
        self.assertEqual(legal_form.state, "confirmed")

        people = profile.answer_ids.filtered(lambda a: a.question_id.name == "Скільки людей залучено зараз?")
        if people:
            self.assertEqual(people.value, "16-50")

    def test_people_from_text_buckets(self):
        cases = [("3 працівники", "1-5"), ("5 осіб", "1-5"), ("6 людей", "6-15"), ("15 співробітників", "6-15"),
                 ("16 працівників", "16-50"), ("50 осіб", "16-50"), ("51 працівник", "50+"), ("немає чисел тут", "")]
        for text, expected in cases:
            self.assertEqual(self.Profile._people_from_text(text), expected, text)

    # ------------------------------------------------------------------ 5. підтвердження відповіді
    def test_action_confirm_requires_value_then_confirms_and_resets(self):
        profile = self.Profile.profile_for(self.company)
        answer = profile.answer_ids.filtered(lambda a: a.state == "missing")[:1]
        self.assertTrue(answer, "має лишитися хоч одне незаповнене питання на свіжій анкеті")
        with self.assertRaises(UserError):
            answer.action_confirm()
        answer.write({"value": "тестова відповідь"})
        answer.action_confirm()
        self.assertEqual(answer.state, "confirmed")
        answer.action_reset()
        self.assertEqual(answer.state, "missing")
        self.assertFalse(answer.value)

    # ------------------------------------------------------------------ 6. обов'язкові питання блокують активацію
    def test_action_activate_blocked_by_required_missing_then_succeeds(self):
        profile = self.Profile.profile_for(self.company)
        self.assertGreater(profile.required_missing, 0, "на свіжій анкеті є незакриті обов'язкові питання")
        with self.assertRaises(UserError):
            profile.action_activate()

        for answer in profile.answer_ids.filtered(lambda a: a.required and a.state == "missing"):
            answer.write({"value": "Тест"})
            answer.action_confirm()
        self.assertEqual(profile.required_missing, 0)
        profile.action_activate()
        self.assertEqual(profile.state, "active")

    def test_action_ready_and_draft_toggle_state(self):
        profile = self.Profile.profile_for(self.company)
        profile.action_ready()
        self.assertEqual(profile.state, "ready")
        profile.action_draft()
        self.assertEqual(profile.state, "draft")

    # ------------------------------------------------------------------ 7. застосування в налаштування компанії
    def test_action_apply_writes_company_setting_and_is_idempotent(self):
        question = self.Question.search([("code", "=", "q010")], limit=1)
        self.assertTrue(question, "q010 - питання про систему оподаткування")
        self.company.write({"ua_tax_system": False})
        profile = self.Profile.profile_for(self.company)
        answer = profile.answer_ids.filtered(lambda a: a.question_id == question)
        answer.write({"value": "ЄП 3 група, 5% (без ПДВ)", "state": "confirmed", "source": "accountant"})

        preview = profile.preview_apply()
        row = next((r for r in preview if r["field"] == "ua_tax_system"), None)
        self.assertTrue(row, "попередній перегляд показує зміну системи оподаткування")
        self.assertEqual(row["new"], "ep3_5")

        profile.action_apply()
        self.assertEqual(self.company.ua_tax_system, "ep3_5")
        self.assertFalse(any(r["field"] == "ua_tax_system" for r in profile.preview_apply()),
                         "після запису переглядати більше нічого")

        with self.assertRaises(UserError):
            profile.action_apply()  # вдруге застосовувати нічого

    def test_action_apply_requires_write_access(self):
        profile = self.Profile.profile_for(self.company)
        user = self._user(["base.group_user"])
        with self.assertRaises(AccessError):
            profile.with_user(user).action_apply()

    # ------------------------------------------------------------------ 8. пробний місяць
    def test_action_test_month_returns_message(self):
        profile = self.Profile.profile_for(self.company)
        result = profile.action_test_month()
        self.assertTrue(result.get("message"))

    # ------------------------------------------------------------------ 9. права доступу звичайного користувача
    def test_profile_write_requires_hr_group(self):
        profile = self.Profile.profile_for(self.company)
        user = self._user(["base.group_user"])
        with self.assertRaises(AccessError):
            profile.with_user(user).write({"description": "щось"})
        with self.assertRaises(AccessError):
            self.Answer.with_user(user).create({
                "profile_id": profile.id,
                "question_id": self.Question.search([], limit=1).id,
            })
