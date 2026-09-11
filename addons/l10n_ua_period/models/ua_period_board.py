# -*- coding: utf-8 -*-
"""Сторінка «Період»: місяць зарплати як чек-лист із восьми кроків.

Кожен крок знає свій стан, коротке число і що відкрити. Проблемні кроки розкриваються
на місці: під рядком видно самі записи, з якими треба щось зробити, без переходу на
інший екран.

Дані беруться з уже наявних моделей: накази, табель, аванс, листки, проводки, відомості
на перерахування, рядки виписки, прогони звітності. Своїх даних модуль не тримає.
"""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
ACCOUNT_CODES = ["23", "91", "92", "93", "661", "6411", "6415", "651", "6851", "471", "311", "378"]


class UaPeriodBoard(models.AbstractModel):
    _name = "ua.period.board"
    _description = "Дані сторінки «Період»"

    # ------------------------------------------------------------------ хелпери
    @staticmethod
    def _r2(value):
        return round(value or 0.0, 2)

    @staticmethod
    def _money(value):
        return "{:,.2f}".format(value or 0.0).replace(",", " ").replace(".", ",")

    @staticmethod
    def _bounds(year, month):
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return first, last

    def _company(self):
        return self.env.company

    @staticmethod
    def _step(key, title, state, fact, action=None, details=None, button=None):
        return {"key": key, "title": title, "state": state, "fact": fact,
                "action": action or {}, "details": details or [], "button": button or ""}

    # ------------------------------------------------------------------ кроки
    def _step_orders(self, company, first, last):
        Order = self.env["ua.hr.order"]
        domain = [("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last)]
        posted = Order.search_count(domain + [("state", "in", ("posted", "acknowledged"))])
        drafts = Order.search(domain + [("state", "=", "draft")])
        state = "warn" if drafts else ("done" if posted else "todo")
        fact = "%s проведено, %s чернеток" % (posted, len(drafts))
        details = [{"id": o.id, "model": "ua.hr.order", "title": o.name or o.display_name,
                    "note": o.employee_id.name or ""} for o in drafts[:20]]
        return self._step("orders", "Кадрові накази", state, fact,
                          {"xmlid": "l10n_ua_hr_orders.action_ua_hr_order"}, details)

    def _step_timesheet(self, company, year, month):
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if not sheet:
            return self._step("timesheet", "Табель", "todo", "не створено",
                              {"xmlid": "l10n_ua_hr_docs.action_ua_timesheet_sheet"})
        fact_days = sum(sheet.line_ids.mapped("days_worked"))
        norm_days = sum(sheet.line_ids.mapped("norm_days"))
        state = "done" if sheet.state == "confirmed" else "warn"
        fact = "%s з %s днів, %s" % (self._money(fact_days).replace(",00", ""),
                                     self._money(norm_days).replace(",00", ""),
                                     "затверджено" if sheet.state == "confirmed" else "чернетка")
        details = [{"id": line.id, "model": "ua.timesheet.line", "title": line.employee_id.name,
                    "note": "відхилення %s дн" % self._money(line.diff_days).replace(",00", "")}
                   for line in sheet.line_ids.filtered(lambda l: abs(l.diff_days) > 0.01)[:20]]
        return self._step("timesheet", "Табель", state, fact,
                          {"model": "ua.timesheet.sheet", "res_id": sheet.id}, details)

    def _step_advance(self, company, year, month):
        sheet = self.env["ua.advance.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if not sheet or not sheet.line_ids:
            return self._step("advance", "Аванс", "todo", "не розраховано",
                              {"xmlid": "l10n_ua_payroll_rules.action_ua_advance_wizard"})
        state = "done" if sheet.state == "confirmed" else "warn"
        fact = "%s · %s осіб" % (self._money(sheet.total), len(sheet.line_ids))
        return self._step("advance", "Аванс", state, fact,
                          {"model": "ua.advance.sheet", "res_id": sheet.id})

    def _step_payslips(self, company, first, last):
        Payslip = self.env["hr.payslip"]
        domain = [("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last)]
        slips = Payslip.search(domain + [("state", "!=", "cancel")])
        done = slips.filtered(lambda s: s.state == "done")
        open_slips = slips - done
        gross = sum(done.mapped("line_ids").filtered(lambda l: l.code == "GROSS").mapped("total"))
        if not slips:
            return self._step("payslips", "Розрахунок листків", "todo", "листків немає",
                              {"xmlid": "payroll.action_hr_payslip_run_tree"})
        state = "done" if not open_slips else "warn"
        fact = "%s проведено · %s" % (len(done), self._money(gross))
        details = [{"id": s.id, "model": "hr.payslip", "title": s.employee_id.name,
                    "note": dict(s._fields["state"].selection).get(s.state, s.state)} for s in open_slips[:20]]
        return self._step("payslips", "Розрахунок листків", state, fact,
                          {"xmlid": "payroll.action_hr_payslip_run_tree"}, details)

    def _step_moves(self, company, first, last):
        Move = self.env["account.move"]
        domain = [("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last)]
        drafts = Move.search(domain + [("state", "=", "draft")])
        self.env.cr.execute(
            """SELECT COALESCE(SUM(aml.debit), 0), COALESCE(SUM(aml.credit), 0)
               FROM account_move_line aml JOIN account_move am ON am.id = aml.move_id
               WHERE am.company_id = %s AND am.state = 'posted' AND aml.date BETWEEN %s AND %s""",
            (company.id, first, last))
        debit, credit = self.env.cr.fetchone()
        balanced = abs(self._r2(debit) - self._r2(credit)) < 0.01
        state = "done" if (balanced and not drafts) else "warn"
        fact = "%s, чернеток %s" % ("дебет = кредит" if balanced else "дебет ≠ кредит", len(drafts))
        details = [{"id": m.id, "model": "account.move", "title": m.name or m.ref or "-",
                    "note": self._money(m.amount_total)} for m in drafts[:20]]
        return self._step("moves", "Проводки", state, fact,
                          {"xmlid": "account.action_move_journal_line"}, details)

    def _step_payment(self, company, year, month):
        batches = self.env["ua.payment.batch"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ])
        if not batches:
            return self._step("payment", "Виплата", "todo", "відомості немає",
                              {"xmlid": "l10n_ua_payments.action_ua_payment_batch"})
        total = sum(batches.mapped("total"))
        paid = batches.filtered(lambda b: b.state == "paid")
        state = "done" if paid else "warn"
        fact = "%s · %s" % (self._money(total), "оплачено" if paid else "не позначено оплаченою")
        return self._step("payment", "Виплата", state, fact,
                          {"model": "ua.payment.batch", "res_id": batches[0].id})

    def _step_bank(self, company, first, last):
        lines = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id), ("is_reconciled", "=", False),
            ("date", ">=", first), ("date", "<=", last),
        ])
        amount = sum(abs(line.amount) for line in lines)
        state = "done" if not lines else "warn"
        fact = "звірено все" if not lines else "%s рядків · %s" % (len(lines), self._money(amount))
        details = [{"id": line.id, "model": "account.bank.statement.line",
                    "title": (line.payment_ref or "")[:60],
                    "note": self._money(line.amount)} for line in lines[:20]]
        return self._step("bank", "Звірка банку", state, fact,
                          {"xmlid": "l10n_ua_bank_online.action_ua_bank_board"}, details,
                          button="Звірити" if lines else "")

    def _step_reporting(self, company, year, month):
        """Податковий розрахунок подається щомісяця: 20 днів після закінчення місяця."""
        run = self.env["ua.report.run"].search([
            ("company_id", "=", company.id), ("report_code", "=", "j05"),
            ("year", "=", year), ("month", "=", month), ("doc_kind", "=", "HZ"),
        ], limit=1)
        deadline = self._bounds(year, month)[1] + timedelta(days=20)
        if run and run.state == "submitted":
            state, fact = "done", "подано %s" % (run.submitted_date.strftime("%d.%m.%Y") if run.submitted_date else "")
        elif run and run.state == "generated":
            state, fact = "warn", "сформовано, не подано · строк %s" % deadline.strftime("%d.%m.%Y")
        else:
            state, fact = "todo", "строк %s" % deadline.strftime("%d.%m.%Y")
        return self._step("reporting", "Податковий розрахунок за місяць", state, fact,
                          {"xmlid": "l10n_ua_reporting.action_ua_reporting"})


    def _step_changes(self, company, year, month):
        """Скільки змін місяця ще не переглянув бухгалтер."""
        Log = self.env["ua.change.log"]
        total = Log.search_count([("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)])
        new = Log.count_new(company, year, month)
        action = {"xmlid": "l10n_ua_changes.action_ua_change_log",
                  "domain": [("year", "=", year), ("month", "=", month)],
                  "context": {"search_default_f_new": 1, "search_default_g_area": 1}}
        if not total:
            return self._step("changes", "Перевірка змін", "done", "змін немає", action)
        if new:
            rows = Log.search([("company_id", "=", company.id), ("year", "=", year),
                               ("month", "=", month), ("state", "=", "new")], limit=20)
            details = [{"id": r.id, "model": "ua.change.log",
                        "title": "%s · %s" % (r.res_name, r.what or dict(r._fields["operation"].selection).get(r.operation, "")),
                        "note": ("%s → %s" % (r.old_value or "—", r.new_value or "—")) if r.what else r.user_id.name}
                       for r in rows]
            return self._step("changes", "Перевірка змін", "warn",
                              "%s нових з %s" % (new, total), action, details)
        return self._step("changes", "Перевірка змін", "done", "%s змін прийнято" % total, action)



    def _steps(self, company, year, month, first, last):
        """Кроки місяця в порядку роботи."""
        return [
            self._step_orders(company, first, last),
            self._step_timesheet(company, year, month),
            self._step_advance(company, year, month),
            self._step_payslips(company, first, last),
            self._step_moves(company, first, last),
            self._step_payment(company, year, month),
            self._step_bank(company, first, last),
            self._step_changes(company, year, month),
            self._step_reporting(company, year, month),
        ]

    # ------------------------------------------------------------------ робоче місце місяця
    def _slips(self, company, first, last):
        return self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "!=", "cancel"),
        ])

    def _estimate(self, company, first, last):
        """Три числа місяця: нараховано, до виплати, внески підприємства."""
        slips = self._slips(company, first, last)
        lines = slips.mapped("line_ids")

        def total(codes):
            return self._r2(sum(lines.filtered(lambda l: l.code in codes).mapped("total")))

        gross = self._r2(total(("GROSS",)) + total(("MAT",)) + total(("DAILY", "AID_FREE", "GIFT_FREE"))
                         + total(("AID_TAX", "GIFT_TAX", "SEVERANCE", "COMP_TOOL")))
        return {
            "gross": self._money(gross),
            "net": self._money(total(("NET",))),
            "employer": self._money(total(("ESV",))),
            "people": len(slips),
            "draft": len(slips.filtered(lambda s: s.state != "done")),
        }

    def _changes(self, company, first, last):
        """Події працівників у місяці: що змінилося проти попереднього місяця."""
        Order = self.env["ua.hr.order"]
        posted = [("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
                  ("state", "in", ("posted", "acknowledged"))]
        rows = []
        kinds = [("hire", "прийнято"), ("wage", "зміна окладу"), ("transfer", "переведення"),
                 ("dismissal", "звільнення")]
        for code, label in kinds:
            count = Order.search_count(posted + [("order_type", "=", code)])
            if count:
                rows.append({"label": label, "count": count, "model": "ua.hr.order",
                             "domain": [("company_id", "=", company.id), ("date", ">=", str(first)),
                                        ("date", "<=", str(last)), ("order_type", "=", code)]})
        Leave = self.env["hr.leave"]
        leave_domain = [("employee_id.company_id", "=", company.id), ("state", "=", "validate"),
                        ("request_date_from", "<=", last), ("request_date_to", ">=", first)]
        groups = [(("SICK", "SICK_CARE"), "лікарняні"), (("VAC", "STUDY", "CHILD_VAC"), "відпустки"),
                  (("MAT",), "декрет"), (("TRIP",), "відрядження")]
        for codes, label in groups:
            count = Leave.search_count(leave_domain + [("holiday_status_id.work_entry_type_id.code", "in", list(codes))])
            if count:
                rows.append({"label": label, "count": count, "model": "hr.leave",
                             "domain": [("employee_id.company_id", "=", company.id), ("state", "=", "validate"),
                                        ("request_date_from", "<=", str(last)), ("request_date_to", ">=", str(first)),
                                        ("holiday_status_id.work_entry_type_id.code", "in", list(codes))]})
        return rows

    def _exceptions(self, company, steps, year, month):
        """Черга винятків: тільки те, що потребує рішення. Причина і дія в одному рядку."""
        out = []
        for step in steps:
            if step["state"] != "warn":
                continue
            out.append({"title": step["title"], "detail": step["fact"], "level": "warning",
                        "action": step["action"], "key": step["key"]})
        for row in self.env["ua.dashboard"]._get_attention(company):
            detail = row["detail"]
            if row.get("count") and str(row["count"]) not in detail:
                detail = "%s %s" % (row["count"], detail)
            out.append({"title": row["title"], "detail": detail,
                        "level": "danger" if row.get("level") == "danger" else "warning",
                        "action": {"model": row.get("res_model"), "domain": row.get("domain")},
                        "key": "attention"})
        return out

    def _headline(self, company, steps, exceptions, close, blockers, estimate):
        """Одна головна дія, яка змінюється зі станом місяця."""
        by_key = {step["key"]: step for step in steps}
        if close.get("state") == "closed":
            return {"title": "Місяць закрито", "detail": close.get("closed_date") or "",
                    "action": "", "label": "", "tone": "ok"}
        if not estimate["people"]:
            return {"title": "Місяць не підготовлено", "detail": "листків ще немає",
                    "action": "prepare", "label": "Підготувати місяць", "tone": "todo"}
        if exceptions:
            count = len(exceptions)
            verb = "потребує" if count == 1 else "потребують"
            return {"title": "Підготовка неповна",
                    "detail": "%s %s рішення" % (self._plural_items(count), verb),
                    "action": "exceptions", "label": "Переглянути винятки", "tone": "warn"}
        if estimate["draft"]:
            return {"title": "Розрахунок попередній", "detail": "%s листків не проведено" % estimate["draft"],
                    "action": "payslips", "label": "Підтвердити розрахунок", "tone": "warn"}
        if by_key.get("payment", {}).get("state") != "done":
            return {"title": "Виплата не підготовлена", "detail": by_key.get("payment", {}).get("fact", ""),
                    "action": "payment", "label": "Підготувати виплати", "tone": "todo"}
        if by_key.get("reporting", {}).get("state") != "done":
            return {"title": "Звітність не подана", "detail": by_key.get("reporting", {}).get("fact", ""),
                    "action": "reporting", "label": "Переглянути звітність", "tone": "todo"}
        if blockers:
            return {"title": "Місяць майже готовий", "detail": "; ".join(blockers),
                    "action": "", "label": "", "tone": "warn"}
        return {"title": "Місяць готовий до закриття", "detail": "усі кроки виконані",
                "action": "close", "label": "Закрити місяць", "tone": "ok"}

    @staticmethod
    def _plural_items(count):
        if count == 1:
            return "1 позиція"
        if 2 <= count <= 4:
            return "%s позиції" % count
        return "%s позицій" % count

    # ------------------------------------------------------------------ обороти
    def _turnover(self, company, first, last):
        """Обороти за групами рахунків: беремо всі субрахунки за префіксом (311 і 311001 разом)."""
        rows = []
        Account = self.env["account.account"]
        for code in ACCOUNT_CODES:
            accounts = Account.search([("code", "=like", "%s%%" % code), ("company_ids", "in", company.id)], order="code")
            accounts = accounts.filtered(lambda a: (a.code or "").startswith(code))
            if not accounts:
                continue
            self.env.cr.execute(
                """SELECT COALESCE(SUM(aml.debit), 0), COALESCE(SUM(aml.credit), 0)
                   FROM account_move_line aml JOIN account_move am ON am.id = aml.move_id
                   WHERE aml.account_id IN %s AND am.state = 'posted' AND aml.date BETWEEN %s AND %s""",
                (tuple(accounts.ids), first, last))
            debit, credit = self.env.cr.fetchone()
            if not debit and not credit:
                continue
            balance = self._r2(debit) - self._r2(credit)
            rows.append({"code": code, "name": accounts[0].name,
                         "debit": self._money(debit), "credit": self._money(credit),
                         "saldo_debit": self._money(balance) if balance > 0 else "",
                         "saldo_credit": self._money(-balance) if balance < 0 else ""})
        return rows

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, year=None, month=None):
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        steps = self._steps(company, year, month, first, last)
        blockers = self.env["ua.period.close"].blockers(company, year, month)
        close = self.env["ua.period.close"].state_of(company, year, month)
        estimate = self._estimate(company, first, last)
        exceptions = self._exceptions(company, steps, year, month)
        done = sum(1 for s in steps if s["state"] == "done")
        periods = []
        y, m = year, month
        for _i in range(6):
            periods.append({"year": y, "month": m, "label": "%s %s" % (MONTHS_UA[m].capitalize(), y)})
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        periods.reverse()
        return {
            "company": company.name,
            "period": {"year": year, "month": month, "label": "%s %s" % (MONTHS_UA[month].capitalize(), year)},
            "periods": periods,
            "steps": steps,
            "done": done,
            "total": len(steps),
            "turnover": self._turnover(company, first, last),
            "blockers": blockers,
            "close": close,
            "new_changes": self.env["ua.change.log"].count_new(company, year, month),
            "estimate": estimate,
            "changes": self._changes(company, first, last),
            "exceptions": exceptions,
            "headline": self._headline(company, steps, exceptions, close, blockers, estimate),
            "quarter": self._quarter_info(company, year, month),
            "year_close": self._year_info(company, year, month),
        }

    def _quarter_info(self, company, year, month):
        """Закриття кварталу показуємо в останньому місяці кварталу."""
        quarter = (month - 1) // 3 + 1
        if month != quarter * 3:
            return {}
        Close = self.env["ua.period.close"]
        rec = Close.search([("company_id", "=", company.id), ("year", "=", year),
                            ("month", "=", month), ("kind", "=", "quarter")], limit=1)
        return {"quarter": quarter, "label": "%s квартал %s" % (quarter, year),
                "closed": rec.state == "closed" if rec else False,
                "blockers": Close.quarter_blockers(company, year, quarter)}

    def _year_info(self, company, year, month):
        """Закриття року показуємо в грудні."""
        if month != 12:
            return {}
        Close = self.env["ua.period.close"]
        rec = Close.search([("company_id", "=", company.id), ("year", "=", year),
                            ("kind", "=", "year")], limit=1)
        return {"label": "%s рік" % year, "closed": rec.state == "closed" if rec else False,
                "blockers": Close.year_blockers(company, year)}

    # ------------------------------------------------------------------ дії
    @api.model
    def action_open(self, action):
        """Відкрити те, що стоїть за кроком: список за xmlid або конкретний запис."""
        if action.get("xmlid"):
            res = dict(self.env["ir.actions.actions"]._for_xml_id(action["xmlid"]))
            if action.get("domain"):
                res["domain"] = action["domain"]
            if action.get("context"):
                res["context"] = dict(action["context"])
            return res
        if action.get("model") and action.get("res_id"):
            return {
                "type": "ir.actions.act_window", "res_model": action["model"], "res_id": int(action["res_id"]),
                "view_mode": "form", "views": [(False, "form")], "target": "current",
            }
        raise ValueError(_("Немає що відкривати."))

    @api.model
    def action_open_record(self, model, res_id):
        view = "form"
        if model == "account.bank.statement.line":
            return {
                "type": "ir.actions.act_window", "res_model": model, "res_id": int(res_id),
                "view_mode": "form", "views": [(False, "form")], "target": "current",
                "context": {"view_ref": "account_reconcile_oca.bank_statement_line_form_reconcile_view"},
            }
        return {"type": "ir.actions.act_window", "res_model": model, "res_id": int(res_id),
                "view_mode": view, "views": [(False, view)], "target": "current"}

    @api.model
    def action_accept_changes(self, year, month):
        """Прийняти всі нові зміни місяця."""
        return self.env["ua.change.log"].accept_period(year, month)

    @api.model
    def action_close_month(self, year, month, hard=False):
        """Закрити місяць: перевірити блокери і поставити дату блокування."""
        return self.env["ua.period.close"].close_period(year, month, hard)

    @api.model
    def action_open_close_record(self, year, month):
        """Відкрити картку закриття періоду (там причина і кнопка «Відкрити знову»)."""
        Close = self.env["ua.period.close"]
        rec = Close.search([("company_id", "=", self.env.company.id),
                            ("year", "=", int(year)), ("month", "=", int(month))], limit=1)
        if not rec:
            rec = Close.create({"company_id": self.env.company.id,
                                "year": int(year), "month": int(month)})
        return {"type": "ir.actions.act_window", "res_model": "ua.period.close",
                "res_id": rec.id, "view_mode": "form", "views": [(False, "form")],
                "target": "current"}

    @api.model
    def action_close_quarter(self, year, quarter):
        return self.env["ua.period.close"].close_quarter(year, quarter)

    @api.model
    def action_close_year(self, year):
        return self.env["ua.period.close"].close_year(year)

    @api.model
    def action_prepare_month(self, year, month):
        """Підготувати місяць: табель, чернетки листків, перерахунок.

        Нічого не проводить і нічого не платить. Мета - щоб бухгалтер побачив числа
        і перелік винятків, а не заповнював документи руками."""
        company = self._company()
        year, month = int(year), int(month)
        first, last = self._bounds(year, month)
        done = []

        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)], limit=1)
        if not sheet:
            sheet = self.env["ua.timesheet.sheet"].create({
                "company_id": company.id, "year": year, "month": month})
            sheet.action_refill()
            done.append(_("табель створено"))
        elif sheet.state == "draft" and not sheet.line_ids:
            sheet.action_refill()
            done.append(_("табель заповнено"))

        Payslip = self.env["hr.payslip"]
        existing = Payslip.search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "!=", "cancel")])
        covered = existing.mapped("employee_id")
        run = self.env["hr.payslip.run"].search([
            ("company_id", "=", company.id), ("date_start", "=", first), ("date_end", "=", last)], limit=1)
        if not run:
            run = self.env["hr.payslip.run"].create({
                "name": _("Зарплата %(month)02d.%(year)s") % {"month": month, "year": year},
                "date_start": first, "date_end": last, "company_id": company.id})
        created = 0
        for employee in self.env["hr.employee"].search([("company_id", "=", company.id), ("active", "=", True)]):
            if employee in covered:
                continue
            version = employee.sudo().version_ids.filtered(
                lambda v: v.contract_date_start and v.contract_date_start <= last
                and (not v.contract_date_end or v.contract_date_end >= first)).sorted("contract_date_start")[-1:]
            if not version:
                continue
            slip = Payslip.create({
                "employee_id": employee.id, "date_from": first, "date_to": last,
                "payslip_run_id": run.id, "company_id": company.id,
            })
            slip.onchange_employee()
            created += 1
        if created:
            done.append(_("створено листків: %s") % created)

        drafts = Payslip.search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "in", ("draft", "verify"))])
        if drafts:
            drafts.compute_sheet()
            done.append(_("перераховано листків: %s") % len(drafts))
        return {"message": "; ".join(done) if done else _("Змінювати не було чого: місяць уже підготовлено.")}

    @api.model
    def action_headline(self, year, month, action):
        """Головна дія робочого місця. Повертає повідомлення або дію Odoo."""
        year, month = int(year), int(month)
        if action == "prepare":
            return self.action_prepare_month(year, month)
        if action == "close":
            self.env["ua.period.close"].close_period(year, month)
            return {"message": _("Місяць закрито.")}
        company = self._company()
        first, last = self._bounds(year, month)
        steps = {step["key"]: step for step in self._steps(company, year, month, first, last)}
        step = steps.get(action)
        if step:
            return self.action_open(step["action"])
        raise UserError(_("Невідома дія."))

    @api.model
    def action_open_exception(self, row):
        """Відкрити те, що стоїть за винятком."""
        action = row.get("action") or {}
        if action.get("xmlid") or (action.get("model") and action.get("res_id")):
            return self.action_open(action)
        if action.get("model"):
            return {"type": "ir.actions.act_window", "res_model": action["model"],
                    "domain": action.get("domain") or [], "view_mode": "list,form",
                    "views": [(False, "list"), (False, "form")], "target": "current",
                    "name": row.get("title") or ""}
        raise UserError(_("Немає що відкривати."))
