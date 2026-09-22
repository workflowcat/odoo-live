# -*- coding: utf-8 -*-
"""Читання для інтерфейсу: один виклик на екран замість десяти.

Навіщо. Інтерфейс живе в окремому репозиторії і розмовляє з ядром по JSON-RPC.
Без цієї моделі кожен екран мусив би сам знати, з яких десяти моделей збирається
«місяць зарплати» або «картка працівника», і при кожній зміні ядра ламався б
мовчки. Тут та сама збірка живе один раз, у ядрі, поруч із логікою, яку вона
читає, і описана в `docs/api/`.

Правила цієї моделі, усі чотири однаково суворі:

1. ЛИШЕ ЧИТАННЯ. Жоден метод нічого не створює, не пише і не видаляє - навіть
   «якщо запису ще немає, створимо чернетку». Записи створюють дії (`ua_compose`,
   `ensure_for`, `ensure_run`), і клієнт кличе їх явно й окремо. Це доводить
   тест `test_api.py` (тег `ua_api`): він рахує виконані запити і падає на
   першому ж INSERT/UPDATE/DELETE.
2. ЖОДНОГО ДРУГОГО РОЗРАХУНКУ. Числа, перевірки, перешкоди і план беруться
   викликом тих самих методів, якими користуються форми Odoo (`_checks()`,
   `blocker_rows()`, `plan()`, `state_of()`). Тут немає власної формули.
3. ПРОСТІ ТИПИ. Відповідь - словники, списки, рядки, числа, булеві. Дати -
   рядками `YYYY-MM-DD`, зв'язки - парою `[id, назва]`, як їх віддає `read()`,
   домени - списками списків, порожнеча - `False`. Кортежів у відповіді немає:
   кожен метод проганяє свій результат через `_plain()` перед поверненням.
4. ДОГОВІР - ЦЕ ДОКРЯДОК. Опис методу нижче і є те, на що спирається UI. Змінили
   склад відповіді - рядок у `docs/api/CHANGELOG.md` у тому ж коміті.

Права доступу не обходяться: `sudo()` тут немає ніде. Користувач без кадрових
прав отримує AccessError, а не порожні дані - це теж частина договору.
"""
import json
from datetime import date, datetime

from odoo import api, fields, models
from odoo.addons.l10n_ua_reporting.models.ua_report_run import PERIOD_TYPE

# Підсумки листків місяця - ті самі коди, що й у календарі виплат (ua.payments.plan).
PAYSLIP_CODES = ("GROSS", "PDFO", "VZ", "ESV", "NET", "ADV_PAID")

# Документи місяця: вид, назва, модель і те, як модель прив'язана до місяця.
# «Вид» (kind) сталий - на ньому UI будує свої кнопки, назва моделі може змінитись.
MONTH_DOCUMENTS = [
    ("timesheet", "Табель", "ua.timesheet.sheet", "year_month"),
    ("staff_list", "Штатний розпис", "ua.staff.list", "date"),
    ("advance_sheet", "Авансова відомість", "ua.advance.sheet", "year_month"),
    ("pfu_claim", "Заява-розрахунок ПФУ", "ua.pfu.claim", "payslip_run"),
    ("payment_order", "Відомість на перерахування", "account.payment.order", "ua_year_month"),
    ("military_list", "Список персонального обліку", "ua.military.list", "date"),
    ("military_notice", "Повідомлення про зміну даних", "ua.military.notice", "date_range"),
    ("military_reserved", "Список заброньованих", "ua.military.reserved", "date"),
]

# Картка працівника: поля вкладок стандартної форми hr.employee. Перелік навмисно
# явний, а не «усе, що починається на ua_»: випадкове нове поле не має мовчки
# з'являтися в договорі, а зникле має валити `contract_check.py`.
CARD_HEAD = ["name", "active", "job_title", "department_id", "company_id",
             "work_email", "work_phone", "employee_type"]
