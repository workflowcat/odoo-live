# -*- coding: utf-8 -*-
"""Бюджет руху грошових коштів (БДДС) за статтями форми № 3.

План - сума на статтю й місяць. Факт - рух коштів за тими самими правилами статей, що й у
формі № 3 (`ua.cashflow.statement.ua_flow_totals`). Зобов'язано - заявки на оплату, подані або
погоджені, але ще не оплачені. Залишок = план - факт - зобов'язано.

Усі суми бюджету додатні: для статті витрачання факт - скільки сплачено, для статті надходження -
скільки надійшло. Затверджений бюджет на рік у компанії один; він і контролює заявки на оплату.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MONTHS = [(str(m), name) for m, name in enumerate(
    ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень",
     "Вересень", "Жовтень", "Листопад", "Грудень"], start=1)]
STATES = [("draft", "Чернетка"), ("approved", "Затверджено"), ("closed", "Закрито")]
CONTROLS = [
    ("none", "Без контролю"),
    ("director", "Понад бюджет - погоджує директор"),
    ("block", "Понад бюджет - заявку не подати"),
]
OPEN_REQUEST_STATES = ("submitted", "approved")


class UaCashflowBudget(models.Model):
    _name = "ua.cashflow.budget"
    _description = "Бюджет руху грошових коштів"
    _inherit = ["mail.thread"]
    _order = "year desc, id desc"

    name = fields.Char("Назва", required=True, default=lambda self: _("Бюджет руху коштів"))
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer(
        "Рік", required=True, tracking=True, default=lambda self: fields.Date.context_today(self).year)
    state = fields.Selection(STATES, string="Стан", default="draft", required=True, tracking=True)
    control = fields.Selection(
        CONTROLS, string="Контроль заявок", default="director", required=True, tracking=True,
        help="Що робити із заявкою на оплату, сума якої більша за залишок статті на місяць оплати.")
    line_ids = fields.One2many("ua.cashflow.budget.line", "budget_id", string="Рядки")
    fact_at = fields.Datetime("Факт оновлено", readonly=True)
    fill_year = fields.Integer("Рік факту", help="Заповнити план фактом цього року.")
    fill_percent = fields.Float("Зміна, %", help="Напр. 10 - на 10 % більше за факт.")
    plan_in = fields.Monetary("План надходжень", compute="_compute_totals", currency_field="currency_id")
    plan_out = fields.Monetary("План витрачань", compute="_compute_totals", currency_field="currency_id")
    fact_in = fields.Monetary("Факт надходжень", compute="_compute_totals", currency_field="currency_id")
    fact_out = fields.Monetary("Факт витрачань", compute="_compute_totals", currency_field="currency_id")

    @api.depends("line_ids.plan", "line_ids.fact", "line_ids.kind")
    def _compute_totals(self):
        for budget in self:
            lines_in = budget.line_ids.filtered(lambda l: l.kind == "in")
            lines_out = budget.line_ids - lines_in
            budget.plan_in = sum(lines_in.mapped("plan"))
            budget.plan_out = sum(lines_out.mapped("plan"))
            budget.fact_in = sum(lines_in.mapped("fact"))
            budget.fact_out = sum(lines_out.mapped("fact"))

    @api.constrains("state", "year", "company_id")
    def _check_one_approved(self):
        for budget in self.filtered(lambda b: b.state == "approved"):
            twins = self.search_count([
                ("id", "!=", budget.id), ("company_id", "=", budget.company_id.id),
                ("year", "=", budget.year), ("state", "=", "approved")])
            if twins:
                raise ValidationError(_("На %s рік уже є затверджений бюджет руху коштів.") % budget.year)

    @api.constrains("year")
    def _check_year(self):
        for budget in self:
            if not 2000 <= budget.year <= 2100:
                raise ValidationError(_("Рік бюджету: від 2000 до 2100."))

    # ------------------------------------------------------------------ пошук
    @api.model
    def ua_active(self, company, day):
        """Затверджений бюджет компанії на рік дня, або порожньо."""
        return self.search([("company_id", "=", company.id), ("year", "=", day.year),
                            ("state", "=", "approved")], limit=1)

    def _ua_line(self, item, month, create=False):
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: l.item_id == item and l.month == str(month))[:1]
        if not line and create:
            line = self.env["ua.cashflow.budget.line"].create(
                {"budget_id": self.id, "item_id": item.id, "month": str(month), "plan": 0.0})
        return line

    @staticmethod
    def _month_range(year, month):
        start = date(year, month, 1)
        return start, start + relativedelta(months=1, days=-1)

    def _ua_fact(self, month):
        """Факт місяця за статтями: {стаття: сума, додатна}."""
        self.ensure_one()
        start, end = self._month_range(self.year, month)
        totals = self.env["ua.cashflow.statement"].sudo().ua_flow_totals(self.company_id, start, end)
        items = self.env["ua.cashflow.item"].browse(list(totals))
        return {item: (totals[item.id] if item.kind == "in" else -totals[item.id]) for item in items}

    def _ua_committed(self, item, month, exclude=None):
        """Подані й погоджені, ще не оплачені заявки зі статтею на місяць оплати."""
        self.ensure_one()
        start, end = self._month_range(self.year, month)
        domain = [("company_id", "=", self.company_id.id), ("ua_cashflow_item_id", "=", item.id),
                  ("state", "in", OPEN_REQUEST_STATES), ("date_due", ">=", start), ("date_due", "<=", end)]
        if exclude:
            domain.append(("id", "not in", exclude.ids))
        return sum(self.env["ua.payment.request"].sudo().search(domain).mapped("amount_company"))

    # ------------------------------------------------------------------ дії
    def action_refresh_fact(self):
        """Факт і зобов'язання в усі рядки; стаття з фактом без плану отримує рядок з нулем плану."""
        for budget in self:
            for month in range(1, 13):
                start, _end = self._month_range(budget.year, month)
                if start > fields.Date.context_today(budget):
                    facts = {}
                else:
                    facts = budget._ua_fact(month)
                for item, amount in facts.items():
                    if not budget.currency_id.is_zero(amount):
                        budget._ua_line(item, month, create=True)
                for line in budget.line_ids.filtered(lambda l: l.month == str(month)):
                    line.write({"fact": facts.get(line.item_id, 0.0),
                                "committed": budget._ua_committed(line.item_id, month)})
            budget.fact_at = fields.Datetime.now()
        return True

    def action_fill_from_fact(self):
        """План = факт року «Рік факту» по місяцях, змінений на «Зміна, %». Лише чернетка."""
        for budget in self:
            if budget.state != "draft":
                raise UserError(_("План змінюють лише в чернетці."))
            source_year = budget.fill_year or budget.year - 1
            factor = 1 + (budget.fill_percent or 0.0) / 100.0
            probe = self.new({"company_id": budget.company_id.id, "year": source_year})
            for month in range(1, 13):
                for item, amount in probe._ua_fact(month).items():
                    if budget.currency_id.is_zero(amount):
                        continue
                    line = budget._ua_line(item, month, create=True)
                    line.plan = budget.currency_id.round(amount * factor)
            budget.message_post(body=_("План заповнено фактом %(year)s року, зміна %(pct)s %%.",
                                       year=source_year, pct=budget.fill_percent or 0))
        return True

    def action_approve(self):
        for budget in self:
            if not budget.line_ids.filtered("plan"):
                raise UserError(_("У бюджеті немає жодної суми плану."))
            budget.state = "approved"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    def action_open_analysis(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Виконання: %s") % self.name,
            "res_model": "ua.cashflow.budget.line", "view_mode": "pivot,list",
            "domain": [("budget_id", "=", self.id)],
            "context": {"pivot_measures": ["plan", "fact", "remaining"]},
        }

    def action_print(self):
        return self.env.ref("l10n_ua_budget.action_report_ua_budget").report_action(self)

    # ------------------------------------------------------------------ друк
    def ua_rows(self, upto_month=12):
        """Рядки виконання за статтями до місяця включно: стаття, план, факт, відхилення, %."""
        self.ensure_one()
        rows = {}
        for line in self.line_ids.filtered(lambda l: int(l.month) <= upto_month):
            row = rows.setdefault(line.item_id, [0.0, 0.0])
            row[0] += line.plan
            row[1] += line.fact
        result = []
        for item in sorted(rows, key=lambda i: i.code):
            plan, fact = rows[item]
            pct = (fact / plan * 100.0) if plan else None
            result.append((item, plan, fact, fact - plan, pct))
        return result


