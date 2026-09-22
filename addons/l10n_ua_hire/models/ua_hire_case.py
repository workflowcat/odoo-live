# -*- coding: utf-8 -*-
"""Справа прийняття: одна картка від першої розмови з кандидатом до поданого повідомлення.

Кандидат і прийняття - той самий запис: на співбесіді збирають ті самі дані, що потім ідуть у картку.
Дані вводять руками або беруть із завантажених документів: розпізнавання дає пропозиції, а в поле
значення потрапляє лише після підтвердження людиною. «Прийняти на роботу» створює картку працівника,
документи, проведений наказ, чернетку J3001005 і, для військовозобов'язаних, чернетку повідомлення ТЦК."""
import json
import logging
import os
import re
from datetime import date, timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_hr_card.models.hr_employee import ID_DOC_TYPES
from odoo.addons.l10n_ua_hr_orders.models.ua_hr_order import CONTRACT_KIND, FTE, REGISTER_BY_TYPE, REGISTERS
from odoo.addons.l10n_ua_military.models.hr_employee import CATEGORY as MIL_CATEGORY
from odoo.addons.l10n_ua_military.models.hr_employee import DOC_TYPE as MIL_DOC_TYPE
from odoo.addons.l10n_ua_military.models.hr_employee import FITNESS, LIABLE_STATUSES
from odoo.addons.l10n_ua_military.models.hr_employee import STATUS as MIL_STATUS

_logger = logging.getLogger(__name__)

STAGES = [
    ("candidate", "Кандидат"),
    ("onboarding", "Оформлення"),
    ("hired", "Прийнято"),
    ("declined", "Відмова"),
]
SEX = [("male", "чоловіча"), ("female", "жіноча")]

# Розділи картки справи в порядку заповнення. Екран будує поля з цього списку.
SECTIONS = [
    ("candidate", "Кандидат", ["last_name", "first_name", "middle_name", "phone", "email", "job_title",
                               "department_id", "expected_wage", "source", "interview_date", "pd_consent", "screening_note"]),
    ("identity", "Особа", ["birthday", "sex", "rnokpp", "id_doc_type", "id_doc_series", "id_doc_number",
                           "id_doc_unzr", "id_doc_issued_by", "id_doc_date", "reg_address", "actual_address"]),
    ("education", "Освіта і трудова", ["diploma_number", "education_year", "labor_book_number", "electronic_labor_book"]),
    ("military", "Військовий облік", ["mil_status", "mil_category", "mil_rank", "mil_vos", "mil_tcc",
                                      "mil_doc_type", "mil_doc_series", "mil_doc_number", "mil_doc_date", "mil_fitness",
                                      "mil_reserve_number", "mil_reserve_date"]),
    ("terms", "Умови", ["date_from", "wage", "fte", "contract_kind", "main_job", "kp_code", "trial_date_end",
                       "pay_advance_percent", "pay_advance_day", "pay_final_day"]),
]
# Поля, які можна взяти з документів. Умови роботи документи кандидата не містять.
EXTRACTABLE = [f for key, _t, names in SECTIONS if key in ("candidate", "identity", "education", "military")
               for f in names if f not in ("job_title", "department_id", "expected_wage", "source", "interview_date",
                                          "pd_consent", "screening_note")]

CHECK_LEVEL_LABELS = {"ok": "OK", "warn": "УВАГА", "error": "ПОМИЛКА"}
CHECK_LEVEL_ORDER = {"error": 0, "warn": 1, "ok": 2}
DIGITS_ONLY = ("rnokpp", "id_doc_unzr")
# Пакет першого дня: ключ, назва, звіт. Наказ після прийняття друкується з проведеного наказу.
PACKAGE = [
    ("statement", "Заява про прийняття", "l10n_ua_hire.report_hire_statement"),
    ("order", "Наказ про прийняття", "l10n_ua_hire.report_hire_order_draft"),
    ("contract", "Трудовий договір", "l10n_ua_hire.report_hire_contract"),
    ("nda", "Договір про нерозголошення", "l10n_ua_hire.report_hire_nda"),
    ("consent", "Згода на обробку персональних даних", "l10n_ua_hire.report_hire_consent"),
    ("ack", "Лист ознайомлення", "l10n_ua_hire.report_hire_ack"),
    ("inventory", "Опис документів особової справи", "l10n_ua_hire.report_hire_file_inventory"),
]
# Кількість аркушів для документів, які система сама друкує (назва «Опис документів особової справи»
# лишається робочою - уточнити з бухгалтерією/HR перед затвердженням форми).
GENERATED_PAGES = {"statement": 1, "order": 1, "contract": 2, "nda": 2, "consent": 1, "ack": 1}
EXTRACT_URL = os.environ.get("UA_EXTRACT_URL", "http://host.docker.internal:8765")
HELPER_UNAVAILABLE = "Помічник розпізнавання недоступний"


def rnokpp_problems(code, birthday=None, sex=None):
    """Перевірка РНОКПП: 10 цифр, контрольна цифра, дата народження в перших 5 цифрах, стать у 9-й."""
    if not code:
        return []
    if not re.fullmatch(r"\d{10}", code):
        return ["має бути 10 цифр"]
    d = [int(c) for c in code]
    problems = []
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    if sum(w * x for w, x in zip(weights, d)) % 11 % 10 != d[9]:
        problems.append("контрольна цифра не збігається")
    encoded = date(1899, 12, 31) + timedelta(days=int(code[:5]))
    if birthday and encoded != birthday:
        problems.append("перші 5 цифр дають дату народження %s" % encoded.strftime("%d.%m.%Y"))
    if sex in ("male", "female") and (d[8] % 2 == 1) != (sex == "male"):
        problems.append("9-та цифра не відповідає статі")
    return problems