CARD_TABS = {
    "person": [
        "ua_rnokpp", "ua_id_doc_type", "ua_id_doc_series", "ua_id_doc_number",
        "ua_id_doc_issued_by", "ua_id_doc_date", "ua_id_doc_unzr", "birthday", "sex",
        "country_id", "private_street", "private_city", "private_zip", "ua_actual_address",
        "private_phone", "marital", "ua_disability_group", "ua_chernobyl_category",
        "ua_veteran", "ua_large_family", "ua_single_parent", "ua_previous_employee_id",
    ],
    "pay": [
        "ua_current_wage", "ua_contract_kind", "ua_main_job", "ua_fte", "ua_esv_category",
        "ua_psp", "ua_psp_children", "ua_insurance_years", "ua_sick_percent",
        "ua_index_off", "ua_index_base_effective",
    ],
    "vacation": [
        "ua_vacation_days_year", "ua_vacation_accrued", "ua_vacation_used",
        "ua_vacation_balance", "ua_vacation_opening_balance", "ua_vacation_opening_date",
        "ua_vac_ubd_days_year", "ua_vac_ubd_used", "ua_vac_ubd_balance",
        "ua_soc_child_days_year", "ua_soc_child_used", "ua_soc_child_balance",
        "ua_special_allocated", "ua_special_used", "ua_special_balance",
    ],
    "military": [
        "ua_mil_status", "ua_mil_women_list", "ua_mil_category", "ua_mil_group",
        "ua_mil_rank", "ua_mil_vos", "ua_mil_tcc", "ua_mil_doc_type", "ua_mil_doc_series",
        "ua_mil_doc_number", "ua_mil_doc_date", "ua_mil_fitness", "ua_mil_vlk_date",
        "ua_mil_reserved", "ua_mil_reserve_order", "ua_mil_reserve_until",
        "ua_mil_deferment", "ua_mil_deferment_until", "ua_reserve_number",
        "ua_reserve_date", "ua_mil_last_check", "ua_mil_needs_check",
    ],
    "overview": [
        "ua_days_in_company", "ua_first_hire_date", "ua_docs_count", "ua_docs_expiring",
        "ua_overview_alert_count",
    ],
}
CARD_VERSION = [
    "contract_date_start", "contract_date_end", "wage", "job_title", "department_id",
    "ua_kp_code", "ua_prof_name", "ua_internal_parttime", "ua_order_ref",
    "ua_end_order_ref", "ua_dismissal_basis", "ua_pay_type", "ua_hour_rate",
    "ua_weekly_hours", "ua_night_shifts",
]
CARD_DOCUMENT = ["name", "type", "number", "date", "valid_until", "ua_doc_state",
                 "state", "signed_date", "attachment_id", "note"]
CARD_ORDER = ["name", "order_type", "register", "date", "state", "job_title", "wage",
              "date_from", "date_to", "basis", "ack_date"]
CARD_ALLOCATION = ["holiday_status_id", "number_of_days", "date_from", "date_to", "state"]
CARD_LEAVE = ["holiday_status_id", "request_date_from", "request_date_to",
              "number_of_days", "state"]


