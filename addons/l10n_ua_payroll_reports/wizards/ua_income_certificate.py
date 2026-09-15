# -*- coding: utf-8 -*-
"""Довідка про доходи працівника: помісячні нарахування, утримання і сума на руки.

Джерело - проведені розрахункові листки за період. Банк або установа просить саме такий
документ; підписують керівник і головний бухгалтер.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}


class UaIncomeCertificateWizard(models.TransientModel):
    _name = "ua.income.certificate.wizard"
    _description = "Довідка про доходи"

    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    date_from = fields.Date("З", required=True, default=lambda s: fields.Date.context_today(s).replace(day=1) - relativedelta(months=6))
    date_to = fields.Date("По", required=True, default=lambda s: fields.Date.context_today(s).replace(day=1) - relativedelta(days=1))
    purpose = fields.Char("Для подання", default="за місцем вимоги")
    show_net = fields.Boolean("Показувати суму на руки", default=True)
    cert_number = fields.Char("Номер довідки", readonly=True)
    cert_date = fields.Date("Дата довідки", readonly=True)

    def _months(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("Дата «По» раніша за дату «З»."))
        slips = self.env["hr.payslip"].search([
            ("employee_id", "=", self.employee_id.id), ("state", "=", "done"),
            ("date_from", ">=", self.date_from), ("date_to", "<=", self.date_to),
        ], order="date_from")
        rows = []
        totals = dict.fromkeys(("gross", "pdfo", "vz", "net"), 0.0)
        for slip in slips:
            lines = slip.line_ids
            def amount(code):
                return sum(lines.filtered(lambda l: l.code == code).mapped("total"))
            row = {
                "period": "%s %s" % (MONTHS_UA[slip.date_from.month].capitalize(), slip.date_from.year),
                "gross": round(amount("GROSS") + amount("MAT"), 2),
                "pdfo": round(abs(amount("PDFO")), 2),
                "vz": round(abs(amount("VZ")), 2),
                "net": round(amount("NET"), 2),
            }
            rows.append(row)
            for key in totals:
                totals[key] += row[key]
        return rows, {key: round(value, 2) for key, value in totals.items()}

    def action_print(self):
        self.ensure_one()
        rows, _totals = self._months()
        if not rows:
            raise UserError(_("За цей період немає проведених розрахункових листків."))
        if not self.cert_number:
            today = fields.Date.context_today(self)
            number = self.env["ir.sequence"].sudo().next_by_code("ua.income.certificate", sequence_date=today)
            if not number:
                raise UserError(_("Не налаштовано нумерацію довідок. Зверніться до адміністратора."))
            self.cert_number = number
            self.cert_date = today
            self.env["ua.income.certificate.register"].sudo().create({
                "name": number, "date": today, "company_id": self.employee_id.company_id.id,
                "employee_id": self.employee_id.id, "date_from": self.date_from, "date_to": self.date_to,
                "purpose": self.purpose,
            })
        return self.env.ref("l10n_ua_payroll_reports.action_report_ua_income_certificate").report_action(self)


class UaIncomeCertificateReport(models.AbstractModel):
    _name = "report.l10n_ua_payroll_reports.report_ua_income_certificate"
    _description = "Дані довідки про доходи"

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env["ua.income.certificate.wizard"].browse(docids)
        content = {}
        for wizard in wizards:
            rows, totals = wizard._months()
            content[wizard.id] = {"rows": rows, "totals": totals}
        return {"doc_ids": docids, "doc_model": "ua.income.certificate.wizard", "docs": wizards, "content": content}
