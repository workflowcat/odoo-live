"""Книга обліку доходів ФОП: касовий метод.

Дохід платника єдиного податку - це кошти, отримані в грошовій формі, а дата
доходу - дата надходження коштів (п. 292.1 і п. 292.6 ПКУ). Тому книга
наповнюється не з рахунків, а з проведених платежів у журналах банку і каси.

Валютне надходження перераховується в гривню за офіційним курсом НБУ на дату
отримання коштів (п. 292.5 ПКУ). Курс беремо з нативних res.currency.rate -
їх наповнює l10n_ua_nbu, але залежності від нього тут немає: підійде будь-яке
джерело курсів.

Повернення коштів покупцю зменшує дохід (п. 292.11 ПКУ) - це від'ємний рядок
книги в періоді повернення.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Стани платежу, у яких гроші вже пройшли: банківський платіж після проведення
# стає in_process, касовий - одразу paid.
PAID_STATES = ("in_process", "paid")


class UaFopIncome(models.Model):
    _name = "ua.fop.income"
    _description = "Книга обліку доходів ФОП"
    _order = "date, id"

    name = fields.Char("Зміст", required=True, default="Надходження коштів")
    date = fields.Date(
        "Дата надходження", required=True, index=True,
        default=fields.Date.context_today,
    )
    company_id = fields.Many2one(
        "res.company", "ФОП", required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Валюта обліку",
    )
    partner_id = fields.Many2one("res.partner", "Платник")
    kind = fields.Selection(
        [
            ("money", "Надходження"),
            ("refund", "Повернення покупцю"),
            ("not_income", "Не дохід"),
        ],
        "Вид", required=True, default="money",
        help="«Не дохід» - кредит, поворотна фіндопомога, власні кошти "
             "підприємця: рядок у книзі є, у розрахунок ЄП не йде.",
    )
    amount = fields.Monetary(
        "Сума, грн", currency_field="currency_id", required=True,
        help="Сума в гривні. Для валютного надходження - за курсом на дату отримання.",
    )
    currency_foreign_id = fields.Many2one("res.currency", "Валюта надходження")
    amount_foreign = fields.Monetary(
        "Сума у валюті", currency_field="currency_foreign_id",
    )
    rate = fields.Float("Курс на дату", digits=(16, 6))
    source = fields.Selection(
        [("bank", "Банк"), ("cash", "Готівка")], "Джерело",
        required=True, default="bank",
    )
    payment_id = fields.Many2one(
        "account.payment", "Платіж", ondelete="set null", copy=False, index=True,
        help="Порожньо - рядок внесено вручну (наприклад, готівковий виторг "
             "без каси в Odoo).",
    )

    _payment_uniq = models.Constraint(
        "unique(payment_id)", "Цей платіж уже є в книзі доходів."
    )

    @api.constrains("kind", "amount")
    def _check_sign(self):
        for rec in self:
            if rec.kind == "refund" and rec.amount > 0:
                raise ValidationError(_("Повернення покупцю - від'ємний рядок книги."))
            if rec.kind == "money" and rec.amount < 0:
                raise ValidationError(_("Надходження не може бути від'ємним."))

    # ------------------------------------------------------------------
    # Підсумки
    # ------------------------------------------------------------------
    @api.model
    def _income_total(self, company, date_from, date_to):
        """Дохід для ЄП за період [date_from, date_to] включно, гривні.

        Рядки з видом «не дохід» не рахуються, повернення зменшують суму.
        """
        rows = self.search([
            ("company_id", "=", company.id),
            ("kind", "!=", "not_income"),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        return round(sum(rows.mapped("amount")), 2)

    @api.model
    def _book_rows(self, company, date_from, date_to):
        """Книга обліку доходів як список: рядки періоду з наростаючим підсумком."""
        rows = self.search([
            ("company_id", "=", company.id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ], order="date, id")
        running, out = 0.0, []
        for row in rows:
            if row.kind != "not_income":
                running = round(running + row.amount, 2)
            out.append({
                "date": row.date,
                "name": row.name,
                "partner": row.partner_id.display_name or "",
                "kind": row.kind,
                "amount": row.amount,
                "amount_foreign": row.amount_foreign,
                "currency": row.currency_foreign_id.name or "",
                "rate": row.rate,
                "running": running,
            })
        return out

    # ------------------------------------------------------------------
    # Наповнення з платежів
    # ------------------------------------------------------------------
    @api.model
    def _ua_fop_payments(self, companies):
        """Проведені платежі ФОП-компаній у журналах банку і каси."""
        return self.env["account.payment"].sudo().search([
            ("company_id", "in", companies.ids),
            ("state", "in", list(PAID_STATES)),
            ("journal_id.type", "in", ("bank", "cash")),
            "|",
            ("payment_type", "=", "inbound"),
            # Повернення коштів покупцю - теж подія книги, лише зі знаком мінус.
            "&", ("payment_type", "=", "outbound"), ("partner_type", "=", "customer"),
        ], order="date, id")

    @api.model
    def _vals_from_payment(self, payment):
        """Рядок книги з платежу: сума в гривні, курс, вид рядка."""
        company_currency = payment.company_id.currency_id
        foreign = payment.currency_id if payment.currency_id != company_currency else False
        amount = payment.amount
        rate = 0.0
        if foreign:
            on_date = payment.date or fields.Date.context_today(self)
            amount = foreign._convert(payment.amount, company_currency, payment.company_id, on_date)
            rate = round(amount / payment.amount, 6) if payment.amount else 0.0
        refund = payment.payment_type == "outbound"
        if payment.ua_fop_not_income:
            kind = "not_income"
        else:
            kind = "refund" if refund else "money"
        sign = -1.0 if refund else 1.0
        label = payment.memo or payment.name or ""
        if refund:
            label = "Повернення покупцю %s" % (payment.name or "")
        return {
            "name": label or "Надходження коштів",
            "date": payment.date,
            "company_id": payment.company_id.id,
            "partner_id": payment.partner_id.id or False,
            "kind": kind,
            "amount": sign * round(amount, 2),
            "currency_foreign_id": foreign.id if foreign else False,
            "amount_foreign": sign * payment.amount if foreign else 0.0,
            "rate": rate,
            "source": "cash" if payment.journal_id.type == "cash" else "bank",
            "payment_id": payment.id,
        }

    @api.model
    def _ua_fop_sync(self, companies=None):
        """Наповнити книгу з платежів. Ідемпотентно: повторний запуск нічого не дублює."""
        Company = self.env["res.company"].sudo()
        companies = companies or Company.search([("ua_fop", "=", True)])
        companies = companies.filtered("ua_fop")
        if not companies:
            return self.browse()
        payments = self._ua_fop_payments(companies)
        known = self.sudo().search([("payment_id", "in", payments.ids)])
        # Рядок, який уже є, не переписуємо: бухгалтер міг уточнити зміст або
        # суму вручну. Оновлюємо лише вид, бо прапорець «не дохід» - його ж дія.
        self._ua_fop_apply_flag(known.payment_id)
        seen = set(known.mapped("payment_id").ids)
        vals_list = [
            self._vals_from_payment(payment)
            for payment in payments
            if payment.id not in seen
        ]
        created = self.sudo().create(vals_list) if vals_list else self.browse()
        if created:
            _logger.info("ФОП: у книгу доходів додано %d рядків", len(created))
        return created

    @api.model
    def _ua_fop_apply_flag(self, payments):
        """Перемкнули «не дохід» на платежі - переставити вид рядка книги."""
        rows = self.sudo().search([("payment_id", "in", payments.ids)])
        for row in rows:
            payment = row.payment_id
            if payment.ua_fop_not_income:
                row.kind = "not_income"
            else:
                row.kind = "refund" if payment.payment_type == "outbound" else "money"
        return rows

    def action_sync(self):
        """Кнопка «Оновити з платежів»."""
        # Наповнення йде через sudo(), тож право перевіряємо тут: книгу веде бухгалтер.
        self.env["ua.fop.income"].check_access("write")
        self.env["ua.fop.income"]._ua_fop_sync()
        return True
