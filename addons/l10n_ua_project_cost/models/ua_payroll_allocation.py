"""Розподіл зарплати за проєктами: години працівника за місяць по проєктах.

Документ на місяць і компанію. Рядок: працівник, проєкт (аналітичний рахунок), рахунок витрат
(порожньо - рахунок витрат працівника, для створення НМА - 154) і години. Коли листок працівника
проводиться, бік витрат кожного рядка проводки (нарахування і ЄСВ) ділиться за годинами: частка
проєкту = його години / усі години працівника в документі. Остання частина бере копійки
округлення, тож проводка лишається збалансованою. Розподіл діє, лише поки документ затверджено.
"""
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень",
          "вересень", "жовтень", "листопад", "грудень"]


def _first_day(value):
    value = fields.Date.to_date(value)
    return value.replace(day=1) if value else value


def _analytic(account):
    """Розподіл аналітики на один рахунок: {"id": 100}."""
    return {str(account.id): 100.0} if account else False


class UaPayrollAllocation(models.Model):
    _name = "ua.payroll.allocation"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Розподіл зарплати за проєктами"
    _order = "month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    month = fields.Date("Місяць", required=True, tracking=True,
                        default=lambda s: fields.Date.context_today(s).replace(day=1),
                        help="Перше число місяця. Розподіл діє на листки, чий період починається в цьому місяці.")
    state = fields.Selection([("draft", "Чернетка"), ("confirmed", "Затверджено")], "Стан", default="draft",
                             required=True, readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many("ua.payroll.allocation.line", "allocation_id", "Години за проєктами", copy=True)
    hours_total = fields.Float("Усього годин", compute="_compute_hours_total")
    note = fields.Text("Примітка")

    _company_month_uniq = models.Constraint(
        "unique(company_id, month)", "Розподіл за цей місяць у компанії вже є.")

    @api.depends("month")
    def _compute_name(self):
        for doc in self:
            doc.name = ("Розподіл зарплати за проєктами, %s %s" % (MONTHS[doc.month.month - 1], doc.month.year)
                        if doc.month else "Розподіл зарплати за проєктами")

    @api.depends("line_ids.hours")
    def _compute_hours_total(self):
        for doc in self:
            doc.hours_total = sum(doc.line_ids.mapped("hours"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("month"):
                vals["month"] = _first_day(vals["month"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("month"):
            vals["month"] = _first_day(vals["month"])
        return super().write(vals)

    # ---- дії ---------------------------------------------------------------------------
    def action_confirm(self):
        for doc in self:
            if not doc.line_ids.filtered(lambda line: line.hours > 0):
                raise UserError(_("Немає жодної години: розподіляти нічого."))
            negative = doc.line_ids.filtered(lambda line: line.hours < 0)
            if negative:
                raise UserError(_("Години не бувають від'ємними: %s.") % ", ".join(negative.employee_id.mapped("name")))
        self.write({"state": "confirmed"})
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_copy_previous(self):
        """Взяти рядки попереднього місяця: ті самі люди, проєкти, рахунки і години."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Рядки змінюються лише в чернетці."))
        previous = self.search([("company_id", "=", self.company_id.id), ("month", "<", self.month)],
                               order="month desc", limit=1)
        if not previous:
            raise UserError(_("Попереднього розподілу немає."))
        self.line_ids.unlink()
        self.write({"line_ids": [(0, 0, {
            "employee_id": line.employee_id.id, "analytic_account_id": line.analytic_account_id.id,
            "account_id": line.account_id.id, "hours": line.hours}) for line in previous.line_ids]})
        return True

    def action_fill_timesheets(self):
        """Години з обліку часу за проєктами (hr_timesheet), якщо він встановлений."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Рядки змінюються лише в чернетці."))
        Line = self.env["account.analytic.line"]
        if "employee_id" not in Line._fields:
            raise UserError(_("Облік часу за проєктами не встановлено: впишіть години або візьміть попередній місяць."))
        start, end = self._period()
        groups = Line.sudo()._read_group(
            [("company_id", "=", self.company_id.id), ("date", ">=", start), ("date", "<=", end),
             ("employee_id", "!=", False), ("account_id", "!=", False)],
            groupby=["employee_id", "account_id"], aggregates=["unit_amount:sum"])
        if not groups:
            raise UserError(_("За місяць немає годин в обліку часу."))
        self.line_ids.unlink()
        self.write({"line_ids": [(0, 0, {"employee_id": employee.id, "analytic_account_id": account.id,
                                         "hours": hours}) for employee, account, hours in groups if hours]})
        return True

    # ---- для листка -------------------------------------------------------------------
    def _period(self):
        self.ensure_one()
        start = self.month
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        return start, fields.Date.subtract(end, days=1)

    @api.model
    def _lines_for(self, employee, company, day):
        """Рядки затвердженого розподілу місяця для працівника, з годинами."""
        doc = self.search([("company_id", "=", company.id), ("month", "=", _first_day(day)),
                           ("state", "=", "confirmed")], limit=1)
        return doc.line_ids.filtered(lambda line: line.employee_id == employee and line.hours > 0)

    # ---- перевірки --------------------------------------------------------------------
    def _slips(self):
        self.ensure_one()
        start, end = self._period()
        return self.env["hr.payslip"].search([
            ("company_id", "=", self.company_id.id), ("date_from", ">=", start), ("date_from", "<=", end),
            ("state", "in", ("draft", "verify", "done"))])

    def _checks(self):
        self.ensure_one()
        out = []
        lines = self.line_ids.filtered(lambda line: line.hours > 0)
        if not lines:
            return [self._check_warn("Немає годин: листки місяця підуть на рахунки витрат працівників без поділу.")]
        if self.state != "confirmed":
            out.append(self._check_warn("Розподіл у чернетці: проведені листки його не бачать."))
        employees = lines.employee_id
        slips = self._slips()
        missing = slips.filtered(lambda slip: slip.employee_id not in employees)
        if missing:
            out.append(self._check_warn("Листки без розподілу: їхні витрати підуть на рахунок працівника.",
                                        len(missing), self._target_records(missing)))
        posted = slips.filtered(lambda slip: slip.employee_id in employees and slip.move_id
                                and not any(slip.move_id.line_ids.mapped("analytic_distribution")))
        if posted:
            out.append(self._check_error(
                "Листки проведено до затвердження розподілу: проєкти їх не бачать. Скасуйте і проведіть ще раз.",
                len(posted), self._target_records(posted)))
        start, _end = self._period()
        sheet_lines = self.env["ua.timesheet.line"].search([
            ("sheet_id.company_id", "=", self.company_id.id), ("sheet_id.year", "=", start.year),
            ("sheet_id.month", "=", start.month), ("employee_id", "in", employees.ids)])
        worked = {}
        for row in sheet_lines:
            worked[row.employee_id] = worked.get(row.employee_id, 0.0) + row.hours
        differ = [emp for emp in employees if emp in worked
                  and abs(sum(lines.filtered(lambda l, e=emp: l.employee_id == e).mapped("hours")) - worked[emp]) > 0.01]
        if differ:
            out.append(self._check_warn("Години розподілу не збігаються з табелем.",
                                        ", ".join(emp.name for emp in differ), self._target_records(sheet_lines)))
        if not out:
            out.append(self._check_ok("Усі листки місяця мають розподіл, години збігаються з табелем.", len(employees)))
        return out


class UaPayrollAllocationLine(models.Model):
    _name = "ua.payroll.allocation.line"
    _description = "Рядок розподілу зарплати за проєктами"
    _order = "employee_id, id"

    allocation_id = fields.Many2one("ua.payroll.allocation", "Розподіл", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="allocation_id.company_id", store=True)
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, check_company=True)
    analytic_account_id = fields.Many2one("account.analytic.account", "Проєкт", check_company=True,
                                          help="Аналітичний рахунок проєкту. Порожньо - без аналітики.")
    account_id = fields.Many2one("account.account", "Рахунок витрат", check_company=True,
                                 help="Порожньо - рахунок витрат працівника або підрозділу (92, 93, 23). "
                                      "Для проєкту, що створює нематеріальний актив, - 154.")
    hours = fields.Float("Годин")
    share = fields.Float("Частка, %", compute="_compute_share", digits=(5, 2))

    @api.depends("hours", "employee_id", "allocation_id.line_ids.hours")
    def _compute_share(self):
        for line in self:
            mine = line.allocation_id.line_ids.filtered(lambda l: l.employee_id == line.employee_id)
            total = sum(mine.mapped("hours"))
            line.share = 100.0 * line.hours / total if total else 0.0

    @api.constrains("hours")
    def _check_hours(self):
        if self.filtered(lambda line: line.hours < 0):
            raise ValidationError(_("Години не бувають від'ємними."))


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_split(self, account, amount, expense):
        if account != expense:
            return super()._ua_split(account, amount, expense)
        lines = self.env["ua.payroll.allocation"]._lines_for(self.employee_id, self.company_id, self.date_from)
        if not lines:
            return super()._ua_split(account, amount, expense)
        currency = self.company_id.currency_id
        total = sum(lines.mapped("hours"))
        parts, done = [], 0.0
        for index, line in enumerate(lines):
            if index == len(lines) - 1:
                part = currency.round(amount - done)
            else:
                part = currency.round(amount * line.hours / total)
                done += part
            if not currency.is_zero(part):
                parts.append((line.account_id or expense, part, _analytic(line.analytic_account_id)))
        return parts or super()._ua_split(account, amount, expense)
