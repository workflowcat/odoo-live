# -*- coding: utf-8 -*-
"""Повідомлення про зміну облікових даних за період: прийняті, звільнені і ті, у кого є подія «зміна даних»,
серед працівників, що підлягають військовому обліку. Відповідає обов'язку повідомляти ТЦК протягом 7 днів."""
from datetime import date as date_type, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .hr_employee import LIABLE_STATUSES

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]
CHANGE_KIND = [("hire", "Прийняття"), ("dismiss", "Звільнення"), ("change", "Зміна даних")]


class UaMilitaryNotice(models.Model):
    _name = "ua.military.notice"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Повідомлення про зміну облікових даних"
    _order = "date_to desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    date_from = fields.Date("Період з", required=True, tracking=True)
    date_to = fields.Date("Період по", required=True, tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.military.notice.line", "notice_id", "Рядки")

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for doc in self:
            d1 = doc.date_from.strftime("%d.%m.%Y") if doc.date_from else ""
            d2 = doc.date_to.strftime("%d.%m.%Y") if doc.date_to else ""
            doc.name = "Повідомлення ТЦК %s - %s" % (d1, d2)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку повідомлення.")

    @api.model
    def ua_compose(self, company, year=None, month=None, date_from=None, date_to=None, **params):
        """Нове повідомлення ТЦК за період, одразу заповнене.

        Межі періоду - явні, якщо їх передали, інакше весь місяць."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        if not (date_from and date_to):
            today = fields.Date.context_today(self)
            year, month = int(year or today.year), int(month or today.month)
            date_from = date_type(year, month, 1)
            date_to = date_type(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        doc = self.create({"company_id": company.id, "date_from": date_from, "date_to": date_to})
        doc.action_refill()
        return doc

    def action_compose_month(self):
        """Кнопка списку «Створити за місяць»: повідомлення за поточний місяць."""
        today = fields.Date.context_today(self)
        doc = self.ua_compose(self.env.company, today.year, today.month)
        return {"type": "ir.actions.act_window", "name": doc.name, "res_model": "ua.military.notice",
                "view_mode": "form", "res_id": doc.id, "target": "current"}

    def action_refill(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            employees = self.env["hr.employee"].sudo().search([
                ("company_id", "=", doc.company_id.id), ("ua_mil_status", "in", list(LIABLE_STATUSES)),
                ("ua_contract_kind", "not in", ["gph", "fop"])])
            rows = []
            if employees:
                versions = self.env["hr.version"].sudo().search([
                    ("employee_id", "in", employees.ids),
                    "|",
                    "&", ("contract_date_start", ">=", doc.date_from), ("contract_date_start", "<=", doc.date_to),
                    "&", ("contract_date_end", ">=", doc.date_from), ("contract_date_end", "<=", doc.date_to),
                ])
                for v in versions:
                    emp = v.employee_id
                    if emp not in employees:
                        continue
                    ln, fn, mn = emp._ua_name_parts()
                    full_name = " ".join(p for p in [ln, fn, mn] if p)
                    job_title = v.job_title or emp.job_title or ""
                    if v.contract_date_start and doc.date_from <= v.contract_date_start <= doc.date_to:
                        rows.append({"employee_id": emp.id, "full_name": full_name, "birthday": emp.birthday, "rnokpp": emp.ua_rnokpp or "",
                                     "tcc": emp.ua_mil_tcc or "", "change_kind": "hire", "date": v.contract_date_start,
                                     "job_title": job_title, "reason": v.ua_order_ref or ""})
                    if v.contract_date_end and doc.date_from <= v.contract_date_end <= doc.date_to:
                        rows.append({"employee_id": emp.id, "full_name": full_name, "birthday": emp.birthday, "rnokpp": emp.ua_rnokpp or "",
                                     "tcc": emp.ua_mil_tcc or "", "change_kind": "dismiss", "date": v.contract_date_end,
                                     "job_title": job_title, "reason": v.ua_end_order_ref or v.ua_dismissal_basis or ""})
                events = self.env["ua.military.event"].sudo().search([
                    ("employee_id", "in", employees.ids), ("kind", "=", "update"), ("date", ">=", doc.date_from), ("date", "<=", doc.date_to),
                ])
                for ev in events:
                    emp = ev.employee_id
                    ln, fn, mn = emp._ua_name_parts()
                    rows.append({"employee_id": emp.id, "full_name": " ".join(p for p in [ln, fn, mn] if p), "birthday": emp.birthday,
                                 "rnokpp": emp.ua_rnokpp or "", "tcc": emp.ua_mil_tcc or "", "change_kind": "change", "date": ev.date,
                                 "job_title": emp.job_title or "", "reason": ev.note or ""})
            rows.sort(key=lambda r: (r["date"], r["full_name"]))
            doc.line_ids = [(0, 0, r) for r in rows]
        return True

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        employees = self.env["hr.employee"].sudo().search([
            ("company_id", "=", self.company_id.id), ("ua_mil_status", "in", list(LIABLE_STATUSES)),
            ("ua_contract_kind", "not in", ["gph", "fop"])])
        expected_ids = set()
        if employees:
            versions = self.env["hr.version"].sudo().search([
                ("employee_id", "in", employees.ids),
                "|",
                "&", ("contract_date_start", ">=", self.date_from), ("contract_date_start", "<=", self.date_to),
                "&", ("contract_date_end", ">=", self.date_from), ("contract_date_end", "<=", self.date_to),
            ])
            expected_ids = {v.employee_id.id for v in versions if v.employee_id in employees}
            events = self.env["ua.military.event"].sudo().search([
                ("employee_id", "in", employees.ids), ("kind", "=", "update"),
                ("date", ">=", self.date_from), ("date", "<=", self.date_to),
            ])
            expected_ids |= {ev.employee_id.id for ev in events}
        have_ids = set(self.line_ids.mapped("employee_id.id"))
        missing = expected_ids - have_ids
        if missing:
            out.append(self._check_error(
                "Подія військового обліку за період не потрапила в повідомлення", fact=len(missing),
                target=self._target_domain("hr.employee", [("id", "in", list(missing))])))
        elif expected_ids:
            out.append(self._check_ok("Усі події періоду в повідомленні", fact=len(expected_ids)))
        else:
            out.append(self._check_ok("Подій військового обліку за період немає"))

        deadline = self.date_to + timedelta(days=7) if self.date_to else False
        today = fields.Date.context_today(self)
        if deadline and self.state == "draft" and self.line_ids and today > deadline:
            out.append(self._check_error(
                "Строк подання повідомлення ТЦК (7 днів від події) минув", fact=deadline.strftime("%d.%m.%Y"),
                target=self._target_record(self)))
        elif deadline:
            out.append(self._check_ok("Строк подання повідомлення ТЦК", fact=deadline.strftime("%d.%m.%Y")))
        out.append(self._check_ok("Стан документа", fact=dict(STATES).get(self.state, self.state)))
        return out


class UaMilitaryNoticeLine(models.Model):
    _name = "ua.military.notice.line"
    _description = "Рядок повідомлення про зміну облікових даних"
    _order = "date, full_name"

    notice_id = fields.Many2one("ua.military.notice", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    full_name = fields.Char("ПІБ")
    birthday = fields.Date("Дата народження")
    rnokpp = fields.Char("РНОКПП")
    tcc = fields.Char("ТЦК")
    change_kind = fields.Selection(CHANGE_KIND, "Вид зміни")
    date = fields.Date("Дата")
    job_title = fields.Char("Посада")
    reason = fields.Char("Підстава (наказ)")
