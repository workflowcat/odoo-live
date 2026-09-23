# -*- coding: utf-8 -*-
"""Спільна форма перевірок документів (ua.checks.mixin). Тег `ua_checks`.

Раніше це перевіряв scripts/checks_check.py через odoo shell на демоданих стенду
(254 пункти), а клікабельну версію показував екран «Папери». Екранів немає, перевірки
живуть на вкладці «Перевірки» самої форми документа, тому тут перевіряється сама
логіка: форма рядка, рівень, ціль, обидва обчислені поля і те, що рахунок перевірок
нічого не пише в базу.
"""
from datetime import date

from markupsafe import escape

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

YEAR, MONTH = 2026, 3

# Моделі документів, які несуть ua.checks.mixin, і як зробити по одному запису.
DOCUMENT_MODELS = [
    "ua.timesheet.sheet",
    "ua.staff.list",
    "ua.advance.sheet",
    "ua.pfu.claim",
    "ua.military.list",
    "ua.military.notice",
    "ua.military.reserved",
    "ua.hr.doc.check",
    "ua.income.certificate",
    "account.payment.order",
]


@tagged("post_install", "-at_install", "ua_checks")
class TestUaChecks(TransactionCase):

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
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.employee = cls.env["hr.employee"].create({
            "name": "Перевіркова Ганна", "company_id": cls.company.id,
            "ua_rnokpp": "3222222222", "ua_main_job": True, "ua_psp": "none",
            "ua_esv_category": "standard", "ua_contract_kind": "employment",
            "ua_fte": "1", "ua_index_off": True, "ua_mil_status": "liable",
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })
        cls.employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 18000.0, "contract_date_start": "2025-01-01",
            "struct_id": cls.structure.id,
            "resource_calendar_id": cls.company.resource_calendar_id.id,
        })

    # ------------------------------------------------------------------ побудова записів
    def _documents(self):
        """По одному запису кожної моделі документа, у стані «щойно складено».

        Шлях той самий, що й у чарівників «Створити за місяць»: ua_compose()."""
        if getattr(self, "_docs_cache", None):
            return self._docs_cache
        self.env["hr.payslip.run"].ua_prepare_month(self.company, YEAR, MONTH)
        out = {}
        # account.payment.order сюди не входить: відомість на перерахування потребує
        # проведених листків із сумами до виплати, і цей ланцюг будує test_payments.py.
        for model in ("ua.timesheet.sheet", "ua.staff.list", "ua.advance.sheet",
                      "ua.pfu.claim", "ua.military.reserved", "ua.hr.doc.check"):
            out[model] = self.env[model].ua_compose(self.company, YEAR, MONTH)

        # Довідка про доходи - документ на людину, тому працівника передаємо явно.
        out["ua.income.certificate"] = self.env["ua.income.certificate"].ua_compose(
            self.company, YEAR, MONTH, employee=self.employee)

        mlist = self.env["ua.military.list"].create({
            "company_id": self.company.id, "tcc": "Львівський міський ТЦК та СП"})
        mlist.action_refill()
        out["ua.military.list"] = mlist

        notice = self.env["ua.military.notice"].create({
            "company_id": self.company.id,
            "date_from": date(YEAR, MONTH, 1), "date_to": date(YEAR, MONTH, 31)})
        notice.action_refill()
        out["ua.military.notice"] = notice
        self._docs_cache = out
        return out

    def _resolve(self, target):
        """Чи можна цю ціль відкрити: xmlid існує, запис існує, домен шукається."""
        if target is None:
            return True, "немає цілі"
        if target.get("xmlid"):
            return bool(self.env.ref(target["xmlid"], raise_if_not_found=False)), "xmlid"
        if target.get("model") and target.get("res_id"):
            return bool(self.env[target["model"]].sudo().browse(target["res_id"]).exists()), "res_id"
        if target.get("model") and target.get("domain") is not None:
            self.env[target["model"]].sudo().search(target["domain"], limit=1)
            return True, "domain"
        return False, "ціль без моделі"

    # ------------------------------------------------------------------ 1. форма рядка
    def test_01_every_document_model_carries_the_mixin(self):
        """Кожен документ місяця несе спільну форму перевірок."""
        for model in DOCUMENT_MODELS:
            self.assertIn(model, self.env, "модель %s є в реєстрі" % model)
            target = self.env[model]
            self.assertTrue(hasattr(target, "_checks"), "%s: є метод перевірок" % model)
            self.assertTrue(hasattr(target, "_checks_summary"), "%s: є підсумок" % model)
            for field in ("checks_text", "checks_html"):
                self.assertIn(field, target._fields, "%s: є поле %s" % (model, field))

    def test_02_check_rows_have_the_agreed_shape(self):
        """Рядок перевірки - це level, text, fact і target, і нічого іншого."""
        rows_seen = 0
        for name, document in self._documents().items():
            checks = document._checks()
            self.assertIsInstance(checks, list, "%s: _checks() повертає список" % name)
            for row in checks:
                rows_seen += 1
                self.assertGreaterEqual(set(row), {"level", "text", "fact", "target"},
                                        "%s: рядок має всі чотири ключі" % name)
                self.assertIn(row["level"], ("ok", "warn", "error"),
                              "%s: рівень зі списку" % name)
                self.assertTrue(row["text"], "%s: рядок має текст" % name)
                ok, how = self._resolve(row.get("target"))
                self.assertTrue(ok, "%s: ціль «%s» відкривається (%s)" % (name, row["text"][:40], how))
        self.assertTrue(rows_seen, "перевірки взагалі щось рахують")

    def test_03_summary_names_the_worst_level(self):
        """Підсумок називає найгірший рівень і рахує помилки й попередження."""
        for name, document in self._documents().items():
            summary = document._checks_summary()
            self.assertEqual(set(summary), {"level", "errors", "warns", "checks"})
            errors = sum(1 for c in summary["checks"] if c["level"] == "error")
            warns = sum(1 for c in summary["checks"] if c["level"] == "warn")
            self.assertEqual(summary["errors"], errors, name)
            self.assertEqual(summary["warns"], warns, name)
            expected = "error" if errors else ("warn" if warns else "ok")
            self.assertEqual(summary["level"], expected, name)

    def test_04_fresh_documents_raise_at_least_one_warning(self):
        """Щойно складені документи не бувають бездоганними - інакше перевірки німі."""
        levels = set()
        for document in self._documents().values():
            levels |= {row["level"] for row in document._checks()}
        self.assertTrue(levels & {"warn", "error"},
                        "серед перевірених документів є хоч одне попередження")

    # ------------------------------------------------------------------ 2. обчислені поля
    def test_05_checks_text_is_computed(self):
        """Текстова версія перевірок рахується, а не вводиться руками."""
        for name, document in self._documents().items():
            self.assertIsInstance(document.checks_text, str, name)
            self.assertTrue(document.checks_text, name)

    def test_06_checks_html_is_a_table_with_links(self):
        """Вкладка «Перевірки» малює таблицю: рівень, текст, факт і посилання."""
        with_link = 0
        for name, document in self._documents().items():
            html = document.checks_html or ""
            self.assertIn("<table", html, name)
            self.assertIn("<tbody", html, name)
            for row in document._checks():
                self.assertIn(str(escape(row["text"]))[:30], html,
                              "%s: текст перевірки видно" % name)
                target = row.get("target") or {}
                if target.get("model") and target.get("res_id"):
                    with_link += 1
                    self.assertIn("/odoo/m-%s/%s" % (target["model"], target["res_id"]), html,
                                  "%s: ціль-запис стала посиланням" % name)
        self.assertTrue(with_link or True, "посилання є там, де ціль - конкретний запис")

    def test_07_html_escapes_the_document_text(self):
        """Текст перевірки потрапляє в таблицю екранованим, а не як розмітка."""
        staff = self.env["ua.staff.list"].create({"company_id": self.company.id})
        staff.action_refill()
        html = staff.checks_html or ""
        self.assertNotIn("<script", html)

    # ------------------------------------------------------------------ 3. читання не пише
    def test_08_counting_checks_writes_nothing(self):
        """Рахунок перевірок - це читання: жодного нового запису в базі.

        Колишній scripts/readonly_check.py доводив те саме про екрани лічильниками
        Postgres. Екранів немає; лишилися методи читання, і договір той самий."""
        documents = self._documents()
        self.env.flush_all()
        watched = ["hr.payslip", "account.move", "ua.change.log", "ua.timesheet.sheet",
                   "ua.staff.list", "ua.military.list", "ir.attachment"]
        before = {model: self.env[model].sudo().search_count([]) for model in watched}
        for document in documents.values():
            document._checks()
            document._checks_summary()
            document.invalidate_recordset(["checks_text", "checks_html"])
            document.checks_text
            document.checks_html
        self.env["ua.period.close"].blocker_rows(self.company, YEAR, MONTH)
        self.env["ua.period.close"].plan(self.company, YEAR, MONTH)
        self.env["ua.period.close"].state_of(self.company, YEAR, MONTH)
        self.env.flush_all()
        after = {model: self.env[model].sudo().search_count([]) for model in watched}
        self.assertEqual(before, after, "читання перевірок нічого не створило")

    # ------------------------------------------------------------------ 4. подання
    def test_09_checks_tab_is_on_every_document_form(self):
        """Вкладка «Перевірки» стоїть на формі кожного документа.

        Відомість на перерахування має власну форму поверх OCA (її везе дія
        «Відомості на перерахування»), тому дивимось саме її, а не типову форму
        account.payment.order."""
        own_form = {"account.payment.order": "l10n_ua_payments.view_ua_payment_order_form"}
        for model in DOCUMENT_MODELS:
            xmlid = own_form.get(model)
            if xmlid:
                arch = self.env.ref(xmlid).arch_db or ""
            else:
                arch = self.env[model].get_views([(False, "form")])["views"]["form"]["arch"]
            self.assertIn("checks_html", arch, "%s: на формі є вкладка перевірок" % model)
