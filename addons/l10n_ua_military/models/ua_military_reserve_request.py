# -*- coding: utf-8 -*-
"""Заявка на бронювання: кого подаємо через Дію, чи вистачає даних і квоти, що вирішили.

Кандидати - військовозобов'язані за трудовим договором, які не заброньовані або чиє бронювання
закінчується протягом заданої кількості днів (продовження). По кожному рядку видно, чого не
вистачає для заявки: РНОКПП, дата народження, номер військово-облікового документа - без них
заявку не приймуть, тому подати не можна. Оклад нижче межі статусу і давня звірка з ТЦК -
попередження. Квота: ті, чиє бронювання лишається чинним, плюс нові рядки заявки не більше квоти.

Перелік вивантажується у CSV як робочий список для заповнення заявки в Дії: склад полів звіряйте
з чинною формою (постанова КМУ № 76 від 27.01.2023 і її зміни). Рішення по кожному рядку
(заброньовано до дати або відмовлено) записується в заявку і переноситься на картки працівників.
"""
import csv
import io
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .hr_employee import DOC_TYPE
from .ua_military_critical import NOT_EMPLOYMENT, QUOTA_STATUSES

STATES = [("draft", "Чернетка"), ("submitted", "Подано"), ("done", "Рішення внесено")]
PURPOSES = [("new", "Нове бронювання"), ("prolong", "Продовження")]
RESULTS = [("pending", "Чекає рішення"), ("approved", "Заброньовано"), ("refused", "Відмовлено")]
CSV_HEADER = ["№", "РНОКПП", "Прізвище", "Ім'я", "По батькові", "Дата народження",
              "Вид військово-облікового документа", "Серія", "Номер", "Посада", "Підстава"]


def _d(day):
    return day.strftime("%d.%m.%Y") if day else ""


