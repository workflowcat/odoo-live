# -*- coding: utf-8 -*-
"""Читання для інтерфейсу: один виклик на екран замість десяти.

Навіщо. Інтерфейс живе в окремому репозиторії і розмовляє з ядром по JSON-RPC.
Без цієї моделі кожен екран мусив би сам знати, з яких десяти моделей збирається
«місяць зарплати» або «картка працівника», і при кожній зміні ядра ламався б
мовчки. Тут та сама збірка живе один раз, у ядрі, поруч із логікою, яку вона
читає, і описана в `docs/api/`.

Читань одинадцять. Чотири бек-офісні: місяць зарплати, документи місяця, картка
працівника, стан звітності. Одне спільне: перевірки будь-якого запису
(`record_checks`). Шість складських: карта складу з місткістю полиць і зонами,
залишки з мінімумом і потребою, нерозкладене на підлозі, складальна карта виробу,
план інвентаризації, картка наряду для кіоску цеху. Складські живуть у розділі
«склад» наприкінці файла.

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
import math
from datetime import date, datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons.l10n_ua_reporting.models.ua_report_run import PERIOD_TYPE
from odoo.addons.l10n_ua_stock_docs.models.product_template import UA_SIZE_SLOTS

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

# Склад. Підлога - локація, куди кладуть те, що не вліз на полицю; назва стала,
# бо на ній тримається і карта складу, і екран «Розкласти».
FLOOR_NAME = "Підлога"
# Скільки днів назад дивимось на витрату, щоб порахувати потребу на місяць.
CONSUMPTION_DAYS = 60
# Скільки днів готова продукція лічиться «щойно з виробництва».
FRESH_MO_DAYS = 3
# Рядків залишків за один виклик. Більше - це вже вивантаження, а не екран;
# далі - сторінками через offset.
GLANCE_LIMIT = 500

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

    # ------------------------------------------------------------------ перевірки запису
    @api.model
    def record_checks(self, model, res_id):
        """Перевірки одного запису: публічний вхід до `_checks()` будь-якої моделі.

        Вхід: model - назва моделі (`hr.payslip`, `ua.timesheet.sheet`...), res_id -
        id запису.

        Вихід:
          model, res_id, name   що саме перевірили
          has_checks            True, якщо модель уміє себе перевіряти
                                (домішка `ua.checks.mixin`); False - `checks` порожні
          level                 найгірший рівень: ok | warn | error
          errors, warns         лічильники
          checks                [{level, text, fact, target}] - рядки `_checks()` як є

        Права - права самого запису: `check_access("read")` на ньому, без sudo().
        Неіснуючий запис або модель - UserError з людським текстом.
        """
        if not model or model not in self.env:
            raise UserError("Моделі «%s» немає." % model)
        record = self.env[model].browse(int(res_id or 0))
        if not record.exists():
            raise UserError("Запису %s з id %s немає." % (model, res_id))
        record.check_access("read")
        rows = self._check_rows(record)
        return self._plain(dict(
            rows, model=model, res_id=record.id, name=record.display_name or "",
            has_checks=hasattr(record, "_checks_summary")))

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

    # ================================================================== склад
    #
    # Шість читань складу і виробництва. Ті самі правила, що й вище: жодного
    # запису, жодного другого розрахунку, жодного sudo(). Числа беруться з полів
    # ядра - `stock.location.ua_capacity_used`, `product.template._ua_slots()`,
    # `ua.stock.inventory.plan()`, `product.template.ua_assembly()` - а не
    # перераховуються тут ще раз. Зовнішній клієнт складу до цих методів збирав
    # кожен екран із пʼяти-восьми викликів `search_read` і тримав власну табличку
    # місткостей у JSON поруч із кодом.
    #
    # Права. Нативний Odoo дає ЧИТАННЯ `stock.location`, `stock.quant`,
    # `stock.move.line` і `ua.stock.inventory` будь-якому внутрішньому
    # користувачеві (`base.group_user`), тому `warehouse_map`, `floor_packages` і
    # `inventory_plan` порожньою відповіддю на брак прав не відповідають - вони
    # просто працюють. `stock_glance` читає `stock.warehouse.orderpoint`
    # (`stock.group_stock_user`), `product_assembly` - `mrp.bom`
    # (`mrp.group_mrp_user` або `stock.group_stock_user`): без цих груп прилітає
    # AccessError, як і має бути.

    @staticmethod
    def _id_list(values):
        """Перелік id із того, що прислав клієнт: порожнє і нулі викидаємо.

        `child_of` з нулем у переліку валиться всередині ORM на TypeError, а не на
        людській помилці, тому чистимо перелік тут, один раз."""
        return [int(one) for one in (values or []) if one]

    @api.model
    def _internal_locations(self, company, location_ids=None):
        """Внутрішні локації компанії, за потреби звужені переліком (разом з дочірніми)."""
        domain = [("usage", "=", "internal"), ("company_id", "in", (False, company.id))]
        chosen = self._id_list(location_ids)
        if chosen:
            domain.append(("id", "child_of", chosen))
        return self.env["stock.location"].search(domain)

    @api.model
    def _category_pair(self, product):
        """Категорія товару парою [id, назва]. У Odoo 19 її може не бути зовсім."""
        category = product.categ_id
        return [category.id, category.display_name] if category else False

    @api.model
    def _size_of(self, product):
        """Габарит товару парою {код, місць}: порожній габарит - одне місце."""
        template = product.product_tmpl_id
        return template.ua_size or False, template._ua_slots()

    # ------------------------------------------------------------------ карта складу
    @api.model
    def warehouse_map(self, company_id):
        """Карта складу: дерево локацій із місткістю, заповненням і вмістом.

        Вхід: company_id (int або False - тоді поточна компанія).

        Вихід:
          company   {id, name}
          sizes     {s: 1, m: 4, l: 16} - скільки місць займає одиниця кожного габариту,
                    плюс `default` (габарит, яким рахується товар без позначки)
          roots     [id] - локації, чийого батька в переліку немає; з них UI будує дерево
          locations [...] - усі внутрішні локації компанії в сталому порядку
                    (`complete_name`), по рядку на локацію:
            id, name          коротка назва локації
            path              повна назва з батьками (WH/Stock/Полиця М1)
            parent_id         [id, назва] або False
            level             глибина від найвищої локації переліку, з нуля
            capacity          `ua_capacity`: скільки місць має полиця; 0 - не задано
            used              `ua_capacity_used`: зайнято місць РАЗОМ З ДОЧІРНІМИ
            own               місць під власним вмістом цієї локації, без дочірніх
            free              capacity - used, не менше нуля; False, коли місткості немає
            overflow          True, якщо місткість задано і used > capacity
            fill              заповнення у відсотках (0-999) або False без місткості
            floor             True для локації «Підлога» - підлоги полиці
            purpose           призначення зони (`ua_purpose`): receiving | storage |
                              hazard | quality | production | finished | shipping |
                              reject, або False; purpose_label - підпис
            plan              {x, y, w, h} - прямокутник зони на плані в клітинках
                              (`ua_plan_*`), або False, коли ширина чи висота нуль
            items             [{product, code, category, quantity, reserved, uom, size,
                               size_label, slots}] - ВЛАСНИЙ вміст локації, без дочірніх
            target            {model: stock.quant, domain: [...]} - показати ці залишки

        Переповнення нічого не блокує: це показник карти, а не обмеження розкладання
        (обмеження вміє нативна `stock.storage.category`). Порожня локація приходить
        із порожнім `items`, а не зникає з карти - карта має показувати вільні полиці.
        """
        company = self._as_company(company_id)
        locations = self._internal_locations(company)
        quants = self.env["stock.quant"].search([
            ("location_id", "in", locations.ids),
            ("company_id", "in", (False, company.id)),
            ("quantity", ">", 0),
        ], order="product_id, id")

        labels = self._labels("product.template", "ua_size")
        purposes = self._labels("stock.location", "ua_purpose")
        own_items, own_slots = {}, {}
        for quant in quants:
            size, slots = self._size_of(quant.product_id)
            own_items.setdefault(quant.location_id.id, []).append({
                "product": [quant.product_id.id, quant.product_id.display_name],
                "code": quant.product_id.default_code or "",
                "category": self._category_pair(quant.product_id),
                "quantity": quant.quantity,
                "reserved": quant.reserved_quantity,
                "uom": quant.product_uom_id.display_name or "",
                "size": size,
                "size_label": labels.get(size, ""),
                "slots": quant.quantity * slots,
            })
            own_slots[quant.location_id.id] = own_slots.get(quant.location_id.id, 0.0) \
                + quant.quantity * slots

        known = set(locations.ids)
        depths = {location.id: (location.complete_name or "").count("/")
                  for location in locations}
        top = min(depths.values()) if depths else 0

        rows = []
        for location in locations:
            capacity = location.ua_capacity or 0
            used = location.ua_capacity_used
            rows.append({
                "id": location.id,
                "name": location.name or "",
                "path": location.complete_name or location.display_name or "",
                "parent_id": [location.location_id.id, location.location_id.display_name]
                             if location.location_id else False,
                "level": depths[location.id] - top,
                "capacity": capacity,
                "used": used,
                "own": int(math.ceil(round(own_slots.get(location.id, 0.0), 6))),
                "free": max(capacity - used, 0) if capacity else False,
                "overflow": bool(capacity and used > capacity),
                "fill": min(round(used * 100.0 / capacity, 1), 999.0) if capacity else False,
                "floor": (location.name or "") == FLOOR_NAME,
                "purpose": location.ua_purpose or False,
                "purpose_label": purposes.get(location.ua_purpose, ""),
                "plan": {"x": location.ua_plan_x, "y": location.ua_plan_y,
                         "w": location.ua_plan_w, "h": location.ua_plan_h}
                        if location.ua_plan_w and location.ua_plan_h else False,
                "items": own_items.get(location.id, []),
                "target": {"model": "stock.quant",
                           "domain": [("location_id", "=", location.id),
                                      ("quantity", ">", 0)],
                           "name": location.complete_name or ""},
            })

        return self._plain({
            "company": {"id": company.id, "name": company.name},
            "sizes": dict(UA_SIZE_SLOTS, default="s"),
            "roots": [row["id"] for row in rows
                      if not (row["parent_id"] and row["parent_id"][0] in known)],
            "locations": rows,
        })

    # ------------------------------------------------------------------ залишки
    @api.model
    def stock_glance(self, company_id, location_ids=None, category_ids=None, query=None,
                     offset=0, limit=500):
        """Залишки з першого погляду: скільки лежить, скільки треба, на скільки вистачить.

        Вхід: company_id; location_ids (список id локацій разом із дочірніми, або
        False - усі внутрішні); category_ids (список id категорій разом із дочірніми,
        або False - усі); query (рядок: частина назви або внутрішнього коду товару,
        без регістру; порожнє - без пошуку); offset (скільки рядків пропустити, з
        нуля); limit (рядків на сторінку, 1..500, типово 500).

        Вихід:
          company    {id, name}
          total      скільки рядків усього під цими звуженнями й пошуком
          offset     з якого рядка віддано, limit - розмір сторінки
          count      скільки рядків віддано в цій сторінці
          truncated  True, якщо після цієї сторінки є ще рядки
                     (offset + count < total): наступна - offset + count
          rows       по рядку на залишок (товар × локація), у порядку товар, локація:
            product     [id, назва], code - внутрішній код
            category    [id, назва]
            location    [id, назва]
            uom         одиниця виміру рядком
            qty         кількість на цій локації
            reserved    з них зарезервовано
            free        вільно на цій локації (`available_quantity`)
            free_total  вільно по ВСІХ локаціях вибірки - від нього рахується enough_for
            value       облікова вартість залишку
            min         `stock.warehouse.orderpoint.product_min_qty`; 0 - правила немає
            month       витрата за 60 днів, поділена навпіл: скільки йде за місяць
            need        max(min, month) - скільки тримати на складі
            level       ok | warn (min задано і free_total нижче за нього) | bad (мінус)
            enough_for  [{product: [tmpl_id, назва], per_unit, units}] - на скільки
                        одиниць кожного виробу, що вживає цей товар, вистачить
                        free_total; per_unit - потреба на ОДНУ одиницю виробу
            size, size_label, slots   габарит і скільки місць займає цей залишок
            last_move   дата останнього проведеного руху товару або False
            target      {model: stock.quant, res_id}

        Витрата рахується проведеними рядками руху з внутрішньої локації у виробництво
        або до клієнта - тобто справжнім споживанням, а не переміщеннями між полицями.
        Нічого не створює: товар без правила поповнення просто має min = 0.
        """
        company = self._as_company(company_id)
        locations = self._internal_locations(company, location_ids)
        domain = [("location_id", "in", locations.ids),
                  ("company_id", "in", (False, company.id))]
        chosen = self._id_list(category_ids)
        if chosen:
            categories = self.env["product.category"].search([("id", "child_of", chosen)])
            domain.append(("product_id.categ_id", "in", categories.ids))
        text = (query or "").strip()
        if text:
            domain += ["|", ("product_id.name", "ilike", text),
                       ("product_id.default_code", "ilike", text)]
        offset = max(int(offset or 0), 0)
        limit = min(max(int(limit or GLANCE_LIMIT), 1), GLANCE_LIMIT)

        total = self.env["stock.quant"].search_count(domain)
        quants = self.env["stock.quant"].search(
            domain, order="product_id, location_id, id", offset=offset, limit=limit)
        products = quants.mapped("product_id")

        # вільне по всій вибірці, мінімум, витрата, останній рух, специфікації
        free_total, size_of = {}, {}
        for quant in self.env["stock.quant"].search([
                ("location_id", "in", locations.ids),
                ("product_id", "in", products.ids)]):
            free_total[quant.product_id.id] = free_total.get(quant.product_id.id, 0.0) \
                + quant.available_quantity

        minimums = {}
        for point in self.env["stock.warehouse.orderpoint"].search([
                ("product_id", "in", products.ids),
                ("company_id", "in", (False, company.id))]):
            minimums[point.product_id.id] = max(minimums.get(point.product_id.id, 0.0),
                                                point.product_min_qty)

        # Витрата - лише справжнє споживання: з внутрішньої локації у виробництво або
        # до клієнта. Переміщення між полицями витратою не є, інакше «потреба» росла б
        # від кожного розкладання.
        Line = self.env["stock.move.line"]
        base = [("state", "=", "done"), ("product_id", "in", products.ids),
                ("company_id", "in", (False, company.id))]
        last_move = {product.id: value for product, value
                     in Line._read_group(base, ["product_id"], ["date:max"])}
        since = fields.Datetime.now() - timedelta(days=CONSUMPTION_DAYS)
        spent = {product.id: value for product, value in Line._read_group(
            base + [("date", ">=", since), ("location_usage", "=", "internal"),
                    ("location_dest_usage", "in", ("production", "customer"))],
            ["product_id"], ["quantity:sum"])}

        uses = {}
        if "mrp.bom.line" in self.env:
            for line in self.env["mrp.bom.line"].search(
                    [("product_id", "in", products.ids)], order="bom_id, id"):
                batch = line.bom_id.product_qty or 1.0
                per_unit = line.product_uom_id._compute_quantity(
                    line.product_qty, line.product_id.uom_id, round=False) / batch
                if per_unit <= 0:
                    continue
                uses.setdefault(line.product_id.id, {}).setdefault(
                    line.bom_id.product_tmpl_id, per_unit)

        labels = self._labels("product.template", "ua_size")
        rows = []
        for quant in quants:
            product = quant.product_id
            if product.id not in size_of:
                size_of[product.id] = self._size_of(product)
            size, slots = size_of[product.id]
            free_all = self._r2(free_total.get(product.id, 0.0))
            minimum = self._r2(minimums.get(product.id, 0.0))
            month = self._r2(spent.get(product.id, 0.0) / 2.0)
            enough = []
            for template, per_unit in sorted(uses.get(product.id, {}).items(),
                                             key=lambda pair: pair[0].display_name):
                enough.append({"product": [template.id, template.display_name],
                               "per_unit": round(per_unit, 4),
                               "units": int(free_all // per_unit)})
            rows.append({
                "product": [product.id, product.display_name],
                "code": product.default_code or "",
                "category": self._category_pair(product),
                "location": [quant.location_id.id, quant.location_id.display_name],
                "uom": quant.product_uom_id.display_name or "",
                "qty": self._r2(quant.quantity),
                "reserved": self._r2(quant.reserved_quantity),
                "free": self._r2(quant.available_quantity),
                "free_total": free_all,
                "value": self._r2(quant.value),
                "min": minimum,
                "month": month,
                "need": max(minimum, month),
                "level": "bad" if free_all < 0 else
                         ("warn" if minimum and free_all < minimum else "ok"),
                "enough_for": enough,
                "size": size,
                "size_label": labels.get(size, ""),
                "slots": self._r2(quant.quantity * slots),
                "last_move": last_move.get(product.id) or False,
                "target": {"model": "stock.quant", "res_id": quant.id},
            })

        return self._plain({
            "company": {"id": company.id, "name": company.name},
            "total": total,
            "offset": offset,
            "limit": limit,
            "count": len(rows),
            "truncated": offset + len(rows) < total,
            "rows": rows,
        })

    # ------------------------------------------------------------------ що лежить на підлозі
    @api.model
    def floor_packages(self, company_id):
        """Що стоїть нерозкладеним: приймання, підлоги полиць і свіжий випуск.

        Вхід: company_id.

        Вихід:
          company  {id, name}
          rows     по рядку на залишок, приймання першим, далі підлоги, далі випуск:
            source      input (локація приймання складу) | floor (підлога полиці,
                        локація з назвою «Підлога») | production (готова продукція
                        замовлень, закритих за останні 3 дні і досі у виробничій
                        локації)
            product     [id, назва], code, uom
            category    [id, назва] категорії товару або False
            lot         [id, назва] партії / серійного номера залишку або False
            location    [id, назва], quantity, reserved, free
            size, size_label   габарит товару - `product.template.ua_size`, те саме
                        поле, яке читають карта і `stock.location.ua_capacity_used`
            per_unit    місць на ОДНУ одиницю (S/M/L = 1/4/16)
            slots       quantity × per_unit - скільки місць займе цей залишок
            order       [id, назва] замовлення на виробництво для source=production,
                        інакше False
            done_date   коли замовлення закрито (лише для source=production)
            suggest     {location: [id, назва], why} - куди це кладуть за нативним
                        правилом розкладання (`_get_putaway_strategy`), або False
            target      {model: stock.quant, res_id}

        Рядки джерела production - це саме ті випуски, що фізично лишились у
        виробничій локації: якщо готову продукцію вже перевезли на полицю, рядка
        не буде. Нічого не створює і не переміщує: «Розкласти» - окрема дія
        інтерфейсу через `stock.picking`.
        """
        company = self._as_company(company_id)
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], order="sequence, id")
        inputs = warehouses.mapped("wh_input_stock_loc_id").filtered("active")
        floors = self._internal_locations(company).filtered(
            lambda location: (location.name or "") == FLOOR_NAME)

        rows = []
        for source, locations in (("input", inputs), ("floor", floors)):
            if not locations:
                continue
            for quant in self.env["stock.quant"].search([
                    ("location_id", "in", locations.ids),
                    ("company_id", "in", (False, company.id)),
                    ("quantity", ">", 0)], order="location_id, product_id, id"):
                rows.append(self._floor_row(source, quant, company))

        if "mrp.production" in self.env:
            since = fields.Date.to_string(
                fields.Date.context_today(self) - timedelta(days=FRESH_MO_DAYS))
            orders = self.env["mrp.production"].search([
                ("company_id", "=", company.id), ("state", "=", "done"),
                ("date_finished", ">=", since + " 00:00:00")], order="date_finished desc, id desc")
            for order in orders:
                for quant in self.env["stock.quant"].search([
                        ("product_id", "=", order.product_id.id),
                        ("location_id.usage", "=", "production"),
                        ("company_id", "in", (False, company.id)),
                        ("quantity", ">", 0)], order="location_id, id"):
                    row = self._floor_row("production", quant, company)
                    row["order"] = [order.id, order.display_name]
                    row["done_date"] = order.date_finished
                    rows.append(row)

        return self._plain({"company": {"id": company.id, "name": company.name},
                            "count": len(rows), "rows": rows})

    @api.model
    def _floor_row(self, source, quant, company):
        """Один рядок «нерозкладеного»: залишок, габарит і куди його кладуть."""
        size, slots = self._size_of(quant.product_id)
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], order="sequence, id", limit=1)
        stock_location = warehouse.lot_stock_id
        suggest = False
        if stock_location:
            putaway = stock_location._get_putaway_strategy(quant.product_id)
            if putaway and putaway != stock_location:
                suggest = {"location": [putaway.id, putaway.display_name],
                           "why": "правило розкладання"}
        return {
            "source": source,
            "product": [quant.product_id.id, quant.product_id.display_name],
            "code": quant.product_id.default_code or "",
            "category": self._category_pair(quant.product_id),
            "lot": [quant.lot_id.id, quant.lot_id.display_name] if quant.lot_id else False,
            "uom": quant.product_uom_id.display_name or "",
            "location": [quant.location_id.id, quant.location_id.display_name],
            "quantity": self._r2(quant.quantity),
            "reserved": self._r2(quant.reserved_quantity),
            "free": self._r2(quant.available_quantity),
            "size": size,
            "size_label": self._labels("product.template", "ua_size").get(size, ""),
            "per_unit": slots,
            "slots": self._r2(quant.quantity * slots),
            "order": False,
            "done_date": False,
            "suggest": suggest,
            "target": {"model": "stock.quant", "res_id": quant.id},
        }

    # ------------------------------------------------------------------ складальна карта
    @api.model
    def product_assembly(self, product_id):
        """Складальна карта виробу з полицями, де комплектуючі лежать ЗАРАЗ.

        Вхід: product_id - id `product.template` (картки товару). З `product.product`
        передавайте `product_tmpl_id[0]`: два переліки мають свої лічильники id, і
        мовчки вгадувати, який із них прийшов, цей метод не буде.

        Вихід - те саме, що віддає `product.template.ua_assembly()`, плюс те, чого
        там нема:
          product      [id, назва] виробу, code
          drawing_svg  текст SVG складального креслення або False (не base64)
          drawing_name назва файла креслення або False
          operations   [{name, workcenter, time_minutes, steps, checks, parts}] у
                       порядку маршруту; рядки специфікації без операції - остання
                       група «Без операції»
            parts      [{pos, product, product_id, qty, bin_location, bin_source}]
              pos          номер позиції на кресленні: елемент з id `bom-N` у SVG,
                           де N = pos. Це єдиний обовʼязковий id; інших схем
                           (pos-N тощо) договір не знає
              qty          потреба на ОДНУ одиницю виробу, в одиниці самого компонента
              bin_location полиця рядком; спершу та, де комплектуюча ЛЕЖИТЬ зараз
                           (найбільший залишок), і лише якщо її ніде немає - та, куди
                           її кладуть за правилом розкладання; інакше False
              bin_source   stock (лежить там) | rule (правило розкладання) | False
          total_minutes сума норм часу операцій

        Різниця з `ua_assembly()` одна і навмисна: там полиця - це перш за все
        правило розкладання («куди належить класти»), тут - перш за все місце, де
        комплектуюча лежить («куди йти зараз»). Збирач іде по деталі, а не по
        налаштуванню.

        Лише читання: ні замовлення на виробництво, ні резерву цей виклик не створює.
        """
        template = self.env["product.template"].browse(int(product_id))
        if not template.exists():
            raise UserError(
                "Картки товару з id %s немає. Передайте id product.template: з "
                "product.product це product_tmpl_id." % product_id)

        card = template.ua_assembly()
        company = self.env.company
        locations = self._internal_locations(company)

        # Позиції йдуть у тому ж порядку, що й у ua_assembly(): sequence, далі id.
        bom = template._ua_bom()
        by_position = {}
        if bom:
            for position, line in enumerate(
                    bom.bom_line_ids.sorted(lambda l: (l.sequence, l.id)), start=1):
                by_position[position] = line.product_id

        for operation in card.get("operations", []):
            for part in operation.get("parts", []):
                product = by_position.get(part.get("pos"))
                part["product_id"] = product.id if product else False
                part["bin_source"] = "rule" if part.get("bin_location") else False
                if not product:
                    continue
                quant = self.env["stock.quant"].search([
                    ("product_id", "=", product.id),
                    ("location_id", "in", locations.ids),
                    ("quantity", ">", 0),
                ], order="quantity desc, id", limit=1)
                if quant:
                    part["bin_location"] = quant.location_id.display_name
                    part["bin_source"] = "stock"

        return self._plain({
            "product": [template.id, template.display_name],
            "code": template.default_code or "",
            "drawing_svg": card.get("drawing_svg") or False,
            "drawing_name": card.get("drawing_name") or False,
            "operations": card.get("operations", []),
            "total_minutes": self._r2(sum(operation.get("time_minutes") or 0.0
                                          for operation in card.get("operations", []))),
        })

    # ------------------------------------------------------------------ план інвентаризації
    @api.model
    def inventory_plan(self, inventory_id):
        """Що зробить проведення інвентаризації - третє дієслово екрана складу.

        Вхід: inventory_id - id `ua.stock.inventory`.

        Вихід:
          inventory {id, name, date, state, state_label, location, client_ref,
                     lines, diff_lines, amount_surplus, amount_shortage, target}
          plan      [{text, level, target}] - рядки з `ua.stock.inventory.plan()`,
                    level: info | warn | crit, той самий вигляд, що в плані закриття
                    місяця
          crit      скільки рядків рівня crit
          can_apply True, якщо жодного crit немає, тобто `action_apply()` пройде

        `can_apply` - не окрема перевірка, а підсумок тих самих рядків: ядро вважає
        проведення неможливим рівно тоді, коли в плані є crit. Саме проведення -
        окремий виклик `ua.stock.inventory.action_apply()` у відповідь на натискання.
        """
        inventory = self.env["ua.stock.inventory"].browse(int(inventory_id))
        if not inventory.exists():
            raise UserError("Інвентаризації з id %s немає." % inventory_id)

        rows = [self._plain(row) for row in inventory.plan()]
        crit = sum(1 for row in rows if row.get("level") == "crit")
        states = self._labels("ua.stock.inventory", "state")
        return self._plain({
            "inventory": {
                "id": inventory.id,
                "name": inventory.name or "",
                "date": inventory.date,
                "state": inventory.state or "",
                "state_label": states.get(inventory.state, ""),
                "location": [inventory.location_id.id, inventory.location_id.display_name]
                            if inventory.location_id else False,
                "client_ref": inventory.ua_client_ref or "",
                "lines": len(inventory.line_ids),
                "diff_lines": len(inventory._lines_with_diff()),
                "amount_surplus": self._r2(inventory.amount_surplus),
                "amount_shortage": self._r2(inventory.amount_shortage),
                "target": {"model": "ua.stock.inventory", "res_id": inventory.id},
            },
            "plan": rows,
            "crit": crit,
            "can_apply": not crit,
        })

    # ------------------------------------------------------------------ картка наряду
    @api.model
    def workorder_card(self, workorder_id):
        """Картка наряду для кіоску цеху: що робити, чим, і що вже перевірено.

        Вхід: workorder_id - id `mrp.workorder`.

        Вихід:
          workorder  {id, name, production: [id, назва], product: [id, назва],
                      workcenter: [id, назва], state, state_label, qty_production,
                      qty_producing, duration_expected, duration (хвилини),
                      date_start, date_finished, target}
          steps      кроки операції (`mrp.routing.workcenter.ua_steps`), по пункту
          checks     `mrp.workorder.ua_check_rows()` - [{index, text, result, note,
                      user, date}], result: ok | fail | False
          open       скільки пунктів ще без відповіді
          failed     скільки пунктів із відповіддю «ні»
          parts      [{product: [id, назва], code, qty, uom, picked}] - рядки
                      списання замовлення, що споживаються в ЦІЙ операції

        Писати - нативно: `mrp.workorder.button_start()`, `button_pending()`,
        `button_finish()`; відповідь на пункт - `mrp.workorder.ua_answer_check(index,
        result, note)`. Цей виклик лише читає.
        """
        workorder = self.env["mrp.workorder"].browse(int(workorder_id or 0))
        if not workorder.exists():
            raise UserError("Наряду з id %s немає." % workorder_id)
        states = self._labels("mrp.workorder", "state")
        checks = workorder.ua_check_rows()
        moves = workorder.production_id.move_raw_ids.filtered(
            lambda move: move.operation_id == workorder.operation_id
            and move.state != "cancel")
        return self._plain({
            "workorder": {
                "id": workorder.id,
                "name": workorder.name or "",
                "production": [workorder.production_id.id,
                               workorder.production_id.display_name],
                "product": [workorder.product_id.id, workorder.product_id.display_name]
                           if workorder.product_id else False,
                "workcenter": [workorder.workcenter_id.id,
                               workorder.workcenter_id.display_name],
                "state": workorder.state or "",
                "state_label": states.get(workorder.state, ""),
                "qty_production": workorder.qty_production,
                "qty_producing": workorder.qty_producing,
                "duration_expected": self._r2(workorder.duration_expected),
                "duration": self._r2(workorder.duration),
                "date_start": workorder.date_start or False,
                "date_finished": workorder.date_finished or False,
                "target": {"model": "mrp.workorder", "res_id": workorder.id},
            },
            "steps": self.env["product.template"]._ua_text_items(
                workorder.operation_id.ua_steps),
            "checks": checks,
            "open": sum(1 for row in checks if not row["result"]),
            "failed": sum(1 for row in checks if row["result"] == "fail"),
            "parts": [{
                "product": [move.product_id.id, move.product_id.display_name],
                "code": move.product_id.default_code or "",
                "qty": self._r2(move.product_uom_qty),
                "uom": move.product_uom.display_name or "",
                "picked": bool(move.picked),
            } for move in moves.sorted(lambda move: (move.sequence, move.id))],
        })
