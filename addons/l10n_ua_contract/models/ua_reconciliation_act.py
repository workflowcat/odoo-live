"""Акт звірки взаєморозрахунків.

Акт складається з проводок на рахунках розрахунків (tools.settlement_accounts) за
контрагентом і, якщо обрано, за одним договором. Сальдо на початок - сума проводок до
дати початку. Рядок акта - один документ: дебет і кредит його рядків на цих рахунках
згорнуто в одну суму, тож внутрішнє перенесення (аванс 681 у погашення 361) дає нуль і
в акт не потрапляє.

Знак: дебет акта - це те, що збільшує борг контрагента перед компанією (відвантаження
покупцю, оплата постачальнику); кредит - те, що його зменшує. Сальдо з плюсом - борг
контрагента, з мінусом - борг компанії.

Дані контрагента бухгалтер вносить одним числом - сальдо на кінець за його обліком, у
тому самому знаку. Різниця має бути нулем, щоб акт став узгодженим.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.l10n_ua_docs.models.tools import amount_in_words

from .tools import settlement_accounts

DOC_LABELS = {
    "out_invoice": "Реалізація",
    "out_refund": "Повернення від покупця",
    "in_invoice": "Надходження",
    "in_refund": "Повернення постачальнику",
    "out_receipt": "Реалізація",
    "in_receipt": "Надходження",
}


class UaReconciliationAct(models.Model):
    _name = "ua.reconciliation.act"
    _description = "Акт звірки взаєморозрахунків"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one("res.partner", "Контрагент", required=True, tracking=True)
    contract_id = fields.Many2one(
        "ua.contract", "Договір", check_company=True, tracking=True,
        domain="[('partner_id', '=', partner_id)]",
        help="Порожньо - звірка за всіма договорами контрагента.")
    date_from = fields.Date("Період з", required=True)
    date_to = fields.Date("по", required=True)
    state = fields.Selection(
        [("draft", "Чернетка"), ("sent", "Надіслано"), ("agreed", "Узгоджено"),
         ("disputed", "Є розбіжності")],
        "Стан", required=True, default="draft", tracking=True)
    line_ids = fields.One2many("ua.reconciliation.act.line", "act_id", "Рядки", copy=False)
    opening_balance = fields.Monetary("Сальдо на початок", readonly=True, copy=False)
    debit_total = fields.Monetary("Дебет", compute="_compute_totals", store=True)
    credit_total = fields.Monetary("Кредит", compute="_compute_totals", store=True)
    closing_balance = fields.Monetary("Сальдо на кінець", compute="_compute_totals", store=True)
    their_closing_balance = fields.Monetary(
        "Сальдо за даними контрагента", tracking=True,
        help="Сальдо на кінець за обліком контрагента, у знаку акта: плюс - контрагент винен компанії.")
    their_filled = fields.Boolean("Дані контрагента внесено")
    difference = fields.Monetary("Розбіжність", compute="_compute_totals", store=True)
    note = fields.Text("Примітки")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("partner_id"):
                partner = self.env["res.partner"].browse(vals["partner_id"])
                vals["partner_id"] = partner.commercial_partner_id.id
            if vals.get("name", "/") == "/":
                company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
                vals["name"] = self.env["ir.sequence"].with_company(company).next_by_code(
                    "l10n_ua_contract.reconciliation.act", sequence_date=vals.get("date_to")) or "/"
        return super().create(vals_list)

    @api.depends("line_ids.debit", "line_ids.credit", "opening_balance",
                 "their_closing_balance", "their_filled")
    def _compute_totals(self):
        for act in self:
            act.debit_total = sum(act.line_ids.mapped("debit"))
            act.credit_total = sum(act.line_ids.mapped("credit"))
            act.closing_balance = act.opening_balance + act.debit_total - act.credit_total
            act.difference = (
                act.closing_balance - act.their_closing_balance if act.their_filled else 0.0)

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for act in self:
            if act.date_from > act.date_to:
                raise UserError(_("Початок періоду пізніше за кінець."))

    # ------------------------------------------------------------------
    # Заповнення
    # ------------------------------------------------------------------
    def _ua_domain(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("partner_id.commercial_partner_id", "=", self.partner_id.commercial_partner_id.id),
            ("parent_state", "=", "posted"),
            ("account_id", "in", settlement_accounts(self.env, self.company_id).ids),
        ]
        if self.contract_id:
            domain.append(("ua_contract_id", "=", self.contract_id.id))
        return domain

    @staticmethod
    def _ua_document_label(move):
        number = move.name or ""
        if move.move_type in ("in_invoice", "in_refund", "in_receipt") and move.ref:
            number = move.ref
        label = DOC_LABELS.get(move.move_type)
        if not label:
            payment = move.origin_payment_id
            if payment:
                label = "Оплата від контрагента" if payment.payment_type == "inbound" else "Оплата контрагенту"
            elif move.statement_line_id:
                label = "Банківська виписка"
            else:
                label = "Операція"
        return "%s № %s" % (label, number) if number and number != "/" else label

    def action_fill(self):
        """Заповнити акт проводками періоду; дані контрагента не чіпає."""
        Line = self.env["account.move.line"]
        for act in self:
            if act.state == "agreed":
                raise UserError(_("Узгоджений акт не перезаповнюється. Поверніть його в чернетку."))
            domain = act._ua_domain()
            before = Line.search(domain + [("date", "<", act.date_from)])
            period = Line.search(
                domain + [("date", ">=", act.date_from), ("date", "<=", act.date_to)],
                order="date, move_id, id")
            rows = []
            for move in period.move_id.sorted(lambda m: (m.date, m.id)):
                lines = period.filtered(lambda line, m=move: line.move_id == m)
                amount = sum(lines.mapped("balance"))
                if act.currency_id.is_zero(amount):
                    continue
                contracts = lines.ua_contract_id
                rows.append((0, 0, {
                    "date": move.date,
                    "move_id": move.id,
                    "document": act._ua_document_label(move),
                    "contract_id": contracts[:1].id if len(contracts) == 1 else False,
                    "debit": amount if amount > 0 else 0.0,
                    "credit": -amount if amount < 0 else 0.0,
                }))
            act.line_ids.unlink()
            act.write({
                "opening_balance": sum(before.mapped("balance")),
                "line_ids": rows,
            })
        return True

    # ------------------------------------------------------------------
    # Стани
    # ------------------------------------------------------------------
    def action_mark_sent(self):
        self.filtered(lambda a: a.state == "draft").write({"state": "sent"})

    def action_mark_agreed(self):
        for act in self:
            if not act.their_filled:
                raise UserError(_("Внесіть сальдо за даними контрагента, щоб узгодити акт."))
            if not act.currency_id.is_zero(act.difference):
                raise UserError(_(
                    "Сальдо не збігається: розбіжність %(diff)s. Позначте акт як «Є розбіжності».",
                    diff=act.currency_id.format(act.difference)))
        self.write({"state": "agreed"})

    def action_mark_disputed(self):
        self.write({"state": "disputed"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_print(self):
        return self.env.ref("l10n_ua_contract.action_report_ua_reconciliation_act").report_action(self)

    # ------------------------------------------------------------------
    # Для друку
    # ------------------------------------------------------------------
    def _ua_conclusion(self):
        """Висновок акта одним реченням, сума прописом."""
        self.ensure_one()
        amount = self.closing_balance
        date = self.date_to.strftime("%d.%m.%Y")
        if self.currency_id.is_zero(amount):
            return "Станом на %s заборгованість між сторонами відсутня." % date
        words = amount_in_words(self.currency_id, abs(amount))
        if amount > 0:
            debtor, creditor = self.partner_id.name, self.company_id.name
        else:
            debtor, creditor = self.company_id.name, self.partner_id.name
        return "Станом на %s заборгованість %s перед %s становить %s (%s)." % (
            date, debtor, creditor, self.currency_id.format(abs(amount)), words)

    def _ua_side(self, amount):
        """Сальдо для рядка друку: (дебет, кредит)."""
        return (amount, 0.0) if amount >= 0 else (0.0, -amount)


class UaReconciliationActLine(models.Model):
    _name = "ua.reconciliation.act.line"
    _description = "Рядок акта звірки"
    _order = "date, id"

    act_id = fields.Many2one(
        "ua.reconciliation.act", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="act_id.currency_id")
    date = fields.Date("Дата", required=True)
    document = fields.Char("Документ", required=True)
    move_id = fields.Many2one("account.move", "Проводка", ondelete="set null")
    contract_id = fields.Many2one("ua.contract", "Договір", ondelete="set null")
    debit = fields.Monetary("Дебет")
    credit = fields.Monetary("Кредит")
