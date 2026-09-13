# -*- coding: utf-8 -*-
"""Дані для клієнтської дії «Зведення»: одна модель без збереження (AbstractModel),
один публічний метод get_data(year, month) - усе інше приватні хелпери.

Джерела: hr.payslip.run / hr.payslip / hr.payslip.line (коди GROSS, PDFO, VZ, ESV, NET, ADV_PAID),
hr.employee (ua_mil_needs_check, ua_docs_expiring, ua_rnokpp), ua.employee.document (valid_until),
account.bank.statement.line (is_reconciled, amount, payment_ref), hr.version (contract_date_end,
trial_date_end), ua.timesheet.sheet, ua.staff.list, ua.pfu.claim, ua.advance.sheet, ir.attachment
(вкладення XML).

Звірка з банком - за текстом payment_ref (немає прямого зв'язку листок <-> рядок виписки):
шаблони підпису рядків задає l10n_ua_bank/hooks.py, наприклад «Заробітна плата за серпень 2026,
остаточний розрахунок», «ПДФО з авансу за серпень 2026», «Єдиний внесок (ЄСВ) за серпень 2026».
Місяць в називному відмінку («серпень», «вересень») - для цих іменників він збігається зі
знахідним, який і вжито в текстах виписки після «за».
"""
from datetime import date, timedelta

from odoo import api, fields, models

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
PAYSLIP_CODES = ("GROSS", "PDFO", "VZ", "ESV", "NET", "ADV_PAID")


