# -*- coding: utf-8 -*-
"""Заява-розрахунок до ПФУ: фінансування допомоги по тимчасовій непрацездатності та вагітності/пологах за пакетом листків."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from .hr_payslip_run import _bounds, as_company

# Повний цикл фінансування: заява - прийняття - гроші від ПФУ - виплата працівнику - повідомлення.
# Кожен перехід має підтвердження: дату, суму або причину відмови.
STATES = [
    ("draft", "Чернетка"),
    ("confirmed", "Затверджено"),
    ("submitted", "Подано"),
    ("accepted", "Прийнято"),
    ("rejected", "Відхилено"),
    ("funded_partial", "Профінансовано частково"),
    ("funded", "Профінансовано"),
    ("paid", "Виплачено"),
    ("notified", "Повідомлення подано"),
    ("done", "Завершено"),
]
NOTICE_DAYS = 30   # повідомлення про виплату подають протягом місяця після виплати
# (код рядка листка, код виду відпустки, kind рядка заяви, назва)
SOURCES = [("SICK_PFU", "SICK", "sick", "Тимчасова непрацездатність"),
           ("SICK_CARE_PAY", "SICK_CARE", "care", "Догляд за хворою дитиною або членом сім'ї"),
           ("MAT", "MAT", "mat", "Вагітність та пологи")]
DAYS_KEY = {"SICK_PFU": "sick_pfu_days", "SICK_CARE_PAY": "sick_care_days", "MAT": "mat_days"}


class UaPfuClaim(models.Model):
    _name = "ua.pfu.claim"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Заява-розрахунок до ПФУ"
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    payslip_run_id = fields.Many2one("hr.payslip.run", "Пакет листків", required=True, tracking=True)
    date = fields.Date("Дата", default=fields.Date.today, required=True, tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.pfu.claim.line", "claim_id", "Рядки")
    total = fields.Monetary("Разом", compute="_compute_total", store=True)

    # цикл фінансування
    submitted_date = fields.Date("Подано", readonly=True, copy=False, tracking=True)
    accepted_date = fields.Date("Прийнято", readonly=True, copy=False, tracking=True)
    reject_reason = fields.Char("Причина відмови", copy=False, tracking=True)
    funded_amount = fields.Monetary("Профінансовано", readonly=True, copy=False, tracking=True)
    funded_date = fields.Date("Дата фінансування", readonly=True, copy=False)
    funding_journal_id = fields.Many2one("account.journal", "Рахунок ПФУ",
                                         domain=[("type", "=", "bank")],
                                         help="Окремий рахунок для коштів ПФУ")
    paid_amount = fields.Monetary("Виплачено працівникам", readonly=True, copy=False, tracking=True)
    paid_date = fields.Date("Дата виплати", readonly=True, copy=False)
    notice_date = fields.Date("Повідомлення подано", readonly=True, copy=False)
    notice_deadline = fields.Date("Строк повідомлення", compute="_compute_notice_deadline", store=True)
    unfunded = fields.Monetary("Не профінансовано", compute="_compute_balances")
    to_pay = fields.Monetary("Залишок до виплати", compute="_compute_balances")

    @api.depends("payslip_run_id.date_start")
    def _compute_name(self):
        for doc in self:
            d = doc.payslip_run_id.date_start
            doc.name = "Заява-розрахунок ПФУ %02d.%d" % (d.month, d.year) if d else "Заява-розрахунок ПФУ"

    @api.depends("line_ids.amount")
    def _compute_total(self):
        for doc in self:
            doc.total = sum(doc.line_ids.mapped("amount"))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку заяви-розрахунку.")

    @api.model
    def ua_compose(self, company, year=None, month=None, **params):
        """Нова заява-розрахунок за місяць: пакет листків місяця і його суми.

        Без пакета листків заяви не буває - рахувати нема з чого, тому метод
        відмовляє, а не створює порожню чернетку."""
        company = as_company(self.env, company)
        first, last = _bounds(int(year), int(month))
        run = self.env["hr.payslip.run"].search([
            ("company_id", "=", company.id), ("date_start", ">=", first), ("date_start", "<=", last)], limit=1)
        if not run:
            raise UserError("Немає розрахунково-платіжної відомості за цей місяць")
        claim = self.create({"company_id": company.id, "payslip_run_id": run.id})
        claim.action_refill()
        return claim

    def action_refill(self):
        """Видалити рядки і заповнити знову: рядки SICK_PFU і MAT листків пакета, відпустка з номером е-ЛН, дні з _ua_leave_calendar_days()."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            doc.line_ids.unlink()
            vals_list = []
            for slip in doc.payslip_run_id.slip_ids.sorted(lambda s: s.employee_id.name):
                emp = slip.employee_id.sudo()
                for code, leave_code, kind, _label in SOURCES:
                    amount = sum(slip.line_ids.filtered(lambda l: l.code == code).mapped("total"))
                    if not amount:
                        continue
                    lv = self.env["hr.leave"].sudo().search([
                        ("employee_id", "=", emp.id), ("state", "=", "validate"),
                        ("holiday_status_id.work_entry_type_id.code", "=", leave_code),
                        ("request_date_from", "<=", slip.date_to), ("request_date_to", ">=", slip.date_from),
                    ], limit=1)
                    days = slip._ua_leave_calendar_days()
                    nd = days.get(DAYS_KEY.get(code, "sick_pfu_days"), 0)
                    percent = 100.0 if code == "MAT" else (emp.ua_sick_percent or 100.0)
                    avg_day = (amount / nd / (percent / 100.0)) if nd else 0.0
                    vals_list.append({
                        "employee_id": emp.id, "kind": kind,
                        "sick_number": lv.ua_sick_number if lv else False,
                        "date_from": lv.request_date_from if lv else False,
                        "date_to": lv.request_date_to if lv else False,
                        "days": nd, "avg_day": avg_day, "percent": percent, "amount": amount,
                    })
            doc.line_ids = [(0, 0, v) for v in vals_list]
        return True

    @api.depends("paid_date")
    def _compute_notice_deadline(self):
        for doc in self:
            doc.notice_deadline = fields.Date.add(doc.paid_date, days=NOTICE_DAYS) if doc.paid_date else False

    @api.depends("total", "funded_amount", "paid_amount")
    def _compute_balances(self):
        for doc in self:
            doc.unfunded = round(doc.total - doc.funded_amount, 2)
            doc.to_pay = round(doc.funded_amount - doc.paid_amount, 2)

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"

    # ------------------------------------------------------------------ цикл фінансування
    def action_submit(self):
        """Заяву подано до ПФУ."""
        for doc in self:
            if doc.state not in ("confirmed", "rejected"):
                raise UserError("Подати можна затверджену заяву.")
            doc.write({"state": "submitted", "submitted_date": fields.Date.context_today(doc),
                       "reject_reason": False})

    def action_accept(self):
        """ПФУ прийняв заяву."""
        for doc in self:
            if doc.state != "submitted":
                raise UserError("Прийняти можна подану заяву.")
            doc.write({"state": "accepted", "accepted_date": fields.Date.context_today(doc)})

    def action_reject(self):
        """ПФУ відмовив. Причина обов'язкова."""
        for doc in self:
            if not (doc.reject_reason or "").strip():
                raise UserError("Впишіть причину відмови.")
            doc.state = "rejected"

    def action_register_funding(self, amount=None):
        """Гроші від ПФУ надійшли. Часткове фінансування лишає залишок."""
        for doc in self:
            if doc.state not in ("accepted", "funded_partial"):
                raise UserError("Фінансування записують після прийняття заяви.")
            value = round(float(amount if amount is not None else doc.total - doc.funded_amount), 2)
            if value <= 0:
                raise UserError("Сума фінансування має бути більшою за нуль.")
            total = round(doc.funded_amount + value, 2)
            doc.write({"funded_amount": total, "funded_date": fields.Date.context_today(doc),
                       "state": "funded" if total >= doc.total - 0.005 else "funded_partial"})

    def action_register_payment(self, amount=None):
        """Допомогу виплачено працівникам. Виплатити можна лише профінансоване."""
        for doc in self:
            if doc.state not in ("funded", "funded_partial", "paid"):
                raise UserError("Виплата можлива після надходження коштів ПФУ.")
            value = round(float(amount if amount is not None else doc.funded_amount - doc.paid_amount), 2)
            if value <= 0:
                raise UserError("Немає що виплачувати: кошти ПФУ ще не надійшли.")
            total = round(doc.paid_amount + value, 2)
            if total > doc.funded_amount + 0.005:
                raise UserError("Не можна виплатити більше, ніж профінансовано.")
            doc.write({"paid_amount": total, "paid_date": fields.Date.context_today(doc), "state": "paid"})

    def action_notice_sent(self):
        """Повідомлення про виплату подано до ПФУ."""
        for doc in self:
            if doc.state != "paid":
                raise UserError("Повідомлення подають після виплати.")
            doc.write({"state": "notified", "notice_date": fields.Date.context_today(doc)})

    def action_done(self):
        for doc in self:
            if doc.state != "notified":
                raise UserError("Завершити можна заяву з поданим повідомленням.")
            if doc.unfunded > 0.005:
                raise UserError("Лишилося непрофінансовано: %s. Завершити не можна." % doc.unfunded)
            doc.state = "done"

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        if not self.line_ids:
            out.append(self._check_error("Немає рядків заяви-розрахунку", target=self._target_record(self)))
            return out
        no_number = self.line_ids.filtered(lambda l: l.kind in ("sick", "care") and not l.sick_number)
        if no_number:
            out.append(self._check_error(
                "Рядки без номера електронного листка непрацездатності", fact=len(no_number),
                target=self._target_records(no_number, "ua.pfu.claim.line")))
        else:
            out.append(self._check_ok("Усі лікарняні рядки мають номер е-ЛН"))
        no_dates = self.line_ids.filtered(lambda l: not l.date_from or not l.date_to)
        if no_dates:
            out.append(self._check_error(
                "Рядки без дат періоду непрацездатності", fact=len(no_dates),
                target=self._target_records(no_dates, "ua.pfu.claim.line")))
        else:
            out.append(self._check_ok("Усі рядки мають дати періоду"))
        no_days = self.line_ids.filtered(lambda l: l.amount and not l.days)
        if no_days:
            out.append(self._check_warn(
                "Сума нарахована, але днів за рахунок ПФУ немає", fact=len(no_days),
                target=self._target_records(no_days, "ua.pfu.claim.line")))
        if self.state == "paid" and self.notice_deadline:
            today = fields.Date.context_today(self)
            if today > self.notice_deadline:
                out.append(self._check_error(
                    "Строк подання повідомлення про виплату минув", fact=self.notice_deadline.strftime("%d.%m.%Y"),
                    target=self._target_record(self)))
            else:
                out.append(self._check_ok(
                    "Строк подання повідомлення про виплату", fact=self.notice_deadline.strftime("%d.%m.%Y")))
        if self.unfunded:
            out.append(self._check_warn("Не профінансовано", fact="%.2f" % self.unfunded, target=self._target_record(self)))
        out.append(self._check_ok("Стан документа", fact=dict(self._fields["state"].selection).get(self.state, self.state)))
        return out


class UaPfuClaimLine(models.Model):
    _name = "ua.pfu.claim.line"
    _description = "Рядок заяви-розрахунку до ПФУ"
    _order = "id"

    claim_id = fields.Many2one("ua.pfu.claim", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="claim_id.currency_id")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    kind = fields.Selection([("sick", "Тимчасова непрацездатність"),
                             ("care", "Догляд за хворою дитиною або членом сім'ї"),
                             ("mat", "Вагітність та пологи")], "Вид", required=True)
    sick_number = fields.Char("№ е-ЛН")
    date_from = fields.Date("Від")
    date_to = fields.Date("До")
    days = fields.Integer("Днів за рахунок ПФУ")
    avg_day = fields.Float("Середньоденна")
    percent = fields.Float("%")
    amount = fields.Monetary("Сума")
    note = fields.Char("Примітка")