class UaHireCase(models.Model):
    _name = "ua.hire.case"
    _inherit = ["mail.thread"]
    _description = "Справа прийняття"
    _order = "write_date desc, id desc"

    name = fields.Char("ПІБ", compute="_compute_name", store=True)
    stage = fields.Selection(STAGES, "Етап", default="candidate", required=True, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    decline_reason = fields.Char("Причина відмови", tracking=True)

    # кандидат
    last_name = fields.Char("Прізвище", tracking=True)
    first_name = fields.Char("Ім'я", tracking=True)
    middle_name = fields.Char("По батькові")
    phone = fields.Char("Телефон")
    email = fields.Char("Email")
    job_title = fields.Char("Посада", tracking=True)
    department_id = fields.Many2one("hr.department", "Підрозділ", tracking=True)
    expected_wage = fields.Monetary("Очікуваний оклад", currency_field="currency_id")
    source = fields.Char("Звідки кандидат")
    interview_date = fields.Date("Співбесіда")
    pd_consent = fields.Boolean("Згода на обробку персональних даних", tracking=True)
    screening_note = fields.Text("Нотатки співбесіди")

    # особа
    birthday = fields.Date("Дата народження")
    sex = fields.Selection(SEX, "Стать")
    rnokpp = fields.Char("РНОКПП")
    id_doc_type = fields.Selection(ID_DOC_TYPES, "Документ особи")
    id_doc_series = fields.Char("Серія")
    id_doc_number = fields.Char("Номер документа")
    id_doc_unzr = fields.Char("УНЗР")
    id_doc_issued_by = fields.Char("Ким виданий")
    id_doc_date = fields.Date("Дата видачі")
    reg_address = fields.Char("Адреса реєстрації")
    actual_address = fields.Char("Фактична адреса")

    # освіта і трудова
    diploma_number = fields.Char("Номер диплома")
    education_year = fields.Integer("Рік закінчення")
    labor_book_number = fields.Char("Номер трудової книжки")
    electronic_labor_book = fields.Boolean("Електронна трудова")

    # військовий облік
    mil_status = fields.Selection(MIL_STATUS, "Стан обліку")
    mil_category = fields.Selection(MIL_CATEGORY, "Категорія обліку")
    mil_rank = fields.Char("Військове звання")
    mil_vos = fields.Char("ВОС")
    mil_tcc = fields.Char("ТЦК та СП")
    mil_doc_type = fields.Selection(MIL_DOC_TYPE, "Військовий документ")
    mil_doc_series = fields.Char("Серія військового документа")
    mil_doc_number = fields.Char("Номер військового документа")
    mil_doc_date = fields.Date("Дата видачі військового документа")
    mil_fitness = fields.Selection(FITNESS, "Придатність")
    # Резерв+ (витяг): необов'язковий блок, дзеркалить hr.employee.ua_reserve_*; переноситься на картку при прийнятті.
    mil_reserve_number = fields.Char("Номер витягу Резерв+")
    mil_reserve_date = fields.Date("Дата витягу Резерв+")
    mil_reserve_filename = fields.Char("Файл витягу (назва)")
    mil_reserve_file = fields.Binary("Файл витягу Резерв+", attachment=True)

    # умови
    date_from = fields.Date("Перший робочий день", tracking=True)
    wage = fields.Monetary("Оклад", currency_field="currency_id", tracking=True)
    fte = fields.Selection(FTE, "Ставка", default="1")
    contract_kind = fields.Selection(CONTRACT_KIND, "Вид відносин", default="employment")
    main_job = fields.Boolean("Основне місце роботи", default=True)
    kp_code = fields.Char("Код КП")
    trial_date_end = fields.Date("Випробувальний строк до")
    pay_advance_percent = fields.Float("Аванс, % окладу", default=lambda s: s.env.company.ua_pay_advance_percent)
    pay_advance_day = fields.Integer("Аванс до числа", default=lambda s: s.env.company.ua_pay_advance_day)
    pay_final_day = fields.Integer("Остаточний розрахунок до числа", default=lambda s: s.env.company.ua_pay_final_day)

    package_skip = fields.Char("Не друкувати в пакеті", help="Ключі документів через кому")
    file_ids = fields.One2many("ua.hire.file", "case_id", "Файли")
    proposal_ids = fields.One2many("ua.hire.proposal", "case_id", "Пропозиції")

    # результат
    employee_id = fields.Many2one("hr.employee", "Працівник", readonly=True, copy=False)
    order_id = fields.Many2one("ua.hr.order", "Наказ", readonly=True, copy=False)
    j30_run_id = fields.Many2one("ua.report.run", "J3001005", readonly=True, copy=False)
    notice_id = fields.Many2one("ua.military.notice", "Повідомлення ТЦК", readonly=True, copy=False)
    hired_date = fields.Date("Прийнято", readonly=True, copy=False)

    # Текстовий підсумок _checks() для сторінки «Перевірки» форми (тим самим рядком, що і
    # ua.checks.mixin у інших картках місяця, але без самого міксину - формат _checks() тут
    # інший (title/detail/section), і його читають action_hire_plan/action_hire та scripts/hire_check.py.
    checks_text = fields.Text("Перевірки", compute="_compute_checks_text")

    @api.depends("last_name", "first_name", "middle_name")
    def _compute_name(self):
        for case in self:
            case.name = " ".join(p for p in [case.last_name, case.first_name, case.middle_name] if p) or _("Новий кандидат")

    # ------------------------------------------------------------------ правила
    def _age_at(self, day):
        b = self.birthday
        if not b or not day:
            return None
        return day.year - b.year - ((day.month, day.day) < (b.month, b.day))

    def _military_required(self):
        """Чоловіки 18-60 років на перший робочий день підлягають обліку; решта - якщо стан обліку вже вказано."""
        self.ensure_one()
        age = self._age_at(self.date_from or fields.Date.context_today(self))
        male_liable = self.sex == "male" and age is not None and 18 <= age <= 60
        return male_liable or self.mil_status in LIABLE_STATUSES

    def _required_fields(self):
        """Обов'язкові за законом: РНОКПП, вид і номер документа особи, дата народження, адреса.
        Ким виданий / дата видачі / УНЗР - корисні, але не обов'язкові для всіх; лишаються
        «необов'язково», а не «бракує», доки їх не заповнили."""
        self.ensure_one()
        need = {"last_name", "first_name", "job_title"}
        if self.stage == "candidate":
            return need
        need |= {"birthday", "sex", "rnokpp", "id_doc_type", "id_doc_number",
                 "reg_address", "date_from", "wage", "department_id", "pd_consent"}
        if self.id_doc_type == "passport_book":
            need.add("id_doc_series")
        if self._military_required():
            need.add("mil_status")
            if self.mil_status in LIABLE_STATUSES:
                need |= {"mil_tcc", "mil_doc_type", "mil_doc_number"}
        return need

    def _field_states(self):
        """Стан кожного поля: provided - є значення; proposed - є пропозиція; missing - обов'язкове і порожнє; empty."""
        self.ensure_one()
        required = self._required_fields()
        pending = set(self.proposal_ids.filtered(lambda p: p.state == "pending").mapped("field_name"))
        out = {}
        for _key, _title, names in SECTIONS:
            for f in names:
                value = self[f]
                has = bool(value) if self._fields[f].type != "boolean" else value
                if has:
                    out[f] = "provided"
                elif f in pending:
                    out[f] = "proposed"
                elif f in required:
                    out[f] = "missing"
                else:
                    out[f] = "empty"
        return out

    def _requirements(self):
        """Обов'язкові документи з довідника, які приносить кандидат. Решту система створює сама."""
        self.ensure_one()
        kind = self.contract_kind or "employment"
        reqs = self.env["ua.hr.doc.requirement"].search([("applies_to", "in", ("all", kind))], order="sequence")
        by_code = {
            "statement": ["statement"],
            "passport_rnokpp": ["passport", "rnokpp"],
            "military_id": ["military_id"],
            "consent": ["consent"],
            "medical": ["medical"],
        }
        have = set(self.file_ids.mapped("doc_type"))
        rows = []
        for req in reqs:
            if req.code in by_code:
                if req.code == "military_id" and not self._military_required():
                    continue
                types = by_code[req.code]
                done = all(t in have for t in types) if req.code == "passport_rnokpp" and self.id_doc_type != "id_card" \
                    else any(t in have for t in types)
                rows.append({"code": req.code, "name": req.name, "state": "done" if done else "missing", "by": "candidate"})
            else:
                rows.append({"code": req.code, "name": req.name, "state": "later", "by": "system"})
        return rows

    def _checks(self):
        self.ensure_one()
        checks = []

        def add(level, title, detail="", section=""):
            checks.append({"level": level, "title": title, "detail": detail, "section": section})

        states = self._field_states()
        missing = [f for f, s in states.items() if s == "missing"]
        if missing:
            labels = ", ".join(self._fields[f].string for f in missing[:6]) + ("…" if len(missing) > 6 else "")
            add("error", _("Бракує даних: %s") % len(missing), labels, self._section_of(missing[0]))
        proposed = [f for f, s in states.items() if s == "proposed"]
        if proposed:
            add("warn", _("Пропозиції чекають підтвердження: %s") % len(proposed),
                ", ".join(self._fields[f].string for f in proposed[:6]), self._section_of(proposed[0]))
        if self.stage == "candidate":
            return checks

        problems = rnokpp_problems(self.rnokpp, self.birthday, self.sex)
        if problems:
            add("error", _("РНОКПП не проходить перевірку"), "; ".join(problems), "identity")
        if self.rnokpp:
            dup = self.env["hr.employee"].sudo().with_context(active_test=False).search([("ua_rnokpp", "=", self.rnokpp)], limit=1)
            if dup:
                add("warn", _("Працівник з цим РНОКПП уже є"), dup.name, "identity")
        if self.id_doc_type == "id_card" and self.id_doc_number and not re.fullmatch(r"\d{9}", self.id_doc_number):
            add("error", _("Номер ID-картки має 9 цифр"), self.id_doc_number, "identity")
        if self.id_doc_unzr and not re.fullmatch(r"\d{13}", self.id_doc_unzr):
            add("error", _("УНЗР має 13 цифр"), self.id_doc_unzr, "identity")
        elif self.id_doc_unzr and self.birthday and self.id_doc_unzr[:8] != self.birthday.strftime("%Y%m%d"):
            add("error", _("УНЗР не відповідає даті народження"), self.id_doc_unzr, "identity")
        if self.id_doc_type == "passport_book":
            if self.id_doc_series and not re.fullmatch(r"[А-ЯІЇЄҐ]{2}", self.id_doc_series):
                add("error", _("Серія паспорта: дві великі українські літери"), self.id_doc_series, "identity")
            if self.id_doc_number and not re.fullmatch(r"\d{6}", self.id_doc_number):
                add("error", _("Номер паспорта-книжки має 6 цифр"), self.id_doc_number, "identity")
        if self.mil_doc_type == "registration" and self.mil_status != "conscript":
            add("error", _("«Посвідчення про приписку» - лише для призовників"),
                dict(MIL_STATUS).get(self.mil_status, self.mil_status or "-"), "military")
        age = self._age_at(self.date_from)
        if age is not None and age < 16:
            add("error", _("Вік на перший робочий день менше 16 років"), str(age), "identity")
        elif age is not None and age < 18:
            add("warn", _("Неповнолітній: обмеження щодо годин і робіт"), str(age), "identity")

        if self.contract_kind == "employment" and self.main_job and self.wage and self.date_from:
            param = self.env["ua.payroll.param"].search([("key", "=", "min_wage"), ("valid_from", "<=", str(self.date_from))],
                                                        order="valid_from desc", limit=1)
            floor = param.value * float(self.fte or 1) if param else 0
            if floor and self.wage < floor:
                add("warn", _("Оклад нижчий за мінімальну зарплату"), "%.2f < %.2f" % (self.wage, floor), "terms")

        missing_docs = [r["name"] for r in self._requirements() if r["state"] == "missing"]
        if missing_docs:
            add("error", _("Бракує документів: %s") % len(missing_docs), ", ".join(missing_docs), "files")

        if self.date_from:
            deadline = self.date_from - timedelta(days=1)
            today = fields.Date.context_today(self)
            if self.date_from <= today:
                add("warn", _("Повідомлення до ДПС (J3001005) мало бути подане до першого робочого дня"),
                    deadline.strftime("%d.%m.%Y"), "terms")
            else:
                add("ok", _("Повідомлення до ДПС (J3001005) подати до %s") % deadline.strftime("%d.%m.%Y"), "", "terms")
        if not [c for c in checks if c["level"] in ("error", "warn")]:
            add("ok", _("Дані і документи повні"), "", "")
        return checks

    def _section_of(self, field_name):
        for key, _title, names in SECTIONS:
            if field_name in names:
                return key
        return ""

    def _compute_checks_text(self):
        for case in self:
            if not case.id:
                case.checks_text = ""
                continue
            checks = sorted(case._checks(), key=lambda c: CHECK_LEVEL_ORDER.get(c["level"], 9))
            if not checks:
                case.checks_text = _("Перевірок немає.")
                continue
            lines = []
            for c in checks:
                line = "%s: %s" % (CHECK_LEVEL_LABELS.get(c["level"], c["level"].upper()), c["title"])
                if c.get("detail"):
                    line += " (%s)" % c["detail"]
                lines.append(line)
            case.checks_text = "\n".join(lines)

    # ------------------------------------------------------------------ пакет першого дня
    def _blank(self, value, width=16):
        return value if value else "_" * width

    def _date(self, day):
        return day.strftime("%d.%m.%Y") if day else "«____» ____________ 20___ р."

    def _money(self, amount):
        if not amount:
            return "__________ грн"
        return "{:,.2f}".format(amount).replace(",", "\u00a0").replace(".", ",") + " грн"

    def _short_name(self):
        self.ensure_one()
        if not self.last_name:
            return "____________________"
        initials = "".join("%s." % p[0] for p in [self.first_name, self.middle_name] if p)
        return ("%s %s" % (initials, self.last_name.upper())).strip()

    def _id_doc_text(self):
        self.ensure_one()
        kind = dict(self._fields["id_doc_type"].selection).get(self.id_doc_type, "документ, що посвідчує особу")
        number = " ".join(p for p in [self.id_doc_series, self.id_doc_number] if p) or "__________"
        issued = ", виданий %s %s" % (self.id_doc_issued_by or "__________", self._date(self.id_doc_date)) if (self.id_doc_issued_by or self.id_doc_date) else ""
        return "%s № %s%s" % (kind, number, issued)

    def _package(self):
        self.ensure_one()
        skip = set((self.package_skip or "").split(","))
        rows = []
        for key, label, report in PACKAGE:
            item = {"r": report, "ids": [self.id], "t": label}
            if key == "order" and self.order_id:
                item = {"r": "l10n_ua_hr_orders.report_ua_hr_order", "ids": [self.order_id.id], "t": label}
            rows.append({"key": key, "label": label, "on": key not in skip, "item": item})
        return rows

    def _pdf_page_count(self, data, filename=""):
        """Кількість сторінок для PDF (через pypdf); для решти форматів - 1 сторінка."""
        if not data:
            return 1
        name = (filename or "").lower()
        looks_pdf = name.endswith(".pdf") or (isinstance(data, bytes) and data[:200].find(b"%PDF-") != -1)
        if not looks_pdf:
            return 1
        try:
            import base64
            import io

            from pypdf import PdfReader
            raw = data if isinstance(data, bytes) else base64.b64decode(data)
            return max(1, len(PdfReader(io.BytesIO(raw)).pages))
        except Exception:  # noqa: BLE001 - формат не PDF або бібліотека недоступна - 1 сторінка як безпечне припущення
            return 1

    def _file_inventory(self):
        """Опис документів особової справи: завантажені файли кандидата (кількість сторінок
        рахуємо для PDF, інакше 1) і документи, які друкує сама система (відома кількість
        сторінок з GENERATED_PAGES)."""
        self.ensure_one()
        skip = set((self.package_skip or "").split(","))
        rows = []
        n = 0
        for f in self.file_ids.filtered("file"):
            n += 1
            rows.append({"n": n, "name": f.name, "pages": self._pdf_page_count(f.file, f.filename or f.name)})
        for key, label, _report in PACKAGE:
            if key in ("inventory",) or key in skip:
                continue
            n += 1
            rows.append({"n": n, "name": label, "pages": GENERATED_PAGES.get(key, 1)})
        return rows

    def set_package_doc(self, key, on):
        self.ensure_one()
        skip = {k for k in (self.package_skip or "").split(",") if k}
        if on:
            skip.discard(key)
        else:
            skip.add(key)
        self.package_skip = ",".join(sorted(skip)) or False
        return True

    # ------------------------------------------------------------------ опис полів і значення
    # Обидва методи лишились у логіці, хоч ними живиться і екран: action_extract() будує з
    # _field_meta() опис полів для помічника розпізнавання і звіряє пропозицію з чинним
    # значенням через _value_for_screen(). Без них розпізнавання не працює навіть тоді,
    # коли l10n_ua_hire_ui не встановлено.
    @api.model
    def _field_meta(self, case=None):
        """case - вибрана справа (щоб приховати «договір ЦПХ» у новому виборі, лишивши його видним,
        якщо саме таке значення вже стоїть на старому записі)."""
        meta = {}
        for key, title, names in SECTIONS:
            for f in names:
                fld = self._fields[f]
                item = {"name": f, "label": fld.string, "type": fld.type, "section": key}
                if fld.type == "selection":
                    options = fld._description_selection(self.env)
                    if f == "contract_kind":
                        current = case.contract_kind if case else False
                        options = [(k, v) for k, v in options if k == "employment" or k == current]
                    item["options"] = [[k, v] for k, v in options]
                meta[f] = item
        return meta

    def _value_for_screen(self, f):
        fld = self._fields[f]
        value = self[f]
        if fld.type == "many2one":
            return [value.id, value.display_name] if value else False
        if fld.type == "date":
            return value.isoformat() if value else ""
        if fld.type in ("char", "text", "selection"):
            return value or ""
        return value

    # ------------------------------------------------------------------ дії справи
    @api.model
    def create_case(self, last_name="", first_name="", job_title=""):
        case = self.create({"last_name": last_name.strip() or False, "first_name": first_name.strip() or False,
                            "job_title": job_title.strip() or False})
        return case.id

    def _coerce(self, field_name, value):
        fld = self._fields[field_name]
        if fld.type == "many2one":
            return int(value) if value else False
        if fld.type == "date":
            return value or False
        if fld.type in ("monetary", "float"):
            return float(str(value).replace(" ", "").replace(",", ".")) if value not in ("", None, False) else 0.0
        if fld.type == "integer":
            return int(value) if value not in ("", None, False) else 0
        if fld.type == "boolean":
            return bool(value)
        if isinstance(value, str):
            value = value.strip()
            if field_name in DIGITS_ONLY:
                value = re.sub(r"\D", "", value)
        return value or False

    def set_value(self, field_name, value):
        self.ensure_one()
        allowed = {f for _k, _t, names in SECTIONS for f in names}
        if field_name not in allowed:
            raise UserError(_("Це поле не редагується з екрана."))
        if self.stage in ("hired", "declined"):
            raise UserError(_("Справа закрита. Відкрийте її знову, щоб змінити дані."))
        try:
            self.write({field_name: self._coerce(field_name, value)})
        except ValueError:
            raise UserError(_("Невірне значення для поля «%s».") % self._fields[field_name].string)
        return True

    def action_start_onboarding(self):
        for case in self:
            if case.stage != "candidate":
                continue
            case.stage = "onboarding"
            case.message_post(body=_("Кандидата взято в оформлення."))
        return True

    def action_decline(self, reason=""):
        for case in self:
            if case.stage == "hired":
                raise UserError(_("Працівника вже прийнято."))
            case.write({"stage": "declined", "decline_reason": reason or False})
        return True

    def action_reopen(self):
        for case in self:
            if case.stage == "hired":
                raise UserError(_("Працівника вже прийнято. Зміни робіть у картці працівника."))
            case.write({"stage": "onboarding" if case.date_from or case.rnokpp else "candidate", "decline_reason": False})
        return True

    def add_file(self, name, data, doc_type="other"):
        self.ensure_one()
        f = self.env["ua.hire.file"].create({"case_id": self.id, "name": name, "filename": name, "file": data,
                                             "doc_type": doc_type or "other"})
        return f.id

    def set_reserve_file(self, filename, data):
        """Файл витягу Резерв+: необов'язковий, не редагується через set_value (не в SECTIONS)."""
        self.ensure_one()
        if self.stage in ("hired", "declined"):
            raise UserError(_("Справа закрита. Відкрийте її знову, щоб змінити дані."))
        self.write({"mil_reserve_file": data, "mil_reserve_filename": filename or "витяг"})
        return True

    def clear_reserve_file(self):
        self.ensure_one()
        self.write({"mil_reserve_file": False, "mil_reserve_filename": False})
        return True

    # ------------------------------------------------------------------ розпізнавання
    @api.model
    def extract_status(self):
        try:
            r = requests.get(EXTRACT_URL + "/health", timeout=1.5)
            if r.ok:
                return r.json()
            return {"ok": False, "error": _(HELPER_UNAVAILABLE), "reason": "HTTP %s" % r.status_code}
        except Exception as e:  # noqa: BLE001 - будь-яка мережева помилка означає «помічник недоступний»
            return {"ok": False, "error": _(HELPER_UNAVAILABLE), "reason": str(e)[:200]}

    def action_extract(self):
        """Надіслати файли локальному помічнику Claude і записати пропозиції. Значення в поля не пишемо."""
        self.ensure_one()
        if not self.pd_consent:
            raise UserError(_("Спершу позначте згоду кандидата на обробку персональних даних."))
        files = self.file_ids.filtered(lambda f: f.file and f.extract_state != "done") or self.file_ids.filtered("file")
        if not files:
            raise UserError(_("Завантажте хоча б один файл."))
        meta = self._field_meta()
        spec = {f: {k: v for k, v in meta[f].items() if k in ("label", "type", "options")} for f in EXTRACTABLE}
        payload = {
            "fields": spec,
            "files": [{"id": f.id, "name": f.filename or f.name, "doc_type": f.doc_type,
                       "data": f.file.decode() if isinstance(f.file, bytes) else f.file} for f in files],
        }
        try:
            # limit_time_real = 240 с: відповідь має прийти раніше, інакше Odoo уб'є робочий процес разом із запитом
            resp = requests.post(EXTRACT_URL + "/extract", data=json.dumps(payload), timeout=(5, 200),
                                 headers={"Content-Type": "application/json"})
            result = resp.json()
        except Exception as e:  # noqa: BLE001
            files.write({"extract_state": "failed", "extract_note": _(HELPER_UNAVAILABLE)})
            _logger.warning("Помічник розпізнавання недоступний: %s", str(e)[:200])
            raise UserError(_("%s. Запустіть scripts/claude_extract_helper.py на цьому комп'ютері.") % _(HELPER_UNAVAILABLE))
        if not resp.ok or result.get("error"):
            files.write({"extract_state": "failed", "extract_note": (result.get("error") or "HTTP %s" % resp.status_code)[:200]})
            raise UserError(_("Розпізнавання не вдалося: %s") % (result.get("error") or resp.status_code))

        by_name = {(f.filename or f.name): f for f in files}
        Proposal = self.env["ua.hire.proposal"]
        created = 0
        for item in result.get("proposals") or []:
            field_name = item.get("field")
            if field_name not in EXTRACTABLE:
                continue
            value = Proposal._normalize(self._fields[field_name], item.get("value"))
            if value in (None, ""):
                continue
            current = self._value_for_screen(field_name)
            if str(current) == value:
                continue
            same = self.proposal_ids.filtered(lambda p: p.field_name == field_name and p.value == value and p.state == "pending")
            if same:
                continue
            Proposal.create({
                "case_id": self.id, "field_name": field_name, "value": value,
                "file_id": by_name.get(item.get("file")).id if by_name.get(item.get("file")) else False,
                "quote": (item.get("quote") or "")[:500],
                "confidence": item.get("confidence") if item.get("confidence") in ("high", "medium", "low") else "medium",
                "model": result.get("model") or "",
            })
            created += 1
        files.write({"extract_state": "done", "extract_note": False})
        self.message_post(body=_("Розпізнано файлів: %(n)s. Пропозицій: %(p)s. Модель: %(m)s.") % {
            "n": len(files), "p": created, "m": result.get("model") or "-"})
        return {"created": created}

    # ------------------------------------------------------------------ план і наслідки прийняття
    # Модель дії (docs/payroll/action-model.md): action_hire_plan() дзеркалить гілки action_hire
    # нижче один в один - той самий пошук «попередньої картки», той самий реєстр наказу, той
    # самий підрахунок документів, той самий період J3001005, той самий пошук повідомлення ТЦК.
    # Спільні гілки винесені в приватні методи, якими користуються обидва - план ніколи не
    # обіцяє того, чого дія не виконає, бо рахує тим самим кодом.
    def _rehire_previous(self):
        """Картка з тим самим РНОКПП, яка вже архівна або звільнена - «попередня картка» при
        повторному прийнятті. Той самий пошук, що і в action_hire."""
        self.ensure_one()
        if not self.rnokpp:
            return self.env["hr.employee"]
        previous = self.env["hr.employee"].sudo().with_context(active_test=False).search([
            ("ua_rnokpp", "=", self.rnokpp), ("id", "!=", self.employee_id.id or 0),
        ], order="id desc")
        return previous.filtered(lambda e: not e.active or e.ua_dismissal_date)[:1]

    def _hire_register_label(self):
        return dict(REGISTERS).get(REGISTER_BY_TYPE.get("hire", "k1"), "К-1")

    def _hire_to_sign_count(self):
        """Скільки документів піде «на підпис»: пакет першого дня (мінус зняті позначкою і
        мінус сам наказ - його друкують з проведеного наказу) плюс документ самого наказу,
        який завжди створює гачок l10n_ua_card_ui при проведенні (ua_hr_order.action_post)."""
        self.ensure_one()
        skip = set((self.package_skip or "").split(","))
        package_to_sign = sum(1 for key, _label, _report in PACKAGE if key != "order" and key not in skip)
        return package_to_sign + 1

    def _j30_period_key(self):
        self.ensure_one()
        return "%s-%02d" % (self.date_from.year, self.date_from.month)

    def _j30_existing_run(self):
        """Прогін J3001005, який _find_or_create нижче або знайде, або створить на цьому місці."""
        self.ensure_one()
        if not self.date_from:
            return self.env["ua.report.run"]
        return self.env["ua.report.run"].sudo().search([
            ("report_code", "=", "j30"), ("company_id", "=", self.company_id.id),
            ("period_key", "=", self._j30_period_key()),
        ], limit=1)

    def _notice_window(self):
        self.ensure_one()
        if not self.date_from:
            return False, False
        return self.date_from, self.date_from + timedelta(days=6)

    def _existing_notice(self):
        """Чернетка повідомлення ТЦК, що вже покриває перший робочий день - той самий пошук,
        що і в action_hire нижче."""
        self.ensure_one()
        d1, _d2 = self._notice_window()
        if not d1:
            return self.env["ua.military.notice"]
        return self.env["ua.military.notice"].sudo().search([
            ("company_id", "=", self.company_id.id), ("state", "=", "draft"),
            ("date_from", "<=", d1), ("date_to", ">=", d1),
        ], limit=1)

    def action_hire_plan(self):
        """План перед «Прийняти на роботу»: перелік того, що action_hire нижче справді зробить
        для ЦІЄЇ справи, у майбутньому часі. Порожній план (справа не готова) - без діалогу;
        action_hire сама відмовить із поясненням."""
        self.ensure_one()
        if self.stage != "onboarding" or any(c["level"] == "error" for c in self._checks()):
            return []
        lines = []
        previous = self._rehire_previous()
        if previous and previous.active:
            lines.append({"text": _("Попередню картку «%s» (той самий РНОКПП) буде заархівовано") % previous.name,
                          "level": "warn"})
            lines.append({"text": _("Створиться нова картка працівника «%s», пов'язана з попередньою") % self.name,
                          "level": "info"})
        elif previous:
            lines.append({"text": _("Створиться картка працівника «%s», пов'язана з попередньою архівною карткою «%s»")
                          % (self.name, previous.name), "level": "info"})
        else:
            lines.append({"text": _("Створиться картка працівника «%s»") % self.name, "level": "info"})

        lines.append({"text": _("Наказ про прийняття буде проведено і отримає номер з реєстру «%s»")
                      % self._hire_register_label(), "level": "info"})
        lines.append({"text": _("На підпис буде створено документів: %s") % self._hire_to_sign_count(), "level": "info"})

        if self.date_from:
            existing_run = self._j30_existing_run()
            period = self.date_from.strftime("%m.%Y")
            deadline = self.date_from - timedelta(days=1)
            today = fields.Date.context_today(self)
            verb = _("поповниться цим прийняттям") if existing_run else _("буде створено")
            if self.date_from <= today:
                lines.append({"text": _("Подання J3001005 за %(period)s %(verb)s; строк подання (%(deadline)s) уже минув")
                              % {"period": period, "verb": verb, "deadline": deadline.strftime("%d.%m.%Y")},
                              "level": "warn"})
            else:
                lines.append({"text": _("Подання J3001005 за %(period)s %(verb)s; подати до %(deadline)s")
                              % {"period": period, "verb": verb, "deadline": deadline.strftime("%d.%m.%Y")},
                              "level": "info"})

        if self.mil_status in LIABLE_STATUSES:
            existing_notice = self._existing_notice()
            if existing_notice:
                lines.append({"text": _("Повідомлення ТЦК «%s» поповниться цим прийняттям") % existing_notice.name,
                              "level": "info"})
            else:
                d1, d2 = self._notice_window()
                lines.append({"text": _("Створиться повідомлення ТЦК на тиждень %(d1)s - %(d2)s")
                              % {"d1": d1.strftime("%d.%m.%Y"), "d2": d2.strftime("%d.%m.%Y")},
                              "level": "info"})
        return lines

    # ------------------------------------------------------------------ прийняття
    def action_hire(self):
        self.ensure_one()
        if self.stage != "onboarding":
            raise UserError(_("Прийняти можна лише справу на етапі оформлення."))
        errors = [c for c in self._checks() if c["level"] == "error"]
        if errors:
            raise UserError(_("Спершу виправте: %s") % "; ".join(c["title"] for c in errors))

        emp_vals = {
            "name": self.name, "company_id": self.company_id.id, "date_version": self.date_from,
            "ua_last_name": self.last_name, "ua_first_name": self.first_name, "ua_middle_name": self.middle_name,
            "birthday": self.birthday, "sex": self.sex, "ua_rnokpp": self.rnokpp,
            "ua_id_doc_type": self.id_doc_type, "ua_id_doc_series": self.id_doc_series, "ua_id_doc_number": self.id_doc_number,
            "ua_id_doc_unzr": self.id_doc_unzr, "ua_id_doc_issued_by": self.id_doc_issued_by, "ua_id_doc_date": self.id_doc_date,
            "private_street": self.reg_address, "ua_actual_address": self.actual_address,
            "private_phone": self.phone, "private_email": self.email,
            "department_id": self.department_id.id, "job_title": self.job_title,
            "ua_diploma_number": self.diploma_number, "ua_education_year": self.education_year,
            "ua_labor_book_number": self.labor_book_number, "ua_electronic_labor_book": self.electronic_labor_book,
            "ua_mil_status": self.mil_status or "none", "ua_mil_category": self.mil_category, "ua_mil_rank": self.mil_rank,
            "ua_mil_vos": self.mil_vos, "ua_mil_tcc": self.mil_tcc, "ua_mil_doc_type": self.mil_doc_type,
            "ua_mil_doc_series": self.mil_doc_series, "ua_mil_doc_number": self.mil_doc_number,
            "ua_mil_doc_date": self.mil_doc_date, "ua_mil_fitness": self.mil_fitness,
            "ua_reserve_number": self.mil_reserve_number, "ua_reserve_date": self.mil_reserve_date,
            "ua_reserve_filename": self.mil_reserve_filename, "ua_reserve_file": self.mil_reserve_file,
        }
        # Повторне прийняття = нова картка, не відновлення старої: якщо з цим РНОКПП уже є звільнений
        # (архівний) працівник, або чинний зі звільненням у даних (нештатна ситуація) - стара картка
        # лишається архівною, нова отримує на неї посилання «Попередня картка».
        previous = self._rehire_previous()
        archived_previous = bool(previous and previous.active)
        if previous:
            emp_vals["ua_previous_employee_id"] = previous.id
        employee = self.env["hr.employee"].sudo().create(emp_vals)
        if archived_previous:
            previous.sudo().active = False

        # Наслідки (docs/payroll/action-model.md): те саме, що action_hire_plan() вище обіцяла,
        # тепер у минулому часі, з посиланням на щойно створений чи змінений запис.
        done = []
        if archived_previous:
            done.append({"text": _("Попередню картку «%s» заархівовано") % previous.name,
                        "target": {"model": "hr.employee", "res_id": previous.id}})
        if previous:
            done.append({"text": _("Створено картку працівника «%s», пов'язану з попередньою") % employee.name,
                        "target": {"model": "hr.employee", "res_id": employee.id}})
        else:
            done.append({"text": _("Створено картку працівника «%s»") % employee.name,
                        "target": {"model": "hr.employee", "res_id": employee.id}})

        Doc = self.env["ua.employee.document"].sudo()
        doc_types = dict(Doc._fields["type"]._description_selection(self.env))
        for f in self.file_ids.filtered("file"):
            Doc.create({"employee_id": employee.id, "type": f.doc_type if f.doc_type in doc_types else "other",
                        "name": f.name, "file": f.file, "filename": f.filename or f.name})

        # Пакет першого дня (документи на підпис): усі ключі PACKAGE, крім "order" - проєкт наказу
        # друкується лише до прийняття; після прийняття документ наказу веде вже проведений наказ
        # (створює l10n_ua_card_ui, коли order.action_post() спрацює нижче). Знята в пакеті позначка
        # (package_skip) переводить документ у "не потрібен" замість "на підпис".
        skip = set((self.package_skip or "").split(","))
        for key, label, report in PACKAGE:
            if key == "order":
                continue
            Doc.create({
                "employee_id": employee.id, "type": key, "name": label,
                "state": "not_needed" if key in skip else "to_sign",
                "report_xmlid": report, "res_model": "ua.hire.case", "res_id": self.id,
            })

        order = self.env["ua.hr.order"].sudo().create({
            "order_type": "hire", "employee_id": employee.id, "company_id": self.company_id.id,
            "date": min(fields.Date.context_today(self), self.date_from), "date_from": self.date_from,
            "department_id": self.department_id.id, "job_title": self.job_title, "wage": self.wage,
            "fte": self.fte, "contract_kind": self.contract_kind, "main_job": self.main_job,
            "kp_code": self.kp_code, "trial_date_end": self.trial_date_end,
            "pay_advance_percent": self.pay_advance_percent, "pay_advance_day": self.pay_advance_day,
            "pay_final_day": self.pay_final_day,
            "basis": _("Заява %s") % self.name,
        })
        order.action_post()
        if "order" in skip:
            # Документ наказу сам створює l10n_ua_card_ui на action_post (гачок на ua.hr.order,
            # спільний для всіх видів наказу); тут лише знімаємо позначку, якщо в пакеті її прибрали.
            order_doc = Doc.search([("res_model", "=", "ua.hr.order"), ("res_id", "=", order.id),
                                    ("type", "=", "order")], limit=1)
            if order_doc:
                order_doc.state = "not_needed"
        done.append({"text": _("Наказ № %(num)s проведено (реєстр «%(reg)s»)")
                    % {"num": order.name, "reg": dict(REGISTERS).get(order.register, order.register)},
                    "target": {"model": "ua.hr.order", "res_id": order.id}})
        to_sign_count = Doc.search_count([("employee_id", "=", employee.id), ("state", "=", "to_sign")])
        done.append({"text": _("Створено документів на підпис: %s") % to_sign_count,
                    "target": {"model": "hr.employee", "res_id": employee.id}})

        existing_run = self._j30_existing_run()
        run = self.env["ua.report.run"].sudo()._find_or_create("j30", self.company_id, self.date_from.year, month=self.date_from.month)
        if run.state == "draft":
            run.action_refresh()
        if existing_run:
            j30_text = _("Подання J3001005 «%s» поповнено цим прийняттям") % run.name
        else:
            j30_text = _("Створено подання J3001005 «%s»") % run.name
        done.append({"text": j30_text, "target": {"model": "ua.report.run", "res_id": run.id}})

        notice = self.env["ua.military.notice"]
        if employee.ua_mil_status in LIABLE_STATUSES:
            Notice = self.env["ua.military.notice"].sudo()
            existing_notice = self._existing_notice()
            notice = existing_notice or Notice.create({"company_id": self.company_id.id, "date_from": self.date_from,
                                                        "date_to": self.date_from + timedelta(days=6)})
            notice.action_refill()
            if existing_notice:
                notice_text = _("Повідомлення ТЦК «%s» поповнено цим прийняттям") % notice.name
            else:
                notice_text = _("Створено повідомлення ТЦК «%s»") % notice.name
            done.append({"text": notice_text, "target": {"model": "ua.military.notice", "res_id": notice.id}})

        self.write({"stage": "hired", "employee_id": employee.id, "order_id": order.id, "j30_run_id": run.id,
                    "notice_id": notice.id or False, "hired_date": fields.Date.context_today(self)})
        self.message_post(body=_("Прийнято: картка %(e)s, наказ № %(o)s.") % {"e": employee.name, "o": order.name})
        return {"done": done}
