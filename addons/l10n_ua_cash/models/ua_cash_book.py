"""Касова книга (типова форма КО-4, додаток 5 до Положення НБУ № 148).

Аркуш заводиться на кожен день, у якому був рух готівки: залишок на початок дня,
рядок на кожен ордер, усього надійшло і видано, залишок на кінець дня. Книга рахує
не з ордерів, а з проводок рахунку каси: тоді залишок на кінець дня дорівнює сальдо
301 і ручна проводка по касі теж потрапляє в аркуш, а не губиться.

Залишок на кінець дня порівнюється з лімітом каси компанії (поле ua_cash_limit).
Перевищення позначається; понадлімітну готівку належить здати в банк.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UaCashBook(models.TransientModel):
    _name = "ua.cash.book"
    _description = "Касова книга (КО-4)"

    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    journal_id = fields.Many2one(
        "account.journal",
        "Каса",
        required=True,
        domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal(),
    )
    account_id = fields.Many2one(
        "account.account", "Рахунок каси", related="journal_id.default_account_id", readonly=True
    )
    date_from = fields.Date("Період з", required=True, default=lambda self: self._default_date_from())
    date_to = fields.Date("Період по", required=True, default=fields.Date.context_today)
    limit_amount = fields.Monetary(
        "Ліміт каси",
        currency_field="currency_id",
        default=lambda self: self.env.company.ua_cash_limit,
        help="Береться з картки компанії; тут можна підставити інший, якщо наказ про ліміт змінювався.",
    )

    opening_balance = fields.Monetary("Залишок на початок", currency_field="currency_id", readonly=True)
    total_in = fields.Monetary("Надходження", currency_field="currency_id", readonly=True)
    total_out = fields.Monetary("Видаток", currency_field="currency_id", readonly=True)
    closing_balance = fields.Monetary("Залишок на кінець", currency_field="currency_id", readonly=True)
    over_limit = fields.Boolean("Ліміт перевищено", readonly=True)
    over_limit_days = fields.Integer("Днів із перевищенням", readonly=True)
    line_ids = fields.One2many("ua.cash.book.line", "book_id", "Аркуші", readonly=True)

    @api.model
    def _default_journal(self):
        return self.env["account.journal"].search(
            [("type", "=", "cash"), ("company_id", "=", self.env.company.id)], limit=1
        )

    @api.model
    def _default_date_from(self):
        return fields.Date.context_today(self).replace(day=1)

    # ------------------------------------------------------------------
    def _aml_domain(self, extra=None):
        self.ensure_one()
        return [
            ("account_id", "=", self.account_id.id),
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
        ] + (extra or [])

    def action_compute(self):
        """Перерахувати книгу. Ідемпотентно: попередні аркуші стираються."""
        for book in self:
            if not book.account_id:
                raise UserError(
                    _("У журналі «%s» не задано рахунок каси.") % book.journal_id.display_name
                )
            if book.date_from > book.date_to:
                raise UserError(_("Початок періоду пізніший за кінець."))
            aml_model = self.env["account.move.line"]

            opening = 0.0
            for _account, debit, credit in aml_model._read_group(
                book._aml_domain([("date", "<", book.date_from)]),
                groupby=["account_id"],
                aggregates=["debit:sum", "credit:sum"],
            ):
                opening += (debit or 0.0) - (credit or 0.0)
            opening = round(opening, 2)

            entries = aml_model.search(
                book._aml_domain([("date", ">=", book.date_from), ("date", "<=", book.date_to)]),
                order="date, move_id, id",
            )
            by_day = {}
            for line in entries:
                by_day.setdefault(line.date, []).append(line)

            limit = round(book.limit_amount or 0.0, 2)
            commands = [(5, 0, 0)]
            balance = opening
            total_in = total_out = 0.0
            over_days = 0
            for sequence, day in enumerate(sorted(by_day)):
                day_lines = by_day[day]
                day_in = round(sum(line.debit for line in day_lines), 2)
                day_out = round(sum(line.credit for line in day_lines), 2)
                day_open = balance
                balance = round(day_open + day_in - day_out, 2)
                total_in = round(total_in + day_in, 2)
                total_out = round(total_out + day_out, 2)
                day_over = bool(limit) and balance > limit + 0.005
                if day_over:
                    over_days += 1
                commands.append(
                    (
                        0,
                        0,
                        {
                            "sequence": sequence,
                            "date": day,
                            "opening_balance": day_open,
                            "total_in": day_in,
                            "total_out": day_out,
                            "closing_balance": balance,
                            "limit_amount": limit,
                            "over_limit": day_over,
                            "entry_ids": [
                                (0, 0, vals) for vals in book._entry_vals(day_lines)
                            ],
                        },
                    )
                )

            book.write(
                {
                    "line_ids": commands,
                    "opening_balance": opening,
                    "total_in": total_in,
                    "total_out": total_out,
                    "closing_balance": balance,
                    "over_limit": over_days > 0,
                    "over_limit_days": over_days,
                }
            )
        return True

    def _entry_vals(self, day_lines):
        """Рядки аркуша: номер ордера, від кого / кому, кореспондуючий рахунок, суми."""
        self.ensure_one()
        vals_list = []
        for sequence, line in enumerate(day_lines):
            payment = line.move_id.origin_payment_id
            counterpart = sorted(
                {
                    sibling.account_id.with_company(self.company_id).code or ""
                    for sibling in line.move_id.line_ids
                    if sibling.id != line.id
                    and (sibling.credit if line.debit else sibling.debit)
                }
            )
            vals_list.append(
                {
                    "sequence": sequence,
                    "document": (
                        payment._ua_order_label() if payment else (line.move_id.name or "")
                    ),
                    "person": (
                        payment._ua_person_label()
                        if payment
                        else (line.partner_id.name or line.name or "")
                    ),
                    "counterpart": ", ".join(code for code in counterpart if code),
                    "move_id": line.move_id.id,
                    "amount_in": line.debit,
                    "amount_out": line.credit,
                }
            )
        return vals_list

    def action_print(self):
        self.ensure_one()
        self.action_compute()
        return self.env.ref("l10n_ua_cash.action_report_ua_cash_book").report_action(self)


class UaCashBookLine(models.TransientModel):
    _name = "ua.cash.book.line"
    _description = "Аркуш касової книги за день"
    _order = "sequence, id"

    book_id = fields.Many2one("ua.cash.book", "Касова книга", required=True, ondelete="cascade")
    currency_id = fields.Many2one("res.currency", related="book_id.currency_id")
    sequence = fields.Integer("№ аркуша")
    date = fields.Date("Дата")
    opening_balance = fields.Monetary("Залишок на початок дня", currency_field="currency_id")
    total_in = fields.Monetary("Надходження", currency_field="currency_id")
    total_out = fields.Monetary("Видаток", currency_field="currency_id")
    closing_balance = fields.Monetary("Залишок на кінець дня", currency_field="currency_id")
    limit_amount = fields.Monetary("Ліміт каси", currency_field="currency_id")
    over_limit = fields.Boolean("Ліміт перевищено")
    entry_ids = fields.One2many("ua.cash.book.entry", "line_id", "Ордери дня")


class UaCashBookEntry(models.TransientModel):
    _name = "ua.cash.book.entry"
    _description = "Рядок аркуша касової книги"
    _order = "sequence, id"

    line_id = fields.Many2one("ua.cash.book.line", "Аркуш", required=True, ondelete="cascade")
    currency_id = fields.Many2one("res.currency", related="line_id.currency_id")
    sequence = fields.Integer("№")
    document = fields.Char("Номер документа")
    person = fields.Char("Від кого одержано чи кому видано")
    counterpart = fields.Char("Кореспондуючий рахунок")
    move_id = fields.Many2one("account.move", "Проводка")
    amount_in = fields.Monetary("Надходження", currency_field="currency_id")
    amount_out = fields.Monetary("Видаток", currency_field="currency_id")
