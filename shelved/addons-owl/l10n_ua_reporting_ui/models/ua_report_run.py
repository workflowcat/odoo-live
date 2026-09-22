# -*- coding: utf-8 -*-
"""Дані екрана «Звітність»: розширення ua.report.run і ua.report.check формувальниками.

Сама звітність - перевірки, формування файлів, стани прогону, коригування - лишилась
у l10n_ua_reporting і працює без цього модуля. Тут живе тільки те, що надає форму
одному екранові: смуга періодів, історія прогонів, словник прогону, таблиця «Дані»
і перелік додатків. Жоден метод нижче нічого не пише і нічого не вирішує.

Помічники, якими користуються і перевірки (_m, _month_range, _account_by_code,
_turnover, _balance_before, _slip_amount, _period_bounds), лишились у логіці: таблиця
«Дані» кличе їх звідти, щоб число на екрані рахувалось тим самим кодом, що й перевірка.
"""
import base64
import calendar
import json
from datetime import date

from odoo import api, fields, models

from odoo.addons.l10n_ua_screen.models.ua_screen import MONTHS_UA

from odoo.addons.l10n_ua_reporting.models.ua_report_run import (
    APPENDIX_LABELS,
    PAYROLL_ACCOUNTS,
    PERIOD_TYPE,
    REPORTS,
    ROWNUM_RE,
)


