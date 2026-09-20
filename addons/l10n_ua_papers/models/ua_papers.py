# -*- coding: utf-8 -*-
"""Сторінка «Папери»: один екран усіх друкованих паперів замість дванадцяти майстрів
і двадцяти чотирьох звітів, кожного у своєму меню. Період угорі задається один раз і
діє на всі папери; ліворуч - які папери бувають, посередині - поля й перегляд обраного
паперу, праворуч - звідки в нього дані і перевірки.

Модуль своїх даних не тримає (як l10n_ua_home і l10n_ua_period.ua_period_board): усе
читає з наявних моделей (табель, штатний розпис, накази, листки, відомості, списки
військового обліку тощо) і звітів, які в них уже є.

Перелік паперів - один реєстр PAPERS (метод `_registry`), а не розгалуження по коду:
кожен папір - один запис зі своєю моделлю, звітом, способом знайти запис періоду і
способом побудувати поля/джерела. Новий папір - новий запис реєстру.

Слова в інтерфейсі - за нормою docs/payroll/words.md: назва речі, не розповідь про неї,
без «ми»/«ви», кнопка одним дієсловом («Друк», «Створити», «Затвердити», «Відкрити»),
причина вимкненої кнопки - один факт без вибачень.
"""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
MONTHS_SHORT = {
    1: "січ", 2: "лют", 3: "бер", 4: "кві", 5: "тра", 6: "чер",
    7: "лип", 8: "сер", 9: "вер", 10: "жов", 11: "лис", 12: "гру",
}
# Родовий відмінок: дата читається «16 вересня», а не «16 вересень».
MONTHS_OF = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
    7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
}
CHECK_LEVEL = {"error": "crit", "warn": "warn", "ok": "ok"}


