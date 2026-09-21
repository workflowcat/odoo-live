# -*- coding: utf-8 -*-
"""Дані екрана «Прийняття»: розширення ua.hire.case самими формувальниками.

Бізнес-логіка справи лишилась у l10n_ua_hire. Тут - лише те, що надає форму
одному екранові: перелік справ зліва, картка обраної справи, наслідки прийняття
і «інші файли». Жоден із цих методів нічого не пише і нічого не вирішує - вони
складають словник для hire.js. Правила, перевірки, пакет документів і сама дія
прийняття лишились у моделі логіки і працюють без цього модуля.
"""
import re
from datetime import timedelta

from odoo import _, api, fields, models

from odoo.addons.l10n_ua_hire.models.ua_hire_case import SECTIONS, STAGES


class UaHireCase(models.Model):
    _inherit = "ua.hire.case"

    # ------------------------------------------------------------------ дані для екрана
    def _other_files(self):
        """Файли справи, що не підпадають під жодну вимогу пакета (docs/payroll/spec-intake.md):
        package_used_file_ids рахує це так само, як рядки employee-блоку package_for - файл,
        що покриває вимогу разом з іншим (паспорт + РНОКПП), не "інший", навіть якщо в рядку
        ціль веде на інший файл із тієї самої пари."""
        self.ensure_one()
        used_ids = self.env["ua.hr.doc.requirement"].package_used_file_ids(self)
        return [
            {"name": f.name, "doc_type": f.doc_type, "target": {"model": "ua.hire.file", "res_id": f.id}}
            for f in self.file_ids if f.id not in used_ids
        ]

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
        # package_split - пакет за формою зі спеки (docs/payroll/spec-intake.md), спільний метод
        # ua.hr.doc.requirement.package_for, яким користується і картка працівника. Ключі
        # requirements/package/checks лишаються - екран переходить на package_split окремим
        # комітом, щоб не поламати його між двома комітами.
        package_split = self.env["ua.hr.doc.requirement"].package_for(case=self)
        return {
            "id": self.id, "name": self.name, "stage": self.stage,
            "stage_label": dict(STAGES)[self.stage], "decline_reason": self.decline_reason or "",
            "values": {f: self._value_for_screen(f) for _k, _t, names in SECTIONS for f in names},
            "states": states, "proposals": proposals, "sections": sections,
            "files": [{"id": x.id, "name": x.name, "doc_type": x.doc_type, "extract_state": x.extract_state,
                       "extract_note": x.extract_note or ""} for x in self.file_ids],
            "requirements": self._requirements(),
            "package_split": package_split,
            "other_files": self._other_files(),
            "checks": checks,
            "can_hire": self.stage == "onboarding" and not any(c["level"] == "error" for c in checks),
            "military_required": self._military_required(),
            "mil_reserve_filename": self.mil_reserve_filename or "",
            "mil_reserve_has_file": bool(self.mil_reserve_file),
            "results": self._results(),
            "package": self._package(),
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
        selected = cases.filtered(lambda c: c.id == case_id) if case_id else self.browse()  # лише зі своїх компаній
        if not selected and rows:
            first = next((r for r in rows if r["stage"] in ("candidate", "onboarding")), rows[0])
            selected = self.browse(first["id"])
        return {
            "cases": rows,
            "stages": [{"key": k, "label": v} for k, v in STAGES],
            "meta": self._field_meta(selected),
            "departments": [[d.id, d.display_name] for d in self.env["hr.department"].search([("company_id", "in", [False] + self.env.companies.ids)])],
            "doc_types": [[k, v] for k, v in self.env["ua.hire.file"]._fields["doc_type"]._description_selection(self.env)],
            "case": selected._case_payload() if selected else None,
        }