class UaDashboard(models.AbstractModel):
    _name = "ua.dashboard"
    _description = "Дані панелі «Зведення»"

    # ------------------------------------------------------------------ хелпери
    @staticmethod
    def _money(value):
        """Українське форматування: 710 887,13"""
        return "{:,.2f}".format(abs(value or 0.0)).replace(",", " ").replace(".", ",")

    @staticmethod
    def _plural(number, one, few, many):
        """Українське число: 1 файл, 2 файли, 5 файлів."""
        number = abs(int(number))
        if number % 10 == 1 and number % 100 != 11:
            return one
        if number % 10 in (2, 3, 4) and number % 100 not in (12, 13, 14):
            return few
        return many

    @staticmethod
    def _r2(value):
        return round(value or 0.0, 2)

    @staticmethod
    def _month_add(year, month, delta):
        m = month - 1 + delta
        return year + m // 12, m % 12 + 1

    @staticmethod
    def _month_bounds(year, month):
        import calendar
        from datetime import date
        d1 = date(year, month, 1)
        d2 = date(year, month, calendar.monthrange(year, month)[1])
        return d1, d2

    @staticmethod
    def _month_name(month):
        return MONTHS_UA.get(month, "")

    def _action_xmlid(self, xmlid):
        """Xmlid дії, якщо дія існує, інакше False. Клієнт відкриває її напряму."""
        return xmlid if self.env.ref(xmlid, raise_if_not_found=False) else False

    def _slip_domain(self, company, year, month, department_id=None):
        """Домен листків місяця - те, що стоїть за сумою в рядку панелі."""
        d1, d2 = self._month_bounds(year, month)
        dom = [
            ("company_id", "=", company.id),
            ("date_from", ">=", fields.Date.to_string(d1)),
            ("date_from", "<=", fields.Date.to_string(d2)),
            ("state", "!=", "cancel"),
        ]
        if department_id:
            dom.append(("employee_id.department_id", "=", department_id))
        elif department_id is False:
            dom.append(("employee_id.department_id", "=", False))
        return dom

    def _bank_domain(self, company, keyword, month, year):
        """Домен рядків виписки за тим самим підписом, що його читає _bank_status."""
        return [
            ("company_id", "=", company.id),
            ("payment_ref", "ilike", keyword),
            ("payment_ref", "ilike", "%s %s" % (self._month_name(month), year)),
        ]

    def _month_payslip_totals(self, company, year, month):
        d1, d2 = self._month_bounds(year, month)
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", d1), ("date_from", "<=", d2),
            ("state", "!=", "cancel"),
        ])
        lines = slips.mapped("line_ids")
        return {code: self._r2(sum(lines.filtered(lambda l: l.code == code).mapped("total"))) for code in PAYSLIP_CODES}

    def _bank_status(self, company, keyword, month, year):
        """Рядки виписки, чий payment_ref містить keyword і назву місяця/рік.
        Повертає (текст стану, state_class, остання дата) - keyword/місяць співставляються
        текстом, бо прямого зв'язку листок <-> рядок виписки в системі немає."""
        lines = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id),
            ("payment_ref", "ilike", keyword),
            ("payment_ref", "ilike", "%s %s" % (self._month_name(month), year)),
        ])
        if not lines:
            return "не сплачено", "todo", False
        last_date = max(lines.mapped("date"))
        if all(l.is_reconciled for l in lines):
            return "сплачено, звірено", "ok", last_date
        return "у виписці, не звірено", "warn", last_date

    # ------------------------------------------------------------------ секції
    def _get_company(self, company, year, month):
        return {
            "name": company.name,
            "edrpou": company.company_registry or "",
            "employee_count": self.env["hr.employee"].search_count([
                ("company_id", "=", company.id), ("active", "=", True),
            ]),
            "year": year,
            "month": month,
            "month_label": self._month_name(month).capitalize(),
        }

    def _get_periods(self, company, year, month):
        out = []
        y, m = year, month
        for _i in range(6):
            d1, d2 = self._month_bounds(y, m)
            has_run = bool(self.env["hr.payslip.run"].search_count([
                ("company_id", "=", company.id), ("date_start", ">=", d1), ("date_start", "<=", d2),
            ]))
            out.append({
                "year": y, "month": m,
                "label": "%s %s" % (self._month_name(m).capitalize(), y),
                "has_run": has_run,
            })
            y, m = self._month_add(y, m, -1)
        out.reverse()
        return out

    def _get_payroll_by_department(self, company, year, month):
        d1, d2 = self._month_bounds(year, month)
        run = self.env["hr.payslip.run"].search([
            ("company_id", "=", company.id), ("date_start", ">=", d1), ("date_start", "<=", d2),
        ], limit=1)
        if run:
            slips = run.slip_ids
        else:
            slips = self.env["hr.payslip"].search([
                ("company_id", "=", company.id), ("date_from", ">=", d1), ("date_from", "<=", d2),
                ("state", "!=", "cancel"),
            ])

        order = []
        by_dept = {}
        for slip in slips:
            dept = slip.employee_id.department_id
            key = dept.id
            row = by_dept.get(key)
            if row is None:
                row = by_dept[key] = {
                    "department": dept.name if dept else "Без підрозділу",
                    "department_id": dept.id if dept else False,
                    "employee_ids": set(), "gross": 0.0, "pdfo": 0.0, "vz": 0.0, "esv": 0.0, "net": 0.0,
                }
                order.append(key)
            row["employee_ids"].add(slip.employee_id.id)
            lines = slip.line_ids
            row["gross"] += sum(lines.filtered(lambda l: l.code == "GROSS").mapped("total"))
            row["pdfo"] += sum(lines.filtered(lambda l: l.code == "PDFO").mapped("total"))
            row["vz"] += sum(lines.filtered(lambda l: l.code == "VZ").mapped("total"))
            row["esv"] += sum(lines.filtered(lambda l: l.code == "ESV").mapped("total"))
            row["net"] += sum(lines.filtered(lambda l: l.code == "NET").mapped("total"))

        rows = []
        total = {"employees": 0, "gross": 0.0, "pdfo": 0.0, "vz": 0.0, "esv": 0.0, "net": 0.0}
        for key in order:
            row = by_dept[key]
            r = {
                "department": row["department"],
                "res_model": "hr.payslip",
                "domain": self._slip_domain(company, year, month, row["department_id"]),
                "title": "Листки · %s · %s %s" % (row["department"], self._month_name(month), year),
                "employees": len(row["employee_ids"]),
                "gross": self._r2(row["gross"]),
                "pdfo": self._r2(abs(row["pdfo"])),
                "vz": self._r2(abs(row["vz"])),
                "esv": self._r2(row["esv"]),
                "net": self._r2(row["net"]),
            }
            rows.append(r)
            total["employees"] += r["employees"]
            for k in ("gross", "pdfo", "vz", "esv", "net"):
                total[k] +=  r[k]
        for k in ("gross", "pdfo", "vz", "esv", "net"):
            total[k] =  self._r2(total[k])

        total["res_model"] = "hr.payslip"
        total["domain"] = self._slip_domain(company, year, month)
        total["title"] = "Листки · %s %s" % (self._month_name(month), year)
        return {
            "rows": rows,
            "total": total,
            "has_run": bool(run),
            "run_action": self._action_xmlid("payroll.hr_payslip_run_action"),
        }

    def _get_payments(self, company, year, month):
        ly, lm = self._month_add(year, month, -1)
        ny, nm = self._month_add(year, month, 1)
        last_name = self._month_name(lm)
        this_name = self._month_name(month)
        next_name = self._month_name(nm)
        last_totals = self._month_payslip_totals(company, ly, lm)
        rows = []

        state, cls, d = self._bank_status(company, "Заробітна плата", lm, ly)
        rows.append({
            "date": d.strftime("%d.%m.%Y") if d else False,
            "label": "Зарплата, %s %s" % (last_name, ly),
            "amount": abs(last_totals["NET"]), "state": state, "state_class": cls,
            "res_model": "account.bank.statement.line" if d else "hr.payslip",
            "domain": self._bank_domain(company, "Заробітна плата", lm, ly) if d
                      else self._slip_domain(company, ly, lm),
            "title": "Зарплата, %s %s" % (last_name, ly),
        })

        for code, keyword, label in (
            ("PDFO", "ПДФО", "ПДФО"),
            ("VZ", "Військовий збір", "Військовий збір"),
            ("ESV", "Єдиний внесок", "ЄСВ"),
        ):
            state, cls, d = self._bank_status(company, keyword, lm, ly)
            rows.append({
                "date": d.strftime("%d.%m.%Y") if d else False,
                "label": "%s, %s %s" % (label, last_name, ly),
                "amount": abs(last_totals[code]), "state": state, "state_class": cls,
                "res_model": "account.bank.statement.line" if d else "hr.payslip",
                "domain": self._bank_domain(company, keyword, lm, ly) if d
                          else self._slip_domain(company, ly, lm),
                "title": "%s, %s %s" % (label, last_name, ly),
            })

        adv = self.env["ua.advance.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if not adv or not adv.line_ids:
            rows.append({
                "date": False, "label": "Аванс, %s %s" % (this_name, year),
                "amount": 0.0, "state": "не розраховано", "state_class": "todo",
                "action": self._action_xmlid("l10n_ua_payroll_rules.action_ua_advance_sheet"),
                "res_model": "ua.advance.sheet",
                "domain": [("company_id", "=", company.id)],
                "title": "Відомості авансу",
            })
        else:
            if adv.state == "confirmed":
                bstate, bcls, bd = self._bank_status(company, "Аванс", month, year)
                date_val = bd or adv.pay_date
            else:
                bstate, bcls = "заплановано", "plan"
                date_val = adv.pay_date
            rows.append({
                "date": date_val.strftime("%d.%m.%Y") if date_val else False,
                "label": "Аванс, %s %s" % (this_name, year),
                "amount": self._r2(adv.total), "state": bstate, "state_class": bcls,
                "res_model": "ua.advance.sheet", "res_id": adv.id,
            })

        # планова виплата за поточний місяць: 6-те число наступного місяця (ст. 115 КЗпП)
        this_totals = self._month_payslip_totals(company, year, month)
        if this_totals["NET"]:
            pay_day = date(ny, nm, 6)
            slip_target = {
                "res_model": "hr.payslip",
                "domain": self._slip_domain(company, year, month),
                "title": "Листки · %s %s" % (this_name, year),
            }
            rows.append(dict(slip_target,
                date=pay_day.strftime("%d.%m.%Y"),
                label="Зарплата, %s %s (остаточний розрахунок)" % (this_name, year),
                amount=abs(this_totals["NET"]), state="планово", state_class="plan"))
            rows.append(dict(slip_target,
                date=pay_day.strftime("%d.%m.%Y"),
                label="ПДФО і ВЗ, %s %s" % (this_name, year),
                amount=abs(this_totals["PDFO"]) + abs(this_totals["VZ"]), state="планово", state_class="plan"))
            rows.append(dict(slip_target,
                date=date(ny, nm, 20).strftime("%d.%m.%Y"),
                label="ЄСВ, %s %s" % (this_name, year),
                amount=abs(this_totals["ESV"]), state="планово", state_class="plan"))

        quarter = (month - 1) // 3 + 1
        q_end_month = quarter * 3
        q_end = self._month_bounds(year, q_end_month)[1]
        deadline = q_end + timedelta(days=40)
        today = fields.Date.context_today(self)
        days_left = (deadline - today).days
        if days_left < 0:
            dstate, dcls = "прострочено", "warn"
        elif days_left <= 10:
            dstate, dcls = "наближається", "warn"
        else:
            dstate, dcls = "заплановано", "plan"
        rows.append({
            "date": deadline.strftime("%d.%m.%Y"),
            "label": "Об'єднана звітність, %s квартал %s" % (quarter, year),
            "amount": 0.0, "detail": "Д1, 4ДФ, Д5", "state": dstate, "state_class": dcls,
            "action": self._action_xmlid("l10n_ua_reporting.action_ua_reporting"),
            "res_model": "ua.report.run",
            "domain": [("company_id", "=", company.id)],
            "title": "Податкова звітність",
        })
        return rows

    def _get_attention(self, company):
        today = fields.Date.context_today(self)
        limit30 = today + timedelta(days=30)
        today_s, limit_s = fields.Date.to_string(today), fields.Date.to_string(limit30)
        rows = []

        mil_count = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id), ("active", "=", True), ("ua_mil_needs_check", "=", True),
        ])
        if mil_count:
            rows.append({
                "title": "Звірка з ТЦК не проведена",
                "detail": self._plural(mil_count, "працівник потребує звірки", "працівники потребують звірки", "працівників потребують звірки"),
                "count": mil_count, "level": "danger",
                "action": self._action_xmlid("l10n_ua_military.action_ua_military_needs_check"),
                "res_model": "hr.employee",
                "domain": [("company_id", "=", company.id), ("ua_mil_needs_check", "=", True)],
            })

        docs_count = self.env["ua.employee.document"].search_count([
            ("employee_id.company_id", "=", company.id),
            ("valid_until", ">=", today_s), ("valid_until", "<=", limit_s),
        ])
        if docs_count:
            rows.append({
                "title": "Документи спливають за 30 днів",
                "detail": self._plural(docs_count, "документ працівника", "документи працівників", "документів працівників"),
                "count": docs_count, "level": "warning", "action": False,
                "res_model": "ua.employee.document",
                "domain": [("employee_id.company_id", "=", company.id),
                           ("valid_until", ">=", today_s), ("valid_until", "<=", limit_s)],
            })

        # індекс споживчих цін за минулий місяць: без нього індексація рахується як нуль
        if "ua.cpi.index" in self.env and self.env["hr.employee"].search_count([
                ("company_id", "=", company.id), ("active", "=", True), ("ua_index_off", "=", False)]):
            year_prev, month_prev = self._month_add(today.year, today.month, -1)
            if not self.env["ua.cpi.index"].sudo().search_count([("year", "=", year_prev), ("month", "=", month_prev)]):
                rows.append({
                    "title": "Немає індексу споживчих цін",
                    "detail": "за %s %s; без нього індексація рахується як нуль" % (self._month_name(month_prev), year_prev),
                    "count": 1, "level": "warning",
                    "action": self._action_xmlid("l10n_ua_index.action_ua_cpi_index"),
                    "res_model": "ua.cpi.index",
                    "domain": [],
                })

        unrec = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id), ("is_reconciled", "=", False),
        ])
        if unrec:
            amount = self._r2(sum(unrec.mapped("amount")))
            rows.append({
                "title": "Незвірені рядки виписки",
                "detail": "%s %s на суму %s грн" % (
                    len(unrec), self._plural(len(unrec), "рядок", "рядки", "рядків"), self._money(amount)),
                "count": len(unrec), "level": "warning",
                "action": self._action_xmlid("account_reconcile_oca.action_bank_statement_line_reconcile_all"),
                "res_model": "account.bank.statement.line",
                "domain": [("company_id", "=", company.id), ("is_reconciled", "=", False)],
            })

        versions = self.env["hr.version"].search([("employee_id.company_id", "=", company.id)])
        ending = versions.filtered(
            lambda v: (v.contract_date_end and today <= v.contract_date_end <= limit30)
            or (v.trial_date_end and today <= v.trial_date_end <= limit30)
        )
        if ending:
            rows.append({
                "title": "Договори і випробування спливають за 30 днів",
                "detail": "версій трудових договорів", "count": len(ending), "level": "warning",
                "action": False, "res_model": "hr.version",
                "domain": [("id", "in", ending.ids)],
            })

        no_rnokpp = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id), ("active", "=", True), ("ua_rnokpp", "=", False),
        ])
        if no_rnokpp:
            rows.append({
                "title": "Працівники без РНОКПП", "detail": "працівників", "count": no_rnokpp,
                "level": "warning", "action": False, "res_model": "hr.employee",
                "domain": [("company_id", "=", company.id), ("active", "=", True), ("ua_rnokpp", "=", False)],
            })

        draft_count = self.env["hr.payslip"].search_count([
            ("company_id", "=", company.id), ("state", "=", "draft"),
        ])
        if draft_count:
            rows.append({
                "title": "Листки в чернетках", "detail": "розрахункових листків", "count": draft_count,
                "level": "info", "action": self._action_xmlid("payroll.hr_payslip_action"),
                "res_model": "hr.payslip", "domain": [("company_id", "=", company.id), ("state", "=", "draft")],
            })

        return rows

    def _get_documents(self, company):
        rows = []

        for rec in self.env["ua.timesheet.sheet"].search(
            [("company_id", "=", company.id)], order="year desc, month desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": "%s %s" % (self._month_name(rec.month).capitalize(), rec.year),
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "action": False, "res_model": "ua.timesheet.sheet", "res_id": rec.id,
            })

        for rec in self.env["ua.staff.list"].search(
            [("company_id", "=", company.id)], order="date desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": rec.date.strftime("%d.%m.%Y") if rec.date else "",
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "action": False, "res_model": "ua.staff.list", "res_id": rec.id,
            })

        for rec in self.env["ua.pfu.claim"].search(
            [("company_id", "=", company.id)], order="date desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": rec.date.strftime("%d.%m.%Y") if rec.date else "",
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "action": False, "res_model": "ua.pfu.claim", "res_id": rec.id,
            })

        for rec in self.env["ua.advance.sheet"].search(
            [("company_id", "=", company.id)], order="year desc, month desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": "%s %s" % (self._month_name(rec.month).capitalize(), rec.year),
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "action": False, "res_model": "ua.advance.sheet", "res_id": rec.id,
            })

        # прогони звітності замість переліку XML-файлів: файли лежать усередині прогону
        if "ua.report.run" in self.env:
            for rec in self.env["ua.report.run"].search(
                [("company_id", "=", company.id)], order="year desc, id desc", limit=6
            ):
                files = len(rec.attachment_ids)
                rows.append({
                    "name": rec.name,
                    "period": "%s %s" % (files, self._plural(files, "файл", "файли", "файлів")) if files else "без файлів",
                    "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                    "action": False, "res_model": "ua.report.run", "res_id": rec.id,
                })

        seen = set()
        unique = []
        for row in rows:
            key = (row["name"], row.get("res_model"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique[:14]

    # ------------------------------------------------------------------ публічний метод
    @api.model
    def get_data(self, year=None, month=None):
        today = fields.Date.context_today(self)
        year = int(year) if year else today.year
        month = int(month) if month else today.month
        company = self.env.company

        return {
            "company": self._get_company(company, year, month),
            "periods": self._get_periods(company, year, month),
            "payroll_by_department": self._get_payroll_by_department(company, year, month),
            "turnover": self._get_turnover(company, year, month),
            "documents": self._get_documents(company),
        }

    def _get_turnover(self, company, year, month):
        """Обороти за період беремо з робочого місця місяця: одне джерело чисел."""
        if "ua.period.board" not in self.env:
            return []
        first, last = self._month_bounds(year, month)
        return self.env["ua.period.board"]._turnover(company, first, last)