class UaMilitaryReserveRequest(models.Model):
    _name = "ua.military.reserve.request"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Заявка на бронювання"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True,
                                 index=True)
    date = fields.Date("Дата заявки", default=fields.Date.context_today, required=True, tracking=True)
    horizon_days = fields.Integer("Продовжувати, якщо бронювання закінчується протягом, днів", default=30)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    critical_id = fields.Many2one("ua.military.critical", "Статус критично важливого", readonly=True)
    liable_count = fields.Integer("Військовозобов'язаних", readonly=True)
    quota = fields.Integer("Квота бронювання", readonly=True)
    kept_count = fields.Integer("Бронювання лишається чинним", readonly=True,
                                help="Заброньовані, яких ця заявка не стосується.")
    wage_floor = fields.Float("Нижня межа окладу", readonly=True)
    submitted_date = fields.Date("Подано в Дії", tracking=True)
    decision_ref = fields.Char("Рішення (номер, дата)", tracking=True,
                               help="Переноситься на картку як підстава бронювання.")
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.military.reserve.request.line", "request_id", "Кандидати", copy=False)
    included_count = fields.Integer("У заявці", compute="_compute_counts")
    blocked_count = fields.Integer("Без потрібних даних", compute="_compute_counts")

    @api.depends("date")
    def _compute_name(self):
        for doc in self:
            doc.name = _("Заявка на бронювання від %s") % _d(doc.date)

    @api.depends("line_ids.include", "line_ids.blocking")
    def _compute_counts(self):
        for doc in self:
            lines = doc.line_ids.filtered("include")
            doc.included_count = len(lines)
            doc.blocked_count = len(lines.filtered("blocking"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError(_("Видалити можна лише чернетку заявки."))

    # ------------------------------------------------------------------ заповнення
    def _candidates(self):
        """Військовозобов'язані за трудовим договором: не заброньовані або бронювання скоро скінчиться."""
        self.ensure_one()
        edge = self.date + timedelta(days=max(self.horizon_days, 0))
        base = self.env["hr.employee"].sudo().search([
            ("company_id", "=", self.company_id.id), ("ua_mil_status", "in", QUOTA_STATUSES),
            ("ua_contract_kind", "not in", NOT_EMPLOYMENT)], order="name")
        return base.filtered(lambda e: not e._ua_is_reserved(self.date)
                             or (e.ua_mil_reserve_until and e.ua_mil_reserve_until <= edge))

    def action_fill(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            doc.line_ids.unlink()
            doc._fill_status()
            vals = []
            for employee in doc._candidates():
                last, first, middle = employee._ua_name_parts()
                reserved = employee._ua_is_reserved(doc.date)
                vals.append({
                    "employee_id": employee.id, "last_name": last, "first_name": first, "middle_name": middle,
                    "rnokpp": employee.ua_rnokpp or "", "birthday": employee.birthday,
                    "doc_type": employee.ua_mil_doc_type, "doc_series": employee.ua_mil_doc_series or "",
                    "doc_number": employee.ua_mil_doc_number or "", "tcc": employee.ua_mil_tcc or "",
                    "job_title": employee.job_title or employee.job_id.name or "",
                    "wage": employee.current_version_id.wage or 0.0,
                    "purpose": "prolong" if reserved else "new",
                    "current_until": employee.ua_mil_reserve_until if reserved else False,
                    "needs_check": employee.ua_mil_needs_check,
                })
            doc.line_ids = [(0, 0, v) for v in vals]
        return True

    def _fill_status(self):
        self.ensure_one()
        status = self.env["ua.military.critical"].sudo()._current(self.company_id, self.date)
        Employee = self.env["hr.employee"]
        base = Employee._ua_quota_base(self.company_id)
        edge = self.date + timedelta(days=max(self.horizon_days, 0))
        kept = base.filtered(lambda e: e._ua_is_reserved(self.date)
                             and not (e.ua_mil_reserve_until and e.ua_mil_reserve_until <= edge))
        self.write({
            "critical_id": status.id, "liable_count": len(base), "kept_count": len(kept),
            "quota": status.quota_counts(self.date)["quota"] if status else 0,
            "wage_floor": status.wage_floor(self.date) if status else 0.0,
        })

    # ------------------------------------------------------------------ подання і рішення
    def action_submit(self):
        for doc in self:
            problems = [row["text"] for row in doc._checks() if row["level"] == "error"]
            if problems:
                raise UserError(_("Заявку не можна подати:\n%s") % "\n".join("- " + p for p in problems))
            doc.write({"state": "submitted", "submitted_date": doc.submitted_date or fields.Date.context_today(doc)})
        return True

    def action_apply(self):
        """Рішення з заявки - на картки працівників і в події обліку."""
        Event = self.env["ua.military.event"].sudo()
        for doc in self:
            if doc.state != "submitted":
                raise UserError(_("Рішення вносять у подану заявку."))
            lines = doc.line_ids.filtered("include")
            if lines.filtered(lambda l: l.result == "pending"):
                raise UserError(_("Вкажіть рішення по кожному рядку заявки."))
            missing = lines.filtered(lambda l: l.result == "approved" and not l.decision_until)
            if missing:
                raise UserError(_("Вкажіть, до якої дати заброньовано: %s") % ", ".join(missing.mapped("full_name")))
            basis = doc.decision_ref or doc.name
            for line in lines:
                employee = line.employee_id.sudo()
                if line.result == "approved":
                    employee.write({"ua_mil_reserved": True, "ua_mil_reserve_until": line.decision_until,
                                    "ua_mil_reserve_order": basis})
                    note = _("Заброньовано до %(date)s (%(basis)s)", date=_d(line.decision_until), basis=basis)
                else:
                    note = _("Відмовлено у бронюванні (%s)") % basis
                Event.create({"employee_id": employee.id, "date": fields.Date.context_today(doc),
                              "kind": "reserve", "note": note})
            doc.state = "done"
        return True

    def action_draft(self):
        for doc in self:
            if doc.state == "done":
                raise UserError(_("Рішення вже перенесено на картки: виправляйте картки працівників."))
        self.write({"state": "draft"})
        return True

    # ------------------------------------------------------------------ вивантаження
    def ua_csv(self):
        """CSV для заповнення заявки: лише включені рядки, у порядку переліку."""
        self.ensure_one()
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(CSV_HEADER)
        kinds = dict(DOC_TYPE)
        purposes = dict(PURPOSES)
        for n, line in enumerate(self.line_ids.filtered("include"), 1):
            writer.writerow([n, line.rnokpp, line.last_name, line.first_name, line.middle_name, _d(line.birthday),
                             kinds.get(line.doc_type, ""), line.doc_series, line.doc_number, line.job_title,
                             purposes.get(line.purpose, "")])
        return buffer.getvalue()

    def action_export_csv(self):
        self.ensure_one()
        data = ("﻿" + self.ua_csv()).encode("utf-8")
        attachment = self.env["ir.attachment"].create({
            "name": "bronyuvannia_%s.csv" % self.date.strftime("%Y-%m-%d"), "raw": data,
            "mimetype": "text/csv", "res_model": self._name, "res_id": self.id})
        return {"type": "ir.actions.act_url", "url": "/web/content/%s?download=true" % attachment.id,
                "target": "self"}

    def action_print(self):
        return self.env.ref("l10n_ua_military.action_report_ua_military_reserve_request").report_action(self)

    def ua_date(self, day):
        return _d(day)

    def ua_doc_label(self, line):
        return dict(DOC_TYPE).get(line.doc_type, "")

    def ua_purpose_label(self, line):
        return dict(PURPOSES).get(line.purpose, "")

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        lines = self.line_ids.filtered("include")
        if not lines:
            out.append(self._check_error(_("У заявці немає кандидатів"), fact=0))
            return out
        status = self.critical_id
        if not status:
            out.append(self._check_error(_("Немає чинного статусу критично важливого підприємства на дату заявки"),
                                         fact=_d(self.date),
                                         target={"model": "ua.military.critical",
                                                 "domain": [("company_id", "=", self.company_id.id)]}))
        else:
            total = self.kept_count + len(lines)
            fact = _("%(total)s з %(quota)s (чинних %(kept)s, у заявці %(new)s)", total=total, quota=self.quota,
                     kept=self.kept_count, new=len(lines))
            if total > self.quota:
                out.append(self._check_error(_("Заявка більша, ніж дозволяє квота"), fact=fact,
                                             target=self._target_record(status)))
            else:
                out.append(self._check_ok(_("Квота бронювання"), fact=fact))
        blocked = lines.filtered("blocking")
        if blocked:
            out.append(self._check_error(_("Не вистачає даних для заявки"), fact=len(blocked),
                                         target=self._target_records(blocked.employee_id, "hr.employee")))
        else:
            out.append(self._check_ok(_("Дані кандидатів повні"), fact=len(lines)))
        if self.wage_floor:
            low = lines.filtered(lambda l: l.wage < self.wage_floor)
            if low:
                out.append(self._check_warn(_("Оклад нижчий за межу статусу"),
                                            fact="%s, межа %.2f" % (len(low), self.wage_floor),
                                            target=self._target_records(low.employee_id, "hr.employee")))
        stale = lines.filtered("needs_check")
        if stale:
            out.append(self._check_warn(_("Дані обліку давно не звіряли з ТЦК"), fact=len(stale),
                                        target=self._target_records(stale.employee_id, "hr.employee")))
        return out


class UaMilitaryReserveRequestLine(models.Model):
    _name = "ua.military.reserve.request.line"
    _description = "Кандидат на бронювання"
    _order = "last_name, first_name, id"

    request_id = fields.Many2one("ua.military.reserve.request", required=True, index=True, ondelete="cascade")
    state = fields.Selection(related="request_id.state")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    include = fields.Boolean("У заявці", default=True)
    purpose = fields.Selection(PURPOSES, "Мета", required=True, default="new")
    last_name = fields.Char("Прізвище")
    first_name = fields.Char("Ім'я")
    middle_name = fields.Char("По батькові")
    full_name = fields.Char("ПІБ", compute="_compute_full_name")
    rnokpp = fields.Char("РНОКПП")
    birthday = fields.Date("Дата народження")
    doc_type = fields.Selection(DOC_TYPE, "Вид документа")
    doc_series = fields.Char("Серія")
    doc_number = fields.Char("Номер документа")
    tcc = fields.Char("ТЦК та СП")
    job_title = fields.Char("Посада")
    wage = fields.Float("Оклад")
    current_until = fields.Date("Чинне бронювання до")
    needs_check = fields.Boolean("Потребує звірки")
    problems = fields.Char("Чого не вистачає", compute="_compute_problems")
    blocking = fields.Boolean("Не можна подати", compute="_compute_problems")
    result = fields.Selection(RESULTS, "Рішення", default="pending", required=True)
    decision_until = fields.Date("Заброньовано до")

    @api.depends("last_name", "first_name", "middle_name")
    def _compute_full_name(self):
        for line in self:
            line.full_name = " ".join(p for p in (line.last_name, line.first_name, line.middle_name) if p)

    @api.depends("rnokpp", "birthday", "doc_number", "wage", "request_id.wage_floor", "needs_check")
    def _compute_problems(self):
        for line in self:
            missing = []
            if not line.rnokpp:
                missing.append(_("РНОКПП"))
            if not line.birthday:
                missing.append(_("дата народження"))
            if not line.doc_number:
                missing.append(_("номер військового документа"))
            warnings = []
            floor = line.request_id.wage_floor
            if floor and line.wage < floor:
                warnings.append(_("оклад нижче межі"))
            if line.needs_check:
                warnings.append(_("давня звірка з ТЦК"))
            line.blocking = bool(missing)
            line.problems = "; ".join(missing + warnings)
