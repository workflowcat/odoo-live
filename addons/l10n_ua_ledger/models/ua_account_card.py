"""Картка рахунку: хронологія проводок одного рахунку з наростаючим сальдо.

Це власний запит, а не надбудова над головною книгою OCA. Причина: потрібна
колонка «кореспондуючий рахунок», якої головна книга OCA не має взагалі, а її
готові числа доступні лише через повний контракт даних її візарда. Власний
пошук по account.move.line - шістдесят рядків і читається без словника.

Задокументоване спрощення: кореспондуючий рахунок - це коди рахунків
протилежного боку тієї самої проводки через кому, без сум. Для проводки з
кількома рядками це перелік, а не розклад.
"""
from odoo import api, fields, models


class UaAccountCard(models.Model):
    _name = "ua.account.card"
    _inherit = "ua.ledger.base"
    _description = "Картка рахунку"
    _order = "date_from desc, id desc"
    _ua_result_view = "l10n_ua_ledger.view_ua_account_card_form"
    _ua_ask_view = "l10n_ua_ledger.view_ua_account_card_ask"

    name = fields.Char("Назва", compute="_compute_name", store=True)

    @api.depends("account_id", "partner_id", "date_from", "date_to")
    def _compute_name(self):
        for card in self:
            who = " · %s" % card.partner_id.name if card.partner_id else ""
            card.name = "Картка рахунку %s%s · %s" % (
                card._acc_code(card.account_id) if card.account_id else "",
                who, card._ua_period_label())

    account_id = fields.Many2one("account.account", "Рахунок", required=True)
    partner_id = fields.Many2one(
        "res.partner", "Партнер",
        help="Якщо вказано - лише проводки цього партнера (розгортання по субконто).",
    )
    line_ids = fields.One2many("ua.account.card.line", "card_id", "Рядки", readonly=True)

    opening_balance = fields.Monetary("Сальдо на початок", currency_field="currency_id",
                                      help="Додатне - дебетове, від'ємне - кредитове.")
    total_debit = fields.Monetary("Оборот Дт", currency_field="currency_id")
    total_credit = fields.Monetary("Оборот Кт", currency_field="currency_id")
    closing_balance = fields.Monetary("Сальдо на кінець", currency_field="currency_id")

    def _extra_domain(self):
        self.ensure_one()
        extra = [("account_id", "=", self.account_id.id)]
        if self.partner_id:
            extra.append(("partner_id", "=", self.partner_id.id))
        return extra

    def action_compute(self):
        for card in self:
            aml_model = card.env["account.move.line"]
            opening = card._opening_balance(card._extra_domain())
            entries = aml_model.search(
                card._aml_domain(card._extra_domain() + [
                    ("date", ">=", card.date_from),
                    ("date", "<=", card.date_to),
                ]),
                order="date, move_id, id",
            )
            # Рядки задіяних проводок одним запитом - для кореспондуючих рахунків.
            siblings = {}
            for line in aml_model.search([("move_id", "in", entries.move_id.ids)]):
                siblings.setdefault(line.move_id.id, []).append(line)

            commands = [(5, 0, 0)]
            balance = opening
            total_debit = total_credit = 0.0
            for sequence, line in enumerate(entries):
                balance = round(balance + line.debit - line.credit, 2)
                total_debit = round(total_debit + line.debit, 2)
                total_credit = round(total_credit + line.credit, 2)
                opposite = "credit" if line.debit else "debit"
                codes = sorted({
                    card._acc_code(sibling.account_id)
                    for sibling in siblings.get(line.move_id.id, [])
                    if sibling.id != line.id and getattr(sibling, opposite)
                })
                commands.append((0, 0, {
                    "sequence": sequence,
                    "date": line.date,
                    "move_id": line.move_id.id,
                    "move_name": line.move_id.name or "",
                    "ref": line.move_id.ref or "",
                    "partner_name": line.partner_id.name or "",
                    "label": line.name or "",
                    "counterpart": ", ".join(code for code in codes if code),
                    "debit": line.debit,
                    "credit": line.credit,
                    "balance": balance,
                }))

            card.write({
                "line_ids": commands,
                "opening_balance": opening,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "closing_balance": balance,
            })
        return True

    def action_print_xlsx(self):
        self.ensure_one()
        self.action_compute()
        return self.env.ref("l10n_ua_ledger.action_report_ua_account_card_xlsx").report_action(self)


class UaAccountCardLine(models.Model):
    _name = "ua.account.card.line"
    _description = "Рядок картки рахунку"
    _order = "sequence, id"

    card_id = fields.Many2one("ua.account.card", "Картка", required=True, ondelete="cascade")
    currency_id = fields.Many2one("res.currency", related="card_id.currency_id")
    sequence = fields.Integer("№")
    date = fields.Date("Дата")
    move_id = fields.Many2one("account.move", "Проводка")
    move_name = fields.Char("Документ")
    ref = fields.Char("Підстава")
    partner_name = fields.Char("Партнер")
    label = fields.Char("Зміст")
    counterpart = fields.Char("Кор. рахунок")
    debit = fields.Monetary("Дт", currency_field="currency_id")
    credit = fields.Monetary("Кт", currency_field="currency_id")
    balance = fields.Monetary("Сальдо", currency_field="currency_id")
