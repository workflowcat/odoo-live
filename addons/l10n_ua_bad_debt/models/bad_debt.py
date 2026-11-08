"""Резерв сумнівних боргів методом класифікації за строками непогашення (НП(С)БО 10).

Береться кожен рахунок покупця (дебетовий рядок на рахунку дебіторів), проведений до дати
розрахунку. Його залишок на дату - сума мінус оплати, зараховані до цієї дати: пізніші оплати
не зменшують боргу, який був на дату. Дні прострочки - від строку оплати. Групи і відсотки - з
наказу про облікову політику, тут вони поля документа і переходять з попереднього розрахунку.

Розрахований резерв порівнюється із залишком на рахунку резерву (38) на дату: недостачу
донараховують (Дт 944 Кт 38), надлишок сторнують в інші доходи (Дт 38 Кт 719).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero, float_round

STATES = [("draft", "Чернетка"), ("posted", "Проведено")]
BUCKETS = [("current", "Не прострочена"), ("d90", "1-90 днів"), ("d180", "91-180 днів"),
           ("d365", "181-365 днів"), ("over", "Понад 365 днів")]
PERCENT_FIELDS = {"current": "pct_current", "d90": "pct_d90", "d180": "pct_d180", "d365": "pct_d365",
                  "over": "pct_over"}


def _money(value):
    return float_round(value, precision_digits=2)


def _bucket(days):
    if days <= 0:
        return "current"
    if days <= 90:
        return "d90"
    if days <= 180:
        return "d180"
    if days <= 365:
        return "d365"
    return "over"


class UaBadDebtReserve(models.Model):
    _name = "ua.bad.debt.reserve"
    _description = "Розрахунок резерву сумнівних боргів"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("На дату", required=True, tracking=True)
    pct_current = fields.Float("Не прострочена, %", default=lambda self: self._ua_previous_pct("pct_current", 0.0))
    pct_d90 = fields.Float("1-90 днів, %", default=lambda self: self._ua_previous_pct("pct_d90", 0.0))
    pct_d180 = fields.Float("91-180 днів, %", default=lambda self: self._ua_previous_pct("pct_d180", 0.0))
    pct_d365 = fields.Float("181-365 днів, %", default=lambda self: self._ua_previous_pct("pct_d365", 0.0))
    pct_over = fields.Float("Понад 365 днів, %", default=lambda self: self._ua_previous_pct("pct_over", 100.0))
    receivable_account_ids = fields.Many2many(
        "account.account", string="Рахунки дебіторів", check_company=True,
        help="Порожньо - усі рахунки дебіторської заборгованості покупців.")
    reserve_account_id = fields.Many2one("account.account", "Рахунок резерву", required=True, check_company=True,
                                         default=lambda self: self._ua_account(("38",)))
    expense_account_id = fields.Many2one("account.account", "Рахунок витрат", required=True, check_company=True,
                                         default=lambda self: self._ua_account(("944", "94")))
    income_account_id = fields.Many2one("account.account", "Рахунок доходу від сторно", required=True,
                                        check_company=True, default=lambda self: self._ua_account(("719", "71")))
    journal_id = fields.Many2one("account.journal", "Журнал", required=True, check_company=True,
                                 default=lambda self: self.env["account.journal"].search(
                                     [*self.env["account.journal"]._check_company_domain(self.env.company),
                                      ("type", "=", "general")], limit=1))
    line_ids = fields.One2many("ua.bad.debt.line", "reserve_id", "Борги")
    debt_total = fields.Monetary("Борг на дату", compute="_compute_totals", store=True)
    reserve_total = fields.Monetary("Резерв за розрахунком", compute="_compute_totals", store=True)
    reserve_before = fields.Monetary("Резерв на рахунку до проведення", readonly=True)
    adjustment = fields.Monetary("Донарахувати (+) / сторнувати (-)", readonly=True)
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True)
    note = fields.Text("Примітка")

    @api.depends("date")
    def _compute_name(self):
        for record in self:
            record.name = _("Резерв сумнівних боргів на %s") % (record.date.strftime("%d.%m.%Y") if record.date else "")

    @api.depends("line_ids.residual", "line_ids.reserve")
    def _compute_totals(self):
        for record in self:
            record.debt_total = sum(record.line_ids.mapped("residual"))
            record.reserve_total = sum(record.line_ids.mapped("reserve"))

    @api.model
    def _ua_account(self, prefixes):
        Account = self.env["account.account"]
        for prefix in prefixes:
            account = Account.search([*Account._check_company_domain(self.env.company),
                                      ("code", "=like", prefix + "%")], limit=1, order="code")
            if account:
                return account
        return Account

    @api.model
    def _ua_previous_pct(self, field, fallback):
        previous = self.search([("company_id", "=", self.env.company.id)], order="date desc, id desc", limit=1)
        return previous[field] if previous else fallback

    @api.constrains("pct_current", "pct_d90", "pct_d180", "pct_d365", "pct_over")
    def _check_pct(self):
        for record in self:
            if any(not 0 <= record[f] <= 100 for f in PERCENT_FIELDS.values()):
                raise ValidationError(_("Відсоток групи - від 0 до 100."))

    def ua_percent(self, bucket):
        self.ensure_one()
        return self[PERCENT_FIELDS[bucket]]

    # ------------------------------------------------------------------ заповнення
    def _ua_receivable_lines(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
                  ("date", "<=", self.date), ("balance", ">", 0), ("partner_id", "!=", False)]
        if self.receivable_account_ids:
            domain.append(("account_id", "in", self.receivable_account_ids.ids))
        else:
            domain.append(("account_id.account_type", "=", "asset_receivable"))
        return self.env["account.move.line"].search(domain, order="partner_id, date_maturity, id")

    def ua_residual_at(self, line):
        """Залишок дебетового рядка на дату: мінус зарахування, зроблені не пізніше дати."""
        self.ensure_one()
        paid = sum(p.amount for p in line.matched_credit_ids if p.max_date and p.max_date <= self.date)
        return _money(line.balance - paid)

    def action_fill(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            manual = {line.move_line_id.id: (line.manual_reserve, line.manual_reason)
                      for line in record.line_ids if line.manual}
            record.line_ids.unlink()
            vals = []
            currency = record.currency_id
            for aml in record._ua_receivable_lines():
                residual = record.ua_residual_at(aml)
                if float_is_zero(residual, precision_rounding=currency.rounding) or residual < 0:
                    continue
                days = (record.date - (aml.date_maturity or aml.date)).days
                item = {"move_line_id": aml.id, "partner_id": aml.partner_id.id, "residual": residual,
                        "due_date": aml.date_maturity or aml.date, "days": max(days, 0), "bucket": _bucket(days)}
                if aml.id in manual:
                    item.update(manual=True, manual_reserve=manual[aml.id][0], manual_reason=manual[aml.id][1])
                vals.append(item)
            record.line_ids = [(0, 0, v) for v in vals]
        return True

    # ------------------------------------------------------------------ проведення
    def _ua_reserve_balance(self):
        """Кредитовий залишок рахунку резерву на дату."""
        self.ensure_one()
        lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id), ("account_id", "=", self.reserve_account_id.id),
            ("parent_state", "=", "posted"), ("date", "<=", self.date)])
        return _money(-sum(lines.mapped("balance")))

    def action_post(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Розрахунок уже проведено."))
            missing = record.line_ids.filtered(lambda l: l.manual and not l.manual_reason)
            if missing:
                raise UserError(_("Вкажіть підставу ручної оцінки: %s") % ", ".join(missing.partner_id.mapped("name")))
            before = record._ua_reserve_balance()
            adjustment = _money(record.reserve_total - before)
            move = self.env["account.move"]
            if not float_is_zero(adjustment, precision_rounding=record.currency_id.rounding):
                if adjustment > 0:
                    debit_account, credit_account = record.expense_account_id, record.reserve_account_id
                    label = _("Нарахування резерву сумнівних боргів")
                else:
                    debit_account, credit_account = record.reserve_account_id, record.income_account_id
                    label = _("Зменшення резерву сумнівних боргів")
                amount = abs(adjustment)
                move = self.env["account.move"].create({
                    "move_type": "entry", "journal_id": record.journal_id.id, "date": record.date,
                    "ref": record.name, "line_ids": [
                        (0, 0, {"name": label, "account_id": debit_account.id, "debit": amount}),
                        (0, 0, {"name": label, "account_id": credit_account.id, "credit": amount})]})
                move.action_post()
            record.write({"state": "posted", "reserve_before": before, "adjustment": adjustment,
                          "move_id": move.id})
        return True

    def action_draft(self):
        for record in self:
            if record.move_id.state == "posted":
                record.move_id._reverse_moves([{"ref": _("Сторно: %s") % record.name, "date": record.date}],
                                              cancel=True)
            record.write({"state": "draft", "move_id": False, "reserve_before": 0.0, "adjustment": 0.0})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_bad_debt.action_report_ua_bad_debt").report_action(self)

    def ua_buckets(self):
        """[(назва групи, борг, відсоток, резерв)] для друку."""
        self.ensure_one()
        out = []
        for key, label in BUCKETS:
            lines = self.line_ids.filtered(lambda l: l.bucket == key and not l.manual)
            out.append((label, _money(sum(lines.mapped("residual"))), self.ua_percent(key),
                        _money(sum(lines.mapped("reserve")))))
        manual = self.line_ids.filtered("manual")
        if manual:
            out.append((_("Оцінені окремо"), _money(sum(manual.mapped("residual"))), None,
                        _money(sum(manual.mapped("reserve")))))
        return out

    def ua_date(self, day):
        return day.strftime("%d.%m.%Y") if day else ""

    @api.ondelete(at_uninstall=False)
    def _unlink_except_posted(self):
        if any(record.state == "posted" for record in self):
            raise UserError(_("Проведений розрахунок не видаляють: поверніть його в чернетку."))


class UaBadDebtLine(models.Model):
    _name = "ua.bad.debt.line"
    _description = "Борг у розрахунку резерву"
    _order = "partner_id, due_date, id"

    reserve_id = fields.Many2one("ua.bad.debt.reserve", required=True, index=True, ondelete="cascade")
    state = fields.Selection(related="reserve_id.state")
    currency_id = fields.Many2one(related="reserve_id.currency_id")
    move_line_id = fields.Many2one("account.move.line", "Рядок боргу", readonly=True)
    move_id = fields.Many2one(related="move_line_id.move_id", string="Документ")
    partner_id = fields.Many2one("res.partner", "Покупець", readonly=True)
    due_date = fields.Date("Строк оплати", readonly=True)
    days = fields.Integer("Днів прострочки", readonly=True)
    bucket = fields.Selection(BUCKETS, "Група", readonly=True)
    residual = fields.Monetary("Борг на дату", readonly=True)
    percent = fields.Float("Відсоток", compute="_compute_reserve", store=True)
    manual = fields.Boolean("Оцінено окремо")
    manual_reserve = fields.Monetary("Резерв вручну")
    manual_reason = fields.Char("Підстава", help="Банкрутство, рішення суду, претензія.")
    reserve = fields.Monetary("Резерв", compute="_compute_reserve", store=True)

    @api.depends("residual", "bucket", "manual", "manual_reserve", "reserve_id.pct_current", "reserve_id.pct_d90",
                 "reserve_id.pct_d180", "reserve_id.pct_d365", "reserve_id.pct_over")
    def _compute_reserve(self):
        for line in self:
            if line.manual:
                line.percent = line.manual_reserve / line.residual * 100.0 if line.residual else 0.0
                line.reserve = _money(min(line.manual_reserve, line.residual))
            else:
                line.percent = line.reserve_id.ua_percent(line.bucket) if line.bucket else 0.0
                line.reserve = _money(line.residual * line.percent / 100.0)
