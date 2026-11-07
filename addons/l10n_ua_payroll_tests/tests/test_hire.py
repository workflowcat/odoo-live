# -*- coding: utf-8 -*-
"""Логіка «Прийняття» (l10n_ua_hire): та сама поведінка, що раніше перевіряв scripts/hire_check.py
запуском на живому стенді. Тут - справжні юніт-тести в транзакції, без OWL-екрана (l10n_ua_hire_ui
відкладено на полицю): РНОКПП, стани полів за етапом, військовий облік, пакет першого дня і його
QWeb-звіти, розпізнавання документів (підробна відповідь помічника), прийняття, що створює картку
працівника/наказ/J3001005/повідомлення ТЦК, і повторне прийняття (звільнення + нова картка).

Не портовано зі сценарію: форма даних для екрана get_screen_data()/_case_payload(), меню
l10n_ua_hire_ui.menu_ua_hire - усе це належало OWL-екрану, якого більше немає.
"""
import base64
import json
import os
from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.l10n_ua_hire.models import ua_hire_case as hc
from odoo.addons.l10n_ua_military.models.hr_employee import LIABLE_STATUSES

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def make_rnokpp(birthday, male, mid="123"):
    """Той самий генератор, що і в scripts/hire_check.py: валідний РНОКПП для тестових даних."""
    days = (birthday - date(1899, 12, 31)).days
    base = "%05d%s" % (days, mid)
    ninth = 1 if male else 2
    d = [int(c) for c in base] + [ninth]
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    return base + str(ninth) + str(sum(w * x for w, x in zip(weights, d)) % 11 % 10)


class FakeExtractResp:
    """Підробна відповідь помічника розпізнавання (scripts/hire_check.py, секція 5)."""
    ok = True
    status_code = 200

    def json(self):
        return {"model": "claude-test", "proposals": [
            {"field": "middle_name", "value": "Іванович", "file": "id-card.png", "quote": "ІВАНОВИЧ", "confidence": "high"},
            {"field": "mil_status", "value": "Військовозобов'язаний", "file": "vijskovyj.png", "quote": "військовозобов'язаний", "confidence": "high"},
            {"field": "mil_tcc", "value": "Шевченківський РТЦК та СП", "file": "vijskovyj.png", "quote": "Шевченківський", "confidence": "medium"},
            {"field": "mil_doc_type", "value": "ticket", "file": "vijskovyj.png", "quote": "", "confidence": "high"},
            {"field": "mil_doc_number", "value": "АА 123456", "file": "vijskovyj.png", "quote": "123456", "confidence": "high"},
            {"field": "birthday", "value": "14.05.1991", "file": "id-card.png", "quote": "14.05.1991", "confidence": "low"},
            {"field": "wage", "value": "99999", "file": "zayava.png", "quote": "", "confidence": "high"},
            {"field": "sex", "value": "невідомо", "file": "id-card.png", "quote": "", "confidence": "low"},
        ]}


