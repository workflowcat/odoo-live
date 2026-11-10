"""Розрахункова відомість з сальдо: розрахунки з кожним працівником за місяць (рахунок 661).

Числа - з проведених проводок, не з листків: сальдо на початок, нараховано (кредит 661),
утримано (дебет 661 у проводках листків: ПДФО, ВЗ, аліменти), виплачено (дебет 661 в інших
проводках: банк, каса), сальдо на кінець. Додатне сальдо - підприємство винне працівнику.
Рахунок розрахунків з картки працівника (замість 661) теж враховується."""
import calendar
from collections import defaultdict
from datetime import date

from odoo import _, fields, models
from odoo.exceptions import UserError

MONTHS = [(str(n), name) for n, name in enumerate(
    ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень",
     "Вересень", "Жовтень", "Листопад", "Грудень"], 1)]


def _money(amount):
    return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")


class UaPayrollStatement(models.TransientModel):
    _name = "ua.payroll.statement"
    _description = "Розрахункова відомість з сальдо"

    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    year = fields.Integer("Рік", required=True, default=lambda s: fields.Date.context_today(s).year)
    month = fields.Selection(MONTHS, "Місяць", required=True,
                             default=lambda s: str(fields.Date.context_today(s).month))
    department_id = fields.Many2one("hr.department", "Підрозділ", help="Порожньо - усі працівники компанії")
    line_ids = fields.One2many("ua.payroll.statement.line", "statement_id", "Працівники")
    computed = fields.Boolean(readonly=True)

    def _period(self):
        year, month = self.year, int(self.month)
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])

    def _employees(self):
        domain = [("company_id", "=", self.company_id.id)]
        if self.department_id:
            domain.append(("department_id", "child_of", self.department_id.id))
        return self.env["hr.employee"].sudo().with_context(active_test=False).search(domain, order="name")

    def _accounts(self, employees):
        Account = self.env["account.account"].sudo().with_company(self.company_id)
        accounts = Account.search([("code", "=like", "661%"), ("company_ids", "in", self.company_id.id)])
        return accounts | employees.mapped("ua_payable_account_id")

    def _figures(self):
        """{працівник: (сальдо на початок, нараховано, утримано, виплачено)}."""
        self.ensure_one()
        d1, d2 = self._period()
        employees = self._employees()
        by_partner = {emp.work_contact_id.id: emp for emp in employees if emp.work_contact_id}
        accounts = self._accounts(employees)
        if not by_partner or not accounts:
            return {}
        Line = self.env["account.move.line"].sudo()
        base = [("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
                ("account_id", "in", accounts.ids), ("partner_id", "in", list(by_partner))]
        opening = defaultdict(float)
        for partner, balance in Line._read_group(base + [("date", "<", d1)], ["partner_id"], ["balance:sum"]):
            opening[partner.id] = -(balance or 0.0)        # кредитове сальдо 661 - борг перед працівником
        lines = Line.search(base + [("date", ">=", d1), ("date", "<=", d2)])
        slip_moves = self.env["hr.payslip"].sudo().search([("move_id", "in", lines.mapped("move_id").ids)]).mapped("move_id")
        accrued, withheld, paid = defaultdict(float), defaultdict(float), defaultdict(float)
        for line in lines:
            pid = line.partner_id.id
            accrued[pid] += line.credit
            if line.move_id in slip_moves:
                withheld[pid] += line.debit
            else:
                paid[pid] += line.debit
        out = {}
        currency = self.company_id.currency_id
        for pid, emp in by_partner.items():
            values = tuple(currency.round(x) for x in (opening[pid], accrued[pid], withheld[pid], paid[pid]))
            if any(values):
                out[emp] = values
        return out

    def action_compute(self):
        self.ensure_one()
        figures = self._figures()
        self.line_ids.unlink()
        Line = self.env["ua.payroll.statement.line"]
        for sequence, emp in enumerate(sorted(figures, key=lambda e: e.name or ""), 1):
            opening, accrued, withheld, paid = figures[emp]
            Line.create({"statement_id": self.id, "sequence": sequence, "employee_id": emp.id,
                         "opening": opening, "accrued": accrued, "withheld": withheld, "paid": paid})
        self.computed = True
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}

    def action_print(self):
        self.ensure_one()
        if not self.computed:
            self.action_compute()
        if not self.line_ids:
            raise UserError(_("За цей місяць немає розрахунків з працівниками: друкувати нічого."))
        return self.env.ref("l10n_ua_payroll_account.action_report_ua_payroll_statement").report_action(self)

    # ---- друк -------------------------------------------------------------------------
    def money(self, amount):
        return _money(amount)

    def period_text(self):
        d1, d2 = self._period()
        return "%s - %s" % (d1.strftime("%d.%m.%Y"), d2.strftime("%d.%m.%Y"))

    def signers(self):
        """Підписи: керівник і головний бухгалтер із картки компанії, якщо модуль документів їх веде."""
        company = self.company_id.sudo()
        return [("Керівник", getattr(company, "ua_director_name", "") or ""),
                ("Головний бухгалтер", getattr(company, "ua_accountant_name", "") or "")]

    def totals(self):
        lines = self.line_ids
        return {key: sum(lines.mapped(key)) for key in ("opening", "accrued", "withheld", "paid", "closing")}


class UaPayrollStatementLine(models.TransientModel):
    _name = "ua.payroll.statement.line"
    _description = "Рядок розрахункової відомості з сальдо"
    _order = "sequence, id"

    statement_id = fields.Many2one("ua.payroll.statement", required=True, ondelete="cascade")
    sequence = fields.Integer("№")
    employee_id = fields.Many2one("hr.employee", "Працівник", readonly=True)
    currency_id = fields.Many2one(related="statement_id.company_id.currency_id")
    opening = fields.Monetary("Сальдо на початок", readonly=True,
                              help="Додатне - підприємство винне працівнику, від'ємне - працівник винен підприємству")
    accrued = fields.Monetary("Нараховано", readonly=True)
    withheld = fields.Monetary("Утримано", readonly=True)
    paid = fields.Monetary("Виплачено", readonly=True)
    closing = fields.Monetary("Сальдо на кінець", compute="_compute_closing")

    def _compute_closing(self):
        for line in self:
            line.closing = line.currency_id.round(line.opening + line.accrued - line.withheld - line.paid) \
                if line.currency_id else line.opening + line.accrued - line.withheld - line.paid
