# -*- coding: utf-8 -*-
"""Дані для клієнтської дії «Зведення»: одна модель без збереження (AbstractModel),
один публічний метод get_screen_data(year, month) - усе інше приватні хелпери.
Цілі рядків - спільного виду ua.screen (`target`), відкриває їх ua.screen.open_target.

Джерела: hr.payslip.run / hr.payslip / hr.payslip.line (коди GROSS, PDFO, VZ, ESV, NET, ADV_PAID),
hr.employee (ua_mil_needs_check, ua_docs_expiring, ua_rnokpp), ua.employee.document (valid_until),
account.bank.statement.line (is_reconciled, amount, payment_ref), hr.version (contract_date_end,
trial_date_end), ua.timesheet.sheet, ua.staff.list, ua.pfu.claim, ua.advance.sheet, ir.attachment
(вкладення XML).

Календар виплат («що сплачено, що заплановано») живе не тут, а в логіці - ua.payments.plan
(l10n_ua_payments): ті самі рядки читають «Банк» і «Період», а логічний модуль не має
залежати від панелі. Домен листків місяця - звідти ж (_slip_domain).
"""
from datetime import timedelta

from odoo import api, fields, models


class UaDashboard(models.AbstractModel):
    _name = "ua.dashboard"
    _inherit = ["ua.screen"]
    _description = "Дані панелі «Зведення»"

    # ------------------------------------------------------------------ хелпери
    # _money / _plural / _r2 / _month_name / MONTHS_UA / open_target - у ua.screen.
    # «Зведення» показує суми без знака і зі звичайним пробілом між тисячами.
    _money_absolute = True
    _money_thousands = " "

    def _plan(self):
        """Логіка чисел місяця: домени листків і календар виплат."""
        return self.env["ua.payments.plan"]

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

    def _period_item_extra(self, year, month):
        """У смузі «Зведення» місяць позначено тим, чи є в ньому пакет листків."""
        d1, d2 = self._bounds(year, month)
        return {"has_run": bool(self.env["hr.payslip.run"].search_count([
            ("company_id", "=", self._company().id), ("date_start", ">=", d1), ("date_start", "<=", d2),
        ]))}

    def _get_payroll_by_department(self, company, year, month):
        d1, d2 = self._bounds(year, month)
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
                "target": {
                    "model": "hr.payslip",
                    "domain": self._plan()._slip_domain(company, year, month, row["department_id"]),
                    "name": "Листки · %s · %s %s" % (row["department"], self._month_name(month), year),
                },
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

        total["target"] = {"model": "hr.payslip", "domain": self._plan()._slip_domain(company, year, month),
                           "name": "Листки · %s %s" % (self._month_name(month), year)}
        return {
            "rows": rows,
            "total": total,
            "has_run": bool(run),
            "run_target": self._xmlid_target("payroll.hr_payslip_run_action"),
        }

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
                "target": {"model": "hr.employee", "name": "Звірка з ТЦК",
                           "domain": [("company_id", "=", company.id), ("ua_mil_needs_check", "=", True)]},
            })

        docs_count = self.env["ua.employee.document"].search_count([
            ("employee_id.company_id", "=", company.id),
            ("valid_until", ">=", today_s), ("valid_until", "<=", limit_s),
        ])
        if docs_count:
            rows.append({
                "title": "Документи спливають за 30 днів",
                "detail": self._plural(docs_count, "документ працівника", "документи працівників", "документів працівників"),
                "count": docs_count, "level": "warning",
                "target": {"model": "ua.employee.document", "name": "Документи працівників",
                           "domain": [("employee_id.company_id", "=", company.id),
                                      ("valid_until", ">=", today_s), ("valid_until", "<=", limit_s)]},
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
                    "target": {"model": "ua.cpi.index", "domain": [],
                               "name": "Індекс споживчих цін"},
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
                "target": {"model": "account.bank.statement.line", "name": "Незвірені рядки виписки",
                           "domain": [("company_id", "=", company.id), ("is_reconciled", "=", False)]},
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
                "target": {"model": "hr.version", "domain": [("id", "in", ending.ids)],
                           "name": "Договори і випробування"},
            })

        no_rnokpp = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id), ("active", "=", True), ("ua_rnokpp", "=", False),
        ])
        if no_rnokpp:
            rows.append({
                "title": "Працівники без РНОКПП", "detail": "працівників", "count": no_rnokpp,
                "level": "warning",
                "target": {"model": "hr.employee", "name": "Працівники без РНОКПП",
                           "domain": [("company_id", "=", company.id), ("active", "=", True),
                                      ("ua_rnokpp", "=", False)]},
            })

        draft_count = self.env["hr.payslip"].search_count([
            ("company_id", "=", company.id), ("state", "=", "draft"),
        ])
        if draft_count:
            rows.append({
                "title": "Листки в чернетках", "detail": "розрахункових листків", "count": draft_count,
                "level": "info",
                "target": {"model": "hr.payslip", "name": "Листки в чернетках",
                           "domain": [("company_id", "=", company.id), ("state", "=", "draft")]},
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
                "target": {"model": "ua.timesheet.sheet", "res_id": rec.id},
            })

        for rec in self.env["ua.staff.list"].search(
            [("company_id", "=", company.id)], order="date desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": rec.date.strftime("%d.%m.%Y") if rec.date else "",
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "target": {"model": "ua.staff.list", "res_id": rec.id},
            })

        for rec in self.env["ua.pfu.claim"].search(
            [("company_id", "=", company.id)], order="date desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": rec.date.strftime("%d.%m.%Y") if rec.date else "",
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "target": {"model": "ua.pfu.claim", "res_id": rec.id},
            })

        for rec in self.env["ua.advance.sheet"].search(
            [("company_id", "=", company.id)], order="year desc, month desc, id desc", limit=5
        ):
            rows.append({
                "name": rec.name, "period": "%s %s" % (self._month_name(rec.month).capitalize(), rec.year),
                "state": dict(rec._fields["state"].selection).get(rec.state, rec.state),
                "target": {"model": "ua.advance.sheet", "res_id": rec.id},
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
                    "target": {"model": "ua.report.run", "res_id": rec.id},
                })

        seen = set()
        unique = []
        for row in rows:
            key = (row["name"], row["target"]["model"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique[:14]

    # ------------------------------------------------------------------ публічний метод
    @api.model
    def get_screen_data(self, year=None, month=None):
        today = fields.Date.context_today(self)
        year = int(year) if year else today.year
        month = int(month) if month else today.month
        company = self.env.company

        return {
            "company": self._get_company(company, year, month),
            "period": self._period_block(year, month),
            "payroll_by_department": self._get_payroll_by_department(company, year, month),
            "turnover": self._get_turnover(company, year, month),
            "documents": self._get_documents(company),
        }

    def _get_turnover(self, company, year, month):
        """Обороти за період беремо з робочого місця місяця: одне джерело чисел."""
        if "ua.period.board" not in self.env:
            return []
        first, last = self._bounds(year, month)
        return self.env["ua.period.board"]._turnover(company, first, last)
