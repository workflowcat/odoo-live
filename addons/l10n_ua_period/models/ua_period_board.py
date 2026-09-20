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
        details = [{"id": o.id, "model": "ua.hr.order", "title": o.name or "без номера",
                    "note": o.employee_id.name or ""} for o in drafts[:20]]
        return self._step("orders", "Кадрові накази", state, fact,
                          {"xmlid": "l10n_ua_hr_orders.action_ua_hr_order"}, details)

    def _step_timesheet(self, company, year, month):
        """Табель формується сам: якщо його ще немає, ua.timesheet.sheet._ua_ensure_for
        створює чернетку і заповнює нормою/фактом, тому кроку завжди є що показати."""
        sheet = self.env["ua.timesheet.sheet"]._ua_ensure_for(company, year, month)
        fact_days = sum(sheet.line_ids.mapped("days_worked"))
        norm_days = sum(sheet.line_ids.mapped("norm_days"))
        summary = sheet._checks_summary()
        state = "done" if (sheet.state == "confirmed" and summary["level"] != "error") else "warn"
        fact = "%s працівників · норма %s днів · факт %s днів" % (
            len(sheet.line_ids), self._money(norm_days).replace(",00", ""),
            self._money(fact_days).replace(",00", ""))
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
    def _slip_domain(self, company, first, last):
        """Домен листків місяця: те, що стоїть за числами зверху екрана."""
        return [
            ("company_id", "=", company.id),
            ("date_from", ">=", str(first)), ("date_from", "<=", str(last)),
            ("state", "!=", "cancel"),
        ]

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
            "model": "hr.payslip",
            "domain": self._slip_domain(company, first, last),
            "draft_domain": self._slip_domain(company, first, last) + [("state", "!=", "done")],
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
        """Черга уваги: тільки те, чого немає в кроках місяця.

        Кроки вже показують свій стан у своєму переліку, тому дублювати їх тут
        не треба: раніше чотири рядки з дев'яти повторювалися.
        """
        out = []
        claim = self.env["ua.pfu.claim"].search([
            ("company_id", "=", company.id),
            ("payslip_run_id.date_start", ">=", self._bounds(year, month)[0]),
            ("payslip_run_id.date_start", "<=", self._bounds(year, month)[1]),
        ], limit=1)
        if claim and claim.state != "done":
            stage = {
                "draft": "заяву не подано", "confirmed": "заяву не подано",
                "submitted": "ПФУ ще не прийняв заяву",
                "rejected": "ПФУ відмовив: %s" % (claim.reject_reason or ""),
                "accepted": "кошти від ПФУ не надійшли",
                "funded_partial": "профінансовано частково, залишок %s" % self._money(claim.unfunded),
                "funded": "допомогу не виплачено працівникам",
                "paid": "повідомлення не подано, строк %s" % (
                    claim.notice_deadline.strftime("%d.%m.%Y") if claim.notice_deadline else ""),
                "notified": "заяву не завершено",
            }.get(claim.state, claim.state)
            out.append({"title": "Фінансування ПФУ", "detail": stage, "level": "warning",
                        "action": {"model": "ua.pfu.claim", "res_id": claim.id}, "key": "pfu"})
        # Анкета компанії: поки є обов'язкові питання без відповіді, реальний розрахунок
        # робити рано. Модуль анкети необов'язковий, тому перевіряємо його наявність.
        if "ua.setup.profile" in self.env:
            profile = self.env["ua.setup.profile"].search([("company_id", "=", company.id)], limit=1)
            if profile and profile.required_missing:
                out.append({"title": "Анкета компанії",
                            "detail": "%s обов'язкових питань без відповіді" % profile.required_missing,
                            "level": "danger",
                            "action": {"model": "ua.setup.profile", "res_id": profile.id},
                            "key": "setup"})
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
                    "action": "payslips", "label": "Затвердити розрахунок", "tone": "warn"}
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


    # ------------------------------------------------------------------ люди і суми
    CATEGORY_ORDER = ("BASIC", "ALW", "AVG", "MAT", "NOTAX", "NOESV", "GROSS", "DED", "NET", "COMP")
    SLIP_STATE = {"draft": "чернетка", "verify": "перевірено", "done": "проведено", "cancel": "скасовано"}

    def _payment_state(self, company, first, last):
        """Стан виплати за працівником: у якій відомості і чи позначена оплаченою."""
        batches = self.env["ua.payment.batch"].search([
            ("company_id", "=", company.id), ("year", "=", first.year), ("month", "=", first.month),
        ])
        out = {}
        for batch in batches:
            for line in batch.line_ids.filtered("employee_id"):
                current = out.get(line.employee_id.id)
                if current and current["paid"]:
                    continue
                out[line.employee_id.id] = {"batch": batch.name, "batch_id": batch.id,
                                            "paid": batch.state == "paid",
                                            "amount": self._money(line.amount)}
        return out

    @api.model
    def get_people(self, year=None, month=None):
        """Рядок на працівника: час, нараховано, до виплати, ЄСВ, стан листка і виплати."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        payments = self._payment_state(company, first, last)
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)], limit=1)
        by_employee = {line.employee_id.id: line for line in sheet.line_ids} if sheet else {}
        rows = []
        for slip in self._slips(company, first, last).sorted(lambda s: s.employee_id.name or ""):
            employee = slip.employee_id
            lines = {line.code: line.total for line in slip.line_ids}
            time_line = by_employee.get(employee.id)
            flags = []
            if not employee.sudo()._ua_payment_account():
                flags.append("немає рахунку")
            if time_line and abs(time_line.diff_days) > 0.01:
                flags.append("відхилення в табелі %s дн" % self._money(time_line.diff_days).replace(",00", ""))
            payment = payments.get(employee.id)
            rows.append({
                "employee_id": employee.id,
                "name": employee.name,
                "job": employee.job_title or "",
                "department": employee.department_id.name or "",
                "days": self._money(time_line.days_worked).replace(",00", "") if time_line else "",
                "gross": self._money(lines.get("GROSS", 0.0)),
                "net": self._money(lines.get("NET", 0.0)),
                "esv": self._money(lines.get("ESV", 0.0)),
                "state": self.SLIP_STATE.get(slip.state, slip.state),
                "done": slip.state == "done",
                "payment": (payment["batch"] if payment else ""),
                "paid": bool(payment and payment["paid"]),
                "flags": flags,
            })
        return rows

    @api.model
    def get_person(self, employee_id, year=None, month=None):
        """Картка працівника за місяць: рядки розрахунку, події, виплата."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        employee = self.env["hr.employee"].browse(int(employee_id))
        slip = self._slips(company, first, last).filtered(lambda s: s.employee_id == employee)[:1]
        lines = []
        if slip:
            order = {code: index for index, code in enumerate(self.CATEGORY_ORDER)}
            for line in slip.line_ids.sorted(lambda l: (order.get(l.category_id.code, 99), l.sequence)):
                if not line.total:
                    continue
                lines.append({"code": line.code, "name": line.name,
                              "category": line.category_id.name or "",
                              "amount": self._money(line.total)})
        events = []
        for order_doc in self.env["ua.hr.order"].search([
                ("employee_id", "=", employee.id), ("date", ">=", first), ("date", "<=", last)]):
            events.append({"title": order_doc.name or order_doc.display_name,
                           "detail": dict(order_doc._fields["order_type"].selection).get(order_doc.order_type, ""),
                           "model": "ua.hr.order", "id": order_doc.id})
        for leave in self.env["hr.leave"].search([
                ("employee_id", "=", employee.id), ("state", "=", "validate"),
                ("request_date_from", "<=", last), ("request_date_to", ">=", first)]):
            events.append({"title": leave.holiday_status_id.name or "",
                           "detail": "%s - %s" % (leave.request_date_from.strftime("%d.%m"),
                                                  leave.request_date_to.strftime("%d.%m")),
                           "model": "hr.leave", "id": leave.id})
        payment = self._payment_state(company, first, last).get(employee.id)
        return {
            "employee_id": employee.id,
            "name": employee.name,
            "job": employee.job_title or "",
            "department": employee.department_id.name or "",
            "slip_id": slip.id if slip else False,
            "state": self.SLIP_STATE.get(slip.state, slip.state) if slip else "листка немає",
            "lines": lines,
            "events": events,
            "payment": payment or {},
        }

    @api.model
    def action_open_person(self, employee_id, slip_id=None):
        if slip_id:
            return {"type": "ir.actions.act_window", "res_model": "hr.payslip", "res_id": int(slip_id),
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        return {"type": "ir.actions.act_window", "res_model": "hr.employee", "res_id": int(employee_id),
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

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
                         "saldo_credit": self._money(-balance) if balance < 0 else "",
                         "model": "account.move.line",
                         "domain": [("account_id", "in", accounts.ids),
                                    ("move_id.state", "=", "posted"),
                                    ("date", ">=", str(first)), ("date", "<=", str(last))]})
        return rows

    # ------------------------------------------------------------------ довідка
    # Пояснення кроків місяця для режиму підказок. Що це, коли готово, що далі.
    STEP_HELP = {
        "orders": {
            "what": "Накази місяця: прийняття, звільнення, зміна окладу, відпустки.",
            "done": "Готово, коли чернеток немає.",
            "next": "Проведений наказ сам змінює договір працівника і рядки його листка.",
        },
        "timesheet": {
            "what": "Дні і години кожного працівника. Норма береться з графіка, факт правите вручну.",
            "done": "Готово, коли табель затверджено.",
            "next": "«Перерахувати листки» в табелі переносить факт у листки.",
        },
        "advance": {
            "what": "Виплата за першу половину місяця за відсотком окладу.",
            "done": "Готово, коли авансову відомість затверджено.",
            "next": "Сума авансу віднімається в листку при остаточному розрахунку.",
        },
        "payslips": {
            "what": "Листок на кожного працівника: нарахування, ПДФО 18 %, військовий збір 5 %, ЄСВ 22 %.",
            "done": "Готово, коли всі листки затверджено.",
            "next": "Затвердження створює проводки і рядки для відомості на виплату.",
        },
        "moves": {
            "what": "Проводки з листків на рахунки 661, 641, 651.",
            "done": "Готово, коли дебет дорівнює кредиту і чернеток немає.",
            "next": "Обороти видно на екрані «Зведення».",
        },
        "payment": {
            "what": "Відомість на перерахування і файл для банку.",
            "done": "Готово, коли відомість позначено оплаченою.",
            "next": "Оплату підтверджує рядок виписки на кроці «Звірка банку».",
        },
        "bank": {
            "what": "Рядки виписки за місяць зіставляються з виплатами і податками.",
            "done": "Готово, коли незвірених рядків за місяць немає.",
            "next": "Звірений рядок закриває платіж на смузі строків.",
        },
        "changes": {
            "what": "Журнал кожної зміни суми, часу або стану після розрахунку: було, стало, хто.",
            "done": "Готово, коли всі зміни прийнято.",
            "next": "Без цього кроку місяць не закривається.",
        },
        "reporting": {
            "what": "Податковий розрахунок J0500111 з додатками Д1, 4ДФ і Д5.",
            "done": "Готово, коли розрахунок позначено поданим.",
            "next": "Строк подання - 20 днів після кінця місяця.",
        },
    }

    def _first_steps(self, company, year, month):
        """Перші кроки для нової компанії. Кожен пункт перевіряє справжні дані."""
        Employee = self.env["hr.employee"]
        steps = []

        def item(key, title, done, fact, action):
            steps.append({"key": key, "title": title, "done": bool(done), "fact": fact, "action": action})

        missing = [label for field, label in (
            ("company_registry", "ЄДРПОУ"), ("ua_sti_code", "код ДПІ"),
            ("ua_director_name", "керівник"), ("ua_accountant_name", "головний бухгалтер"),
        ) if field in company._fields and not company[field]]
        item("company", "Реквізити компанії", not missing,
             "заповнено" if not missing else "бракує: %s" % ", ".join(missing),
             {"model": "res.company", "res_id": company.id})

        if "ua.setup.profile" in self.env:
            profile = self.env["ua.setup.profile"].search([("company_id", "=", company.id)], limit=1)
            left = profile.required_missing if profile else None
            item("setup", "Анкета компанії", profile and not left,
                 "не почато" if not profile else ("усі обов'язкові відповіді є" if not left else "%s обов'язкових питань без відповіді" % left),
                 {"xmlid": "l10n_ua_setup.action_ua_setup_board"})

        first, _last = self._bounds(year, month)
        min_wage = self.env["ua.payroll.param"].search([("key", "=", "min_wage"), ("valid_from", "<=", str(first)),
                                                         ("valid_from", ">=", "%s-01-01" % year)], limit=1)
        item("params", "Законодавчі числа на %s рік" % year, min_wage,
             "мінімальна зарплата %s" % self._money(min_wage.value) if min_wage else "немає мінімальної зарплати на рік",
             {"xmlid": "l10n_ua_payroll_rules.action_ua_payroll_param"})

        if "ua.cpi.index" in self.env:
            py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
            cpi = self.env["ua.cpi.index"].sudo().search_count([("year", "=", py), ("month", "=", pm)])
            item("cpi", "Індекс цін за %s %s" % (MONTHS_UA[pm], py), cpi,
                 "внесено" if cpi else "немає - індексація рахується як нуль",
                 {"xmlid": "l10n_ua_index.action_ua_cpi_index"})

        employees = Employee.search([("company_id", "=", company.id), ("active", "=", True)])
        no_code = employees.filtered(lambda e: "ua_rnokpp" in e._fields and not e.ua_rnokpp)
        item("employees", "Працівники", employees and not no_code,
             "немає - почніть з імпорту" if not employees else ("%s працівників" % len(employees) +
                                                            (", без РНОКПП: %s" % len(no_code) if no_code else "")),
             {"xmlid": "l10n_ua_onboarding.action_ua_employee_import"} if not employees
             else {"xmlid": "hr.open_view_employee_list_my"})

        no_terms = employees.filtered(lambda e: not e.resource_calendar_id or not (e.version_id and e.version_id.wage))
        item("terms", "Оклади і графіки", employees and not no_terms,
             "у всіх працівників" if employees and not no_terms else "без окладу або графіка: %s" % len(no_terms),
             {"xmlid": "hr.open_view_employee_list_my"})

        banks = company.partner_id.bank_ids
        item("bank", "Рахунок компанії в банку", banks,
             ", ".join(banks.mapped("acc_number"))[:40] if banks else "немає рахунку",
             {"xmlid": "l10n_ua_bank_online.action_ua_bank_board"})

        run = self.env["hr.payslip.run"].search_count([("company_id", "=", company.id)])
        item("first_month", "Перший розрахунок", run,
             "є пакет листків" if run else "ще не рахували",
             {"xmlid": "payroll.action_hr_payslip_run_tree"})
        return steps

    # ------------------------------------------------------------------ документи кроків
    def _doc(self, kind, name, report=None, records=None, deadline=None, target=None, state=None, checks=None):
        """Документ біля кроку місяця.

        kind: print - друкується; filing - подається в держорган; file - машинний файл.
        report + ids відкривають перегляд /ua/print, target - запис, де документ ведуть.
        checks_available - чи рахує запис перевірки (ua.checks.mixin._checks()); самі перевірки
        board більше не рахує на завантаженні - фронт бере їх лениво через get_doc_checks,
        коли відкриває перегляд саме цього документа (раніше board рахував checks() для
        КОЖНОГО документа кожного кроку при кожному завантаженні сторінки).
        """
        ids = records.ids if records else []
        checks_available = bool(records and len(records) == 1 and "_checks" in dir(records))
        return {"kind": kind, "name": name, "report": report or "", "ids": ids,
                "deadline": deadline.strftime("%d.%m.%Y") if deadline else "",
                "target": target or {}, "state": state or "",
                "checks_available": checks_available}

    @api.model
    def get_doc_checks(self, model, res_id):
        """Перевірки одного документа, порахувані лише коли фронт відкриває його перегляд."""
        record = self.env[model].browse(int(res_id))
        if not record.exists() or "_checks" not in dir(record):
            return []
        try:
            return record._checks()
        except Exception:
            return []

    @staticmethod
    def _doc_state(records):
        states = set(records.mapped("state")) if records and "state" in records._fields else set()
        if not records:
            return "немає"
        if states <= {"draft", "verify"}:
            return "чернетка"
        return "створено"

    def _documents(self, company, year, month, first, last):
        """Документи, які породжує кожен крок місяця. Ключ - ключ кроку."""
        out = {}
        Order = self.env["ua.hr.order"]
        orders = Order.search([("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
                               ("state", "!=", "cancel")])
        docs = []
        if orders:
            docs.append(self._doc("print", "Накази · %s" % len(orders), "l10n_ua_hr_orders.report_ua_hr_order", orders,
                                  state=self._doc_state(orders)))
        if "ua.military.notice" in self.env:
            notices = self.env["ua.military.notice"].search([("company_id", "=", company.id),
                                                            ("date_from", "<=", last), ("date_to", ">=", first)])
            for notice in notices:
                docs.append(self._doc("filing", "Повідомлення ТЦК", "l10n_ua_military.report_ua_military_notice", notice,
                                      deadline=notice.date_to + timedelta(days=7),
                                      target={"model": "ua.military.notice", "res_id": notice.id},
                                      state=self._doc_state(notice)))
        out["orders"] = docs

        sheet = self.env["ua.timesheet.sheet"].search([("company_id", "=", company.id), ("year", "=", year),
                                                       ("month", "=", month), ("department_id", "=", False)], limit=1)
        out["timesheet"] = [self._doc("print", "Табель П-5", "l10n_ua_hr_docs.report_ua_timesheet", sheet,
                                      target={"model": "ua.timesheet.sheet", "res_id": sheet.id},
                                      state=self._doc_state(sheet))] if sheet else []

        advance = self.env["ua.advance.sheet"].search([("company_id", "=", company.id), ("year", "=", year),
                                                       ("month", "=", month)], limit=1)
        out["advance"] = [self._doc("print", "Авансова відомість", "l10n_ua_payroll_reports.report_ua_advance_sheet",
                                    advance, target={"model": "ua.advance.sheet", "res_id": advance.id},
                                    state=self._doc_state(advance))] if advance else []

        slips = self.env["hr.payslip"].search([("company_id", "=", company.id), ("date_from", ">=", first),
                                               ("date_from", "<=", last), ("state", "!=", "cancel")])
        run = self.env["hr.payslip.run"].search([("company_id", "=", company.id), ("date_start", ">=", first),
                                                 ("date_start", "<=", last)], limit=1)
        docs = []
        if slips:
            docs.append(self._doc("print", "Розрахункові листки · %s" % len(slips),
                                  "l10n_ua_payroll_reports.report_ua_payslip", slips, state=self._doc_state(slips)))
        if run:
            docs.append(self._doc("print", "Розрахунково-платіжна відомість",
                                  "l10n_ua_payroll_reports.report_ua_payroll_sheet", run,
                                  target={"model": "hr.payslip.run", "res_id": run.id},
                                  state=self._doc_state(slips)))
        out["payslips"] = docs

        batches = self.env["ua.payment.batch"].search([("company_id", "=", company.id), ("year", "=", year),
                                                       ("month", "=", month)])
        docs = []
        for batch in batches:
            docs.append(self._doc("print", batch.name, "l10n_ua_payments.report_ua_payment_batch", batch,
                                  target={"model": "ua.payment.batch", "res_id": batch.id},
                                  state=self._doc_state(batch)))
            docs.append(self._doc("file", "Файл для банку · %s" % batch.name,
                                  target={"model": "ua.payment.batch", "res_id": batch.id}))
        out["payment"] = docs

        deadline = last + timedelta(days=20)
        docs = []
        run_j05 = self.env["ua.report.run"].search([("company_id", "=", company.id), ("report_code", "=", "j05"),
                                                    ("year", "=", year), ("month", "=", month)], limit=1)
        docs.append(self._doc("filing", "J0500111 · Д1, 4ДФ, Д5", deadline=deadline,
                              target={"xmlid": "l10n_ua_reporting.action_ua_reporting"},
                              state={"submitted": "подано", "generated": "сформовано"}.get(run_j05.state, "чернетка")
                              if run_j05 else "немає"))
        claims = self.env["ua.pfu.claim"].search([("company_id", "=", company.id),
                                                  ("payslip_run_id.date_start", ">=", first),
                                                  ("payslip_run_id.date_start", "<=", last)])
        for claim in claims:
            docs.append(self._doc("filing", "Заява-розрахунок ПФУ", "l10n_ua_hr_docs.report_ua_pfu_claim", claim,
                                  deadline=deadline, target={"model": "ua.pfu.claim", "res_id": claim.id},
                                  state=self._doc_state(claim)))
        out["reporting"] = docs
        return out

    def _deadlines(self, company, year, month):
        """Смуга строків: платежі і подання навколо місяця, за датою."""
        state_map = {"ok": "ok", "warn": "warn", "todo": "crit", "plan": "todo"}
        rows = []
        import re
        for row in self.env["ua.dashboard"]._get_payments(company, year, month):
            # квартальний рядок - залишок старої схеми; розрахунок подається щомісяця
            if not row.get("date") or "квартал" in row["label"]:
                continue
            label = re.sub(r",\s*\S+\s+\d{4}", "", row["label"]).replace(" (остаточний розрахунок)", "")
            rows.append({"date": row["date"], "label": label, "state": state_map.get(row.get("state_class"), "todo")})
        first, last = self._bounds(year, month)
        rows.append({"date": (last + timedelta(days=20)).strftime("%d.%m.%Y"),
                     "label": "Податковий розрахунок", "state": "todo"})

        def key(r):
            d, m, y = r["date"].split(".")
            return (y, m, d)
        rows.sort(key=key)
        # однакові дати зливаються в одну позначку
        merged = []
        for r in rows:
            if merged and merged[-1]["date"] == r["date"]:
                merged[-1]["label"] += " · " + r["label"]
                if r["state"] in ("crit", "warn") and merged[-1]["state"] not in ("crit",):
                    merged[-1]["state"] = r["state"]
            else:
                merged.append(dict(r))
        today = fields.Date.context_today(self).strftime("%Y%m%d")
        for r in merged:
            d, m, y = r["date"].split(".")
            r["past"] = y + m + d < today
        return merged

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
            "documents": self._documents(company, year, month, first, last),
            "first_steps": self._first_steps(company, year, month),
            "help": self.STEP_HELP,
            "deadlines": self._deadlines(company, year, month),
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

    @staticmethod
    def _decode_period(ids, year, month):
        """Рік і місяць: прямий виклик (odoo shell, action_headline) дає їх окремо.

        Кнопки, підключені через ua_act (l10n_ua_shell), звуть план-метод без жодних
        kwargs (сервіс так влаштований: docs/payroll/action-model.md, «Як
        користуватися»), тому клієнт (period.js) пакує рік і місяць в один-єдиний
        параметр id, який RPC доносить сюди як список з одним числом - рік*100+місяць.
        Виклик із kwargs (є рік і місяць) завжди має перевагу над запакованим ids.
        """
        if year is not None and month is not None:
            return int(year), int(month)
        code = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        return divmod(int(code), 100)

    @api.model
    def action_accept_changes(self, ids=False, year=None, month=None):
        """Прийняти всі нові зміни місяця.

        Клас «узгодження» (action-model.md): без плану, зі скасуванням 20 с -
        action_undo_accept_changes нижче справді повертає щойно прийняті рядки
        назад у стан «нова», а не просто ховає повідомлення."""
        year, month = self._decode_period(ids, year, month)
        company = self._company()
        n = self.env["ua.change.log"].accept_period(year, month)
        text = _("Прийнято змін: %s.") % n if n else _("Приймати не було чого: нових змін немає.")
        return {"done": [{
            "text": text,
            "target": {"model": "ua.change.log",
                      "domain": [("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)]},
        }]}

    @api.model
    def action_undo_accept_changes(self, ids=False, year=None, month=None):
        """Скасування «Прийняти всі зміни»: чесний відкат тих самих рядків журналу назад
        у «нова», не приховування результату (action-model.md, «Вікно скасування»).

        ua_act кличе цей метод без жодних kwargs (лише ids), тому які рядки повертати
        назад визначаємо за вікном часу: прийняті цим користувачем за останні 25 с -
        з запасом над 20-секундною смугою скасування на екрані."""
        year, month = self._decode_period(ids, year, month)
        since = fields.Datetime.now() - timedelta(seconds=25)
        rows = self.env["ua.change.log"].search([
            ("company_id", "=", self._company().id), ("year", "=", year), ("month", "=", month),
            ("state", "=", "accepted"), ("accepted_user_id", "=", self.env.uid),
            ("accepted_date", ">=", since),
        ])
        rows.action_reset()
        return True

    @api.model
    def action_close_month_plan(self, ids=False, year=None, month=None):
        """План перед закриттям місяця (action-model.md, клас «проведення»).

        Читає ті самі перевірки, що й ua.period.close.blockers()/close_period() -
        не викликає їх, а дзеркалить: кожна перешкода тут стає рядком рівня "crit"
        із ціллю, що відкриває саме ті записи, які заважають, щоб їх можна було
        поправити просто з діалогу."""
        year, month = self._decode_period(ids, year, month)
        company = self._company()
        first, last = self._bounds(year, month)
        Close = self.env["ua.period.close"]
        rec = Close.search([("company_id", "=", company.id), ("year", "=", year),
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

        new_changes = self.env["ua.change.log"].count_new(company, year, month)
        if new_changes:
            lines.append({
                "text": _("У журналі змін %s непереглянутих рядків - спершу прийміть їх.") % new_changes,
                "level": "crit",
                "target": {"model": "ua.change.log",
                          "domain": [("company_id", "=", company.id), ("year", "=", year),
                                     ("month", "=", month), ("state", "=", "new")]},
            })

        drafts = self.env["account.move"].search([
            ("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
            ("state", "=", "draft"),
        ])
        if drafts:
            lines.append({
                "text": _("Чернеток проводок місяця: %s - їх треба провести або скасувати.") % len(drafts),
                "level": "crit",
                "target": {"model": "account.move", "domain": [("id", "in", drafts.ids)]},
            })

        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "not in", ("done", "cancel")),
        ])
        if slips:
            lines.append({
                "text": _("Непроведених листків: %s.") % len(slips),
                "level": "crit",
                "target": {"model": "hr.payslip", "domain": [("id", "in", slips.ids)]},
            })

        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if sheet and sheet.state != "confirmed":
            lines.append({
                "text": _("Табель місяця не затверджено."),
                "level": "crit",
                "target": {"model": "ua.timesheet.sheet", "res_id": sheet.id},
            })

        has_blockers = any(l["level"] == "crit" for l in lines)
        if has_blockers:
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

    @api.model
    def action_close_month(self, ids=False, year=None, month=None, hard=False):
        """Закрити місяць: перевірити блокери і поставити дату блокування.

        Перешкоди перевіряє ua.period.close.close_period() - і відмовляє (UserError),
        якщо вони є, навіть якщо діалог плану якось обійшли."""
        year, month = self._decode_period(ids, year, month)
        close_id = self.env["ua.period.close"].close_period(year, month, hard)
        rec = self.env["ua.period.close"].browse(close_id)
        return {"done": [{
            "text": _("Місяць %s закрито: дата блокування обліку %s.") % (
                rec.name, rec.lock_date.strftime("%d.%m.%Y") if rec.lock_date else ""),
            "target": {"model": "ua.period.close", "res_id": close_id},
        }]}

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
