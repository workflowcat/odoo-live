# -*- coding: utf-8 -*-
"""Закриття місяця.

Закритий місяць = дата блокування в обліку. Odoo після цього не дає провести або
змінити документ із датою до цієї межі. Закриваємо тільки тоді, коли в журналі змін
немає нових рядків і немає чернеток проводок та листків.

М'яке закриття знімає адміністратор із причиною. Остаточне закриття (hard) не
знімається ніколи — його ставлять один раз на рік, після річної звітності.
"""
from datetime import date, timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень", 5: "Травень", 6: "Червень",
    7: "Липень", 8: "Серпень", 9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень",
}
STATES = [("open", "Відкритий"), ("closed", "Закритий")]
KINDS = [("month", "Місяць"), ("quarter", "Квартал"), ("year", "Рік")]


class UaPeriodClose(models.Model):
    _name = "ua.period.close"
    _description = "Закриття періоду"
    _order = "year desc, month desc"
    _rec_name = "name"

    name = fields.Char("Період", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda s: s.env.company)
    year = fields.Integer("Рік", required=True, default=lambda s: fields.Date.context_today(s).year)
    month = fields.Integer("Місяць", required=True,
                           default=lambda s: fields.Date.context_today(s).month)
    kind = fields.Selection(KINDS, "Вид періоду", default="month", required=True)
    state = fields.Selection(STATES, "Стан", default="open", required=True)
    hard = fields.Boolean("Остаточно", help="Дата блокування, яку не можна зняти")
    lock_date = fields.Date("Дата блокування", readonly=True)
    closed_user_id = fields.Many2one("res.users", "Закрив", readonly=True)
    closed_date = fields.Datetime("Закрито", readonly=True)
    reopen_reason = fields.Text("Причина відкриття")
    reopened_user_id = fields.Many2one("res.users", "Відкрив", readonly=True)
    reopened_date = fields.Datetime("Відкрито", readonly=True)
    changes_accepted = fields.Integer("Прийнято змін", readonly=True)

    plan_html = fields.Html("План", compute="_compute_plan_html", sanitize=False)
    payslip_count = fields.Integer("Листки", compute="_compute_counts")
    draft_move_count = fields.Integer("Чернетки проводок", compute="_compute_counts")
    new_change_count = fields.Integer("Непереглянуті зміни", compute="_compute_counts")

    _period_uniq = models.Constraint("unique(company_id, year, month, kind)", "Період уже є в списку.")
    _month_ok = models.Constraint("CHECK (month BETWEEN 1 AND 12)", "Місяць від 1 до 12.")

    @api.model
    def _as_company(self, company):
        if isinstance(company, int):
            return self.env["res.company"].browse(company)
        return company or self.env.company

    @api.model
    def _months(self):
        return MONTHS_UA

    @api.depends("year", "month", "kind")
    def _compute_name(self):
        for rec in self:
            if rec.kind == "year":
                rec.name = "%s рік" % rec.year
            elif rec.kind == "quarter":
                rec.name = "%s квартал %s" % ((rec.month - 1) // 3 + 1, rec.year)
            else:
                rec.name = "%s %s" % (MONTHS_UA.get(rec.month, rec.month), rec.year)

    @api.onchange("kind")
    def _onchange_kind(self):
        """Квартал числиться останнім місяцем кварталу, рік - груднем."""
        for rec in self:
            if rec.kind == "quarter" and rec.month:
                rec.month = ((rec.month - 1) // 3 + 1) * 3
            elif rec.kind == "year":
                rec.month = 12

    # ------------------------------------------------------------------ межі
    @staticmethod
    def _bounds(year, month):
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return first, last

    # ------------------------------------------------------------------ перевірки
    @api.model
    def blocker_rows(self, company, year, month):
        """Кожна перешкода закриття місяця - одним записом, з усіма трьома її словами.

        Одне джерело істини «чому місяць закрити не можна»: раніше ті самі чотири
        перевірки стояли в трьох копіях - тут, у позначці кроку на сторінці «Період»
        і в діалозі плану закриття. Копії різнилися лише формулюванням, тому кожен
        запис несе всі три:
          key   - ділянка (крок сторінки «Період», який цю перешкоду знімає);
          text  - рядок для blockers(): «непереглянутих змін у журналі: 5»;
          short - позначка кроку: «непереглянутих змін: 5»;
          plan  - речення діалогу плану, з поясненням, що робити;
          target- ціль, яка відкриває саме ті записи, що заважають.
        Порядок сталий: зміни, проводки, банк, листки, табель.
        """
        company = self._as_company(company)
        year, month = int(year), int(month)
        first, last = self._bounds(year, month)
        out = []

        # Лише число: сторінку «Період» бачить і той, хто сам журнал не читає.
        new_changes = self.env["ua.change.log"].sudo().count_new(company, year, month)
        if new_changes:
            out.append({
                "key": "changes",
                "text": _("непереглянутих змін у журналі: %s") % new_changes,
                "short": _("непереглянутих змін: %s") % new_changes,
                "plan": _("У журналі змін %s непереглянутих рядків - спершу прийміть їх.") % new_changes,
                "target": {"model": "ua.change.log",
                           "domain": [("company_id", "=", company.id), ("year", "=", year),
                                      ("month", "=", month), ("state", "=", "new")]},
            })

        drafts = self.env["account.move"].search([
            ("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
            ("state", "=", "draft"),
        ])
        if drafts:
            out.append({
                "key": "moves",
                "text": _("чернеток проводок: %s") % len(drafts),
                "short": _("чернеток проводок: %s") % len(drafts),
                "plan": _("Чернеток проводок місяця: %s - їх треба провести або скасувати.") % len(drafts),
                "target": {"model": "account.move", "domain": [("id", "in", drafts.ids)]},
            })

        # Ядро не дасть поставити дату блокування, поки в періоді є незведені рядки
        # виписки. Без цієї перевірки сторінка казала «можна закривати», а закриття
        # падало вже на самій даті блокування.
        bank_lines = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id), ("date", "<=", last),
            ("is_reconciled", "=", False), ("move_id.state", "in", ("draft", "posted")),
        ])
        if bank_lines:
            out.append({
                "key": "bank",
                "text": _("незведених рядків виписки: %s") % len(bank_lines),
                "short": _("незведених рядків виписки: %s") % len(bank_lines),
                "plan": _("Незведених рядків банківської виписки: %s - зведіть їх з платежами.") % len(bank_lines),
                "target": {"model": "account.bank.statement.line", "domain": [("id", "in", bank_lines.ids)]},
            })

        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "not in", ("done", "cancel")),
        ])
        if slips:
            out.append({
                "key": "payslips",
                "text": _("непроведених листків: %s") % len(slips),
                "short": _("непроведених листків: %s") % len(slips),
                "plan": _("Непроведених листків: %s.") % len(slips),
                "target": {"model": "hr.payslip", "domain": [("id", "in", slips.ids)]},
            })

        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if sheet and sheet.state != "confirmed":
            out.append({
                "key": "timesheet",
                "text": _("табель не затверджено"),
                "short": _("табель не затверджено"),
                "plan": _("Табель місяця не затверджено."),
                "target": {"model": "ua.timesheet.sheet", "res_id": sheet.id},
            })
        return out

    @api.model
    def blockers(self, company, year, month):
        """Список причин, чому місяць закрити не можна. Порожній список = можна."""
        return [row["text"] for row in self.blocker_rows(company, year, month)]

    @api.model
    def plan(self, company, year, month):
        """План перед закриттям місяця: що станеться, що заважає, що лишиться потім.

        Рядки того самого вигляду, що їх чекає діалог плану на сторінці «Період»
        (`text`, `level`, за потреби `target`). Перешкоди беруться з blocker_rows() -
        не перераховуються вдруге."""
        company = self._as_company(company)
        year, month = int(year), int(month)
        last = self._bounds(year, month)[1]
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", month), ("kind", "=", "month")], limit=1)
        if rec and rec.state == "closed":
            return [{"text": _("Місяць %s уже закрито %s.") % (
                        rec.name, rec.lock_date.strftime("%d.%m.%Y") if rec.lock_date else ""),
                     "level": "info"}]

        lines = [{
            "text": _("Дата блокування обліку стане %s: проводки й листки з датою до цього дня "
                      "більше не можна буде створити, провести чи змінити.") % last.strftime("%d.%m.%Y"),
            "level": "info",
        }]
        for row in self.blocker_rows(company, year, month):
            lines.append({"text": row["plan"], "level": "crit", "target": row["target"]})
        if any(line["level"] == "crit" for line in lines):
            lines.append({
                "text": _("Поки ці перешкоди лишаються, сервіс не дасть закрити місяць - "
                          "кнопка підтвердження нічого не змінить."),
                "level": "warn",
            })
        lines.append({
            "text": _("Після закриття лишаються доступні: перегляд і друк документів місяця, "
                      "звірка банку, подання звітності. Відкрити місяць знову зможе лише головний "
                      "бухгалтер - окремою дією, з причиною."),
            "level": "info",
        })
        return lines

    # ------------------------------------------------------------------ план на формі
    LEVEL_CLASS = {"info": "", "warn": "text-warning", "crit": "text-danger"}
    LEVEL_WORDS = {"info": "", "warn": "увага", "crit": "перешкода"}

    def _plan_rows(self):
        """Рядки плану для цього запису: місяць, квартал або рік - за видом періоду."""
        self.ensure_one()
        if self.kind == "quarter":
            quarter = (self.month - 1) // 3 + 1
            reasons = self.quarter_blockers(self.company_id, self.year, quarter)
            head = _("Закриття %s кварталу %s поставить податкову дату блокування на кінець "
                     "кварталу.") % (quarter, self.year)
        elif self.kind == "year":
            reasons = self.year_blockers(self.company_id, self.year)
            head = _("Закриття %s року поставить остаточну дату блокування 31.12 - зняти її "
                     "не можна.") % self.year
        else:
            return self.plan(self.company_id, self.year, self.month)
        rows = [{"text": head, "level": "info"}]
        rows += [{"text": reason, "level": "crit"} for reason in reasons]
        return rows

    def _compute_plan_html(self):
        for rec in self:
            if not rec.id or not rec.year or not rec.month:
                rec.plan_html = False
                continue
            try:
                rows = rec._plan_rows()
            except Exception:
                rec.plan_html = Markup("<p>План не порахувався.</p>")
                continue
            items = []
            for row in rows:
                level = row.get("level") or "info"
                link = Markup("")
                target = row.get("target") or {}
                if target.get("model") and target.get("res_id"):
                    link = Markup(' <a href="/odoo/m-%s/%s">відкрити запис</a>') % (
                        target["model"], int(target["res_id"]))
                elif target.get("model"):
                    link = Markup(" <span class=\"text-muted\">(%s)</span>") % escape(target["model"])
                word = self.LEVEL_WORDS.get(level) or ""
                mark = Markup("<b>%s:</b> ") % word if word else Markup("")
                items.append(Markup('<li class="%s">%s%s%s</li>') % (
                    self.LEVEL_CLASS.get(level, ""), mark, escape(row.get("text") or ""), link))
            rec.plan_html = Markup('<ul class="o_ua_plan">%s</ul>') % Markup("").join(items)

    def _compute_counts(self):
        for rec in self:
            if not rec.id or not rec.year or not rec.month:
                rec.payslip_count = rec.draft_move_count = rec.new_change_count = 0
                continue
            first, last = self._bounds(rec.year, rec.month)
            rec.payslip_count = self.env["hr.payslip"].search_count([
                ("company_id", "=", rec.company_id.id),
                ("date_from", ">=", first), ("date_from", "<=", last)])
            rec.draft_move_count = self.env["account.move"].search_count([
                ("company_id", "=", rec.company_id.id), ("date", ">=", first),
                ("date", "<=", last), ("state", "=", "draft")])
            rec.new_change_count = self.env["ua.change.log"].sudo().count_new(
                rec.company_id, rec.year, rec.month)

    def _period_domain(self, model, date_field):
        first, last = self._bounds(self.year, self.month)
        return [("company_id", "=", self.company_id.id),
                (date_field, ">=", fields.Date.to_string(first)),
                (date_field, "<=", fields.Date.to_string(last))]

    def _open_list(self, model, domain, name):
        return {"type": "ir.actions.act_window", "name": name, "res_model": model,
                "view_mode": "list,form", "domain": domain, "target": "current"}

    def action_open_payslips(self):
        self.ensure_one()
        return self._open_list("hr.payslip", self._period_domain("hr.payslip", "date_from"),
                               _("Листки: %s") % self.name)

    def action_open_draft_moves(self):
        self.ensure_one()
        return self._open_list("account.move",
                               self._period_domain("account.move", "date") + [("state", "=", "draft")],
                               _("Чернетки проводок: %s") % self.name)

    def action_open_changes(self):
        self.ensure_one()
        return self._open_list("ua.change.log", [
            ("company_id", "=", self.company_id.id), ("year", "=", self.year),
            ("month", "=", self.month)], _("Журнал змін: %s") % self.name)

    # ------------------------------------------------------------------ кнопки місяця
    def action_prepare_month(self):
        """Підготувати місяць: табель, пакет листків, розрахунок.

        Сама процедура живе в hr.payslip.run.ua_prepare_month() - тут лише кнопка."""
        self.ensure_one()
        result = self.env["hr.payslip.run"].with_company(self.company_id).ua_prepare_month(
            self.company_id, self.year, self.month)
        self.invalidate_recordset(["payslip_count", "plan_html"])
        return self._notify(result.get("message") or _("Місяць підготовано."))

    def action_accept_changes(self):
        """Прийняти всі непереглянуті зміни місяця."""
        self.ensure_one()
        count = self.env["ua.change.log"].with_company(self.company_id).accept_period(
            self.year, self.month)
        self.invalidate_recordset(["new_change_count", "plan_html"])
        return self._notify(_("Прийнято змін: %s.") % count)

    def _notify(self, message):
        """Повідомлення про зроблене, не залишаючи форму."""
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": message, "type": "success", "sticky": False}}

    # ------------------------------------------------------------------ дії
    @api.model
    def ensure_for(self, company, year, month):
        """Картка закриття місяця: наявна або нова чернетка.

        «Відкрити картку закриття» з екрана має показати запис навіть тоді, коли
        місяць ще ніхто не закривав, тому запис тут створюється явно - а не побічно
        в методі інтерфейсу."""
        company = self._as_company(company)
        year, month = int(year), int(month)
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", month)], limit=1)
        if not rec:
            rec = self.create({"company_id": company.id, "year": year, "month": month})
        return rec

    @api.model
    def close_period(self, year, month, hard=False):
        company = self.env.company
        year, month = int(year), int(month)
        reasons = self.blockers(company, year, month)
        if reasons:
            raise UserError(_("Місяць закрити не можна: %s.") % "; ".join(reasons))
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", month), ("kind", "=", "month")], limit=1)
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
            vals.update({"company_id": company.id, "year": year, "month": month, "kind": "month"})
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
        self.with_company(self.company_id).close_period(self.year, self.month, self.hard)
        self.invalidate_recordset()
        return True

    def action_close_quarter(self):
        self.ensure_one()
        self.with_company(self.company_id).close_quarter(self.year, (self.month - 1) // 3 + 1)
        self.invalidate_recordset()
        return True

    def action_close_year(self):
        self.ensure_one()
        self.with_company(self.company_id).close_year(self.year)
        self.invalidate_recordset()
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

    # ------------------------------------------------------------------ квартал і рік
    @api.model
    def quarter_blockers(self, company, year, quarter):
        """Чому не можна закрити квартал: незакриті місяці або неподана звітність."""
        company = self._as_company(company)
        year, quarter = int(year), int(quarter)
        months = [quarter * 3 - 2, quarter * 3 - 1, quarter * 3]
        out = []
        closed = self.search([("company_id", "=", company.id), ("year", "=", year),
                              ("kind", "=", "month"), ("month", "in", months), ("state", "=", "closed")])
        left = sorted(set(months) - set(closed.mapped("month")))
        if left:
            out.append(_("не закриті місяці: %s") % ", ".join(MONTHS_UA[m].lower() for m in left))
        run = self.env["ua.report.run"].search([
            ("company_id", "=", company.id), ("report_code", "=", "j05"), ("year", "=", year),
            ("quarter", "=", quarter), ("doc_kind", "=", "HZ"),
        ], limit=1)
        if not run or run.state != "submitted":
            out.append(_("податковий розрахунок за квартал не позначено поданим"))
        return out

    @api.model
    def year_blockers(self, company, year):
        """Чому не можна закрити рік: незакриті квартали."""
        company = self._as_company(company)
        year = int(year)
        out = []
        closed = self.search([("company_id", "=", company.id), ("year", "=", year),
                              ("kind", "=", "quarter"), ("state", "=", "closed")])
        left = sorted({1, 2, 3, 4} - {(m - 1) // 3 + 1 for m in closed.mapped("month")})
        if left:
            out.append(_("не закриті квартали: %s") % ", ".join(str(q) for q in left))
        return out

    @api.model
    def close_quarter(self, year, quarter):
        """Закрити квартал: дата податкового блокування на кінець кварталу."""
        company = self.env.company
        year, quarter = int(year), int(quarter)
        reasons = self.quarter_blockers(company, year, quarter)
        if reasons:
            raise UserError(_("Квартал закрити не можна: %s.") % "; ".join(reasons))
        last = self._bounds(year, quarter * 3)[1]
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", quarter * 3), ("kind", "=", "quarter")], limit=1)
        vals = {"state": "closed", "lock_date": last, "closed_user_id": self.env.uid,
                "closed_date": fields.Datetime.now()}
        if rec:
            rec.write(vals)
        else:
            rec = self.create({**vals, "company_id": company.id, "year": year,
                               "month": quarter * 3, "kind": "quarter"})
        sudo = company.sudo()
        if not sudo.tax_lock_date or sudo.tax_lock_date < last:
            sudo.write({"tax_lock_date": last})
        rec._apply_lock(last)
        return rec.id

    @api.model
    def close_year(self, year):
        """Закрити рік остаточно: жорстка дата блокування, яку не знімає ніхто."""
        company = self.env.company
        year = int(year)
        reasons = self.year_blockers(company, year)
        if reasons:
            raise UserError(_("Рік закрити не можна: %s.") % "; ".join(reasons))
        last = date(year, 12, 31)
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", 12), ("kind", "=", "year")], limit=1)
        vals = {"state": "closed", "hard": True, "lock_date": last,
                "closed_user_id": self.env.uid, "closed_date": fields.Datetime.now()}
        if rec:
            rec.write(vals)
        else:
            rec = self.create({**vals, "company_id": company.id, "year": year, "month": 12, "kind": "year"})
        rec._apply_lock(last, hard=True)
        return rec.id

    @api.model
    def state_of(self, company, year, month):
        company = self._as_company(company)
        rec = self.search([("company_id", "=", company.id), ("year", "=", int(year)),
                           ("month", "=", int(month)), ("kind", "=", "month")], limit=1)
        if not rec:
            return {"state": "open", "hard": False, "closed_by": "", "closed_date": ""}
        return {
            "state": rec.state, "hard": rec.hard,
            "closed_by": rec.closed_user_id.name or "",
            "closed_date": rec.closed_date and rec.closed_date.strftime("%d.%m.%Y") or "",
        }
