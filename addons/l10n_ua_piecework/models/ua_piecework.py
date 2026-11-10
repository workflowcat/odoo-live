"""Виробіток працівників (відрядна оплата) за виконаними операціями виробництва.

Що рахуємо:
  - операція технологічної карти має розцінку, грн за одиницю виробу;
  - завершена операція виробничого замовлення (наряд) дає кількість - скільки виробів через неї
    пройшло;
  - кількість ділиться між працівниками пропорційно їхнім хвилинам в обліку часу цієї операції
    (користувач облікового запису -> працівник тієї ж компанії). Немає часу - один рядок без
    працівника, його вказують руками;
  - сума рядка = кількість × розцінка, до копійки.

Затверджений виробіток лягає в розрахунковий листок працівника рядком введення «Відрядна оплата»
(код PIECE) - у той листок, чий період містить кінець періоду виробітку. Рядок введення веде
лише цей модуль (позначка ua_piecework_auto); ручну суму PIECE модуль не перезаписує.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PIECE = "PIECE"
OPEN_SLIP_STATES = ("draft", "verify")


class UaPiecework(models.Model):
    _name = "ua.piecework"
    _description = "Виробіток (відрядна оплата)"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date("З", required=True, tracking=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date("По", required=True, tracking=True,
                          default=lambda self: self._default_date_to())
    workcenter_ids = fields.Many2many(
        "mrp.workcenter", string="Робочі центри", check_company=True,
        help="Порожньо - усі робочі центри компанії.")
    state = fields.Selection(
        [("draft", "Чернетка"), ("confirmed", "Затверджено"), ("cancel", "Скасовано")],
        "Стан", default="draft", required=True, readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many("ua.piecework.line", "piecework_id", "Рядки", copy=False)
    amount_total = fields.Monetary("Разом", compute="_compute_amount_total", store=True)
    note = fields.Text("Примітка")

    @api.model
    def _default_date_to(self):
        first = fields.Date.context_today(self).replace(day=1)
        return (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for doc in self:
            doc.amount_total = sum(doc.line_ids.mapped("amount"))

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for doc in self:
            if doc.date_from > doc.date_to:
                raise ValidationError(_("Початок періоду пізніше за кінець."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].with_company(
                    vals.get("company_id") or self.env.company.id
                ).next_by_code("ua.piecework", sequence_date=vals.get("date_to")) or "/"
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(doc.state == "confirmed" for doc in self):
            raise UserError(_("Затверджений виробіток не видаляють - спершу скасуйте його."))

    # ------------------------------------------------------------------
    # Заповнення
    # ------------------------------------------------------------------
    def _workorder_domain(self):
        self.ensure_one()
        start = datetime.combine(self.date_from, time.min)
        stop = datetime.combine(self.date_to + timedelta(days=1), time.min)
        domain = [
            ("state", "=", "done"), ("production_id.company_id", "=", self.company_id.id),
            ("date_finished", ">=", start), ("date_finished", "<", stop),
            ("operation_id.ua_piece_rate", ">", 0.0),
        ]
        if self.workcenter_ids:
            domain.append(("workcenter_id", "in", self.workcenter_ids.ids))
        return domain

    def _taken_workorders(self):
        """Операції, що вже є в іншому незаскасованому виробітку."""
        self.ensure_one()
        return self.env["ua.piecework.line"].search([
            ("piecework_id", "!=", self.id), ("piecework_id.state", "!=", "cancel"),
            ("workorder_id", "!=", False), ("company_id", "=", self.company_id.id),
        ]).workorder_id

    def _employee_of(self, user):
        return user.employee_ids.filtered(lambda e: e.company_id == self.company_id)[:1]

    def _split(self, workorder):
        """[(працівник, хвилини, кількість)]: кількість операції за часом працівників."""
        qty = workorder.qty_produced
        uom = workorder.product_uom_id
        minutes = defaultdict(float)
        for log in workorder.time_ids:
            employee = self._employee_of(log.user_id)
            if employee and log.duration > 0:
                minutes[employee] += log.duration
        total = sum(minutes.values())
        if not total:
            return [(self.env["hr.employee"], 0.0, qty)]
        rows, left = [], qty
        ordered = sorted(minutes.items(), key=lambda item: (-item[1], item[0].id))
        for index, (employee, spent) in enumerate(ordered):
            part = left if index == len(ordered) - 1 else uom.round(qty * spent / total)
            left -= part
            rows.append((employee, spent, part))
        return rows

    def _ua_auto_lines(self):
        """Рядки, які «Заповнити» перебудовує (решту вписано руками)."""
        return self.line_ids.filtered("workorder_id")

    def _ua_fill_values(self):
        """Значення рядків із завершених операцій виробництва; інші джерела додають свої."""
        self.ensure_one()
        workorders = self.env["mrp.workorder"].search(
            self._workorder_domain(), order="date_finished, id") - self._taken_workorders()
        values = []
        for workorder in workorders:
            if not workorder.qty_produced:
                continue
            for employee, spent, qty in self._split(workorder):
                values.append({
                    "piecework_id": self.id, "workorder_id": workorder.id,
                    "employee_id": employee.id or False, "minutes": spent, "quantity": qty,
                    "rate": workorder.operation_id.ua_piece_rate,
                })
        return values

    def action_fill(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            doc._ua_auto_lines().unlink()
            self.env["ua.piecework.line"].create(doc._ua_fill_values())
            if not doc.line_ids:
                raise UserError(_("За період немає завершених робіт з розцінкою, яких ще немає в "
                                  "іншому виробітку."))
        return True

    # ------------------------------------------------------------------
    # Затвердження і листки
    # ------------------------------------------------------------------
    def _slips(self, states):
        self.ensure_one()
        return self.env["hr.payslip"].search([
            ("employee_id", "in", self.line_ids.employee_id.ids), ("state", "in", list(states)),
            ("company_id", "=", self.company_id.id),
            ("date_from", "<=", self.date_to), ("date_to", ">=", self.date_to),
        ])

    def _check_closed_slips(self):
        for doc in self:
            closed = doc._slips(("done",))
            if closed:
                raise UserError(_("Листок за цей період уже проведено (%s). Виробіток у ньому "
                                  "змінювати не можна.") % ", ".join(closed.mapped("employee_id.name")))

    def _recompute_slips(self):
        for doc in self:
            doc._slips(OPEN_SLIP_STATES).compute_sheet()

    def action_confirm(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Затвердити можна лише чернетку."))
            if not doc.line_ids:
                raise UserError(_("Немає рядків. Натисніть «Заповнити»."))
            missing = doc.line_ids.filtered(lambda l: not l.employee_id)
            if missing:
                raise UserError(_("Вкажіть працівника в рядках: %s.") % ", ".join(
                    missing.mapped(lambda l: l._ua_source_name())))
            if doc.line_ids.filtered(lambda l: l.quantity < 0 or l.rate < 0):
                raise UserError(_("Кількість і розцінка не бувають від'ємними."))
        self._check_closed_slips()
        self.write({"state": "confirmed"})
        self._recompute_slips()
        return True

    def action_cancel(self):
        for doc in self:
            if doc.state != "confirmed":
                raise UserError(_("Скасувати можна лише затверджений виробіток."))
        self._check_closed_slips()
        self.write({"state": "cancel"})
        self._recompute_slips()
        return True

    def action_draft(self):
        for doc in self:
            if doc.state != "cancel":
                raise UserError(_("У чернетку повертається лише скасований виробіток."))
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_piecework.action_report_ua_piecework").report_action(self)

    # ------------------------------------------------------------------
    # Друк
    # ------------------------------------------------------------------
    @api.model
    def money(self, amount):
        """1 240,50 - сума для друку."""
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    @api.model
    def qty(self, amount):
        return ("{:,.3f}".format(amount or 0.0).rstrip("0").rstrip(".")).replace(",", " ").replace(".", ",")

    def by_employee(self):
        """[(працівник, рядки, сума)] за абеткою."""
        self.ensure_one()
        groups = defaultdict(lambda: self.env["ua.piecework.line"])
        for line in self.line_ids:
            groups[line.employee_id] |= line
        return sorted(((employee, lines, sum(lines.mapped("amount")))
                       for employee, lines in groups.items()),
                      key=lambda row: row[0].name or "")


class UaPieceworkLine(models.Model):
    _name = "ua.piecework.line"
    _description = "Рядок виробітку"
    _order = "piecework_id, employee_id, id"

    piecework_id = fields.Many2one("ua.piecework", "Виробіток", required=True, index=True,
                                   ondelete="cascade")
    company_id = fields.Many2one(related="piecework_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="piecework_id.currency_id")
    state = fields.Selection(related="piecework_id.state", store=True)
    workorder_id = fields.Many2one("mrp.workorder", "Операція замовлення", index="btree_not_null",
                                   ondelete="restrict", check_company=True)
    production_id = fields.Many2one(related="workorder_id.production_id", store=True,
                                    string="Виробниче замовлення")
    operation_id = fields.Many2one(related="workorder_id.operation_id", store=True, string="Операція")
    workcenter_id = fields.Many2one(related="workorder_id.workcenter_id", store=True,
                                    string="Робочий центр")
    product_id = fields.Many2one(related="workorder_id.product_id", store=True, string="Виріб")
    employee_id = fields.Many2one("hr.employee", "Працівник", index=True, check_company=True)
    minutes = fields.Float("Хвилин", digits=(16, 2), readonly=True,
                           help="Час працівника в обліку часу операції: за ним ділиться кількість.")
    quantity = fields.Float("Кількість", digits="Product Unit", required=True, default=0.0)
    rate = fields.Float("Розцінка", digits="Product Price", required=True, default=0.0)
    amount = fields.Monetary("Сума", compute="_compute_amount", store=True)

    @api.depends("quantity", "rate", "piecework_id.currency_id")
    def _compute_amount(self):
        for line in self:
            currency = line.piecework_id.currency_id or self.env.company.currency_id
            line.amount = currency.round(line.quantity * line.rate)

    def _ua_source_name(self):
        """Звідки рядок: для повідомлень і друку."""
        self.ensure_one()
        return self.workorder_id.display_name or self.operation_id.name or "-"

    def _ua_doc_name(self):
        """Документ-джерело для друку: виробниче замовлення або інший документ."""
        self.ensure_one()
        return self.production_id.name or "-"

    def _ua_work_name(self):
        """Назва роботи для друку."""
        self.ensure_one()
        return self.operation_id.name or "-"

    def _ua_norm_minutes(self):
        """Нормативні хвилини виконаної роботи: кількість × норма часу операції на одиницю."""
        self.ensure_one()
        return self.quantity * (self.operation_id.time_cycle_manual or 0.0)

    def write(self, vals):
        if any(line.piecework_id.state != "draft" for line in self) and set(vals) - {"state"}:
            raise UserError(_("Рядки змінюють лише в чернетці виробітку."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(line.piecework_id.state == "confirmed" for line in self):
            raise UserError(_("Рядки затвердженого виробітку не видаляють."))