class UaCashflowBudgetLine(models.Model):
    _name = "ua.cashflow.budget.line"
    _description = "Рядок бюджету руху коштів"
    _order = "item_code, month_num"

    budget_id = fields.Many2one("ua.cashflow.budget", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="budget_id.company_id", store=True)
    currency_id = fields.Many2one(related="budget_id.currency_id")
    year = fields.Integer(related="budget_id.year", store=True)
    item_id = fields.Many2one("ua.cashflow.item", string="Стаття", required=True, ondelete="restrict")
    item_code = fields.Char(related="item_id.code", store=True)
    kind = fields.Selection(related="item_id.kind", store=True)
    section = fields.Selection(related="item_id.section", store=True)
    month = fields.Selection(MONTHS, string="Місяць", required=True)
    month_num = fields.Integer(compute="_compute_month_num", store=True)
    plan = fields.Monetary("План", currency_field="currency_id")
    fact = fields.Monetary("Факт", currency_field="currency_id", readonly=True)
    committed = fields.Monetary(
        "Зобов'язано", currency_field="currency_id", readonly=True,
        help="Подані й погоджені заявки на оплату з цією статтею, ще не оплачені.")
    remaining = fields.Monetary(
        "Залишок", currency_field="currency_id", compute="_compute_remaining", store=True)

    _line_uniq = models.Constraint(
        "unique(budget_id, item_id, month)", "Стаття вже має рядок на цей місяць у бюджеті.")

    @api.depends("month")
    def _compute_month_num(self):
        for line in self:
            line.month_num = int(line.month or 0)

    @api.depends("plan", "fact", "committed")
    def _compute_remaining(self):
        for line in self:
            line.remaining = line.plan - line.fact - line.committed

    @api.constrains("plan")
    def _check_plan(self):
        for line in self:
            if line.plan < 0:
                raise ValidationError(_("План - додатна сума: напрям задає стаття."))

    def write(self, vals):
        if "plan" in vals and self.filtered(lambda l: l.budget_id.state != "draft"):
            raise UserError(_("План затвердженого бюджету не змінюють: поверніть бюджет у чернетку."))
        return super().write(vals)
