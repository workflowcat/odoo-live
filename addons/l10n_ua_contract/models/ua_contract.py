"""Договір з контрагентом.

Як у 1С/BAS: розрахунки ведуться не лише за контрагентом, а й за договором. Договір
стоїть на замовленні, рахунку, оплаті і на кожному рядку проводки (account.move.line),
тому сальдо договору - це сума проводок на рахунках розрахунків з цим договором.

Сума договору - верхня межа виставлених рахунків. Що робити, коли її перевищено, каже
поле limit_mode: не контролювати, попередити в стрічці документа або не проводити.

Окремий облік (постанова КМУ № 363 для оборонних контрактів, а також будь-який договір,
де замовник хоче бачити фактичні витрати): договір отримує власний аналітичний рахунок
у плані «Договори», і він лягає на рядки замовлень і рахунків, де аналітики ще немає.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .tools import settlement_accounts

KINDS = [
    ("sale", "З покупцем"),
    ("purchase", "З постачальником"),
    ("other", "Інший"),
]


class UaContract(models.Model):
    _name = "ua.contract"
    _description = "Договір з контрагентом"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", required=True, tracking=True)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, index=True,
        default=lambda self: self.env.company)
    partner_id = fields.Many2one(
        "res.partner", "Контрагент", required=True, index=True, tracking=True,
        help="Юридична особа або ФОП. Контактна особа замінюється на її компанію.")
    kind = fields.Selection(KINDS, "Вид", required=True, default="sale", tracking=True)
    state = fields.Selection(
        [("draft", "Чернетка"), ("active", "Діє"), ("closed", "Закрито")],
        "Стан", required=True, default="active", tracking=True,
        help="За закритим договором рахунки не проводяться.")
    is_main = fields.Boolean(
        "Основний", help="Підставляється в нові документи контрагента цього виду.")
    subject = fields.Text("Предмет договору")
    date_end = fields.Date("Діє до", tracking=True)
    currency_id = fields.Many2one(
        "res.currency", "Валюта", required=True,
        default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(
        "Сума договору", tracking=True,
        help="Нуль - сума не обмежена.")
    limit_mode = fields.Selection(
        [("none", "Не контролювати"), ("warn", "Попереджати"), ("block", "Не проводити понад суму")],
        "Контроль суми", required=True, default="warn")
    payment_term_id = fields.Many2one(
        "account.payment.term", "Умови оплати", check_company=True)
    separate_accounting = fields.Boolean(
        "Окремий облік витрат",
        help="Договір отримує свій аналітичний рахунок; він лягає на рядки замовлень і "
             "рахунків, де аналітики ще немає. Потрібно для державних і оборонних контрактів.")
    analytic_account_id = fields.Many2one(
        "account.analytic.account", "Аналітичний рахунок", copy=False, check_company=True)
    note = fields.Html("Примітки")

    invoiced_amount = fields.Monetary(
        "Виставлено", compute="_compute_money",
        help="Проведені рахунки за договором мінус повернення, у валюті договору.")
    remaining_amount = fields.Monetary("Залишок суми", compute="_compute_money")
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    balance = fields.Monetary(
        "Сальдо розрахунків", compute="_compute_money", currency_field="company_currency_id",
        help="Плюс - заборгованість контрагента; мінус - заборгованість перед контрагентом. "
             "У валюті компанії, за проведеними документами.")
    move_count = fields.Integer("Документи", compute="_compute_money")

    _name_company_partner_uniq = models.Constraint(
        "UNIQUE(company_id, partner_id, kind, name, date)",
        "Договір з таким номером і датою в цього контрагента вже є.",
    )

    # ------------------------------------------------------------------
    # Відображення
    # ------------------------------------------------------------------
    @api.depends("name", "date")
    def _compute_display_name(self):
        for contract in self:
            contract.display_name = contract._ua_print_name()

    def _ua_print_name(self):
        """«Договір № 15/2026 від 03.02.2026» - так договір стоїть у підставі первинки."""
        self.ensure_one()
        text = "Договір № %s" % (self.name or "")
        if self.date:
            text += " від %s" % self.date.strftime("%d.%m.%Y")
        return text

    # ------------------------------------------------------------------
    # Створення
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("partner_id"):
                partner = self.env["res.partner"].browse(vals["partner_id"])
                vals["partner_id"] = partner.commercial_partner_id.id
        contracts = super().create(vals_list)
        contracts.filtered("separate_accounting")._ua_ensure_analytic()
        return contracts

    def write(self, vals):
        if vals.get("partner_id"):
            partner = self.env["res.partner"].browse(vals["partner_id"])
            vals["partner_id"] = partner.commercial_partner_id.id
        result = super().write(vals)
        if vals.get("separate_accounting"):
            self.filtered("separate_accounting")._ua_ensure_analytic()
        return result

    def _ua_ensure_analytic(self):
        """Аналітичний рахунок договору в плані «Договори», якщо його ще немає."""
        plan = self.env.ref("l10n_ua_contract.analytic_plan_contracts", raise_if_not_found=False)
        if not plan:
            plan = self.env["account.analytic.plan"].sudo().create({"name": "Договори"})
        for contract in self.filtered(lambda c: not c.analytic_account_id):
            # Рахунок аналітики заводить система: користувачу з правами на договір
            # окремих прав на аналітику не треба.
            contract.analytic_account_id = self.env["account.analytic.account"].sudo().create({
                "name": "%s, %s" % (contract._ua_print_name(), contract.partner_id.name or ""),
                "code": contract.name,
                "plan_id": plan.id,
                "company_id": contract.company_id.id,
                "partner_id": contract.partner_id.id,
            })

    @api.constrains("is_main", "partner_id", "kind", "company_id", "state")
    def _check_one_main(self):
        for contract in self.filtered(lambda c: c.is_main and c.state != "closed"):
            others = self.search_count([
                ("id", "!=", contract.id),
                ("is_main", "=", True),
                ("state", "!=", "closed"),
                ("partner_id", "=", contract.partner_id.id),
                ("kind", "=", contract.kind),
                ("company_id", "=", contract.company_id.id),
            ])
            if others:
                raise ValidationError(_(
                    "У контрагента %(partner)s уже є основний договір цього виду.",
                    partner=contract.partner_id.display_name))

    @api.constrains("date", "date_end")
    def _check_dates(self):
        for contract in self:
            if contract.date_end and contract.date and contract.date_end < contract.date:
                raise ValidationError(_("Договір не може діяти до дати, ранішої за дату укладення."))

    # ------------------------------------------------------------------
    # Підстановка в документи
    # ------------------------------------------------------------------
    @api.model
    def _ua_default_for(self, partner, company, kind):
        """Договір для нового документа: основний, інакше єдиний чинний."""
        partner = partner.commercial_partner_id
        if not partner or not kind:
            return self.browse()
        domain = [
            ("partner_id", "=", partner.id),
            ("kind", "=", kind),
            ("state", "=", "active"),
            ("company_id", "=", (company or self.env.company).id),
        ]
        main = self.search(domain + [("is_main", "=", True)], limit=1)
        if main:
            return main
        found = self.search(domain, limit=2)
        return found if len(found) == 1 else self.browse()

    def _ua_fits(self, partner):
        """Чи можна лишити цей договір на документі з таким контрагентом."""
        self.ensure_one()
        return self.partner_id == partner.commercial_partner_id

    def _ua_analytic_distribution(self):
        self.ensure_one()
        if self.separate_accounting and self.analytic_account_id:
            return {str(self.analytic_account_id.id): 100}
        return False

    # ------------------------------------------------------------------
    # Суми
    # ------------------------------------------------------------------
    def _ua_invoices(self):
        return self.env["account.move"].search([
            ("ua_contract_id", "in", self.ids),
            ("state", "=", "posted"),
            ("move_type", "in", ("out_invoice", "out_refund", "in_invoice", "in_refund")),
        ])

    def _ua_invoiced(self, moves):
        """Сума рахунків у валюті договору; повернення зменшують."""
        self.ensure_one()
        total = 0.0
        for move in moves:
            sign = -1 if move.move_type in ("out_refund", "in_refund") else 1
            amount = move.amount_total
            if move.currency_id != self.currency_id:
                amount = move.currency_id._convert(
                    amount, self.currency_id, move.company_id, move.invoice_date or move.date)
            total += sign * amount
        return total

    def _ua_settlement_lines(self, date_to=False):
        self.ensure_one()
        domain = [
            ("ua_contract_id", "=", self.id),
            ("parent_state", "=", "posted"),
            ("account_id", "in", settlement_accounts(self.env, self.company_id).ids),
        ]
        if date_to:
            domain.append(("date", "<=", date_to))
        return self.env["account.move.line"].search(domain)

    def _compute_money(self):
        for contract in self:
            if not contract.id:
                contract.invoiced_amount = contract.remaining_amount = contract.balance = 0.0
                contract.move_count = 0
                continue
            invoices = contract._ua_invoices()
            contract.invoiced_amount = contract._ua_invoiced(invoices)
            contract.remaining_amount = (
                contract.amount - contract.invoiced_amount if contract.amount else 0.0)
            lines = contract._ua_settlement_lines()
            contract.balance = sum(lines.mapped("balance"))
            contract.move_count = len(lines.move_id)

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Документи за договором"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("ua_contract_id", "=", self.id)],
            "context": {"default_ua_contract_id": self.id, "create": False},
        }

    def action_close(self):
        self.write({"state": "closed", "is_main": False})

    def action_activate(self):
        self.write({"state": "active"})

    def action_new_reconciliation_act(self):
        """Акт звірки за договором з початку року по сьогодні."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        act = self.env["ua.reconciliation.act"].create({
            "company_id": self.company_id.id,
            "partner_id": self.partner_id.id,
            "contract_id": self.id,
            "date_from": today.replace(month=1, day=1),
            "date_to": today,
        })
        act.action_fill()
        return {
            "type": "ir.actions.act_window",
            "res_model": "ua.reconciliation.act",
            "res_id": act.id,
            "view_mode": "form",
        }

    def _ua_check_posting(self, moves):
        """Перевірка рахунків перед проведенням: закритий договір і сума договору.

        moves - рахунки цього договору, які проводяться зараз (ще не проведені).
        """
        self.ensure_one()
        if self.state == "closed":
            raise UserError(_(
                "%(contract)s закрито: рахунок за ним не проводиться. Відкрийте договір "
                "або оберіть інший.", contract=self._ua_print_name()))
        if not self.amount or self.limit_mode == "none":
            return
        before = self._ua_invoiced(self._ua_invoices() - moves)
        after = before + self._ua_invoiced(moves)
        if self.currency_id.compare_amounts(after, self.amount) <= 0:
            return
        over = after - self.amount
        text = _(
            "Сума рахунків за договором %(contract)s (%(after)s) перевищує суму договору "
            "%(amount)s на %(over)s.",
            contract=self._ua_print_name(),
            after=self.currency_id.format(after),
            amount=self.currency_id.format(self.amount),
            over=self.currency_id.format(over))
        if self.limit_mode == "block":
            raise UserError(text)
        for move in moves:
            move.message_post(body=text)
