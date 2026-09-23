# -*- coding: utf-8 -*-
"""Довідка про доходи працівника: документ із помісячними нарахуваннями, утриманнями
і сумою на руки.

Джерело - проведені розрахункові листки за період. Банк або установа просить саме такий
документ; підписують керівник і головний бухгалтер.

Раніше довідка була майстром (ua.income.certificate.wizard), а слід від неї лишався в
окремому реєстрі (ua.income.certificate.register). Тепер довідка - звичайний запис:
список довідок і є реєстром, а номер із послідовності «ua.income.certificate»
присвоюється при видачі.
"""
import calendar
from datetime import date as date_type

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("issued", "Видано")]

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}


class UaIncomeCertificate(models.Model):
    _name = "ua.income.certificate"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Довідка про доходи"
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    number = fields.Char("Номер", readonly=True, copy=False, tracking=True)
    date = fields.Date("Дата видачі", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda s: s.env.company)
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, tracking=True)
    date_from = fields.Date("Період з", required=True, tracking=True,
                            default=lambda s: fields.Date.context_today(s).replace(day=1) - relativedelta(months=6))
    date_to = fields.Date("Період по", required=True, tracking=True,
                          default=lambda s: fields.Date.context_today(s).replace(day=1) - relativedelta(days=1))
    purpose = fields.Char("Для подання", default="за місцем вимоги")
    show_net = fields.Boolean("Показувати суму на руки", default=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.income.certificate.line", "certificate_id", "Рядки")
    currency_id = fields.Many2one(related="company_id.currency_id")
    total_gross = fields.Monetary("Нараховано, разом", currency_field="currency_id",
                                  compute="_compute_totals", store=True)
    total_pdfo = fields.Monetary("ПДФО, разом", currency_field="currency_id",
                                 compute="_compute_totals", store=True)
    total_vz = fields.Monetary("Військовий збір, разом", currency_field="currency_id",
                               compute="_compute_totals", store=True)
    total_net = fields.Monetary("До виплати, разом", currency_field="currency_id",
                                compute="_compute_totals", store=True)

    @api.depends("employee_id", "number", "date_from", "date_to")
    def _compute_name(self):
        for doc in self:
            who = doc.employee_id.name or ""
            if doc.number:
                doc.name = "Довідка про доходи № %s · %s" % (doc.number, who)
            else:
                doc.name = ("Довідка про доходи · %s" % who).strip(" ·")

    @api.depends("line_ids.gross", "line_ids.pdfo", "line_ids.vz", "line_ids.net")
    def _compute_totals(self):
        for doc in self:
            doc.total_gross = round(sum(doc.line_ids.mapped("gross")), 2)
            doc.total_pdfo = round(sum(doc.line_ids.mapped("pdfo")), 2)
            doc.total_vz = round(sum(doc.line_ids.mapped("vz")), 2)
            doc.total_net = round(sum(doc.line_ids.mapped("net")), 2)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку довідки про доходи.")

    # ------------------------------------------------------------------ складання
    @api.model
    def ua_compose(self, company, year=None, month=None, employee=None,
                   date_from=None, date_to=None, **params):
        """Нова довідка про доходи, одразу заповнена листками періоду.

        Без явних меж періоду беремо весь місяць; без явного працівника - першого, у кого
        в цьому періоді є проведений листок (довідка без людини не буває)."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        if not (date_from and date_to):
            today = fields.Date.context_today(self)
            year, month = int(year or today.year), int(month or today.month)
            date_from = date_type(year, month, 1)
            date_to = date_type(year, month, calendar.monthrange(year, month)[1])
        if isinstance(employee, int):
            employee = self.env["hr.employee"].browse(employee)
        if not employee:
            slip = self.env["hr.payslip"].sudo().search([
                ("company_id", "=", company.id), ("state", "=", "done"),
                ("date_from", ">=", date_from), ("date_to", "<=", date_to)], limit=1)
            employee = slip.employee_id
        if not employee:
            raise UserError("Немає працівника з проведеним листком за цей період.")
        doc = self.create({
            "company_id": company.id, "employee_id": employee.id,
            "date_from": date_from, "date_to": date_to,
        })
        doc.action_refill()
        return doc

    def action_refill(self):
        """Видалити рядки і заповнити знову з проведених листків періоду."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            if doc.date_to < doc.date_from:
                raise UserError("Дата «Період по» раніша за дату «Період з».")
            doc.line_ids.unlink()
            slips = self.env["hr.payslip"].sudo().search([
                ("employee_id", "=", doc.employee_id.id), ("state", "=", "done"),
                ("date_from", ">=", doc.date_from), ("date_to", "<=", doc.date_to),
            ], order="date_from")
            vals_list = []
            for slip in slips:
                lines = slip.line_ids

                def amount(code, lines=lines):
                    return sum(lines.filtered(lambda l: l.code == code).mapped("total"))

                vals_list.append({
                    "period": "%s %s" % (MONTHS_UA[slip.date_from.month].capitalize(), slip.date_from.year),
                    "date_from": slip.date_from,
                    "payslip_id": slip.id,
                    "gross": round(amount("GROSS") + amount("MAT"), 2),
                    "pdfo": round(abs(amount("PDFO")), 2),
                    "vz": round(abs(amount("VZ")), 2),
                    "net": round(amount("NET"), 2),
                })
            doc.line_ids = [(0, 0, v) for v in vals_list]
        return True

    def action_confirm(self):
        """Видати довідку: присвоїти номер із послідовності і дату видачі."""
        for doc in self:
            if not doc.line_ids:
                raise UserError("За цей період немає проведених розрахункових листків.")
            if not doc.number:
                today = fields.Date.context_today(doc)
                number = self.env["ir.sequence"].sudo().next_by_code(
                    "ua.income.certificate", sequence_date=today)
                if not number:
                    raise UserError("Не налаштовано нумерацію довідок. Зверніться до адміністратора.")
                doc.write({"number": number, "date": today})
            doc.state = "issued"
        return True

    def action_draft(self):
        self.state = "draft"

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        if not self.line_ids:
            out.append(self._check_error(
                "Немає проведених листків за період", target=self._target_record(self)))
        else:
            out.append(self._check_ok("Місяців у довідці", fact=len(self.line_ids)))
        if not self.employee_id.ua_rnokpp:
            out.append(self._check_warn(
                "У працівника немає РНОКПП", target=self._target_records(self.employee_id, "hr.employee")))
        if not self.company_id.ua_director_name:
            out.append(self._check_warn("Керівника компанії не вказано",
                                        target=self._target_records(self.company_id, "res.company")))
        if not self.company_id.ua_accountant_name:
            out.append(self._check_warn("Головного бухгалтера компанії не вказано",
                                        target=self._target_records(self.company_id, "res.company")))
        out.append(self._check_ok("Стан документа", fact=dict(STATES).get(self.state, self.state)))
        return out


class UaIncomeCertificateLine(models.Model):
    _name = "ua.income.certificate.line"
    _description = "Рядок довідки про доходи"
    _order = "date_from, id"

    certificate_id = fields.Many2one("ua.income.certificate", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="certificate_id.currency_id")
    period = fields.Char("Місяць")
    date_from = fields.Date("Початок місяця")
    payslip_id = fields.Many2one("hr.payslip", "Листок")
    gross = fields.Monetary("Нараховано", currency_field="currency_id")
    pdfo = fields.Monetary("ПДФО", currency_field="currency_id")
    vz = fields.Monetary("Військовий збір", currency_field="currency_id")
    net = fields.Monetary("До виплати", currency_field="currency_id")
