# -*- coding: utf-8 -*-
"""Закриття місяця.

Закритий місяць = дата блокування в обліку. Odoo після цього не дає провести або
змінити документ із датою до цієї межі. Закриваємо тільки тоді, коли в журналі змін
немає нових рядків і немає чернеток проводок та листків.

М'яке закриття знімає адміністратор із причиною. Остаточне закриття (hard) не
знімається ніколи — його ставлять один раз на рік, після річної звітності.
"""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень", 5: "Травень", 6: "Червень",
    7: "Липень", 8: "Серпень", 9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень",
}
STATES = [("open", "Відкритий"), ("closed", "Закритий")]


class UaPeriodClose(models.Model):
    _name = "ua.period.close"
    _description = "Закриття періоду"
    _order = "year desc, month desc"
    _rec_name = "name"

    name = fields.Char("Період", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda s: s.env.company)
    year = fields.Integer("Рік", required=True)
    month = fields.Integer("Місяць", required=True)
    state = fields.Selection(STATES, "Стан", default="open", required=True)
    hard = fields.Boolean("Остаточно", help="Дата блокування, яку не можна зняти")
    lock_date = fields.Date("Дата блокування", readonly=True)
    closed_user_id = fields.Many2one("res.users", "Закрив", readonly=True)
    closed_date = fields.Datetime("Закрито", readonly=True)
    reopen_reason = fields.Text("Причина відкриття")
    reopened_user_id = fields.Many2one("res.users", "Відкрив", readonly=True)
    reopened_date = fields.Datetime("Відкрито", readonly=True)
    changes_accepted = fields.Integer("Прийнято змін", readonly=True)

    _period_uniq = models.Constraint("unique(company_id, year, month)", "Період уже є в списку.")
    _month_ok = models.Constraint("CHECK (month BETWEEN 1 AND 12)", "Місяць від 1 до 12.")

    @api.model
    def _as_company(self, company):
        if isinstance(company, int):
            return self.env["res.company"].browse(company)
        return company or self.env.company

    @api.model
    def _months(self):
        return MONTHS_UA

    @api.depends("year", "month")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s %s" % (MONTHS_UA.get(rec.month, rec.month), rec.year)

    # ------------------------------------------------------------------ межі
    @staticmethod
    def _bounds(year, month):
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return first, last

    # ------------------------------------------------------------------ перевірки
    @api.model
    def blockers(self, company, year, month):
        """Список причин, чому місяць закрити не можна. Порожній список = можна."""
        company = self._as_company(company)
        year, month = int(year), int(month)
        first, last = self._bounds(year, month)
        out = []
        new_changes = self.env["ua.change.log"].count_new(company, year, month)
        if new_changes:
            out.append(_("непереглянутих змін у журналі: %s") % new_changes)
        drafts = self.env["account.move"].search_count([
            ("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
            ("state", "=", "draft"),
        ])
        if drafts:
            out.append(_("чернеток проводок: %s") % drafts)
        slips = self.env["hr.payslip"].search_count([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "not in", ("done", "cancel")),
        ])
        if slips:
            out.append(_("непроведених листків: %s") % slips)
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if sheet and sheet.state != "confirmed":
            out.append(_("табель не затверджено"))
        return out

    # ------------------------------------------------------------------ дії
    @api.model
    def close_period(self, year, month, hard=False):
        company = self.env.company
        year, month = int(year), int(month)
        reasons = self.blockers(company, year, month)
        if reasons:
            raise UserError(_("Місяць закрити не можна: %s.") % "; ".join(reasons))
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", month)], limit=1)
        if rec and rec.state == "closed":
            raise UserError(_("Місяць уже закрито."))
        last = self._bounds(year, month)[1]
        vals = {"state": "closed", "hard": bool(hard), "lock_date": last,
                "closed_user_id": self.env.uid, "closed_date": fields.Datetime.now(),
                "changes_accepted": self.env["ua.change.log"].search_count([
                    ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)]),
                "reopen_reason": False, "reopened_user_id": False, "reopened_date": False}
        if rec:
            rec.write(vals)
        else:
            vals.update({"company_id": company.id, "year": year, "month": month})
            rec = self.create(vals)
        rec._apply_lock(last, hard)
        return rec.id

    def _apply_lock(self, day, hard=False):
        company = self.company_id.sudo()
        field = "hard_lock_date" if hard else "fiscalyear_lock_date"
        current = company[field]
        if not current or current < day:
            company.write({field: day})
        if hard and (not company.fiscalyear_lock_date or company.fiscalyear_lock_date < day):
            company.write({"fiscalyear_lock_date": day})

    def action_close(self):
        self.ensure_one()
        self.close_period(self.year, self.month, self.hard)
        return True

    def action_reopen(self):
        self.ensure_one()
        if not self.env.user.has_group("account.group_account_manager"):
            raise UserError(_("Відкрити період може тільки головний бухгалтер."))
        if self.hard:
            raise UserError(_("Період закрито остаточно. Відкрити не можна."))
        if not (self.reopen_reason or "").strip():
            raise UserError(_("Напишіть причину відкриття періоду."))
        previous = self.search([("company_id", "=", self.company_id.id), ("state", "=", "closed"),
                                ("id", "!=", self.id), ("lock_date", "<", self.lock_date)],
                               order="lock_date desc", limit=1)
        company = self.company_id.sudo()
        company.write({"fiscalyear_lock_date": previous.lock_date or False})
        self.write({"state": "open", "reopened_user_id": self.env.uid,
                    "reopened_date": fields.Datetime.now()})
        self.env["ua.change.log"].sudo().with_context(ua_no_log=True).create({
            "user_id": self.env.uid, "company_id": self.company_id.id, "area": "account",
            "operation": "write", "model_name": self._name, "res_id": self.id,
            "res_name": self.name, "what": "Період відкрито знову",
            "old_value": "закритий", "new_value": "відкритий",
            "year": self.year, "month": self.month, "note": self.reopen_reason,
        })
        return True

    @api.model
    def state_of(self, company, year, month):
        company = self._as_company(company)
        rec = self.search([("company_id", "=", company.id), ("year", "=", int(year)),
                           ("month", "=", int(month))], limit=1)
        if not rec:
            return {"state": "open", "hard": False, "closed_by": "", "closed_date": ""}
        return {
            "state": rec.state, "hard": rec.hard,
            "closed_by": rec.closed_user_id.name or "",
            "closed_date": rec.closed_date and rec.closed_date.strftime("%d.%m.%Y") or "",
        }