class UaPapers(models.AbstractModel):
    _name = "ua.papers"
    _description = "Дані екрана «Папери»"

    # ------------------------------------------------------------------ хелпери
    def _company(self):
        return self.env.company

    @staticmethod
    def _bounds(year, month):
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return first, last

    @staticmethod
    def _t_record(record):
        """Ціль на конкретний запис - та сама форма, що приймає open_target."""
        if not record:
            return None
        return {"model": record._name, "res_id": record.id}

    # ------------------------------------------------------------------ реєстр паперів
    def _registry(self):
        """Усі папери екрана. Кожен запис описує себе повністю: модель, звіт, як
        знайти запис періоду (`find_domain`/`find_fn`), додаткові поля вибору
        (`extra_fields` для «за місяць», `options_fn` для «на людину»), як
        скласти чернетку (`composable` + `compose_vals`/`compose_fn`) і звідки
        в папір дані (`sources_fn`). Новий папір - новий запис тут, без правок
        методів нижче."""
        return [
            # ------------------------------------------------------------ за місяць
            {
                "key": "timesheet", "group": "month", "group_label": "За місяць",
                "short_name": "Табель П-5", "full_name": "Табель обліку робочого часу",
                "subtitle": "типова форма П-5", "model": "ua.timesheet.sheet",
                "report": "l10n_ua_hr_docs.action_report_ua_timesheet",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
                    ("department_id", "=", params.get("department_id") or False),
                ],
                "extra_fields": [{"key": "department_id", "label": "Підрозділ", "options_fn": self._opt_departments}],
                "composable": True, "compose_fn": self._compose_timesheet,
                "missing_text": "Немає табеля за {m}", "empty_action": "Створити",
                "sources_fn": self._src_timesheet,
                "line_model": "ua.timesheet.line", "line_inverse": "sheet_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_timesheet_line_list",
            },
            {
                "key": "staff_list", "group": "month", "group_label": "За місяць",
                "short_name": "Штатний розпис", "full_name": "Штатний розпис",
                "subtitle": "на дату", "model": "ua.staff.list",
                "report": "l10n_ua_hr_docs.action_report_ua_staff_list",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id), ("date", "<=", last),
                ],
                "find_order": "date desc, id desc",
                "composable": True,
                "compose_vals": lambda company, year, month, first, last, params: {
                    "company_id": company.id, "date": last},
                "compose_fill": "action_refill",
                "missing_text": "Немає штатного розпису на цю дату", "empty_action": "Створити",
                "sources_fn": self._src_staff_list,
                "line_model": "ua.staff.list.line", "line_inverse": "list_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_staff_list_line_list",
            },
            {
                "key": "advance", "group": "month", "group_label": "За місяць",
                "short_name": "Авансова відомість", "full_name": "Авансова відомість",
                "subtitle": "", "model": "ua.advance.sheet",
                "report": "l10n_ua_payroll_reports.action_report_ua_advance_sheet",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
                ],
                "composable": True,
                "compose_vals": lambda company, year, month, first, last, params: {
                    "company_id": company.id, "year": year, "month": month},
                "compose_fill": "action_refill",
                "missing_text": "Аванс за {m} не розраховано", "empty_action": "Створити",
                "sources_fn": self._src_advance,
                "line_model": "ua.advance.line", "line_inverse": "sheet_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_advance_line_list",
            },
            {
                "key": "payment_batch", "group": "month", "group_label": "За місяць",
                "short_name": "Відомість на перерахування", "full_name": "Відомість на перерахування",
                "subtitle": "", "model": "ua.payment.batch",
                "report": "l10n_ua_payments.action_report_ua_payment_batch",
                "find_fn": self._find_payment_batch,
                "extra_fields": [{"key": "kind", "label": "Вид виплати", "options_fn": self._opt_payment_kinds,
                                  "default": "salary"}],
                "composable": True,
                "compose_vals": lambda company, year, month, first, last, params: {
                    "company_id": company.id, "year": year, "month": month,
                    "kind": params.get("kind") or "salary"},
                "compose_fill": "action_fill",
                "missing_text": "Немає відомості цього виду за {m}", "empty_action": "Створити",
                "sources_fn": self._src_payment_batch,
                "line_model": "ua.payment.line", "line_inverse": "batch_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_payment_line_list",
            },
            {
                "key": "payroll_sheet", "group": "month", "group_label": "За місяць",
                "short_name": "Розрахунково-платіжна відомість", "full_name": "Розрахунково-платіжна відомість",
                "subtitle": "пакет листків місяця", "model": "hr.payslip.run",
                "report": "l10n_ua_payroll_reports.action_report_ua_payroll_sheet",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id), ("date_start", ">=", first), ("date_start", "<=", last),
                ],
                "find_order": "date_start desc, id desc",
                "composable": True,
                "compose_vals": lambda company, year, month, first, last, params: {
                    "name": "Зарплата %02d.%d" % (month, year), "date_start": first, "date_end": last,
                    "company_id": company.id},
                "missing_text": "Немає розрахунку за {m}", "empty_action": "Створити",
                "sources_fn": self._src_payroll_sheet,
            },
            # ------------------------------------------------------------ на людину
            {
                "key": "order", "group": "person", "group_label": "На людину",
                "short_name": "Наказ", "full_name": "Кадровий наказ",
                "subtitle": "", "model": "ua.hr.order",
                "report": "l10n_ua_hr_orders.action_report_ua_hr_order",
                "picker_label": "Наказ", "options_fn": self._opt_orders,
                "state_field": "state", "draft_states": {"draft", "cancelled"},
                "composable": False, "compose_block_reason": "Наказ заводять у кадрах",
                "missing_text": "Немає наказів за {m}", "sources_fn": self._src_order,
            },
            {
                "key": "payslip", "group": "person", "group_label": "На людину",
                "short_name": "Розрахунковий листок", "full_name": "Розрахунковий листок",
                "subtitle": "", "model": "hr.payslip",
                "report": "l10n_ua_payroll_reports.action_report_ua_payslip",
                "picker_label": "Листок", "options_fn": self._opt_payslips,
                "state_field": "state", "draft_states": {"draft", "verify", "cancel"},
                "composable": False, "compose_block_reason": "Листок рахує розрахунок",
                "missing_text": "Немає розрахункових листків за {m}", "sources_fn": self._src_payslip,
            },
            {
                "key": "p2", "group": "person", "group_label": "На людину",
                "short_name": "Особова картка П-2", "full_name": "Особова картка",
                "subtitle": "типова форма П-2", "model": "hr.employee",
                "report": "l10n_ua_hr_card.action_report_ua_p2",
                "picker_label": "Працівник", "options_fn": self._opt_employees,
                "state_field": None,
                "composable": False, "compose_block_reason": "Картку редагують у працівнику",
                "missing_text": "Немає активних працівників", "sources_fn": self._src_p2,
            },
            {
                "key": "contract", "group": "person", "group_label": "На людину",
                "short_name": "Трудовий договір", "full_name": "Трудовий договір",
                "subtitle": "", "model": "ua.hire.case",
                "report": "l10n_ua_hire.action_report_hire_contract",
                "picker_label": "Справа", "options_fn": self._opt_hire_cases,
                "state_field": "stage", "draft_states": {"candidate", "onboarding", "declined"},
                "composable": False, "compose_block_reason": "Справу заводять у прийнятті",
                "missing_text": "Немає справ прийняття", "sources_fn": self._src_contract,
            },
            # ------------------------------------------------------------ для держави
            {
                "key": "pfu", "group": "state", "group_label": "Для держави",
                "short_name": "Заява-розрахунок до ПФУ", "full_name": "Заява-розрахунок до ПФУ",
                "subtitle": "", "model": "ua.pfu.claim",
                "report": "l10n_ua_hr_docs.action_report_ua_pfu_claim",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id),
                    ("payslip_run_id.date_start", ">=", first), ("payslip_run_id.date_start", "<=", last),
                ],
                "composable": True, "compose_fn": self._compose_pfu,
                "missing_text": "Немає заяви-розрахунку за {m}", "empty_action": "Створити",
                "sources_fn": self._src_pfu,
                "line_model": "ua.pfu.claim.line", "line_inverse": "claim_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_pfu_claim_line_list",
            },
            {
                "key": "military_list", "group": "state", "group_label": "Для держави",
                "short_name": "Список військового обліку", "full_name": "Список персонального військового обліку",
                "subtitle": "постанова КМУ № 1487", "model": "ua.military.list",
                "report": "l10n_ua_military.action_report_ua_military_list",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id), ("date", "<=", last),
                ],
                "find_order": "date desc, id desc",
                "composable": False, "compose_block_reason": "Потрібно вказати ТЦК та СП",
                "edit_fallback": {"xmlid": "l10n_ua_military.action_ua_military_list"},
                "missing_text": "Немає списку військового обліку на цю дату", "empty_action": "Відкрити",
                "sources_fn": self._src_military_list,
                "line_model": "ua.military.list.line", "line_inverse": "list_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_military_list_line_list",
            },
            {
                "key": "military_reserved", "group": "state", "group_label": "Для держави",
                "short_name": "Список заброньованих", "full_name": "Список заброньованих",
                "subtitle": "", "model": "ua.military.reserved",
                "report": "l10n_ua_military.action_report_ua_military_reserved",
                "find_domain": lambda company, first, last, year, month, params: [
                    ("company_id", "=", company.id), ("date", "<=", last),
                ],
                "find_order": "date desc, id desc",
                "composable": True,
                "compose_vals": lambda company, year, month, first, last, params: {
                    "company_id": company.id, "date": last},
                "compose_fill": "action_refill",
                "missing_text": "Немає списку заброньованих на цю дату", "empty_action": "Створити",
                "sources_fn": self._src_military_reserved,
                "line_model": "ua.military.reserved.line", "line_inverse": "reserved_id",
                "line_view_xmlid": "l10n_ua_papers.view_ua_papers_military_reserved_line_list",
            },
            # ------------------------------------------------------------ журнали
            {
                "key": "order_register", "group": "register", "group_label": "Журнали",
                "short_name": "Журнал наказів", "full_name": "Журнал реєстрації наказів",
                "subtitle": "", "model": "ua.hr.order.register.wizard",
                "report": "l10n_ua_hr_orders.action_report_ua_hr_order_register",
                "print_fallback": {"xmlid": "l10n_ua_hr_orders.action_ua_hr_order_register_wizard"},
                "composable": False, "compose_block_reason": "Журнал не існує як документ",
                "missing_text": "Журнал не має окремого перегляду", "empty_action": "Друк",
                "sources_fn": self._src_order_register,
            },
        ]

    # ------------------------------------------------------------------ вибір за групою «на людину»
    def _opt_orders(self, company, first, last):
        orders = self.env["ua.hr.order"].search([
            ("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last)],
            order="date desc, id desc")
        return [(o.id, "%s - %s" % (o.name or "без номера", o.employee_id.name or "")) for o in orders]

    def _opt_payslips(self, company, first, last):
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "!=", "cancel")], order="id desc")
        return [(s.id, s.employee_id.name or s.display_name) for s in slips]

    def _opt_employees(self, company, first, last):
        # Особова картка не прив'язана до місяця - перелік не звужується періодом.
        employees = self.env["hr.employee"].search([
            ("company_id", "=", company.id), ("active", "=", True)], order="name")
        return [(e.id, e.name) for e in employees]

    def _opt_hire_cases(self, company, first, last):
        # Так само не прив'язана до місяця - справу прийняття шукають за іменем, не за періодом.
        cases = self.env["ua.hire.case"].search([("company_id", "=", company.id)], order="id desc", limit=200)
        return [(c.id, c.name or "без імені") for c in cases]

    # ------------------------------------------------------------------ вибір за місяць: додаткові поля
    def _opt_departments(self, company):
        depts = self.env["hr.department"].search([("company_id", "=", company.id)], order="name")
        return [(False, "усі")] + [(d.id, d.name) for d in depts]

    def _opt_payment_kinds(self, company):
        return list(self.env["ua.payment.batch"]._fields["kind"].selection)

    def _find_payment_batch(self, company, first, last, year, month, params):
        """Відомостей на місяць може бути кілька (аванс/зарплата/податки/інше) - обраний вид
        іде в params["kind"]; без вибору береться перша наявна цього місяця, типово «зарплата»."""
        Model = self.env["ua.payment.batch"]
        domain = [("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)]
        kind = params.get("kind")
        if kind:
            return Model.search(domain + [("kind", "=", kind)], limit=1)
        existing = Model.search(domain, order="id", limit=1)
        if existing:
            return existing
        return Model.search(domain + [("kind", "=", "salary")], limit=1)

    # ------------------------------------------------------------------ складання чернетки (run_action="compose")
    def _compose_timesheet(self, company, year, month, first, last, params):
        # Ідемпотентний метод самої моделі (той самий, що використовує «Період»): бере
        # наявний табель або створює чернетку і заповнює нормою й фактом.
        self.env["ua.timesheet.sheet"]._ua_ensure_for(company, year, month)

    def _compose_pfu(self, company, year, month, first, last, params):
        run = self.env["hr.payslip.run"].search([
            ("company_id", "=", company.id), ("date_start", ">=", first), ("date_start", "<=", last)], limit=1)
        if not run:
            raise UserError(_("Немає розрахунково-платіжної відомості за цей місяць"))
        claim = self.env["ua.pfu.claim"].create({"company_id": company.id, "payslip_run_id": run.id})
        claim.action_refill()

    # ------------------------------------------------------------------ джерела паперу ("звідки дані")
    def _src_timesheet(self, record, company, first, last):
        leave_domain = [
            ("employee_id.company_id", "=", company.id), ("state", "=", "validate"),
            ("request_date_from", "<=", str(last)), ("request_date_to", ">=", str(first)),
        ]
        return [
            {"label": "Графік роботи", "text": "робочі дні й години графіка кожного працівника",
             "state": "calculated", "target": None},
            {"label": "Відсутності", "text": "підтверджені відпустки й лікарняні за місяць",
             "state": "imported", "target": {"model": "hr.leave", "domain": leave_domain,
                                              "name": "Відсутності місяця"}},
            {"label": "Правки рядків", "text": "дні, виправлені в табелі вручну",
             "state": "manual", "target": self._t_record(record)},
        ]

    def _src_staff_list(self, record, company, first, last):
        return [
            {"label": "Контракти", "text": "чинні версії контрактів на дату розпису",
             "state": "imported", "target": None},
            {"label": "Мінімальна зарплата", "text": "оклад рядка звіряється з мінімальною зарплатою на дату",
             "state": "supplied", "target": {"xmlid": "l10n_ua_payroll_rules.action_ua_payroll_param"}},
            {"label": "Номер наказу", "text": "номер і дата - при затвердженні",
             "state": "manual", "target": self._t_record(record)},
        ]

    def _src_advance(self, record, company, first, last):
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", record.year), ("month", "=", record.month),
            ("department_id", "=", False)], limit=1)
        return [
            {"label": "Відсоток окладу", "text": "%s%% окладу" % int(record.percent or 0),
             "state": "supplied", "target": self._t_record(record)},
            {"label": "Табель місяця", "text": "відпрацьовані дні першої половини місяця",
             "state": "imported" if sheet else "missing", "target": self._t_record(sheet) if sheet else None},
            {"label": "Відсутності", "text": "зменшують частку відпрацьованих днів",
             "state": "calculated", "target": None},
        ]

    def _src_payment_batch(self, record, company, first, last):
        if record.kind == "advance":
            first_row = {"label": "Авансова відомість", "text": "суми авансу за місяць",
                        "state": "imported", "target": None}
        elif record.kind == "tax":
            first_row = {"label": "Розрахункові листки", "text": "ПДФО, військовий збір і ЄСВ з листків",
                        "state": "calculated", "target": None}
        else:
            first_row = {"label": "Розрахункові листки", "text": "сума до виплати з проведених листків",
                        "state": "imported", "target": None}
        return [
            first_row,
            {"label": "Рахунок працівника", "text": "IBAN з картки працівника",
             "state": "supplied", "target": None},
            {"label": "Банк", "text": record.journal_id.name or "не вибрано",
             "state": "supplied" if record.journal_id else "missing",
             "target": {"model": "account.journal", "res_id": record.journal_id.id} if record.journal_id else None},
        ]

    def _src_payroll_sheet(self, record, company, first, last):
        return [
            {"label": "Листки пакета", "text": "нарахування й утримання кожного листка",
             "state": "imported", "target": {"model": "hr.payslip",
                                              "domain": [("payslip_run_id", "=", record.id)],
                                              "name": "Листки пакета"}},
            {"label": "Період", "text": "%s - %s" % (record.date_start, record.date_end),
             "state": "supplied", "target": self._t_record(record)},
        ]

    def _src_order(self, record, company, first, last):
        return [
            {"label": "Поля наказу", "text": "вид, дата й підстава з оформлення",
             "state": "supplied", "target": self._t_record(record)},
            {"label": "Картка працівника", "text": "ПІБ, посада й підрозділ на момент наказу",
             "state": "imported", "target": {"model": "hr.employee", "res_id": record.employee_id.id}},
            {"label": "Версія договору", "text": "наказ змінює версію трудового договору",
             "state": "calculated" if record.version_id else "not_applicable",
             "target": {"model": "hr.version", "res_id": record.version_id.id} if record.version_id else None},
        ]

    def _src_payslip(self, record, company, first, last):
        # Джерела вже рахує ua.explain (той самий слід, що й розрахунок) - тут лише
        # перекладаємо його payload у форму рядка джерела, нічого не рахуємо вдруге.
        payload = self.env["ua.explain"].explain("hr.payslip", record.id)
        rows = []
        for key, item in (payload.get("inputs") or {}).items():
            state = item.get("state") or "supplied"
            if state == "not_applicable":
                continue
            text = item.get("note") or ""
            if not text:
                value = item.get("value")
                if value in (None, False):
                    text = "немає значення"
                elif isinstance(value, float):
                    text = "значення %s" % ("%g" % value)
                else:
                    text = "значення %s" % value
            source = item.get("source")
            target = source if isinstance(source, dict) and source.get("model") else None
            rows.append({"label": item.get("label") or key, "text": text, "state": state, "target": target})
            if len(rows) >= 6:
                break
        return rows

    def _src_p2(self, record, company, first, last):
        return [
            {"label": "Особові дані", "text": "ПІБ, дата народження, адреса, документи",
             "state": "supplied", "target": self._t_record(record)},
            {"label": "Кадрові накази", "text": "прийняття, переведення, відпустки, звільнення",
             "state": "imported", "target": {"model": "ua.hr.order", "domain": [("employee_id", "=", record.id)],
                                              "name": "Накази працівника"}},
            {"label": "Освіта і стаж", "text": "диплом, трудова книжка - вручну",
             "state": "manual", "target": self._t_record(record)},
        ]

    def _src_contract(self, record, company, first, last):
        return [
            {"label": "Умови прийняття", "text": "оклад, ставка, вид договору",
             "state": "supplied", "target": self._t_record(record)},
            {"label": "Особа кандидата", "text": "ПІБ, РНОКПП, документ особи",
             "state": "supplied", "target": self._t_record(record)},
            {"label": "Компанія", "text": "керівник і назва роботодавця",
             "state": "imported", "target": {"model": "res.company", "res_id": company.id}},
        ]

    def _src_pfu(self, record, company, first, last):
        run_target = None
        if record.payslip_run_id:
            run_target = {"model": "hr.payslip", "domain": [("payslip_run_id", "=", record.payslip_run_id.id)],
                         "name": "Листки пакета"}
        return [
            {"label": "Лікарняні й декретні", "text": "суми з розрахункових листків пакета",
             "state": "imported", "target": run_target},
            {"label": "Листок непрацездатності", "text": "номер е-ЛН з відсутності",
             "state": "imported", "target": None},
            {"label": "Дні за календарем", "text": "кількість оплачуваних днів",
             "state": "calculated", "target": None},
        ]

    def _src_military_list(self, record, company, first, last):
        return [
            {"label": "Військовий облік", "text": "категорія, стан обліку і ТЦК з картки",
             "state": "supplied", "target": {"model": "hr.employee", "domain": [("ua_mil_tcc", "=", record.tcc)],
                                              "name": "Працівники цього ТЦК"}},
            {"label": "Розділ форми", "text": "офіцери, рядовий склад, призовники, жінки",
             "state": "calculated", "target": None},
        ]

    def _src_military_reserved(self, record, company, first, last):
        return [
            {"label": "Бронювання", "text": "ознака «заброньований» на картці",
             "state": "supplied", "target": {"model": "hr.employee", "domain": [("ua_mil_reserved", "=", True)],
                                              "name": "Заброньовані працівники"}},
            {"label": "Підстава і строк", "text": "номер довідки й дата завершення",
             "state": "supplied", "target": self._t_record(record)},
            {"label": "Днів до завершення", "text": "рахунок від дати списку",
             "state": "calculated", "target": None},
        ]

    def _src_order_register(self, record, company, first, last):
        return [
            {"label": "Накази реєстру", "text": "проведені накази обраного реєстру за рік",
             "state": "imported", "target": {"xmlid": "l10n_ua_hr_orders.action_ua_hr_order"}},
        ]

    # ------------------------------------------------------------------ факти й тексти (docs/payroll/words.md)
    def _fact(self, entry, month):
        """Один факт без крапки - для reason кнопки і note поля."""
        text = entry["missing_text"]
        if "{m}" in text:
            text = text.format(m=MONTHS_UA.get(month, ""))
        return text

    def _empty_text(self, entry, month):
        """Факт і що робити - для preview.empty_text, коли паперу немає."""
        fact = self._fact(entry, month)
        action = entry.get("empty_action")
        if action:
            return "%s. Натисніть «%s»." % (fact, action)
        return "%s." % fact

    # ------------------------------------------------------------------ пошук запису періоду
    def _locate(self, entry, company, year, month, first, last, params):
        """Запис обраного паперу для цього періоду. Єдине місце, де реєстр перетворюється
        на конкретний запис - викликають get_screen_data, run_action, позначки (mark)
        і «раніше»; жодне з них саме не лізе в домени чи вибір запису."""
        group = entry["group"]
        if group == "register":
            # Журнал - майстер, не документ: запису для перегляду свідомо немає ніколи.
            return self.env[entry["model"]]
        if group == "person":
            options = entry["options_fn"](company, first, last)
            raw_value = params.get("record_id")
            try:
                value = int(raw_value) if raw_value else False
            except (TypeError, ValueError):
                value = False
            valid_ids = [v for v, _l in options]
            if value not in valid_ids:
                value = options[0][0] if options else False
            return self.env[entry["model"]].browse(value) if value else self.env[entry["model"]]
        if entry.get("find_fn"):
            return entry["find_fn"](company, first, last, year, month, params)
        domain = entry["find_domain"](company, first, last, year, month, params)
        return self.env[entry["model"]].search(domain, order=entry.get("find_order", "id desc"), limit=1)

    # ------------------------------------------------------------------ позначка (mark)
    def _mark_for(self, entry, company, year, month, first, last):
        """ok - є затверджений запис; warn - є чернетка; crit - нічого немає, а папір
        потрібен цього місяця; none - папір не прив'язаний до місяця (на людину, журнал).
        Рахується з _checks() документа там, де вона є (ua.checks.mixin) - не вигадується
        окремо. Завжди без params вибраного паперу: позначка про сам папір цього місяця,
        а не про поточний вибір поля (підрозділ, вид виплати тощо)."""
        if entry["group"] in ("person", "register"):
            return "none"
        record = self._locate(entry, company, year, month, first, last, {})
        if not record:
            return "crit"
        if "_checks" in dir(record):
            level = record._checks_summary()["level"]
            return CHECK_LEVEL.get(level, "warn")
        return "ok" if self._state_bucket(entry, record) == "confirmed" else "warn"

    # ------------------------------------------------------------------ стан паперу
    def _state_bucket(self, entry, record):
        if not record:
            return "none"
        state_field = entry.get("state_field", "state")
        if not state_field or state_field not in record._fields:
            return "none"
        value = record[state_field]
        if value in entry.get("draft_states", {"draft"}):
            return "draft"
        if not value:
            return "none"
        return "confirmed"

    def _state_text(self, entry, record):
        if not record:
            return ""
        state_field = entry.get("state_field", "state")
        if not state_field or state_field not in record._fields:
            return ""
        value = record[state_field]
        selection = dict(record.fields_get([state_field])[state_field].get("selection") or [])
        label = selection.get(value, value or "")
        if value in entry.get("draft_states", {"draft"}):
            return label
        who = record.write_uid.name if "write_uid" in record._fields and record.write_uid else ""
        when_str = ""
        if "write_date" in record._fields and record.write_date:
            local = fields.Datetime.context_timestamp(self, record.write_date)
            when_str = "%s %s" % (local.day, MONTHS_OF.get(local.month, ""))
        text = label
        if when_str:
            text = "%s %s" % (text, when_str)
        if who:
            text = "%s, %s" % (text, who)
        return text

    # ------------------------------------------------------------------ перевірки
    @staticmethod
    def _checks_list(record):
        if not record or "_checks" not in dir(record):
            return []
        try:
            raw = record._checks()
        except Exception:
            return []
        order = {"error": 0, "warn": 1, "ok": 2}
        rows = []
        for c in sorted(raw, key=lambda c: order.get(c.get("level"), 9)):
            text = c.get("text") or ""
            if c.get("fact"):
                text = "%s (%s)" % (text, c["fact"])
            rows.append({"level": CHECK_LEVEL.get(c.get("level"), c.get("level")), "text": text,
                        "target": c.get("target")})
        return rows

    # ------------------------------------------------------------------ додаткові поля («за місяць»)
    def _extra_fields(self, entry, company, params, record):
        out = []
        for spec in entry.get("extra_fields") or []:
            options = spec["options_fn"](company)
            values = [v for v, _l in options]
            key = spec["key"]
            if key in params:
                value = params[key]
            elif record and key in record._fields:
                raw = record[key]
                value = raw.id if hasattr(raw, "id") else raw
            else:
                value = spec.get("default", False)
            if value not in values:
                value = values[0] if values else False
            display = dict(options).get(value, "")
            out.append({
                "key": key, "label": spec["label"], "kind": "choice", "value": value,
                "display": display, "options": [{"value": v, "label": l} for v, l in options],
                "missing": False, "note": None,
            })
        return out

    # ------------------------------------------------------------------ перегляд
    def _preview(self, entry, record, month):
        if record:
            Report = self.env["ir.actions.report"]
            content, _report_type = Report._render_qweb_html(entry["report"], record.ids)
            html = content.decode() if isinstance(content, bytes) else content
            return {"html": html, "empty_text": None}
        if entry["group"] == "person":
            return {"html": "", "empty_text": "%s." % self._fact(entry, month)}
        return {"html": "", "empty_text": self._empty_text(entry, month)}

    # ------------------------------------------------------------------ режим «Дані» (List, task 4)
    def _build_edit(self, entry, record):
        """'edit' - модель рядка + домен + вузький вигляд для режиму «Дані»: список рядків
        документа (`editable="bottom"`), не форма (spec-papers.md, «Спершу дані, потім
        бланк» - вбудована повна форма пробувалася і виявилася непридатною: своя переписка,
        свої кнопки в шапці, свої копії полів «Що вказати»).

        None для паперів без `line_model` у реєстрі (на людину, журнал - рядків не мають,
        для них бланк і є даними) і завжди, коли запису ще немає: правити рядки нема чого,
        поки немає самого документа."""
        line_model = entry.get("line_model")
        if not record or not line_model:
            return None
        inverse = entry["line_inverse"]
        view_id = self.env.ref(entry["line_view_xmlid"]).id
        count = self.env[line_model].search_count([(inverse, "=", record.id)])
        return {
            "model": line_model,
            "domain": [[inverse, "=", record.id]],
            "view_id": view_id,
            "context": {"default_%s" % inverse: record.id},
            "editable": self._state_bucket(entry, record) == "draft",
            "count": count,
            "doc": {"model": entry["model"], "res_id": record.id},
        }

    # ------------------------------------------------------------------ дії
    def _build_actions(self, entry, record, month):
        """Головна дія залежить від стану документа (spec-papers.md, «Спершу дані, потім
        бланк»): немає запису - Створити; чернетка - Затвердити; затверджено - Друк.
        confirm/to_draft ідуть лише туди, де запис і справді має action_confirm/action_draft
        (табель, штатний розпис, аванс, відомість, ПФУ, обидва військові списки). Там, де
        методів з такими іменами немає - hr.payslip.run (є лише close_payslip_run, без дії
        назад), hr.payslip (action_payslip_done/_draft - інша пара, і "done" зазвичай тягне
        бухгалтерські проведення), ua.hr.order (action_post/action_cancel - не те саме, що
        "повернути в чернетку") - дію свідомо не пропонуємо, а не малюємо вимкненою:
        головною лишається Друк, як і до цього зрізу. Журнал (register) - виняток за формою
        реєстру: запису в нього немає ніколи (spec-papers.md, «Перелік паперів»), і Друк
        відкриває майстер одразу, без проміжного «Створити», яке б довіку стояло вимкненим."""
        fact = self._fact(entry, month)
        can_print = bool(record) or bool(entry.get("print_fallback"))
        can_open = bool(record) or bool(entry.get("edit_fallback"))
        bucket = self._state_bucket(entry, record)
        can_confirm = bool(record) and bucket == "draft" and hasattr(record, "action_confirm")
        can_to_draft = bool(record) and bucket == "confirmed" and hasattr(record, "action_draft")

        actions = []
        if not record:
            if entry["group"] == "register":
                actions.append({"key": "print", "label": "Друк", "primary": True,
                                 "enabled": can_print, "reason": None if can_print else fact})
            else:
                composable = bool(entry.get("composable"))
                actions.append({"key": "compose", "label": "Створити", "primary": True,
                                 "enabled": composable,
                                 "reason": None if composable else entry.get("compose_block_reason")})
                actions.append({"key": "print", "label": "Друк", "primary": False,
                                 "enabled": can_print, "reason": None if can_print else fact})
        elif can_confirm:
            actions.append({"key": "confirm", "label": "Затвердити", "primary": True,
                             "enabled": True, "reason": None})
            actions.append({"key": "print", "label": "Друк", "primary": False,
                             "enabled": can_print, "reason": None if can_print else fact})
        elif can_to_draft:
            actions.append({"key": "print", "label": "Друк", "primary": True,
                             "enabled": can_print, "reason": None if can_print else fact})
            actions.append({"key": "to_draft", "label": "Повернути в чернетку", "primary": False,
                             "enabled": True, "reason": None})
        else:
            actions.append({"key": "print", "label": "Друк", "primary": True,
                             "enabled": can_print, "reason": None if can_print else fact})

        actions.append({"key": "open", "label": "Відкрити", "primary": False, "enabled": can_open,
                         "reason": None if can_open else fact})
        return actions

    # ------------------------------------------------------------------ джерела
    def _build_sources(self, entry, record, company, first, last):
        fn = entry.get("sources_fn")
        if not fn:
            return []
        if not record and entry["group"] != "register":
            return []
        return fn(record, company, first, last)

    # ------------------------------------------------------------------ раніше
    def _earlier(self, entry, company, year, month):
        if entry["group"] not in ("month", "state"):
            return []
        rows = []
        y, m = year, month
        for _i in range(3):
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
            first, last = self._bounds(y, m)
            record = self._locate(entry, company, y, m, first, last, {})
            if not record:
                continue
            rows.append({"label": MONTHS_UA.get(m, str(m)), "note": self._state_text(entry, record),
                        "target": self._t_record(record)})
        return rows

    # ------------------------------------------------------------------ один папір цілком
    def _build_paper(self, entry, company, year, month, first, last, params):
        record = self._locate(entry, company, year, month, first, last, params)
        if entry["group"] == "person":
            options = entry["options_fn"](company, first, last)
            display = dict(options).get(record.id, "") if record else ""
            fields_list = [{
                "key": "record_id", "label": entry["picker_label"], "kind": "record",
                "value": record.id if record else False, "display": display or "немає",
                "options": [{"value": v, "label": l} for v, l in options],
                "missing": not options, "note": None if options else self._fact(entry, month),
            }]
        elif entry["group"] == "register":
            fields_list = []
        else:
            fields_list = self._extra_fields(entry, company, params, record)

        edit = self._build_edit(entry, record)
        return {
            "key": entry["key"],
            "name": entry["full_name"],
            "subtitle": entry.get("subtitle", ""),
            "state": self._state_bucket(entry, record),
            "state_text": self._state_text(entry, record),
            "record": self._t_record(record),
            "fields": fields_list,
            "edit": edit,
            "default_mode": "edit" if edit else "print",
            "preview": self._preview(entry, record, month),
            "actions": self._build_actions(entry, record, month),
            "sources": self._build_sources(entry, record, company, first, last),
            "checks": self._checks_list(record),
            "earlier": self._earlier(entry, company, year, month),
        }

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, year=None, month=None, paper=None, params=None):
        """Дані екрана. Читання, нічого не пише і не змінює: жодного create/write/unlink
        ні тут, ні в жодному методі, який цей виклик використовує (_locate, _mark_for,
        _build_paper, _preview - усі лише search/browse і _render_qweb_html, який сам
        не пише). Запис створює лише run_action(action_key="compose") - окремий виклик,
        який бухгалтер викликає кнопкою «Створити», а не побічно від відкриття екрана."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        params = dict(params or {})
        registry = self._registry()

        periods = []
        y, m = year, month
        for _i in range(6):
            periods.append({"year": y, "month": m, "label": MONTHS_SHORT.get(m, str(m)),
                           "current": (y == year and m == month)})
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        periods.reverse()

        close = self.env["ua.period.close"].state_of(company, year, month)
        employees = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id), ("active", "=", True),
            ("ua_contract_kind", "not in", ("gph", "fop"))])

        papers_list = []
        for entry in registry:
            mark = self._mark_for(entry, company, year, month, first, last)
            count = None
            if entry["group"] == "person":
                count = len(entry["options_fn"](company, first, last))
            papers_list.append({
                "group": entry["group"], "group_label": entry["group_label"],
                "key": entry["key"], "name": entry["short_name"], "mark": mark, "count": count,
            })

        by_key = {entry["key"]: entry for entry in registry}
        entry = by_key.get(paper) or registry[0]
        detail = self._build_paper(entry, company, year, month, first, last, params)

        return {
            "period": {
                "year": year, "month": month, "label": "%s %s" % (MONTHS_UA[month], year),
                "closed": close.get("state") == "closed", "employees": employees, "periods": periods,
            },
            "papers": papers_list,
            "paper": detail,
        }

    # ------------------------------------------------------------------ дії
    @api.model
    def run_action(self, paper, action_key, year=None, month=None, params=None):
        registry = self._registry()
        entry = next((e for e in registry if e["key"] == paper), None)
        if not entry:
            raise UserError(_("Невідомий папір: %s") % paper)
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        params = dict(params or {})

        if action_key == "compose":
            if not entry.get("composable"):
                raise UserError(entry["compose_block_reason"])
            if entry.get("compose_fn"):
                entry["compose_fn"](company, year, month, first, last, params)
            else:
                vals = entry["compose_vals"](company, year, month, first, last, params)
                record = self.env[entry["model"]].create(vals)
                fill = entry.get("compose_fill")
                if fill and hasattr(record, fill):
                    getattr(record, fill)()
            return {"reload": True}

        record = self._locate(entry, company, year, month, first, last, params)

        if action_key == "print":
            if record:
                report = self.env.ref(entry["report"])
                return report.report_action(record)
            if entry.get("print_fallback"):
                return self.open_target(entry["print_fallback"])
            raise UserError(_("Немає паперу за цей період"))

        if action_key == "open":
            if record:
                return self.open_target({"model": entry["model"], "res_id": record.id})
            if entry.get("edit_fallback"):
                return self.open_target(entry["edit_fallback"])
            raise UserError(_("Немає запису для відкриття"))

        if action_key == "confirm":
            if not record or not hasattr(record, "action_confirm"):
                raise UserError(_("Затвердження недоступне для цього паперу"))
            record.action_confirm()
            return {"reload": True}

        if action_key == "to_draft":
            if not record or not hasattr(record, "action_draft"):
                raise UserError(_("Повернення в чернетку недоступне для цього паперу"))
            record.action_draft()
            return {"reload": True}

        raise UserError(_("Невідома дія: %s") % action_key)

    @api.model
    def open_target(self, target):
        """Один в один як ua.home.open_target: xmlid, або модель+res_id, або модель+домен."""
        target = target or {}
        if target.get("xmlid"):
            res = dict(self.env["ir.actions.actions"]._for_xml_id(target["xmlid"]))
            if target.get("domain"):
                res["domain"] = target["domain"]
            if target.get("context"):
                res["context"] = dict(target["context"])
            return res
        if target.get("model") and target.get("res_id"):
            model, res_id = target["model"], int(target["res_id"])
            if model == "account.bank.statement.line":
                return {
                    "type": "ir.actions.act_window", "res_model": model, "res_id": res_id,
                    "view_mode": "form", "views": [(False, "form")], "target": "current",
                    "context": {"view_ref": "account_reconcile_oca.bank_statement_line_form_reconcile_view"},
                }
            return {"type": "ir.actions.act_window", "res_model": model, "res_id": res_id,
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        if target.get("model"):
            return {"type": "ir.actions.act_window", "res_model": target["model"],
                    "domain": target.get("domain") or [], "view_mode": "list,form",
                    "views": [(False, "list"), (False, "form")], "target": "current",
                    "name": target.get("name") or ""}
        raise UserError(_("Немає що відкривати."))
