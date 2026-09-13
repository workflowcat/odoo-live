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
from odoo.addons.l10n_ua_hr_orders.models.ua_hr_order import CONTRACT_KIND, FTE
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
                                      "mil_doc_type", "mil_doc_series", "mil_doc_number", "mil_doc_date", "mil_fitness"]),
    ("terms", "Умови", ["date_from", "wage", "fte", "contract_kind", "main_job", "kp_code", "trial_date_end"]),
]
# Поля, які можна взяти з документів. Умови роботи документи кандидата не містять.
EXTRACTABLE = [f for key, _t, names in SECTIONS if key in ("candidate", "identity", "education", "military")
               for f in names if f not in ("job_title", "department_id", "expected_wage", "source", "interview_date",
                                          "pd_consent", "screening_note")]

DIGITS_ONLY = ("rnokpp", "id_doc_unzr")
EXTRACT_URL = os.environ.get("UA_EXTRACT_URL", "http://host.docker.internal:8765")


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
    mil_category = fields.Selection([("officers", "Офіцери"), ("sergeants", "Сержанти і старшини"),
                                     ("soldiers", "Солдати і матроси")], "Категорія обліку")
    mil_rank = fields.Char("Військове звання")
    mil_vos = fields.Char("ВОС")
    mil_tcc = fields.Char("ТЦК та СП")
    mil_doc_type = fields.Selection(MIL_DOC_TYPE, "Військовий документ")
    mil_doc_series = fields.Char("Серія військового документа")
    mil_doc_number = fields.Char("Номер військового документа")
    mil_doc_date = fields.Date("Дата видачі військового документа")
    mil_fitness = fields.Selection(FITNESS, "Придатність")

    # умови
    date_from = fields.Date("Перший робочий день", tracking=True)
    wage = fields.Monetary("Оклад", currency_field="currency_id", tracking=True)
    fte = fields.Selection(FTE, "Ставка", default="1")
    contract_kind = fields.Selection(CONTRACT_KIND, "Вид відносин", default="employment")
    main_job = fields.Boolean("Основне місце роботи", default=True)
    kp_code = fields.Char("Код КП")
    trial_date_end = fields.Date("Випробувальний строк до")

    file_ids = fields.One2many("ua.hire.file", "case_id", "Файли")
    proposal_ids = fields.One2many("ua.hire.proposal", "case_id", "Пропозиції")

    # результат
    employee_id = fields.Many2one("hr.employee", "Працівник", readonly=True, copy=False)
    order_id = fields.Many2one("ua.hr.order", "Наказ", readonly=True, copy=False)
    j30_run_id = fields.Many2one("ua.report.run", "J3001005", readonly=True, copy=False)
    notice_id = fields.Many2one("ua.military.notice", "Повідомлення ТЦК", readonly=True, copy=False)
    hired_date = fields.Date("Прийнято", readonly=True, copy=False)

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
        self.ensure_one()
        need = {"last_name", "first_name", "job_title"}
        if self.stage == "candidate":
            return need
        need |= {"birthday", "sex", "rnokpp", "id_doc_type", "id_doc_number", "id_doc_issued_by", "id_doc_date",
                 "reg_address", "date_from", "wage", "department_id", "pd_consent"}
        if self.id_doc_type == "passport_book":
            need.add("id_doc_series")
        if self.id_doc_type == "id_card":
            need.add("id_doc_unzr")
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

    # ------------------------------------------------------------------ дані для екрана
    @api.model
    def _field_meta(self):
        meta = {}
        for key, title, names in SECTIONS:
            for f in names:
                fld = self._fields[f]
                item = {"name": f, "label": fld.string, "type": fld.type, "section": key}
                if fld.type == "selection":
                    item["options"] = [[k, v] for k, v in fld._description_selection(self.env)]
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

    def _case_payload(self):
        self.ensure_one()
        states = self._field_states()
        proposals = {}
        for p in self.proposal_ids.filtered(lambda p: p.state == "pending"):
            proposals.setdefault(p.field_name, []).append({
                "id": p.id, "value": p.value, "display": p._display_value(), "file": p.file_id.name or "",
                "quote": p.quote or "", "confidence": p.confidence, "conflict": bool(self[p.field_name]),
            })
        sections = []
        for key, title, names in SECTIONS:
            missing = sum(1 for f in names if states[f] == "missing")
            proposed = sum(1 for f in names if states[f] == "proposed")
            sections.append({"key": key, "title": title, "fields": names, "missing": missing, "proposed": proposed})
        checks = self._checks()
        return {
            "id": self.id, "name": self.name, "stage": self.stage,
            "stage_label": dict(STAGES)[self.stage], "decline_reason": self.decline_reason or "",
            "values": {f: self._value_for_screen(f) for _k, _t, names in SECTIONS for f in names},
            "states": states, "proposals": proposals, "sections": sections,
            "files": [{"id": x.id, "name": x.name, "doc_type": x.doc_type, "extract_state": x.extract_state,
                       "extract_note": x.extract_note or ""} for x in self.file_ids],
            "requirements": self._requirements(),
            "checks": checks,
            "can_hire": self.stage == "onboarding" and not any(c["level"] == "error" for c in checks),
            "military_required": self._military_required(),
            "results": self._results(),
            "log": [{"date": m.date.strftime("%d.%m.%Y %H:%M"), "author": m.author_id.name or "",
                     "body": re.sub(r"<[^>]+>", " ", m.body or "").strip()}
                    for m in self.message_ids.filtered(lambda m: m.body)[:8]],
        }

    def _results(self):
        self.ensure_one()
        out = []
        if self.employee_id:
            out.append({"key": "employee", "label": _("Картка працівника"), "detail": self.employee_id.name,
                        "model": "hr.employee", "res_id": self.employee_id.id})
        if self.order_id:
            out.append({"key": "order", "label": _("Наказ про прийняття"), "detail": "№ %s" % (self.order_id.name or "-"),
                        "model": "ua.hr.order", "res_id": self.order_id.id,
                        "print": {"r": "l10n_ua_hr_orders.report_ua_hr_order", "ids": [self.order_id.id],
                                  "t": _("Наказ № %s") % (self.order_id.name or "")}})
        if self.j30_run_id:
            out.append({"key": "j30", "label": _("Повідомлення до ДПС J3001005"),
                        "detail": dict(self.j30_run_id._fields["state"]._description_selection(self.env)).get(self.j30_run_id.state, ""),
                        "run_id": self.j30_run_id.id})
        if self.notice_id:
            out.append({"key": "notice", "label": _("Повідомлення ТЦК"), "detail": self.notice_id.name,
                        "model": "ua.military.notice", "res_id": self.notice_id.id})
        return out

    @api.model
    def get_screen_data(self, case_id=None):
        cases = self.search([("company_id", "in", self.env.companies.ids)])
        today = fields.Date.context_today(self)
        rows = []
        for c in cases:
            if c.stage == "hired" and c.hired_date and c.hired_date < today - timedelta(days=60):
                continue
            states = c._field_states()
            rows.append({"id": c.id, "name": c.name, "stage": c.stage, "job_title": c.job_title or "",
                         "date_from": c.date_from.strftime("%d.%m") if c.date_from else "",
                         "missing": sum(1 for s in states.values() if s == "missing"),
                         "proposed": sum(1 for s in states.values() if s == "proposed")})
        selected = self.browse(case_id).exists() if case_id else self.browse()
        if not selected and rows:
            first = next((r for r in rows if r["stage"] in ("candidate", "onboarding")), rows[0])
            selected = self.browse(first["id"])
        return {
            "cases": rows,
            "stages": [{"key": k, "label": v} for k, v in STAGES],
            "meta": self._field_meta(),
            "departments": [[d.id, d.display_name] for d in self.env["hr.department"].search([("company_id", "in", [False] + self.env.companies.ids)])],
            "doc_types": [[k, v] for k, v in self.env["ua.hire.file"]._fields["doc_type"]._description_selection(self.env)],
            "case": selected._case_payload() if selected else None,
        }

    # ------------------------------------------------------------------ дії з екрана
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

    # ------------------------------------------------------------------ розпізнавання
    @api.model
    def extract_status(self):
        try:
            r = requests.get(EXTRACT_URL + "/health", timeout=1.5)
            return r.json() if r.ok else {"ok": False, "error": "HTTP %s" % r.status_code}
        except Exception as e:  # noqa: BLE001 - будь-яка мережева помилка означає «помічник недоступний»
            return {"ok": False, "error": str(e)[:200]}

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
            resp = requests.post(EXTRACT_URL + "/extract", data=json.dumps(payload), timeout=600,
                                 headers={"Content-Type": "application/json"})
            result = resp.json()
        except Exception as e:  # noqa: BLE001
            files.write({"extract_state": "failed", "extract_note": str(e)[:200]})
            raise UserError(_("Помічник розпізнавання недоступний. Запустіть scripts/claude_extract_helper.py на цьому комп'ютері.\n%s") % str(e)[:200])
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
        }
        employee = self.env["hr.employee"].sudo().create(emp_vals)

        Doc = self.env["ua.employee.document"].sudo()
        doc_types = dict(Doc._fields["type"]._description_selection(self.env))
        for f in self.file_ids.filtered("file"):
            Doc.create({"employee_id": employee.id, "type": f.doc_type if f.doc_type in doc_types else "other",
                        "name": f.name, "file": f.file, "filename": f.filename or f.name})

        order = self.env["ua.hr.order"].sudo().create({
            "order_type": "hire", "employee_id": employee.id, "company_id": self.company_id.id,
            "date": min(fields.Date.context_today(self), self.date_from), "date_from": self.date_from,
            "department_id": self.department_id.id, "job_title": self.job_title, "wage": self.wage,
            "fte": self.fte, "contract_kind": self.contract_kind, "main_job": self.main_job,
            "kp_code": self.kp_code, "trial_date_end": self.trial_date_end,
            "basis": _("Заява %s") % self.name,
        })
        order.action_post()

        run = self.env["ua.report.run"].sudo()._find_or_create("j30", self.company_id, self.date_from.year, month=self.date_from.month)
        if run.state == "draft":
            run.action_refresh()

        notice = self.env["ua.military.notice"]
        if employee.ua_mil_status in LIABLE_STATUSES:
            Notice = self.env["ua.military.notice"].sudo()
            notice = Notice.search([("company_id", "=", self.company_id.id), ("state", "=", "draft"),
                                    ("date_from", "<=", self.date_from), ("date_to", ">=", self.date_from)], limit=1)
            if not notice:
                notice = Notice.create({"company_id": self.company_id.id, "date_from": self.date_from,
                                        "date_to": self.date_from + timedelta(days=6)})
            notice.action_refill()

        self.write({"stage": "hired", "employee_id": employee.id, "order_id": order.id, "j30_run_id": run.id,
                    "notice_id": notice.id or False, "hired_date": fields.Date.context_today(self)})
        self.message_post(body=_("Прийнято: картка %(e)s, наказ № %(o)s.") % {"e": employee.name, "o": order.name})
        return True
