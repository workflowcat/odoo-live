# -*- coding: utf-8 -*-
"""Стандартна форма hr.employee як заміна знятої з полиці картки на OWL (l10n_ua_card_ui,
див. /Users/kit/Codius/odoo-live/shelved/addons-owl/l10n_ua_card_ui). Тег `ua_card`.

Продукт іде на голий Odoo: власного віджета більше немає, картка - це наслідувані вкладки
стандартної форми hr.employee (Особова картка, Зарплата, Документи, Військовий облік,
Відпустки). Тест - регресійний вартовий: перелічує явно кожне поле, яке раніше малювала
get_card_data() (шапка/особа/оплата/відпустка/військовий облік/документи), і провалюється,
якщо поле випаде з арки форми - так само, як провалився б OWL-шаблон із порожнім рядком.

Не портовано (OWL-специфічне, без відповідника на звичайній формі): збірка web.assets_backend.js
з віджетом ua_employee_card, вид-обгортка view_employee_form_ua_card_wrapper і хук, що
підміняє форму для БУДЬ-ЯКОЇ дії на hr.employee (act_window тепер завжди відкриває саму форму,
підміняти нема що), єдина хроніка (get_card_data.timeline) як один список подій - на звичайній
формі вона розкладена по вкладці «Огляд» (контракти, військові події) і нативній стрічці."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "ua_card")
class TestUaEmployeeStandardForm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Employee = cls.env["hr.employee"]

    def _employee(self, name="Формова Ганна", **values):
        vals = {"name": name, "company_id": self.company.id}
        vals.update(values)
        return self.Employee.create(vals)

    # ------------------------------------------------------------------ 1. форма взагалі рендериться
    def test_01_employee_form_renders(self):
        """Форма hr.employee (голий Odoo, без OWL) віддає арку без падіння."""
        views = self.Employee.get_views([(False, "form")])
        self.assertIn("form", views["views"])
        arch = views["views"]["form"]["arch"]
        self.assertTrue(arch)

    # ------------------------------------------------------------------ 2. поля картки «Особа» + «Ідентифікація»
    def test_02_person_fields_are_on_the_form(self):
        """Усе, що get_card_data() малювала в колонці «Особа», лишається доступним - плюс
        «Попередня картка» (ua_previous_employee_id), якого в самій OWL-арці не було (він жив
        лише в шапці картки як посилання, тепер - звичайне поле)."""
        arch = self.Employee.get_views([(False, "form")])["views"]["form"]["arch"]
        for field in (
            "ua_rnokpp", "ua_id_doc_type", "ua_id_doc_series", "ua_id_doc_number", "ua_id_doc_unzr",
            "birthday", "sex", "country_id", "private_street", "private_city", "private_zip",
            "ua_actual_address", "private_phone", "marital", "ua_child_ids",
            "ua_disability_group", "ua_chernobyl_category", "ua_veteran", "ua_large_family",
            "ua_single_parent", "ua_previous_employee_id",
        ):
            self.assertIn('name="%s"' % field, arch, "поле %s має бути на формі" % field)

    # ------------------------------------------------------------------ 3. поля картки «Оплата»
    def test_03_pay_fields_are_on_the_form(self):
        """«Зарплата»: ставка, вид відносин, ЄСВ, ПСП, стаж/лікарняні і - додано цим шматком -
        ua_internal_parttime (internal сумісництво), якого на звичайній формі не було зовсім."""
        arch = self.Employee.get_views([(False, "form")])["views"]["form"]["arch"]
        for field in (
            "ua_current_wage", "ua_contract_kind", "ua_main_job", "ua_fte", "ua_esv_category",
            "ua_psp", "ua_insurance_years", "ua_sick_percent", "ua_internal_parttime",
        ):
            self.assertIn('name="%s"' % field, arch, "поле %s має бути на формі" % field)

    # ------------------------------------------------------------------ 4. поля картки «Відпустка» - тепер окрема вкладка
    def test_04_vacation_fields_are_on_their_own_tab(self):
        """Відпустки більше не мішанина всередині «Зарплата» - окрема вкладка ua_vacation."""
        arch = self.Employee.get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn('name="ua_vacation"', arch, "вкладка «Відпустки» має існувати")
        for field in (
            "ua_vacation_days_year", "ua_vacation_accrued", "ua_vacation_used", "ua_vacation_balance",
            "ua_vacation_opening_balance", "ua_vacation_opening_date",
            "ua_vac_ubd_days_year", "ua_vac_ubd_balance",
            "ua_soc_child_days_year", "ua_soc_child_balance",
            "ua_special_allocated", "ua_special_balance",
        ):
            self.assertIn('name="%s"' % field, arch, "поле %s має бути на формі" % field)

    # ------------------------------------------------------------------ 5. поля картки «Військовий облік»
    def test_05_military_fields_are_on_the_form(self):
        arch = self.Employee.get_views([(False, "form")])["views"]["form"]["arch"]
        for field in (
            "ua_mil_status", "ua_mil_women_list", "ua_mil_category", "ua_mil_group",
            "ua_mil_rank", "ua_mil_vos", "ua_mil_tcc", "ua_mil_doc_type", "ua_mil_doc_series",
            "ua_mil_doc_number", "ua_mil_fitness", "ua_mil_vlk_date", "ua_mil_reserved",
            "ua_mil_reserve_until", "ua_mil_deferment", "ua_mil_deferment_until",
            "ua_reserve_number", "ua_reserve_date", "ua_mil_last_check", "ua_mil_needs_check",
        ):
            self.assertIn('name="%s"' % field, arch, "поле %s має бути на формі" % field)

    # ------------------------------------------------------------------ 6. поля картки «Документи»
    def test_06_document_fields_are_on_the_form(self):
        arch = self.Employee.get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn('name="ua_document_ids"', arch)
        for field in ("type", "number", "date", "valid_until", "state", "ua_doc_state"):
            self.assertIn('name="%s"' % field, arch, "поле документа %s має бути в списку" % field)

    # ------------------------------------------------------------------ 7. кнопки картки - методи існують
    def test_07_card_button_methods_exist_on_the_model(self):
        """Кнопки, що лишаються реальними на звичайній формі (друк П-2, звірка ТЦК, документи,
        довідка про доходи - автобіндингом). «Наказ», «Пакет документів», «Змінити оклад»,
        «Перевести», «Звільнити» не портовано - їхня логіка лежить у моделі ua.hr.order і
        ua.hr.doc.pack.wizard (модуль l10n_ua_hr_orders), який ЗАЛЕЖИТЬ від l10n_ua_hr_card,
        а не навпаки - прив'язати їхню кнопку звідси означало б кругову залежність."""
        self.assertTrue(hasattr(self.Employee, "action_view_ua_documents"))
        self.assertTrue(hasattr(self.Employee, "action_ua_mil_register_check"))
        self.assertTrue(hasattr(self.Employee, "ua_mil_register_check"))
        Document = self.env["ua.employee.document"]
        self.assertTrue(hasattr(Document, "action_mark_signed"))
        self.assertTrue(hasattr(Document, "action_print"))

    # ------------------------------------------------------------------ 8. П-2 далі друкується з форми
    def test_08_p2_report_renders(self):
        employee = self._employee()
        report = self.env.ref("l10n_ua_hr_card.action_report_ua_p2")
        # wkhtmltopdf у контейнері тестів немає, тому доводимо, що рендериться шаблон:
        # саме він ламається, коли на картці зникає поле. PDF друкує стенд (views_check.py).
        html, data_format = report._render_qweb_html(report.report_name, employee.ids)
        self.assertEqual(data_format, "html")
        text = html.decode("utf-8") if isinstance(html, bytes) else str(html)
        self.assertIn("ОСОБОВА КАРТКА", text, "шапка П-2 на місці")
        self.assertIn(employee.name, text, "картка друкує саме цього працівника")

    # ------------------------------------------------------------------ 9. «Записати звірку ТЦК» - та сама логіка, кнопкою форми
    def test_09_register_check_button_creates_event_and_updates_date(self):
        """Портовано з scripts/card_ui_check.py, частина 6: раніше кнопка картки викликала
        ua_mil_register_check() напряму; тепер те саме робить action_ua_mil_register_check(),
        додана в l10n_ua_military/models/hr_employee.py і прив'язана кнопкою на формі."""
        from odoo import fields as odoo_fields

        employee = self._employee("ТЕСТ Тимчасовий (test_employee_form)")
        today = odoo_fields.Date.context_today(employee)

        result = employee.action_ua_mil_register_check()
        employee.invalidate_recordset()

        self.assertIn(result, (False, None), "кнопка лише перечитує форму, дії не повертає")
        self.assertEqual(employee.ua_mil_event_ids.mapped("kind"), ["check"])
        self.assertEqual(employee.ua_mil_last_check, today)