@tagged("post_install", "-at_install", "ua_hire")
class TestUaHireCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Case = cls.env["ua.hire.case"].sudo()
        cls.department = cls.env["hr.department"].search([("company_id", "=", cls.company.id)], limit=1) \
            or cls.env["hr.department"].create({"name": "Тестовий підрозділ", "company_id": cls.company.id})

    # ------------------------------------------------------------------ будівельні блоки
    def _new_case(self, last_name="Перевірочний", first_name="Тарас", job_title="Бухгалтер"):
        return self.Case.browse(self.Case.create_case(last_name=last_name, first_name=first_name, job_title=job_title))

    def _fill_onboarding(self, case, birthday, sex, rnokpp, date_from, wage="25000", id_doc_number="123456789",
                          address="м. Київ, вул. Перевірочна, 1"):
        for f, v in [("birthday", birthday.isoformat()), ("sex", sex), ("id_doc_type", "id_card"),
                     ("id_doc_number", id_doc_number), ("reg_address", address), ("date_from", date_from.isoformat()),
                     ("wage", wage), ("department_id", str(self.department.id)), ("pd_consent", True), ("rnokpp", rnokpp)]:
            case.set_value(f, v)

    # ------------------------------------------------------------------ 1. РНОКПП
    def test_01_rnokpp_problems(self):
        """rnokpp_problems: контрольна цифра, дата народження, стать, довжина."""
        bday = date(1990, 5, 14)
        good = make_rnokpp(bday, True)
        self.assertEqual(hc.rnokpp_problems(good, bday, "male"), [])

        bad_sum = good[:9] + str((int(good[9]) + 1) % 10)
        self.assertTrue(any("контрольна" in p for p in hc.rnokpp_problems(bad_sum)))
        self.assertTrue(any("дату народження" in p for p in hc.rnokpp_problems(good, date(1991, 1, 1))))
        self.assertTrue(any("статі" in p for p in hc.rnokpp_problems(good, bday, "female")))
        self.assertEqual(hc.rnokpp_problems("12345"), ["має бути 10 цифр"])
        self.assertEqual(hc.rnokpp_problems(""), [])

    # ------------------------------------------------------------------ 2. кандидат: мінімум полів
    def test_02_candidate_stage_minimum_required_fields(self):
        """На етапі «Кандидат» обов'язкові лише ПІБ і посада - решта просто «порожньо», не «бракує»."""
        case = self._new_case()
        states = case._field_states()
        self.assertEqual(states["last_name"], "provided")
        self.assertEqual(states["rnokpp"], "empty")
        self.assertFalse([c for c in case._checks() if c["level"] == "error"])

    def test_02b_checks_text_summarizes_the_same_checks(self):
        """checks_text - той самий _checks(), зведений у текст для сторінки «Перевірки»."""
        case = self.Case.create({"last_name": "Безпосадний", "first_name": "Іван"})
        self.assertIn("ПОМИЛКА", case.checks_text)
        case.job_title = "Бухгалтер"
        case.invalidate_recordset(["checks_text"])
        self.assertEqual(case.checks_text, "Перевірок немає.")

    # ------------------------------------------------------------------ 3. оформлення: нові обов'язкові поля
    def test_03_onboarding_requires_more_fields_and_blocks_hire(self):
        case = self._new_case()
        case.action_start_onboarding()
        self.assertEqual(case.stage, "onboarding")

        states = case._field_states()
        self.assertEqual(states["rnokpp"], "missing")
        self.assertEqual(states["date_from"], "missing")
        self.assertEqual(states["id_doc_issued_by"], "empty", "ким виданий не обов'язковий")
        self.assertEqual(states["id_doc_date"], "empty")
        self.assertEqual(states["id_doc_unzr"], "empty")

        options = [k for k, _v in case._field_meta(case)["contract_kind"]["options"]]
        self.assertEqual(options, ["employment"], "«Прийняття» пропонує лише трудовий договір")

        with self.assertRaises(UserError):
            case.action_hire()

    # ------------------------------------------------------------------ 4. ручне введення і службові поля
    def test_04_manual_entry_writes_typed_values(self):
        bday = date(1990, 5, 14)
        good = make_rnokpp(bday, True)
        bad_sum = good[:9] + str((int(good[9]) + 1) % 10)
        start = date.today() + timedelta(days=10)
        case = self._new_case()
        case.action_start_onboarding()
        self._fill_onboarding(case, bday, "male", bad_sum, start)

        self.assertEqual(case.birthday, bday)
        self.assertEqual(case.wage, 25000)
        self.assertEqual(case.department_id, self.department)

        titles = [c["title"] for c in case._checks()]
        self.assertIn("РНОКПП не проходить перевірку", titles)

        case.set_value("rnokpp", good)
        self.assertTrue(case._military_required(), "чоловік 36 років на перший день - підлягає обліку")
        self.assertEqual(case._field_states()["mil_status"], "missing")

        case.set_value("sex", "female")
        self.assertFalse(case._military_required(), "жінці облік не обов'язковий")
        case.set_value("sex", "male")

    def test_04b_service_fields_are_not_editable_from_set_value(self):
        case = self._new_case()
        with self.assertRaises(UserError):
            case.set_value("employee_id", 1)

    def test_04c_closed_case_rejects_set_value(self):
        case = self._hired_case()
        with self.assertRaises(UserError):
            case.set_value("phone", "123")

    # ------------------------------------------------------------------ 5. пакет першого дня і звіти
    def test_05_package_defaults_and_toggle(self):
        case = self._new_case()
        case.action_start_onboarding()
        pkg = case._package()
        self.assertEqual(len(pkg), 7, "7 документів пакета, включно з описом справи")
        self.assertTrue(all(d["on"] for d in pkg))
        self.assertEqual(case.pay_advance_percent, self.company.ua_pay_advance_percent)
        self.assertEqual(case.pay_advance_day, self.company.ua_pay_advance_day)

        case.set_package_doc("nda", False)
        self.assertEqual([d["key"] for d in case._package() if not d["on"]], ["nda"])
        case.set_package_doc("nda", True)
        self.assertTrue(all(d["on"] for d in case._package()))

    def test_05b_package_reports_render_with_case_data(self):
        bday = date(1990, 5, 14)
        good = make_rnokpp(bday, True)
        start = date.today() + timedelta(days=10)
        case = self._new_case()
        case.action_start_onboarding()
        self._fill_onboarding(case, bday, "male", good, start)

        Report = self.env["ir.actions.report"].sudo()
        for d in case._package():
            html, _fmt = Report._render_qweb_html(d["item"]["r"], d["item"]["ids"])
            text = html.decode()
            self.assertTrue("Перевірочний" in text or "ПЕРЕВІРОЧНИЙ" in text,
                             "звіт «%s» містить ПІБ" % d["label"])

        contract_html = Report._render_qweb_html("l10n_ua_hire.report_hire_contract", [case.id])[0].decode()
        self.assertIn("25", contract_html)
        self.assertIn(start.strftime("%d.%m.%Y"), contract_html)

        inventory_html = Report._render_qweb_html("l10n_ua_hire.report_hire_file_inventory", [case.id])[0].decode()
        self.assertIn("ОПИС ДОКУМЕНТІВ", inventory_html)
        self.assertIn("Заява про прийняття", inventory_html)

    def test_05c_requirements_reflect_missing_documents(self):
        case = self._new_case()
        case.action_start_onboarding()
        reqs = {r["code"]: r["state"] for r in case._requirements()}
        self.assertEqual(reqs.get("statement"), "missing")
        self.assertEqual(reqs.get("passport_rnokpp"), "missing")
        self.assertEqual(reqs.get("hire_order"), "later", "накази система друкує сама")

    HELPER_ENV = {"UA_EXTRACT_URL": "http://helper.test", "UA_EXTRACT_TOKEN": "test-token-0123456789abcdef"}

    def setUp(self):
        super().setUp()
        self.startPatcher(patch.dict(os.environ, self.HELPER_ENV))

    # ------------------------------------------------------------------ 6. файли і розпізнавання
    def test_06_extract_requires_consent(self):
        case = self._new_case()
        case.action_start_onboarding()
        case.add_file("zayava.png", PNG, "statement")
        case.write({"pd_consent": False})
        with self.assertRaises(UserError):
            case.action_extract()

    def test_06b_extract_creates_normalized_proposals_only(self):
        case = self._new_case()
        case.action_start_onboarding()
        for name, t in [("zayava.png", "statement"), ("id-card.png", "passport"), ("rnokpp.png", "rnokpp"),
                        ("vijskovyj.png", "military_id"), ("zgoda.png", "consent")]:
            case.add_file(name, PNG, t)
        case.write({"pd_consent": True})

        with patch.object(hc.requests, "post", return_value=FakeExtractResp()) as post:
            res = case.action_extract()
            sent = json.loads(post.call_args.kwargs["data"])

        self.assertNotIn("wage", sent["fields"], "умови роботи не йдуть у документи кандидата")
        self.assertEqual(post.call_args.args[0], "http://helper.test/extract")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-token-0123456789abcdef")
        self.assertIn("rnokpp", sent["fields"])
        self.assertEqual(len(sent["files"]), 5)
        self.assertEqual(res["created"], 6, "умови роботи і хибна стать відкинуті нормалізацією")

        props = {p.field_name: p for p in case.proposal_ids}
        self.assertEqual(props["mil_status"].value, "liable", "вибір за назвою перетворено на ключ")
        self.assertEqual(props["birthday"].value, "1991-05-14", "дата перетворена в ISO")
        self.assertFalse(case.middle_name)
        self.assertFalse(case.mil_status)
        self.assertEqual(case._field_states()["middle_name"], "proposed")
        self.assertEqual(set(case.file_ids.mapped("extract_state")), {"done"})

    def test_06c_proposal_accept_reject_leaves_a_decision_trail(self):
        case = self._new_case()
        case.action_start_onboarding()
        for name, t in [("zayava.png", "statement"), ("id-card.png", "passport"), ("vijskovyj.png", "military_id")]:
            case.add_file(name, PNG, t)
        case.write({"pd_consent": True})
        with patch.object(hc.requests, "post", return_value=FakeExtractResp()):
            case.action_extract()
        props = {p.field_name: p for p in case.proposal_ids}

        for f in ("middle_name", "mil_status", "mil_tcc", "mil_doc_type", "mil_doc_number"):
            props[f].action_accept()
        props["birthday"].action_reject()

        self.assertEqual(case.middle_name, "Іванович")
        self.assertEqual(case.mil_status, "liable")
        self.assertEqual(case.mil_doc_type, "ticket")
        self.assertFalse(case.birthday, "відхилена пропозиція не пише значення")
        self.assertEqual(props["mil_tcc"].decided_by.id, self.env.uid)
        self.assertTrue(props["mil_tcc"].decided_at)

        # повтор не повинен дублювати вже прийняті значення
        with patch.object(hc.requests, "post", return_value=FakeExtractResp()):
            res2 = case.action_extract()
        self.assertLessEqual(res2["created"], 2)

    def test_06e_extract_is_off_without_a_helper_address(self):
        """Без UA_EXTRACT_URL розпізнавання вимкнено: кнопка пояснює, запитів назовні немає."""
        case = self._new_case()
        case.action_start_onboarding()
        case.add_file("id-card.png", PNG, "passport")
        case.write({"pd_consent": True})
        with patch.dict(os.environ, {"UA_EXTRACT_URL": ""}), \
                patch.object(hc.requests, "post") as post, patch.object(hc.requests, "get") as get:
            with self.assertRaises(UserError):
                case.action_extract()
            status = self.env["ua.hire.case"].extract_status()
        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "off")
        post.assert_not_called()
        get.assert_not_called()

    def test_06d_accepting_a_decided_proposal_raises(self):
        case = self._new_case()
        case.action_start_onboarding()
        case.add_file("id-card.png", PNG, "passport")
        case.write({"pd_consent": True})
        with patch.object(hc.requests, "post", return_value=FakeExtractResp()):
            case.action_extract()
        proposal = case.proposal_ids.filtered(lambda p: p.field_name == "middle_name")
        proposal.action_accept()
        with self.assertRaises(UserError):
            proposal.action_accept()

    # ------------------------------------------------------------------ 7. прийняття
    def _hired_case(self, last_name="Готова", first_name="Кандидатка", mid="321"):
        """Жінка - щоб не тягнути за собою обов'язковий військовий облік; те окремо покриває
        test_07b_military_liable_hire_creates_a_notice нижче."""
        bday = date(1990, 5, 14)
        good = make_rnokpp(bday, False, mid=mid)
        start = date.today() + timedelta(days=10)
        case = self._new_case(last_name=last_name, first_name=first_name)
        case.action_start_onboarding()
        self._fill_onboarding(case, bday, "female", good, start, id_doc_number="323456789")
        for name, t in [("zayava.png", "statement"), ("id-card.png", "passport"), ("zgoda.png", "consent")]:
            case.add_file(name, PNG, t)
        self.assertFalse([c for c in case._checks() if c["level"] == "error"], "справа готова до прийняття")
        case.action_hire()
        return case

    def test_07_hire_creates_employee_order_j30_and_locks_the_case(self):
        case = self._hired_case()
        emp = case.employee_id
        self.assertTrue(emp)
        self.assertEqual(emp.ua_rnokpp, case.rnokpp)
        self.assertEqual(emp.job_title, case.job_title)
        self.assertEqual(len(emp.ua_document_ids.filtered("file")), 3, "3 завантажені файли справи стали документами картки")

        self.assertEqual(case.order_id.state, "posted")
        self.assertTrue(case.order_id.name)
        self.assertEqual(len(emp.version_ids), 1)
        self.assertEqual(emp.version_ids.wage, case.wage)

        self.assertEqual(case.j30_run_id.report_code, "j30")
        self.assertEqual(case.j30_run_id.month, case.date_from.month)

        self.assertEqual(case.stage, "hired")
        self.assertTrue(case.hired_date)

        # закрита справа не редагується
        with self.assertRaises(UserError):
            case.set_value("phone", "123")

    def test_07b_military_liable_hire_creates_a_notice(self):
        """Чоловік призовного віку зі станом обліку «Військовозобов'язаний»: прийняття створює
        повідомлення ТЦК, що містить нового працівника."""
        bday = date(1990, 5, 14)
        good = make_rnokpp(bday, True, mid="789")
        start = date.today() + timedelta(days=15)
        liable_case = self._new_case(last_name="Обліковий", first_name="Резервіст")
        liable_case.action_start_onboarding()
        self._fill_onboarding(liable_case, bday, "male", good, start, id_doc_number="423456789")
        liable_case.set_value("mil_status", "liable")
        liable_case.set_value("mil_tcc", "Шевченківський РТЦК та СП")
        liable_case.set_value("mil_doc_type", "ticket")
        liable_case.set_value("mil_doc_number", "АА 123456")
        for name, t in [("zayava.png", "statement"), ("id-card.png", "passport"), ("zgoda.png", "consent"),
                        ("vijskovyj.png", "military_id")]:
            liable_case.add_file(name, PNG, t)
        self.assertFalse([c for c in liable_case._checks() if c["level"] == "error"])
        liable_case.action_hire()

        self.assertTrue(liable_case.employee_id.ua_mil_status in LIABLE_STATUSES)
        self.assertTrue(liable_case.notice_id)
        self.assertIn(liable_case.employee_id, liable_case.notice_id.line_ids.mapped("employee_id"))

    def test_07c_hire_produces_documents_to_sign_pointing_back_to_the_case(self):
        case = self._hired_case(last_name="Пакетна", first_name="Справа", mid="111")
        emp = case.employee_id
        to_sign = emp.ua_document_ids.filtered(lambda d: d.state == "to_sign")
        self.assertEqual(len(to_sign), 7, "6 документів пакета (включно з описом справи) плюс наказ")
        for doc in to_sign:
            self.assertTrue(doc.report_xmlid, "документ на підпис має звіт для передруку")
            self.assertTrue(doc.res_model and doc.res_id)
        order_doc = emp.ua_document_ids.filtered(lambda d: d.type == "order")
        self.assertEqual(order_doc.res_model, "ua.hr.order")
        self.assertEqual(order_doc.res_id, case.order_id.id)

    def test_07d_requirement_package_agrees_between_case_and_employee(self):
        case = self._hired_case(last_name="Звіряна", first_name="Справа", mid="222")
        Requirement = self.env["ua.hr.doc.requirement"].sudo()
        pkg_emp = Requirement.package_for(employee=case.employee_id)
        pkg_case = Requirement.package_for(case=case)

        def rows_by_code(pkg):
            return {r["code"]: {k: v for k, v in r.items() if k != "target"}
                    for block in ("employee", "company") for r in pkg[block]["rows"]}

        self.assertEqual(rows_by_code(pkg_emp), rows_by_code(pkg_case),
                         "картка й справа того самого працівника дають однакові рядки")

    # ------------------------------------------------------------------ 8. звільнення і повторне прийняття
    def test_08_rehire_after_dismissal_creates_a_new_linked_employee(self):
        bday = date(1985, 3, 20)
        good = make_rnokpp(bday, False, mid="777")
        start = date.today() + timedelta(days=5)

        case1 = self._new_case(last_name="Рехайрна", first_name="Богдана")
        case1.action_start_onboarding()
        self._fill_onboarding(case1, bday, "female", good, start, wage="20000", id_doc_number="523456789",
                              address="м. Київ, вул. Перша, 2")
        for name, t in [("zayava.png", "statement"), ("id.png", "passport"), ("zgoda.png", "consent")]:
            case1.add_file(name, PNG, t)
        self.assertFalse([c for c in case1._checks() if c["level"] == "error"])
        case1.action_hire()
        emp1 = case1.employee_id
        self.assertTrue(emp1)

        Order = self.env["ua.hr.order"].sudo()
        dismiss = Order.create({"order_type": "dismissal", "employee_id": emp1.id, "company_id": case1.company_id.id,
                                "date_to": start + timedelta(days=60), "dismissal_basis": "п. 1 ст. 36 КЗпП"})
        dismiss.action_post()
        self.assertFalse(emp1.active, "звільнення архівує працівника")

        start2 = start + timedelta(days=120)
        case2 = self._new_case(last_name="Рехайрна", first_name="Богдана")
        case2.action_start_onboarding()
        self._fill_onboarding(case2, bday, "female", good, start2, wage="21000", id_doc_number="523456789",
                              address="м. Київ, вул. Перша, 2")
        for name, t in [("zayava2.png", "statement"), ("id2.png", "passport"), ("zgoda2.png", "consent")]:
            case2.add_file(name, PNG, t)
        self.assertFalse([c for c in case2._checks() if c["level"] == "error"])
        case2.action_hire()
        emp2 = case2.employee_id

        self.assertNotEqual(emp2.id, emp1.id, "повторне прийняття створює нову картку")
        self.assertEqual(emp2.ua_previous_employee_id.id, emp1.id)
        self.assertFalse(emp1.active, "стара картка лишається архівною")

    # ------------------------------------------------------------------ 9. план прийняття
    def test_09_hire_plan_is_empty_until_the_case_is_ready(self):
        case = self._new_case()
        case.action_start_onboarding()
        self.assertEqual(case.action_hire_plan(), [], "план порожній, доки є помилки")

    def test_09b_hire_plan_describes_what_hire_will_do(self):
        bday = date(1990, 5, 14)
        good = make_rnokpp(bday, False, mid="333")
        start = date.today() + timedelta(days=10)
        case = self._new_case(last_name="Планова", first_name="Справа")
        case.action_start_onboarding()
        self._fill_onboarding(case, bday, "female", good, start, id_doc_number="623456789")
        for name, t in [("zayava.png", "statement"), ("id.png", "passport"), ("zgoda.png", "consent")]:
            case.add_file(name, PNG, t)
        self.assertFalse([c for c in case._checks() if c["level"] == "error"])

        plan = case.action_hire_plan()
        self.assertTrue(plan)
        self.assertTrue(any("картка працівника" in line["text"] or "картку" in line["text"]
                            for line in plan))
        self.assertTrue(any("Наказ" in line["text"] for line in plan))
        self.assertTrue(any("J3001005" in line["text"] for line in plan))

        case.action_hire()
        self.assertTrue(case.order_id.name)

    # ------------------------------------------------------------------ 10. представлення (перевірка, що форма/список живі)
    def test_10_views_load(self):
        views = self.env["ua.hire.case"].get_views([(False, "form"), (False, "list")])
        self.assertIn("form", views["views"])
        self.assertIn("list", views["views"])
        self.assertTrue(self.env.ref("l10n_ua_hire.hr_employee_view_list_no_create").exists(),
                         "«Новий працівник» лишається відключеним - оформлюють через «Прийняття»")