class UaApi(models.AbstractModel):
    _name = "ua.api"
    _inherit = ["ua.screen"]
    _description = "Читання для інтерфейсу"

    # ------------------------------------------------------------------ службове
    @api.model
    def _as_company(self, company_id):
        """Компанія за id, або поточна, якщо id не передали."""
        if company_id:
            return self.env["res.company"].browse(int(company_id))
        return self.env.company

    @api.model
    def _plain(self, value):
        """Значення, яке переживе json.dumps: дата - рядком, набір - списком."""
        if isinstance(value, (datetime, date)):
            return fields.Date.to_string(value) if not isinstance(value, datetime) \
                else fields.Datetime.to_string(value)
        if isinstance(value, (list, tuple)):
            return [self._plain(item) for item in value]
        if isinstance(value, dict):
            return {key: self._plain(item) for key, item in value.items()}
        if isinstance(value, bytes):
            return True                     # двійкове тіло екрану не потрібне, лише факт
        if value is None:
            return False                    # Odoo порожнечу теж віддає як False
        if isinstance(value, (bool, int, float, str)):
            return value
        return str(value)

    @api.model
    def _rows(self, records, field_names):
        """`read()` названих полів, приведений до простих типів."""
        return [self._plain(row) for row in records.read(field_names)]

    @api.model
    def _labels(self, model, field_name):
        """{значення: підпис} для Selection-поля - через публічний fields_get()."""
        described = self.env[model].fields_get([field_name]).get(field_name) or {}
        return {key: label for key, label in (described.get("selection") or [])}

    @api.model
    def _check_rows(self, record):
        """Перевірки документа: рядки {level, text, fact, target} і підсумок.

        Форму дає ua.checks.mixin; документ без міксину віддає порожній перелік."""
        if not hasattr(record, "_checks_summary"):
            return {"level": "ok", "errors": 0, "warns": 0, "checks": []}
        summary = record._checks_summary()
        return {
            "level": summary["level"],
            "errors": summary["errors"],
            "warns": summary["warns"],
            "checks": [self._plain(row) for row in summary["checks"]],
        }

    @api.model
    def _document_domain(self, company, year, month, binding):
        first, last = self._bounds(year, month)
        base = [("company_id", "=", company.id)]
        if binding == "year_month":
            return base + [("year", "=", year), ("month", "=", month)]
        if binding == "ua_year_month":
            return base + [("ua_year", "=", year), ("ua_month", "=", month)]
        if binding == "date":
            return base + [("date", ">=", first), ("date", "<=", last)]
        if binding == "date_range":
            return base + [("date_from", "<=", last), ("date_to", ">=", first)]
        if binding == "payslip_run":
            return base + [("payslip_run_id.date_start", ">=", first),
                           ("payslip_run_id.date_start", "<=", last)]
        return base

    # ------------------------------------------------------------------ місяць зарплати
    @api.model
    def month_summary(self, company_id, year, month):
        """Усе, що показує екран місяця зарплати, одним читанням.

        Вхід: company_id (int або False - тоді поточна компанія), year, month (int).

        Вихід:
          company   {id, name}
          period    {year, month, label, closed, hard, closed_by, closed_date,
                     periods: [{year, month, label, current, closed}]} - смуга останніх
                    шести місяців, як її бачить будь-який екран (ua.screen._period_block);
                    стан місяця - ua.period.close.state_of()
          blockers  [{key, text, short, plan, target}] - чому місяць не закрити;
                    порожній список означає «можна закривати» (ua.period.close.blocker_rows)
          plan      [{text, level, target}] - що станеться при закритті (ua.period.close.plan);
                    level: info | warn | crit
          payslips  {count, draft, done, cancel, totals: {GROSS, PDFO, VZ, ESV, NET,
                    ADV_PAID}, target} - листки місяця за date_from
          documents [...] - те саме, що віддає documents_for_month() цього ж місяця

        Нічого не створює: місяць без картки закриття і без листків віддає порожні
        переліки і state «open», а не заводить чернетку.
        """
        company = self._as_company(company_id)
        year, month = int(year), int(month)
        first, last = self._bounds(year, month)
        Close = self.env["ua.period.close"]
        state = Close.state_of(company, year, month)

        period = self.with_company(company)._period_block(year, month,
                                                          closed=state["state"] == "closed")
        period.update({"hard": bool(state.get("hard")), "closed_by": state.get("closed_by") or "",
                       "closed_date": state.get("closed_date") or ""})

        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last)])
        alive = slips.filtered(lambda s: s.state != "cancel")
        lines = alive.mapped("line_ids")
        totals = {code: self._r2(sum(lines.filtered(lambda l: l.code == code).mapped("total")))
                  for code in PAYSLIP_CODES}

        return self._plain({
            "company": {"id": company.id, "name": company.name},
            "period": period,
            "blockers": [self._plain(row) for row in Close.blocker_rows(company, year, month)],
            "plan": [self._plain(row) for row in Close.plan(company, year, month)],
            "payslips": {
                "count": len(slips),
                "draft": len(slips.filtered(lambda s: s.state in ("draft", "verify"))),
                "done": len(slips.filtered(lambda s: s.state == "done")),
                "cancel": len(slips.filtered(lambda s: s.state == "cancel")),
                "totals": totals,
                "target": {"model": "hr.payslip",
                           "domain": [("company_id", "=", company.id),
                                      ("date_from", ">=", str(first)),
                                      ("date_from", "<=", str(last))],
                           "name": period["label"]},
            },
            "documents": self.documents_for_month(company.id, year, month),
        })

    # ------------------------------------------------------------------ документи місяця
    @api.model
    def documents_for_month(self, company_id, year, month):
        """Документи місяця з їхніми перевірками, по одному рядку на ВИД документа.

        Вхід: company_id, year, month.

        Вихід: список сталої довжини і сталого порядку - вісім видів завжди на місці,
        навіть коли запису ще немає. Один елемент:
          kind      сталий код виду: timesheet, staff_list, advance_sheet, pfu_claim,
                    payment_order, military_list, military_notice, military_reserved
          label     українська назва виду
          model     модель запису (може змінитися - вид не змінюється)
          present   чи є хоч один запис місяця
          records   [{id, name, state, state_label, level, errors, warns, checks, target}]
                    checks - рядки ua.checks.mixin: {level, text, fact, target},
                    level загалом - найгірший рівень документа (ok | warn | error)
          target    ціль «показати всі записи цього виду за місяць»

        Порожній `records` означає саме «документа ще немає»; цей метод його не створює.
        Створює чарівник виду або `ua_compose()` відповідної моделі.
        """
        company = self._as_company(company_id)
        year, month = int(year), int(month)
        out = []
        for kind, label, model, binding in MONTH_DOCUMENTS:
            if model not in self.env:
                continue                     # модуль виду не встановлено - виду немає
            domain = self._document_domain(company, year, month, binding)
            records = self.env[model].search(domain)
            labels = self._labels(model, "state")
            rows = []
            for record in records:
                checks = self._check_rows(record)
                rows.append({
                    "id": record.id,
                    "name": record.display_name or "",
                    "state": record.state or "",
                    "state_label": labels.get(record.state, record.state or ""),
                    "level": checks["level"],
                    "errors": checks["errors"],
                    "warns": checks["warns"],
                    "checks": checks["checks"],
                    "target": {"model": model, "res_id": record.id},
                })
            out.append({
                "kind": kind, "label": label, "model": model,
                "present": bool(rows), "records": rows,
                "target": {"model": model, "domain": domain, "name": label},
            })
        return self._plain(out)

    # ------------------------------------------------------------------ картка працівника
    @api.model
    def employee_card(self, employee_id):
        """Картка працівника: те саме, що показує стандартна форма hr.employee.

        Вхід: employee_id (int).

        Вихід:
          employee   {id, name, active, job_title, department_id, company_id, work_email,
                      work_phone, employee_type} - шапка форми
          tabs       {person, pay, vacation, military, overview} - по словнику на вкладку,
                     значення такі самі, як їх віддає read() цих полів
          children   [{id, name, birthday, note}] - вкладка «Особова картка», діти
          version    поточна версія контракту (hr.version) або False, якщо її немає
          documents  [{id, name, type, date, valid_until, ua_doc_state, state, ...}] -
                     документи працівника (ua.employee.document), найближчі до спливання перші
          orders     [{id, name, order_type, date, state, ...}] - накази (ua.hr.order),
                     найновіші перші
          leaves     {allocations: [...], requests: [...]} - нарахування і заявки відпусток;
                     залишки днів лежать у tabs.vacation, другий раз тут їх немає
          alerts     {count, docs_expiring, military_needs_check} - те, що форма показує
                     лічильником «Потребує уваги»
          targets    {form, documents, orders} - цілі для ua.screen.open_target()

        Права. Метод не робить sudo(): користувач без hr.group_hr_user отримає
        AccessError на кадрових полях, а не картку з порожніми значеннями.
        """
        employee = self.env["hr.employee"].browse(int(employee_id))
        head = self._rows(employee, CARD_HEAD)[0]
        tabs = {}
        for tab, field_names in CARD_TABS.items():
            known = [name for name in field_names if name in employee._fields]
            tabs[tab] = self._rows(employee, known)[0] if known else {}
            tabs[tab].pop("id", None)

        version = employee.version_id
        version_fields = [name for name in CARD_VERSION if name in version._fields]
        documents = employee.ua_document_ids.sorted(lambda d: (d.valid_until or date.max, d.id))
        orders = self.env["ua.hr.order"].search([("employee_id", "=", employee.id)],
                                                order="date desc, id desc")

        return self._plain({
            "employee": head,
            "tabs": tabs,
            "children": self._rows(employee.ua_child_ids, ["name", "birthday", "note"]),
            "version": self._rows(version, version_fields)[0] if version else False,
            "documents": self._rows(documents, CARD_DOCUMENT),
            "orders": self._rows(orders, CARD_ORDER),
            "leaves": {
                "allocations": self._rows(
                    self.env["hr.leave.allocation"].search(
                        [("employee_id", "=", employee.id)], order="date_from desc, id desc"),
                    CARD_ALLOCATION),
                "requests": self._rows(
                    self.env["hr.leave"].search(
                        [("employee_id", "=", employee.id)],
                        order="request_date_from desc, id desc"),
                    CARD_LEAVE),
            },
            "alerts": {
                "count": employee.ua_overview_alert_count,
                "docs_expiring": employee.ua_docs_expiring,
                "military_needs_check": bool(employee.ua_mil_needs_check),
            },
            "targets": {
                "form": {"model": "hr.employee", "res_id": employee.id},
                "documents": {"model": "ua.employee.document",
                              "domain": [("employee_id", "=", employee.id)],
                              "name": "Документи"},
                "orders": {"model": "ua.hr.order",
                           "domain": [("employee_id", "=", employee.id)], "name": "Накази"},
            },
        })

    # ------------------------------------------------------------------ звітність
    @api.model
    def reporting_status(self, company_id, year, month=None):
        """Стан звітності за період: по рядку на кожен звіт робочого місця.

        Вхід: company_id, year, month (необов'язковий; без нього - лише річні
        й ті звіти, чий прогін уже існує на цей рік).

        Вихід:
          company {id, name}, year, month
          reports [{code, label, period_type, run_id, name, state, state_label,
                    doc_kind, submitted_date, checks: {ok, warn, error, rows},
                    files, receipts, target}]
            code         сталий код звіту: j05, j30, pfu, trial, ledger, timesheet,
                         staff, orders
            period_type  month | date | year - чим цей звіт нумерується
            run_id       False, якщо прогону ще немає (цей метод його не створює;
                         створює ua.report.run.ensure_run())
            checks.rows  [{level, code, title, detail, value, target}] - перевірки прогону
            files        [{id, name}] - сформовані файли, receipts - квитанції

        Порядок рядків сталий - той самий, що й перелік звітів у ядрі.
        """
        company = self._as_company(company_id)
        year = int(year)
        month = int(month) if month else None
        Run = self.env["ua.report.run"]
        labels = self._labels("ua.report.run", "report_code")
        states = self._labels("ua.report.run", "state")
        kinds = self._labels("ua.report.run", "doc_kind")

        out = []
        for code, label in (Run._fields["report_code"].selection or []):
            domain = [("company_id", "=", company.id), ("year", "=", year),
                      ("report_code", "=", code)]
            if month:
                domain.append(("month", "in", (month, False)))
            run = Run.search(domain, order="month desc, id desc", limit=1)
            checks = run.check_ids if run else self.env["ua.report.check"].browse()
            rows = []
            for check in checks:
                rows.append({
                    "level": check.level or "ok", "code": check.code or "",
                    "title": check.title or "", "detail": check.detail or "",
                    "value": check.value or "",
                    "target": self._check_target(check),
                })
            out.append({
                "code": code,
                "label": labels.get(code, label),
                "period_type": PERIOD_TYPE.get(code, "month"),
                "run_id": run.id if run else False,
                "name": run.display_name if run else "",
                "state": run.state if run else "",
                "state_label": states.get(run.state, "") if run else "",
                "doc_kind": kinds.get(run.doc_kind, "") if run else "",
                "submitted_date": self._plain(run.submitted_date) if run else False,
                "checks": {
                    "ok": sum(1 for row in rows if row["level"] == "ok"),
                    "warn": sum(1 for row in rows if row["level"] == "warn"),
                    "error": sum(1 for row in rows if row["level"] == "error"),
                    "rows": rows,
                },
                "files": [{"id": a.id, "name": a.name} for a in run.attachment_ids] if run else [],
                "receipts": [{"id": a.id, "name": a.name} for a in run.receipt_ids] if run else [],
                "target": {"model": "ua.report.run", "res_id": run.id} if run else
                          {"model": "ua.report.run", "domain": domain, "name": label},
            })
        return self._plain({"company": {"id": company.id, "name": company.name},
                            "year": year, "month": month or False, "reports": out})

    @api.model
    def _check_target(self, check):
        """Ціль рядка перевірки прогону у звичайній формі {model, res_id} / {model, domain}."""
        if not check.target_model:
            return False
        if check.target_res_id:
            return {"model": check.target_model, "res_id": check.target_res_id}
        if check.target_domain:
            try:
                return {"model": check.target_model, "domain": json.loads(check.target_domain)}
            except ValueError:
                return {"model": check.target_model}
        return {"model": check.target_model}
