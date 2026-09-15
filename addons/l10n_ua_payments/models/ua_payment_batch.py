# -*- coding: utf-8 -*-
"""Відомість на перерахування: кого і скільки платимо, файл для банку, друкована форма.

Зарплату платять зарплатним проєктом: банк отримує список «рахунок - сума - призначення».
Відомість збирається з розрахункових листків (остаточний розрахунок) або з авансової
відомості (аванс). Призначення платежу пишемо тими самими словами, що й правила звірки,
тому виписка потім знаходить ці рядки сама.

Файл: CSV у кодуванні windows-1251 з колонками ПІБ, РНОКПП, рахунок, сума, призначення.
Такий список приймає більшість банків; формат конкретного банку додається окремо, як і
постачальники виписок.
"""
import base64
import csv
import io
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
KINDS = [("advance", "Аванс"), ("salary", "Заробітна плата"), ("tax", "Податки і внески"), ("other", "Інша виплата")]
# Податки до бюджету: код рядка -> (правило листка, назва, поле рахунку компанії, текст призначення).
# Текст збігається з правилами звірки виписки, тому платіж потім знаходиться сам.
TAXES = [
    ("PDFO", "ПДФО", "ua_iban_pdfo", "ПДФО за %s %s"),
    ("VZ", "Військовий збір", "ua_iban_vz", "Військовий збір за %s %s"),
    ("ESV", "Єдиний внесок (ЄСВ)", "ua_iban_esv", "Єдиний внесок (ЄСВ) за %s %s"),
]
STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено"), ("paid", "Оплачено")]


