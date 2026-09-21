"""Авансовий звіт: працівник звітує за гроші, взяті під звіт.

Ланцюг простий. Видали аванс з каси - ВКО дає Дт 372 / Кт 301. Працівник приносить
чеки - звіт дає Дт <рахунки витрат> / Кт 372. Залишок закривається ще одним касовим
ордером: невитрачене повертають у касу (ПКО, Дт 301 / Кт 372), перевитрату доплачують
(ВКО, Дт 372 / Кт 301). Після цього 372 за цим звітом дорівнює нулю.

Рахунок підзвіту беремо з плану за кодом 372 (у плані ПСБО це 3721 - розрахунки з
підзвітними особами в національній валюті).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .tools import amount_in_words

SEQUENCE_CODE = "l10n_ua_cash.advance.report"
SETTLEMENT_CODE = "372%"
STATES = [("draft", "Чернетка"), ("done", "Затверджено")]


class UaAdvanceReport(models.Model):
    _name = "ua.advance.report"
    _description = "Авансовий звіт"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", readonly=True, copy=False, default="Новий")
    partner_id = fields.Many2one(
        "res.partner", "Підзвітна особа", required=True, tracking=True,
        help="Працівник, який отримав гроші під звіт.",
    )
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    payment_id = fields.Many2one(
        "account.payment",
        "ВКО на видачу авансу",
        domain="[('ua_order_kind', '=', 'out'), ('company_id', '=', company_id)]",
        tracking=True,
        help="Видатковий касовий ордер, яким видано аванс під звіт.",
    )
    line_ids = fields.One2many("ua.advance.report.line", "report_id", "Рядки витрат", copy=True)
    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, copy=False, tracking=True)

    amount_total = fields.Monetary("Витрачено", compute="_compute_amount_total", store=True)
    amount_given = fields.Monetary("Видано під звіт", compute="_compute_balance", store=True)
    amount_balance = fields.Monetary("Залишок", compute="_compute_balance", store=True,
                                     help="Видано мінус витрачено. Більше нуля - повернути в касу, "
                                          "менше нуля - доплатити працівникові.")
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)
    settle_payment_id = fields.Many2one(
        "account.payment", "Ордер на залишок", readonly=True, copy=False
    )

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for report in self:
            report.amount_total = round(sum(report.line_ids.mapped("amount")), 2)

    @api.depends("payment_id.amount", "amount_total")
    def _compute_balance(self):
        for report in self:
            given = report.payment_id.amount if report.payment_id else 0.0
            report.amount_given = given
            report.amount_balance = round(given - report.amount_total, 2)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "Новий":
                vals["name"] = self.env["ir.sequence"].next_by_code(SEQUENCE_CODE) or "Новий"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    def _settlement_account(self):
        """Рахунок розрахунків з підзвітними особами (372 / 3721)."""
        self.ensure_one()
        account = self.env["account.account"].search(
            [("code", "=like", SETTLEMENT_CODE), ("company_ids", "in", self.company_id.id)],
            limit=1,
            order="code",
        )
        if not account:
            raise UserError(
                _("У плані рахунків компанії «%s» немає рахунку 372 (розрахунки з підзвітними особами).")
                % self.company_id.name
            )
        return account

    def _general_journal(self):
        self.ensure_one()
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.company_id.id)], limit=1
        )
        if not journal:
            raise UserError(
                _("У компанії «%s» немає журналу інших операцій.") % self.company_id.name
            )
        return journal

    def _cash_journal(self):
        self.ensure_one()
        journal = self.env["account.journal"].search(
            [("type", "=", "cash"), ("company_id", "=", self.company_id.id)], limit=1
        )
        if not journal:
            raise UserError(_("У компанії «%s» немає журналу каси.") % self.company_id.name)
        return journal

    # ------------------------------------------------------------------
    def action_confirm(self):
        """Затвердити звіт: Дт рахунки витрат / Кт 372 на суму звіту."""
        for report in self:
            if report.state != "draft":
                raise UserError(_("Звіт «%s» уже затверджено.") % report.name)
            if not report.line_ids:
                raise UserError(_("У звіті «%s» немає жодного рядка витрат.") % report.name)
            for line in report.line_ids:
                if line.amount <= 0:
                    raise UserError(_("Сума рядка «%s» має бути більшою за нуль.") % line.name)
            settlement = report._settlement_account()
            move_lines = []
            total = 0.0
            for line in report.line_ids:
                amount = round(line.amount, 2)
                total = round(total + amount, 2)
                move_lines.append(
                    (0, 0, {
                        "account_id": line.expense_account_id.id,
                        "partner_id": report.partner_id.id,
                        "name": line.name,
                        "debit": amount,
                        "credit": 0.0,
                    })
                )
            move_lines.append(
                (0, 0, {
                    "account_id": settlement.id,
                    "partner_id": report.partner_id.id,
                    "name": _("Авансовий звіт %s") % report.name,
                    "debit": 0.0,
                    "credit": total,
                })
            )
            move = self.env["account.move"].create({
                "journal_id": report._general_journal().id,
                "company_id": report.company_id.id,
                "date": report.date,
                "ref": "%s: %s" % (report.name, report.partner_id.name or ""),
                "line_ids": move_lines,
            })
            move.action_post()
            report.write({"move_id": move.id, "state": "done"})
        return True

    def action_draft(self):
        for report in self:
            if report.move_id:
                raise UserError(
                    _("Звіт «%s» проведено. Спершу сторнуйте проводку.") % report.name
                )
            report.state = "draft"
        return True

    def action_settle_balance(self):
        """Закрити залишок підзвіту касовим ордером.

        Залишок більше нуля - працівник повертає невитрачене (ПКО, Дт 301 / Кт 372).
        Менше нуля - компанія доплачує перевитрату (ВКО, Дт 372 / Кт 301).
        Повторний виклик нічого не дублює.
        """
        self.ensure_one()
        if self.state != "done":
            raise UserError(_("Спершу затвердьте авансовий звіт."))
        if self.settle_payment_id:
            return self.settle_payment_id
        if abs(self.amount_balance) < 0.005:
            raise UserError(_("Залишку немає - підзвіт зійшовся копійка в копійку."))
        is_return = self.amount_balance > 0
        settlement = self._settlement_account()
        payment = self.env["account.payment"].create({
            "payment_type": "inbound" if is_return else "outbound",
            "partner_type": "customer" if is_return else "supplier",
            "partner_id": self.partner_id.id,
            "journal_id": self._cash_journal().id,
            "company_id": self.company_id.id,
            "date": fields.Date.context_today(self),
            "amount": abs(self.amount_balance),
            "destination_account_id": settlement.id,
            "memo": (
                _("Повернення залишку підзвіту за %s") if is_return
                else _("Доплата перевитрати за %s")
            ) % self.name,
            "ua_person": self.partner_id.name,
        })
        payment.action_post()
        self.settle_payment_id = payment
        return payment

    def action_print(self):
        self.ensure_one()
        return self.env.ref("l10n_ua_cash.action_report_ua_advance_report").report_action(self)

    def _ua_amount_words(self):
        """Сума звіту прописом."""
        self.ensure_one()
        return amount_in_words(self.env, self.currency_id, self.amount_total)


class UaAdvanceReportLine(models.Model):
    _name = "ua.advance.report.line"
    _description = "Рядок авансового звіту"
    _order = "report_id, id"

    report_id = fields.Many2one("ua.advance.report", "Авансовий звіт", required=True, ondelete="cascade")
    name = fields.Char("Що придбано або оплачено", required=True)
    amount = fields.Monetary("Сума", required=True)
    expense_account_id = fields.Many2one(
        "account.account",
        "Рахунок витрат",
        required=True,
        domain="[('company_ids', 'in', company_id)]",
        help="92 - адміністративні витрати, 93 - збут, 23 - виробництво, 201 - запаси.",
    )
    company_id = fields.Many2one(
        "res.company", related="report_id.company_id", store=True, readonly=True
    )
    currency_id = fields.Many2one("res.currency", related="report_id.currency_id")