class UaReportRun(models.Model):
    _inherit = "ua.report.run"

    def _periods_for(self, report_code, company):
        today = fields.Date.context_today(self)
        out = []
        if report_code in ("j05", "j30", "pfu", "timesheet", "trial", "ledger"):
            y, m = today.year, today.month
            for _i in range(6):
                out.append({"key": "%s-%02d" % (y, m), "label": "%s %s" % (MONTHS_UA.get(m, "").capitalize(), y), "year": y, "month": m})
                m -= 1
                if m == 0:
                    m, y = 12, y - 1
        elif report_code == "orders":
            y = today.year
            for _i in range(6):
                out.append({"key": str(y), "label": "%s рік" % y, "year": y})
                y -= 1
        elif report_code == "staff":
            existing = self.env["ua.staff.list"].search([("company_id", "=", company.id)], order="date desc", limit=5).mapped("date")
            dates = sorted(set(existing) | {today}, reverse=True)[:6]
            for d in dates:
                out.append({"key": d.isoformat(), "label": d.strftime("%d.%m.%Y"), "year": d.year, "date": d.isoformat()})
        out.reverse()
        for p in out:
            key = p["key"]
            run = self.search([("report_code", "=", report_code), ("company_id", "=", company.id), ("period_key", "=", key)], limit=1)
            p["run_id"] = run.id if run else False
            p["state"] = run.state if run else False
        return out

    @api.model
    def _history(self, report_code, company):
        if not report_code:
            return []
        runs = self.search([("report_code", "=", report_code), ("company_id", "=", company.id)], order="id desc", limit=10)
        return [{"id": r.id, "name": r.name, "state": r.state, "files": len(r.attachment_ids)} for r in runs]

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, run_id=None, report_code=None, year=None, quarter=None, month=None, date=None):
        """Дані екрана. Читання: ні create, ні write.

        Якщо на обраний період прогону ще немає, віддаємо його в пам'яті (`new`) -
        назва, дані і додатки рахуються так само, а запису в базі немає і його id
        порожній. Запис створює лише `ensure_run`, який клієнт кличе на дію бухгалтера."""
        company = self.env.company
        today = fields.Date.context_today(self)
        run = self.browse(run_id).exists() if run_id else self.browse()
        if not run:
            report_code = report_code or REPORTS[0][0]
            y = int(year) if year else today.year
            q = int(quarter) if quarter else ((today.month - 1) // 3 + 1)
            m = int(month) if month else today.month
            d_ = fields.Date.to_date(date) if date else today
            run = self._find_run(report_code, company, y, quarter=q, month=m, date_=d_)
            if not run:
                run = self.new(self._run_vals(report_code, company, y, q, m, d_))
        reports = [{"code": code, "name": name, "period_type": PERIOD_TYPE[code]} for code, name in REPORTS]
        periods = self._periods_for(run.report_code, company)
        return {
            "reports": reports,
            "periods": periods,
            "run": run._screen_data(),
            "checks": [c._screen_data() for c in run.check_ids],
            "summary": run._summary(),
            "appendices": run._appendices(),
            "history": self._history(run.report_code, company),
        }

    def _screen_data(self):
        self.ensure_one()
        return {
            # id порожній у прогону, якого ще немає в базі (екран відкрито на місяць
            # без прогону) - клієнт на дії кличе ensure_run і дістає справжній id.
            "id": self._origin.id or False, "name": self.name, "report_code": self.report_code, "state": self.state,
            "year": self.year, "quarter": self.quarter or False, "month": self.month or False,
            "date": self.date.isoformat() if self.date else False,
            "submitted_date": self.submitted_date.isoformat() if self.submitted_date else False,
            "submitted_by": self.submitted_by.name or "",
            "doc_kind": self.doc_kind,
            "doc_kind_label": dict(self._fields["doc_kind"].selection).get(self.doc_kind, ""),
            "base_run": self.base_run_id.name or "",
            "corrections": [{"id": r._origin.id or False, "name": r.name, "state": r.state}
                            for r in self.correction_ids],
            "can_correct": self.report_code == "j05" and self.state in ("generated", "submitted"),
            "files": [{"id": a.id, "name": a.name, "mimetype": a.mimetype} for a in self.attachment_ids],
            "receipts": [{"id": a.id, "name": a.name, "mimetype": a.mimetype} for a in self.receipt_ids],
            "note": self.note or "",
        }

    def _appendices(self):
        self.ensure_one()
        if self.report_code != "j05":
            return []
        rows = []
        for att in self.attachment_ids.filtered(lambda a: a.name and a.name.upper().endswith(".XML")):
            sub = next((s for s in APPENDIX_LABELS if ("J05%s" % s) in att.name), None)
            label = APPENDIX_LABELS.get(sub, att.name)
            content = base64.b64decode(att.datas or b"")
            nums = ROWNUM_RE.findall(content)
            row_count = max((int(n) for n in nums), default=0)
            rows.append({"attachment_id": att.id, "name": att.name, "label": label, "rows": row_count, "state": "сформовано"})
        return rows


    def _summary(self):
        self.ensure_one()
        method = getattr(self, "_summary_%s" % self.report_code, None)
        data = method() if method else {"columns": [], "rows": [], "total": None}
        data.setdefault("money", [])
        data.setdefault("targets", [])
        # targets вирівнюємо по rows: клік по рядку веде в запис, який правлять
        rows = data.get("rows") or []
        targets = list(data["targets"])
        while len(targets) < len(rows):
            targets.append(False)
        data["targets"] = targets[:len(rows)]
        return data

    def _slip_target(self, d1, d2, employee=None, name=""):
        """Ціль кліку: листки періоду, за потреби одного працівника."""
        domain = [("company_id", "=", self.company_id.id),
                  ("date_from", ">=", str(d1)), ("date_from", "<=", str(d2)),
                  ("state", "!=", "cancel")]
        if employee:
            domain.append(("employee_id", "=", employee.id))
        return {"model": "hr.payslip", "domain": domain, "name": name or "Листки"}


    def _summary_accounting(self):
        d1, d2 = self._month_range()
        columns = ["Рахунок", "Назва", "Сальдо на початок", "Дебет", "Кредит", "Сальдо на кінець"]
        rows, targets = [], []
        codes = [c[0] for c in PAYROLL_ACCOUNTS] + ["311", "301", "471", "378", "6851", "92", "93", "23", "91"]
        seen = set()
        for code in codes:
            if code in seen:
                continue
            seen.add(code)
            account = self._account_by_code(code)
            if not account:
                continue
            debit, credit = self._turnover(account, d1, d2)
            if not debit and not credit:
                continue
            opening = self._balance_before(account, d1)
            rows.append([account.code, account.name, opening, debit, credit, round(opening + debit - credit, 2)])
            targets.append({"model": "account.move.line",
                            "domain": [("account_id", "=", account.id), ("parent_state", "=", "posted"),
                                       ("date", ">=", str(d1)), ("date", "<=", str(d2)),
                                       ("company_id", "=", self.company_id.id)],
                            "name": "%s %s" % (account.code, account.name)})
        total = ["Разом", "", round(sum(r[2] for r in rows), 2), round(sum(r[3] for r in rows), 2),
                 round(sum(r[4] for r in rows), 2), round(sum(r[5] for r in rows), 2)] if rows else None
        return {"columns": columns, "rows": rows, "total": total, "money": [2, 3, 4, 5], "targets": targets}

    def _summary_trial(self):
        return self._summary_accounting()

    def _summary_ledger(self):
        return self._summary_accounting()


    def _summary_j05(self):
        c = self.company_id
        columns = ["Місяць", "Осіб", "Нараховано", "ПДФО", "ВЗ", "ЄСВ"]
        rows, targets = [], []
        totals = {"employees": 0, "gross": 0.0, "pdfo": 0.0, "vz": 0.0, "esv": 0.0}
        for m in self._report_months():
            d1, d2 = date(self.year, m, 1), date(self.year, m, calendar.monthrange(self.year, m)[1])
            slips = self.env["hr.payslip"].search([("company_id", "=", c.id), ("state", "=", "done"), ("date_from", ">=", d1), ("date_to", "<=", d2)])
            lines = slips.mapped("line_ids")
            row = {
                "employees": len(slips.mapped("employee_id")),
                "gross": round(sum(lines.filtered(lambda l: l.code == "GROSS").mapped("total")), 2),
                "pdfo": round(abs(sum(lines.filtered(lambda l: l.code == "PDFO").mapped("total"))), 2),
                "vz": round(abs(sum(lines.filtered(lambda l: l.code == "VZ").mapped("total"))), 2),
                "esv": round(sum(lines.filtered(lambda l: l.code == "ESV").mapped("total")), 2),
            }
            rows.append(["%s %s" % (MONTHS_UA.get(m, "").capitalize(), self.year), row["employees"], row["gross"], row["pdfo"], row["vz"], row["esv"]])
            targets.append(self._slip_target(d1, d2, name="Листки · %s %s" % (MONTHS_UA.get(m, ""), self.year)))
            for k in totals:
                totals[k] += row[k]
        total = ["Разом", totals["employees"], round(totals["gross"], 2), round(totals["pdfo"], 2), round(totals["vz"], 2), round(totals["esv"], 2)]
        return {"columns": columns, "rows": rows, "total": total, "money": [2, 3, 4, 5], "targets": targets}

    def _summary_j30(self):
        d1, d2 = self._period_bounds()
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", self.company_id.id), ("contract_date_start", ">=", d1), ("contract_date_start", "<=", d2)])
        rows = [[v.employee_id.name, v.contract_date_start.strftime("%d.%m.%Y"), v.job_title or v.ua_prof_name or "-"] for v in versions]
        targets = [{"model": "hr.employee", "res_id": v.employee_id.id, "name": v.employee_id.name} for v in versions]
        return {"columns": ["Працівник", "Дата прийняття", "Посада"], "rows": rows, "total": None, "targets": targets}

    def _summary_pfu(self):
        d1, d2 = self._period_bounds()
        run_rec = self.env["hr.payslip.run"].search([("company_id", "=", self.company_id.id), ("date_start", ">=", d1), ("date_start", "<=", d2)], limit=1)
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", run_rec.id)], limit=1) if run_rec else self.env["ua.pfu.claim"]
        kinds = dict(self.env["ua.pfu.claim.line"]._fields["kind"].selection)
        rows = [[l.employee_id.name, kinds.get(l.kind), l.sick_number or "-", l.days, round(l.amount, 2)] for l in claim.line_ids]
        targets = [self._slip_target(d1, d2, l.employee_id, l.employee_id.name) for l in claim.line_ids]
        total = ["Разом", "", "", sum(claim.line_ids.mapped("days")), round(sum(claim.line_ids.mapped("amount")), 2)] if claim and claim.line_ids else None
        return {"columns": ["Працівник", "Вид", "№ е-ЛН", "Днів", "Сума"], "rows": rows, "total": total,
                "money": [4], "targets": targets}

    def _summary_timesheet(self):
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company_id.id), ("year", "=", self.year), ("month", "=", self.month), ("department_id", "=", False)], limit=1)
        rows = [[l.employee_id.name, l.job_title or "-", l.days_worked, l.days_vac, l.days_sick, l.days_unpaid] for l in sheet.line_ids] if sheet else []
        targets = ([{"model": "ua.timesheet.sheet", "res_id": sheet.id, "name": "Табель"}] * len(rows)) if sheet else []
        total = (["Разом", "", sum(sheet.line_ids.mapped("days_worked")), sum(sheet.line_ids.mapped("days_vac")),
                 sum(sheet.line_ids.mapped("days_sick")), sum(sheet.line_ids.mapped("days_unpaid"))]
                if sheet and sheet.line_ids else None)
        return {"columns": ["Працівник", "Посада", "Р", "В", "ТН", "НА"], "rows": rows, "total": total,
                "targets": targets}

    def _summary_staff(self):
        sheet = self.env["ua.staff.list"].search([("company_id", "=", self.company_id.id), ("date", "=", self.date)], limit=1)
        rows = [[l.department_id.name or "-", l.job_title, l.kp_code or "-", l.units, round(l.wage, 2), round(l.fund, 2)] for l in sheet.line_ids] if sheet else []
        targets = ([{"model": "ua.staff.list", "res_id": sheet.id, "name": "Штатний розпис"}] * len(rows)) if sheet else []
        total = ["Разом", "", "", sheet.total_units, "", round(sheet.total_fund, 2)] if sheet and sheet.line_ids else None
        return {"columns": ["Підрозділ", "Посада", "Код КП", "Штат. один.", "Оклад", "Фонд"], "rows": rows,
                "total": total, "money": [4, 5], "targets": targets}

    def _summary_orders(self):
        d1, d2 = self._period_bounds()
        Order = self.env["ua.hr.order"]
        orders = Order.search([("company_id", "=", self.company_id.id), ("date", ">=", d1), ("date", "<=", d2)], order="date")
        type_labels = dict(Order._fields["order_type"].selection)
        state_labels = dict(Order._fields["state"].selection)
        rows = [[o.name or "-", o.date.strftime("%d.%m.%Y"), type_labels.get(o.order_type), o.employee_id.name, state_labels.get(o.state)] for o in orders]
        targets = [{"model": "ua.hr.order", "res_id": o.id, "name": o.name or "Наказ"} for o in orders]
        return {"columns": ["№", "Дата", "Вид", "Працівник", "Стан"], "rows": rows, "total": None, "targets": targets}



class UaReportCheck(models.Model):
    _inherit = "ua.report.check"

    def _screen_data(self):
        self.ensure_one()
        domain = []
        if self.target_domain:
            try:
                domain = json.loads(self.target_domain)
            except ValueError:
                domain = []
        return {
            "id": self.id, "sequence": self.sequence, "code": self.code, "title": self.title,
            "level": self.level, "detail": self.detail or "", "value": self.value or "",
            "target_model": self.target_model or "", "target_domain": domain, "target_res_id": self.target_res_id or False,
        }