class UaPaymentBatch(models.Model):
    _name = "ua.payment.batch"
    _description = "Відомість на перерахування"
    _inherit = ["mail.thread"]
    _order = "year desc, month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer("Рік", required=True, default=lambda s: date.today().year, tracking=True)
    month = fields.Integer("Місяць", required=True, default=lambda s: date.today().month, tracking=True)
    kind = fields.Selection(KINDS, "Вид виплати", default="salary", required=True, tracking=True)
    pay_date = fields.Date("Дата виплати", default=fields.Date.context_today, tracking=True)
    journal_id = fields.Many2one("account.journal", "Банк", domain=[("type", "=", "bank")], tracking=True)
    number = fields.Char("Номер", tracking=True)
    number_date = fields.Date("Дата затвердження", tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.payment.line", "batch_id", "Рядки")
    total = fields.Monetary("Разом", compute="_compute_total", store=True)
    employee_count = fields.Integer("Працівників", compute="_compute_total", store=True)
    without_account = fields.Integer("Без рахунку", compute="_compute_total", store=True)
    note = fields.Text("Примітка")

    @api.depends("year", "month", "kind")
    def _compute_name(self):
        labels = dict(KINDS)
        for doc in self:
            doc.name = "%s %02d.%s" % (labels.get(doc.kind, ""), doc.month or 0, doc.year or "")

    @api.depends("line_ids.amount", "line_ids.account_number")
    def _compute_total(self):
        for doc in self:
            doc.total = round(sum(doc.line_ids.mapped("amount")), 2)
            doc.employee_count = len(doc.line_ids)
            doc.without_account = len(doc.line_ids.filtered(lambda line: not line.account_number))

    def _period(self):
        self.ensure_one()
        first = date(self.year, self.month, 1)
        last = date(self.year + (self.month == 12), self.month % 12 + 1, 1)
        return first, last

    def _purpose(self):
        """Текст призначення. Збігається з правилами звірки виписки."""
        self.ensure_one()
        month_name = MONTHS_UA.get(self.month, "")
        if self.kind == "advance":
            return "Аванс за %s %s" % (month_name, self.year)
        if self.kind == "salary":
            return "Заробітна плата за %s %s, остаточний розрахунок" % (month_name, self.year)
        if self.kind == "tax":
            return "Податки і внески за %s %s" % (month_name, self.year)
        return "Виплата за %s %s" % (month_name, self.year)

    # ------------------------------------------------------------------ наповнення
    def action_fill(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            doc.line_ids.unlink()
            first, last = doc._period()
            values = []
            if doc.kind == "advance":
                sheet = self.env["ua.advance.sheet"].search([
                    ("company_id", "=", doc.company_id.id), ("year", "=", doc.year), ("month", "=", doc.month),
                ], limit=1)
                if not sheet:
                    raise UserError(_("Немає авансової відомості за цей місяць."))
                for line in sheet.line_ids.filtered(lambda l: l.amount > 0):
                    values.append((line.employee_id, round(line.amount, 2)))
            elif doc.kind == "tax":
                doc._fill_taxes()
                continue
            else:
                slips = self.env["hr.payslip"].search([
                    ("company_id", "=", doc.company_id.id), ("state", "in", ("done", "verify")),
                    ("date_from", ">=", first), ("date_from", "<", last),
                ])
                for slip in slips:
                    net = sum(slip.line_ids.filtered(lambda l: l.code == "NET").mapped("total"))
                    if round(net, 2) > 0:
                        values.append((slip.employee_id, round(net, 2)))
            if not values:
                raise UserError(_("Немає сум до виплати за цей місяць."))
            doc.line_ids = [(0, 0, {
                "employee_id": employee.id,
                "amount": amount,
                "account_number": employee.sudo()._ua_payment_account(),
                "purpose": doc._purpose(),
            }) for employee, amount in sorted(values, key=lambda item: item[0].name or "")]
        return True

    def _fill_taxes(self):
        """Рядки на сплату ПДФО, військового збору і ЄСВ за місяць. Суми беремо з проведених листків."""
        self.ensure_one()
        first, last = self._period()
        month_name = MONTHS_UA.get(self.month, "")
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("date_from", ">=", first), ("date_from", "<", last),
        ])
        lines = slips.mapped("line_ids")
        partner = self.company_id.sudo()._ua_partner("dps")
        values = []
        for code, label, iban_field, purpose in TAXES:
            amount = round(abs(sum(lines.filtered(lambda l: l.code == code).mapped("total"))), 2)
            if not amount:
                continue
            values.append({
                "name": label, "partner_id": partner.id, "amount": amount,
                "account_number": self.company_id[iban_field] or "",
                "purpose": purpose % (month_name, self.year),
            })
        if not values:
            raise UserError(_("За цей місяць немає проведених листків, тому немає що платити."))
        self.line_ids = [(0, 0, vals) for vals in values]
        return True

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError(_("Немає рядків. Натисніть «Заповнити»."))
            missing = doc.line_ids.filtered(lambda line: not line.account_number)
            if missing and doc.kind == "tax":
                raise UserError(_("Немає рахунку бюджету: %s. Впишіть рахунки в картці компанії.")
                                % ", ".join(missing.mapped("name")[:5]))
            if missing:
                raise UserError(_("Без рахунку: %s. Впишіть IBAN у картці працівника або в рядку.")
                                % ", ".join(missing.mapped("employee_id.name")[:10]))
            if not doc.number:
                today = fields.Date.context_today(doc)
                doc.number = self.env["ir.sequence"].sudo().next_by_code("ua.payment.batch", sequence_date=today)
                if not doc.number:
                    raise UserError(_("Не налаштовано нумерацію відомостей. Зверніться до адміністратора."))
                doc.number_date = today
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"

    def action_paid(self):
        for doc in self:
            if doc.state != "confirmed":
                raise UserError(_("Позначити оплаченою можна лише затверджену відомість."))
            doc.state = "paid"

    # ------------------------------------------------------------------ файл для банку
    def action_export(self):
        """CSV для зарплатного проєкту: ПІБ, РНОКПП, рахунок, сума, призначення."""
        self.ensure_one()
        if self.state == "draft":
            raise UserError(_("Спершу затвердьте відомість."))
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["ПІБ", "РНОКПП", "Рахунок", "Сума", "Призначення"])
        for line in self.line_ids:
            writer.writerow([
                line.employee_id.name or line.name or "",
                (line.employee_id.sudo().ua_rnokpp if line.employee_id else (line.partner_id.vat or "")) or "",
                line.account_number or "",
                ("%.2f" % line.amount).replace(".", ","),
                line.purpose or self._purpose(),
            ])
        content = stream.getvalue().encode("windows-1251", "replace")
        attachment = self.env["ir.attachment"].create({
            "name": "%s.csv" % self.name,
            "type": "binary",
            "datas": base64.b64encode(content),
            "mimetype": "text/csv",
            "res_model": self._name,
            "res_id": self.id,
        })
        self.message_post(body=_("Сформовано файл для банку: %s") % attachment.name,
                          attachment_ids=[attachment.id])
        return {"type": "ir.actions.act_url", "url": "/web/content/%s?download=1" % attachment.id, "target": "self"}


class UaPaymentLine(models.Model):
    _name = "ua.payment.line"
    _description = "Рядок відомості на перерахування"
    _order = "id"

    batch_id = fields.Many2one("ua.payment.batch", "Відомість", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    partner_id = fields.Many2one("res.partner", "Отримувач", help="Для платежів до бюджету")
    name = fields.Char("Рядок", help="Назва платежу, коли одержувач не працівник")
    currency_id = fields.Many2one(related="batch_id.currency_id")
    account_number = fields.Char("Рахунок (IBAN)")
    amount = fields.Monetary("Сума", required=True)
    purpose = fields.Char("Призначення")
