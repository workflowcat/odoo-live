# -*- coding: utf-8 -*-
"""Інвентаризація каси (акт інвентаризації наявних коштів).

Залишок за обліком - сальдо рахунку каси журналу (default_account_id) з проведених проводок по дату
акта включно. Фактична готівка - сума рядків номіналів, а без них - введена сума. Різниця: нестача -
Дт рахунок винної особи (375) з контрагентом або Дт рахунок нестач (947), Кт каса; лишок - Дт каса
Кт рахунок доходу (719). Без різниці акт затверджується без проводки.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("done", "Затверджено")]
SHORTAGE_TO = [("culprit", "На винну особу"), ("expense", "У витрати")]
# Звичайний набір номіналів гривні: банкноти і монети, у гривнях.
NOMINALS = [1000, 500, 200, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.1]
DEFAULT_ACCOUNTS = {"culprit": "375", "expense": "947", "surplus": "719"}


class UaCashCount(models.Model):
    _name = "ua.cash.count"
    _description = "Інвентаризація каси"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    journal_id = fields.Many2one(
        "account.journal", "Каса", required=True, check_company=True,
        domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
        default=lambda s: s.env["account.journal"].search(
            [("type", "=", "cash"), ("company_id", "=", s.env.company.id)], limit=1))
    account_id = fields.Many2one(related="journal_id.default_account_id", string="Рахунок каси")
    date = fields.Date("Дата інвентаризації", required=True, default=fields.Date.context_today, tracking=True)
    order_ref = fields.Char("Наказ про інвентаризацію")
    commission = fields.Text("Склад комісії", help="По одному на рядок: посада, прізвище та ініціали.")
    cashier_id = fields.Many2one("res.partner", "Касир (матеріально відповідальна особа)")
    last_receipt = fields.Char("Останній прибутковий ордер", help="Номер і дата останнього ПКО.")
    last_payment = fields.Char("Останній видатковий ордер", help="Номер і дата останнього ВКО.")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.cash.count.line", "count_id", "Номінали")
    counted_manual = fields.Monetary("Фактично (без номіналів)",
                                     help="Сума готівки, якщо номінали не розписано.")
    book_balance = fields.Monetary("Залишок за обліком", readonly=True,
                                   help="Сальдо рахунку каси на дату; оновлюється кнопкою і під час затвердження.")
    counted = fields.Monetary("Фактично", compute="_compute_amounts", store=True)
    difference = fields.Monetary("Різниця (лишок +, нестача -)", compute="_compute_amounts", store=True)
    shortage_to = fields.Selection(SHORTAGE_TO, "Нестачу віднести", default="culprit", required=True)
    culprit_id = fields.Many2one("res.partner", "Винна особа", help="Порожньо - касир.")
    culprit_account_id = fields.Many2one("account.account", "Рахунок винної особи", check_company=True,
                                         default=lambda s: s._ua_default_account("culprit"))
    expense_account_id = fields.Many2one("account.account", "Рахунок нестач", check_company=True,
                                         default=lambda s: s._ua_default_account("expense"))
    surplus_account_id = fields.Many2one("account.account", "Рахунок доходу від лишку", check_company=True,
                                         default=lambda s: s._ua_default_account("surplus"))
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)

    @api.depends("journal_id.name", "date")
    def _compute_name(self):
        for doc in self:
            doc.name = _("Інвентаризація каси %(journal)s на %(date)s") % {
                "journal": doc.journal_id.name or "", "date": doc.date.strftime("%d.%m.%Y") if doc.date else ""}

    @api.model
    def _ua_default_account(self, key):
        company = self.env.company
        return self.env["account.account"].with_company(company).search(
            [("company_ids", "in", company.id), ("code", "=like", DEFAULT_ACCOUNTS[key] + "%")],
            order="code", limit=1)

    @api.depends("line_ids.amount", "counted_manual", "book_balance")
    def _compute_amounts(self):
        for doc in self:
            doc.counted = sum(doc.line_ids.mapped("amount")) if doc.line_ids else doc.counted_manual
            doc.difference = doc.counted - doc.book_balance

    @api.model_create_multi
    def create(self, vals_list):
        docs = super().create(vals_list)
        docs.action_refresh()
        return docs

    def _ua_book_balance(self):
        self.ensure_one()
        if not (self.account_id and self.date):
            return 0.0
        groups = self.env["account.move.line"]._read_group(
            [("company_id", "=", self.company_id.id), ("account_id", "=", self.account_id.id),
             ("parent_state", "=", "posted"), ("date", "<=", self.date)],
            aggregates=["balance:sum"])
        return groups[0][0] or 0.0 if groups else 0.0

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError(_("Видалити можна лише чернетку."))

    def action_nominals(self):
        """Поставити звичайний набір номіналів (наявні рядки лишаються)."""
        for doc in self:
            present = set(doc.line_ids.mapped("nominal"))
            doc.line_ids = [(0, 0, {"nominal": n, "quantity": 0}) for n in NOMINALS if n not in present]
        return True

    def action_refresh(self):
        """Перечитати залишок за обліком на дату акта (після нових проводок по касі)."""
        for doc in self:
            if doc.state == "draft":
                doc.book_balance = doc._ua_book_balance()
        return True

    def action_done(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Акт уже затверджено."))
            doc.action_refresh()
            difference = doc.difference
            if not doc.currency_id.is_zero(difference):
                doc.move_id = doc._ua_post(difference)
            doc.state = "done"
            doc.message_post(body=_("Затверджено: за обліком %(book).2f, фактично %(fact).2f, різниця %(diff).2f.")
                             % {"book": doc.book_balance, "fact": doc.counted, "diff": difference})
        return True

    def _ua_post(self, difference):
        self.ensure_one()
        cash = self.account_id
        if difference > 0:
            if not self.surplus_account_id:
                raise UserError(_("Не вказано рахунок доходу від лишку."))
            debit, credit, partner = cash, self.surplus_account_id, False
            label = _("Лишок готівки за інвентаризацією")
        else:
            if self.shortage_to == "culprit":
                partner = self.culprit_id or self.cashier_id
                if not (partner and self.culprit_account_id):
                    raise UserError(_("Для нестачі на винну особу потрібні сама особа (або касир) і рахунок."))
                debit = self.culprit_account_id
            else:
                if not self.expense_account_id:
                    raise UserError(_("Не вказано рахунок нестач."))
                debit, partner = self.expense_account_id, False
            credit = cash
            label = _("Нестача готівки за інвентаризацією")
        amount = abs(difference)
        move = self.env["account.move"].create({
            "move_type": "entry", "date": self.date, "journal_id": self.journal_id.id,
            "ref": "%s: %s" % (label, self.name),
            "line_ids": [
                (0, 0, {"account_id": debit.id, "partner_id": partner and partner.id, "name": label, "debit": amount}),
                (0, 0, {"account_id": credit.id, "partner_id": partner and partner.id, "name": label,
                        "credit": amount}),
            ]})
        move.action_post()
        return move

    def action_print(self):
        return self.env.ref("l10n_ua_cash_count.action_report_ua_cash_count").report_action(self)

    def ua_money(self, value):
        self.ensure_one()
        return "{:,.2f}".format(value or 0.0).replace(",", " ").replace(".", ",")

    def ua_nominal(self, line):
        """Номінал для друку: гривні цілим числом, монети - у копійках."""
        if line.nominal >= 1:
            return _("%d грн") % line.nominal
        return _("%d коп.") % round(line.nominal * 100)


class UaCashCountLine(models.Model):
    _name = "ua.cash.count.line"
    _description = "Номінал в акті інвентаризації каси"
    _order = "nominal desc, id"

    count_id = fields.Many2one("ua.cash.count", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="count_id.company_id", store=True)
    currency_id = fields.Many2one(related="count_id.currency_id")
    nominal = fields.Float("Номінал, грн", digits=(16, 2), required=True)
    quantity = fields.Integer("Кількість, шт.")
    amount = fields.Monetary("Сума", compute="_compute_amount", store=True)

    @api.depends("nominal", "quantity")
    def _compute_amount(self):
        for line in self:
            line.amount = line.nominal * line.quantity
