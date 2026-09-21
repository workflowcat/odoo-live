# -*- coding: utf-8 -*-
"""Календар виплат місяця: що вже сплачено, що в банку і не звірено, що заплановано.

Це логіка, не екран: ті самі рядки читають і «Зведення» (l10n_ua_dashboard), і «Банк»
(l10n_ua_bank_online), і «Період» (l10n_ua_period). Раніше вони жили на ua.dashboard,
тож банк - логічний модуль - залежав від панелі, тобто від інтерфейсу. Тепер числа
живуть тут, поруч із відомостями на перерахування, а екрани лише питають.

Звірка з банком - за текстом payment_ref (прямого зв'язку листок <-> рядок виписки в
системі немає): шаблони підпису рядків задає l10n_ua_bank/hooks.py, наприклад
«Заробітна плата за серпень 2026, остаточний розрахунок», «ПДФО з авансу за серпень
2026», «Єдиний внесок (ЄСВ) за серпень 2026». Місяць у називному відмінку («серпень»,
«вересень») - для цих іменників він збігається зі знахідним, який і вжито після «за».
"""
from datetime import date, timedelta

from odoo import api, fields, models

PAYSLIP_CODES = ("GROSS", "PDFO", "VZ", "ESV", "NET", "ADV_PAID")


class UaPaymentsPlan(models.AbstractModel):
    _name = "ua.payments.plan"
    _inherit = ["ua.screen"]
    _description = "Календар виплат місяця"

    # ------------------------------------------------------------------ домени і підсумки
    def _slip_domain(self, company, year, month, department_id=None):
        """Домен листків місяця - те, що стоїть за сумою в рядку екрана."""
        d1, d2 = self._bounds(year, month)
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
        d1, d2 = self._bounds(year, month)
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", d1), ("date_from", "<=", d2),
            ("state", "!=", "cancel"),
        ])
        lines = slips.mapped("line_ids")
        return {code: self._r2(sum(lines.filtered(lambda l: l.code == code).mapped("total"))) for code in PAYSLIP_CODES}

    def _bank_status(self, company, keyword, month, year):
        """Рядки виписки, чий payment_ref містить keyword і назву місяця/рік.
        Повертає (текст стану, state_class, остання дата)."""
        lines = self.env["account.bank.statement.line"].search(
            self._bank_domain(company, keyword, month, year))
        if not lines:
            return "не сплачено", "todo", False
        last_date = max(lines.mapped("date"))
        if all(l.is_reconciled for l in lines):
            return "сплачено, звірено", "ok", last_date
        return "у виписці, не звірено", "warn", last_date

    # ------------------------------------------------------------------ рядки календаря
    @api.model
    def month_rows(self, company, year, month):
        """Рядки календаря виплат місяця: минулий місяць - факт, поточний - план."""
        ly, lm = self._month_add(year, month, -1)
        ny, nm = self._month_add(year, month, 1)
        last_name = self._month_name(lm)
        this_name = self._month_name(month)
        last_totals = self._month_payslip_totals(company, ly, lm)
        rows = []

        state, cls, d = self._bank_status(company, "Заробітна плата", lm, ly)
        rows.append({
            "date": d.strftime("%d.%m.%Y") if d else False,
            "label": "Зарплата, %s %s" % (last_name, ly),
            "amount": abs(last_totals["NET"]), "state": state, "state_class": cls,
            "target": {
                "model": "account.bank.statement.line" if d else "hr.payslip",
                "domain": self._bank_domain(company, "Заробітна плата", lm, ly) if d
                          else self._slip_domain(company, ly, lm),
                "name": "Зарплата, %s %s" % (last_name, ly),
            },
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
                "target": {
                    "model": "account.bank.statement.line" if d else "hr.payslip",
                    "domain": self._bank_domain(company, keyword, lm, ly) if d
                              else self._slip_domain(company, ly, lm),
                    "name": "%s, %s %s" % (label, last_name, ly),
                },
            })

        adv = self.env["ua.advance.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if not adv or not adv.line_ids:
            rows.append({
                "date": False, "label": "Аванс, %s %s" % (this_name, year),
                "amount": 0.0, "state": "не розраховано", "state_class": "todo",
                "target": self._xmlid_target("l10n_ua_payroll_rules.action_ua_advance_sheet") or {
                    "model": "ua.advance.sheet", "domain": [("company_id", "=", company.id)],
                    "name": "Відомості авансу"},
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
                "target": {"model": "ua.advance.sheet", "res_id": adv.id},
            })

        # планова виплата за поточний місяць: 6-те число наступного місяця (ст. 115 КЗпП)
        this_totals = self._month_payslip_totals(company, year, month)
        if this_totals["NET"]:
            pay_day = date(ny, nm, 6)
            slip_target = {"target": {
                "model": "hr.payslip",
                "domain": self._slip_domain(company, year, month),
                "name": "Листки · %s %s" % (this_name, year),
            }}
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
        q_end = self._bounds(year, q_end_month)[1]
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
            "target": self._xmlid_target("l10n_ua_reporting_ui.action_ua_reporting") or {
                "model": "ua.report.run", "domain": [("company_id", "=", company.id)],
                "name": "Податкова звітність"},
        })
        return rows
