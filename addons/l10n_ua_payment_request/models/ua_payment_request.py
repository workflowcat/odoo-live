"""Заявка на оплату з погодженням - «Заявка на витрачання коштів» з 1С.

Порядок:

    чернетка -> на погодженні -> погоджено -> передано на оплату
                            \\-> відхилено (з причиною)

Погоджують кроками. Перший крок - фінансист (група «Фінансист (погоджує)»). Якщо сума в
гривні більша за ліміт компанії (`ua_payment_request_limit`), потрібен ще другий крок -
директор. Хто склав заявку, той її не погоджує: розподіл обов'язків. Кожне рішення - запис у
`ua.payment.request.approval`: хто, коли, що вирішив і чому.

Платіж створює бухгалтер із погодженої заявки. Є рахунки постачальника - платіж іде через
стандартний майстер реєстрації оплати й закриває їх. Рахунків немає - звичайний вихідний платіж
(аванс). Сума платежу - сума заявки: частково погоджений рахунок оплачується частково.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATES = [
    ("draft", "Чернетка"),
    ("submitted", "На погодженні"),
    ("approved", "Погоджено"),
    ("rejected", "Відхилено"),
    ("payment", "Передано на оплату"),
    ("cancel", "Скасовано"),
]
STEPS = [("finance", "Фінансист"), ("director", "Директор")]
STEP_GROUPS = {
    "finance": "l10n_ua_payment_request.group_ua_payment_request_approver",
    "director": "l10n_ua_payment_request.group_ua_payment_request_director",
}


class UaPaymentRequest(models.Model):
    _name = "ua.payment.request"
    _description = "Заявка на оплату"
    _inherit = ["mail.thread"]
    _order = "date_due, priority desc, id"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    currency_id = fields.Many2one("res.currency", "Валюта", required=True, tracking=True,
                                  default=lambda self: self.env.company.currency_id)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True,
                             copy=False, index=True)
    user_id = fields.Many2one("res.users", "Ініціатор", required=True, readonly=True,
                              default=lambda self: self.env.user, copy=False)
    date = fields.Date("Дата заявки", required=True, default=fields.Date.context_today)
    date_due = fields.Date("Оплатити до", required=True, tracking=True, index=True,
                           default=fields.Date.context_today)
    priority = fields.Selection([("0", "Звичайна"), ("1", "Термінова")], "Терміновість",
                                default="0")
    partner_id = fields.Many2one("res.partner", "Одержувач", required=True, tracking=True,
                                 check_company=True)
    partner_bank_id = fields.Many2one(
        "res.partner.bank", "Рахунок одержувача", check_company=True, tracking=True,
        domain="[('partner_id', '=', partner_id)]",
        compute="_compute_partner_bank_id", store=True, readonly=False)
    journal_id = fields.Many2one(
        "account.journal", "Оплатити з рахунку", check_company=True,
        domain="[('type', 'in', ('bank', 'cash'))]")
    contract_id = fields.Many2one("ua.contract", "Договір", check_company=True,
                                  domain="[('partner_id', '=', partner_id)]")
    bill_ids = fields.Many2many(
        "account.move", "ua_payment_request_bill_rel", "request_id", "move_id",
        "Рахунки постачальника", check_company=True,
        domain="[('partner_id', 'child_of', partner_id), ('state', '=', 'posted'), "
               "('move_type', 'in', ('in_invoice', 'in_receipt')), "
               "('payment_state', 'in', ('not_paid', 'partial'))]")
    amount = fields.Monetary("Сума", required=True, tracking=True, currency_field="currency_id")
    amount_company = fields.Monetary("Сума в гривні", compute="_compute_amount_company",
                                     store=True, currency_field="company_currency_id")
    purpose = fields.Text("Призначення платежу", required=True)
    reject_reason = fields.Text("Причина відхилення", copy=False)

    approval_ids = fields.One2many("ua.payment.request.approval", "request_id", "Погодження",
                                   readonly=True, copy=False)
    approval_round = fields.Integer("Подання", default=0, readonly=True, copy=False,
                                    help="Скільки разів заявку подавали на погодження. "
                                         "Рішення попередніх подань лишаються в історії.")
    steps_required = fields.Char("Потрібні кроки", compute="_compute_steps")
    next_step = fields.Selection(STEPS, "Наступний крок", compute="_compute_steps")
    can_approve = fields.Boolean(compute="_compute_steps")
    payment_ids = fields.Many2many("account.payment", "ua_payment_request_payment_rel",
                                   "request_id", "payment_id", "Платежі", readonly=True,
                                   copy=False)
    is_paid = fields.Boolean("Сплачено", compute="_compute_is_paid",
                             help="Усі платежі заявки проведені й звірені з випискою банку.")

    _amount_positive = models.Constraint("CHECK (amount > 0)",
                                         "Сума заявки має бути більшою за нуль.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.payment.request") or "/"
        return super().create(vals_list)

    @api.depends("partner_id")
    def _compute_partner_bank_id(self):
        for request in self:
            if request.partner_bank_id.partner_id != request.partner_id:
                request.partner_bank_id = request.partner_id.bank_ids.filtered(
                    lambda b: b.company_id in (False, request.company_id))[:1]

    @api.depends("amount", "currency_id", "date")
    def _compute_amount_company(self):
        for request in self:
            request.amount_company = request.currency_id._convert(
                request.amount, request.company_currency_id, request.company_id,
                request.date or fields.Date.context_today(request))

    @api.onchange("bill_ids")
    def _onchange_bill_ids(self):
        if self.bill_ids:
            self.currency_id = self.bill_ids[0].currency_id
            self.amount = sum(self.bill_ids.mapped("amount_residual"))
            if not self.purpose:
                self.purpose = _("Оплата за %s") % ", ".join(
                    self.bill_ids.mapped(lambda b: b.ref or b.name))

    @api.constrains("bill_ids", "partner_id", "currency_id")
    def _check_bills(self):
        # Ініціатор може не мати прав на бухгалтерію: рахунки читаємо від імені системи.
        for request in self.sudo():
            if request.bill_ids.filtered(
                    lambda b: b.commercial_partner_id != request.partner_id.commercial_partner_id):
                raise ValidationError(_("Рахунки в заявці мають бути від одержувача."))
            if request.bill_ids.filtered(lambda b: b.currency_id != request.currency_id):
                raise ValidationError(_("Валюта заявки має збігатися з валютою рахунків."))

    def _steps(self):
        """Кроки погодження цієї заявки по порядку."""
        self.ensure_one()
        limit = self.company_id.ua_payment_request_limit
        steps = ["finance"]
        if not limit or self.company_currency_id.compare_amounts(self.amount_company, limit) > 0:
            steps.append("director")
        return steps

    def _current_approvals(self):
        self.ensure_one()
        return self.approval_ids.filtered(lambda a: a.submission == self.approval_round)

    @api.depends("amount_company", "approval_ids", "state", "approval_round")
    @api.depends_context("uid")
    def _compute_steps(self):
        labels = dict(STEPS)
        for request in self:
            steps = request._steps() if request.company_id else []
            done = request._current_approvals().filtered(
                lambda a: a.decision == "approve").mapped("step")
            pending = [step for step in steps if step not in done]
            request.steps_required = ", ".join(labels[step] for step in steps)
            request.next_step = pending[0] if pending and request.state == "submitted" else False
            request.can_approve = bool(request.next_step) and request._may_decide(
                request.next_step)

    def _may_decide(self, step):
        self.ensure_one()
        return self.env.user.has_group(STEP_GROUPS[step]) and self.env.user != self.user_id

    @api.depends("payment_ids.state", "payment_ids.is_matched")
    def _compute_is_paid(self):
        for request in self:
            payments = request.sudo().payment_ids.filtered(lambda p: p.state != "canceled")
            request.is_paid = bool(payments) and all(
                p.state == "paid" or p.is_matched for p in payments)

    # ------------------------------------------------------------------ дії
    def action_submit(self):
        for request in self:
            if request.state not in ("draft", "rejected"):
                raise UserError(_("На погодження подають чернетку або відхилену заявку."))
            request.write({"state": "submitted", "reject_reason": False,
                           "approval_round": request.approval_round + 1})
            request.message_post(body=_("Подано на погодження: %s.") % request.steps_required)
        return True

    def _decide(self, decision, note=False):
        self.ensure_one()
        if self.state != "submitted":
            raise UserError(_("Заявка %s не на погодженні.") % self.name)
        step = self.next_step
        if self.env.user == self.user_id:
            raise UserError(_("Ініціатор не погоджує власну заявку."))
        if not self.env.user.has_group(STEP_GROUPS[step]):
            raise UserError(_("Крок «%s» вам не доступний.") % dict(STEPS)[step])
        self.env["ua.payment.request.approval"].create({
            "request_id": self.id, "step": step, "decision": decision, "note": note,
            "submission": self.approval_round})
        self.invalidate_recordset(["next_step", "can_approve"])

    def action_approve(self):
        for request in self:
            request._decide("approve")
            if not request.next_step:
                request.state = "approved"
                request.message_post(body=_("Заявку погоджено."))
        return True

    def action_reject(self):
        for request in self:
            reason = (request.reject_reason or "").strip()
            if not reason:
                raise UserError(_("Напишіть причину відхилення."))
            request._decide("reject", reason)
            request.state = "rejected"
            request.message_post(body=_("Заявку відхилено: %s") % reason)
        return True

    def action_cancel(self):
        for request in self:
            if request.state == "payment":
                raise UserError(_("За заявкою %s уже створено платіж - скасуйте платіж.")
                                % request.name)
            request.state = "cancel"
        return True

    def action_draft(self):
        for request in self:
            if request.state not in ("rejected", "cancel"):
                raise UserError(_("У чернетку повертають відхилену або скасовану заявку."))
            request.state = "draft"
        return True

    def action_create_payment(self):
        """Платіж за погодженою заявкою: за рахунками - майстром оплати, інакше аванс."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError(_("Платіж створюють лише за погодженою заявкою."))
        journal = self.journal_id or self.env["account.journal"].search([
            ("company_id", "=", self.company_id.id), ("type", "=", "bank")], limit=1)
        if not journal:
            raise UserError(_("Вкажіть рахунок, з якого платити."))
        bills = self.bill_ids.filtered(lambda b: b.payment_state in ("not_paid", "partial"))
        if bills:
            open_amount = sum(bills.mapped("amount_residual"))
            if self.currency_id.compare_amounts(self.amount, open_amount) > 0:
                raise UserError(_("Сума заявки %(amount)s більша за залишок рахунків %(open)s.",
                                  amount=self.amount, open=open_amount))
            wizard = self.env["account.payment.register"].with_context(
                active_model="account.move", active_ids=bills.ids).create({
                    "journal_id": journal.id,
                    "payment_date": self.date_due,
                    "amount": self.amount,
                    "currency_id": self.currency_id.id,
                    "partner_bank_id": self.partner_bank_id.id,
                    "group_payment": True,
                    "communication": self.purpose,
                })
            payments = wizard._create_payments()
        else:
            payments = self.env["account.payment"].create({
                "payment_type": "outbound", "partner_type": "supplier",
                "partner_id": self.partner_id.id, "amount": self.amount,
                "currency_id": self.currency_id.id, "journal_id": journal.id,
                "date": self.date_due, "memo": self.purpose,
                "partner_bank_id": self.partner_bank_id.id,
                "company_id": self.company_id.id,
            })
            payments.action_post()
        if self.contract_id and "ua_contract_id" in payments._fields:
            payments.filtered(lambda p: not p.ua_contract_id).ua_contract_id = self.contract_id
        self.write({"payment_ids": [(4, p.id) for p in payments], "state": "payment"})
        self.message_post(body=_("Створено платіж %s.") % ", ".join(payments.mapped("name")))
        return {"type": "ir.actions.act_window", "res_model": "account.payment",
                "res_id": payments[:1].id, "view_mode": "form"}

    def action_print(self):
        return self.env.ref("l10n_ua_payment_request.action_report_ua_payment_request") \
            .report_action(self)

    def unlink(self):
        if any(request.state not in ("draft", "cancel") for request in self):
            raise UserError(_("Видалити можна лише чернетку або скасовану заявку."))
        return super().unlink()

    @api.model
    def calendar_rows(self, date_from, date_to, company=None):
        """Платіжний календар: заявки на погодженні й погоджені за датами оплати.

        [{date, requests, amount, approved}] у гривні, по днях, по порядку."""
        company = company or self.env.company
        requests = self.search([("company_id", "=", company.id),
                                ("state", "in", ("submitted", "approved")),
                                ("date_due", ">=", date_from), ("date_due", "<=", date_to)])
        days = {}
        for request in requests:
            row = days.setdefault(request.date_due, {"date": request.date_due, "requests": 0,
                                                     "amount": 0.0, "approved": 0.0})
            row["requests"] += 1
            row["amount"] += request.amount_company
            if request.state == "approved":
                row["approved"] += request.amount_company
        return [days[day] for day in sorted(days)]


class UaPaymentRequestApproval(models.Model):
    _name = "ua.payment.request.approval"
    _description = "Рішення щодо заявки на оплату"
    _order = "request_id, id"

    request_id = fields.Many2one("ua.payment.request", required=True, ondelete="cascade",
                                 index=True)
    submission = fields.Integer("Подання", required=True, default=1)
    step = fields.Selection(STEPS, "Крок", required=True)
    decision = fields.Selection([("approve", "Погоджено"), ("reject", "Відхилено")], "Рішення",
                                required=True)
    user_id = fields.Many2one("res.users", "Хто", required=True, default=lambda s: s.env.user)
    date = fields.Datetime("Коли", required=True, default=fields.Datetime.now)
    note = fields.Text("Коментар")
