"""План і факт виробітку працівників за місяць.

План на працівника - сума виробітку, грн, і за бажанням нормо-години. Факт - із затверджених
документів «Виробіток», чий кінець періоду в цьому місяці: сума, нормативний час виконаних робіт
(кількість × норма часу операції) і фактичний час з обліку часу операцій.

Дві формули:
  виконання плану, %  = факт, грн / план, грн × 100;
  ефективність, %     = нормативні години / фактичні години × 100 (вище 100 - швидше за норму).
"""
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _first_day(value):
    return value.replace(day=1) if value else value


def _last_day(first):
    return (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


class UaPieceworkPlan(models.Model):
    _name = "ua.piecework.plan"
    _inherit = ["mail.thread"]
    _description = "План і факт виробітку"
    _order = "month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    month = fields.Date("Місяць", required=True, default=lambda s: _first_day(fields.Date.context_today(s)),
                        tracking=True, help="Будь-яка дата місяця; зберігається перше число.")
    line_ids = fields.One2many("ua.piecework.plan.line", "plan_id", "Працівники", copy=True)
    plan_total = fields.Monetary("План, грн", compute="_compute_totals", store=True)
    fact_total = fields.Monetary("Факт, грн", compute="_compute_totals", store=True)
    percent_total = fields.Float("Виконання, %", digits=(6, 1), compute="_compute_totals", store=True)
    computed_on = fields.Datetime("Факт пораховано", readonly=True, copy=False)

    _company_month_uniq = models.Constraint("unique(company_id, month)", "План на цей місяць уже є.")

    @api.depends("month")
    def _compute_name(self):
        for plan in self:
            plan.name = _("План виробітку %s") % plan.month.strftime("%m.%Y") if plan.month else "/"

    @api.depends("line_ids.plan_amount", "line_ids.fact_amount")
    def _compute_totals(self):
        for plan in self:
            plan.plan_total = sum(plan.line_ids.mapped("plan_amount"))
            plan.fact_total = sum(plan.line_ids.mapped("fact_amount"))
            plan.percent_total = plan.fact_total / plan.plan_total * 100.0 if plan.plan_total else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("month"):
                vals["month"] = _first_day(fields.Date.to_date(vals["month"]))
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("month"):
            vals["month"] = _first_day(fields.Date.to_date(vals["month"]))
        return super().write(vals)

    def _fact_lines(self):
        self.ensure_one()
        return self.env["ua.piecework.line"].search([
            ("company_id", "=", self.company_id.id), ("state", "=", "confirmed"), ("employee_id", "!=", False),
            ("piecework_id.date_to", ">=", self.month), ("piecework_id.date_to", "<=", _last_day(self.month))])

    def action_compute(self):
        """Порахувати факт; працівник з виробітком без плану отримує рядок з нульовим планом."""
        for plan in self:
            facts = defaultdict(lambda: [0.0, 0.0, 0.0])
            for line in plan._fact_lines():
                fact = facts[line.employee_id]
                fact[0] += line.amount
                fact[1] += line._ua_norm_minutes()
                fact[2] += line.minutes
            Line = self.env["ua.piecework.plan.line"]
            existing = {line.employee_id: line for line in plan.line_ids}
            for employee in set(facts) - set(existing):
                existing[employee] = Line.create({"plan_id": plan.id, "employee_id": employee.id})
            for employee, line in existing.items():
                amount, norm, actual = facts.get(employee, (0.0, 0.0, 0.0))
                line.write({"fact_amount": plan.currency_id.round(amount), "fact_norm_hours": norm / 60.0,
                            "fact_hours": actual / 60.0})
            plan.computed_on = fields.Datetime.now()
        return True

    def action_copy_previous(self):
        """План минулого місяця як початок для цього."""
        for plan in self:
            previous = self.search([("company_id", "=", plan.company_id.id),
                                    ("month", "=", _first_day(plan.month - timedelta(days=1)))], limit=1)
            if not previous:
                raise UserError(_("Плану за попередній місяць немає."))
            have = plan.line_ids.employee_id
            plan.line_ids = [(0, 0, {"employee_id": line.employee_id.id, "plan_amount": line.plan_amount,
                                     "plan_norm_hours": line.plan_norm_hours})
                             for line in previous.line_ids if line.employee_id not in have]
        return True


class UaPieceworkPlanLine(models.Model):
    _name = "ua.piecework.plan.line"
    _description = "План і факт виробітку працівника"
    _order = "plan_id, employee_id"

    plan_id = fields.Many2one("ua.piecework.plan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="plan_id.company_id", store=True)
    currency_id = fields.Many2one(related="plan_id.currency_id")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, check_company=True)
    plan_amount = fields.Monetary("План, грн")
    plan_norm_hours = fields.Float("План, нормо-год", digits=(10, 2))
    fact_amount = fields.Monetary("Факт, грн", readonly=True)
    fact_norm_hours = fields.Float("Факт, нормо-год", digits=(10, 2), readonly=True,
                                   help="Кількість × норма часу операції на одиницю.")
    fact_hours = fields.Float("Відпрацьовано, год", digits=(10, 2), readonly=True,
                              help="Час працівника в обліку часу операцій.")
    percent_plan = fields.Float("Виконання плану, %", digits=(6, 1), compute="_compute_percent", store=True)
    efficiency = fields.Float("Ефективність, %", digits=(6, 1), compute="_compute_percent", store=True,
                              help="Нормативні години / відпрацьовані × 100.")

    _plan_employee_uniq = models.Constraint("unique(plan_id, employee_id)", "Працівник уже є в плані.")

    @api.depends("plan_amount", "fact_amount", "fact_norm_hours", "fact_hours", "plan_norm_hours")
    def _compute_percent(self):
        for line in self:
            if line.plan_amount:
                line.percent_plan = line.fact_amount / line.plan_amount * 100.0
            elif line.plan_norm_hours:
                line.percent_plan = line.fact_norm_hours / line.plan_norm_hours * 100.0
            else:
                line.percent_plan = 0.0
            line.efficiency = line.fact_norm_hours / line.fact_hours * 100.0 if line.fact_hours else 0.0
