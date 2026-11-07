"""Гарантії і забезпечення за договорами.

Реєстр замість позабалансових рахунків: надані гарантії - рахунок 05, отримані - 06.
Сума і строк - з тексту гарантії; стан веде користувач (діє, повернуто, пред'явлено вимогу),
а «строк минув» ставить щоденне завдання.

Гарантія повернення авансу покриває аванс за договором (див. ua_contract.py). Отриману
гарантію повернення авансу не повертають, поки аванс постачальника не відпрацьовано або
його не покривають інші діючі гарантії: інакше підприємство лишається з авансом без
забезпечення.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TODO = "mail.mail_activity_data_todo"

DIRECTIONS = [
    ("given", "Надана (05)"),
    ("received", "Отримана (06)"),
]
KINDS = [
    ("bid", "Тендерне забезпечення"),
    ("performance", "Забезпечення виконання договору"),
    ("advance", "Повернення авансу"),
    ("warranty", "Гарантійні зобов'язання"),
    ("other", "Інше"),
]
FORMS = [
    ("bank", "Банківська гарантія"),
    ("deposit", "Грошове забезпечення"),
    ("other", "Інша форма"),
]
STATES = [
    ("draft", "Чернетка"),
    ("active", "Діє"),
    ("released", "Повернуто"),
    ("claimed", "Пред'явлено вимогу"),
    ("expired", "Строк минув"),
]


class UaGuarantee(models.Model):
    _name = "ua.guarantee"
    _description = "Гарантія або забезпечення"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_expiry, id"
    _check_company_auto = True

    name = fields.Char("Номер", required=True, tracking=True,
                       help="Номер гарантії в банку або номер документа про забезпечення.")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    direction = fields.Selection(DIRECTIONS, "Напрям", required=True, default="given", tracking=True,
                                 help="Надана - підприємство забезпечує свої зобов'язання перед "
                                      "контрагентом; отримана - контрагент забезпечує свої.")
    kind = fields.Selection(KINDS, "Вид", required=True, default="performance", tracking=True)
    form = fields.Selection(FORMS, "Форма", required=True, default="bank")
    partner_id = fields.Many2one("res.partner", "Контрагент", required=True, index=True, tracking=True,
                                 help="Бенефіціар наданої гарантії або принципал отриманої.")
    issuer_id = fields.Many2one("res.partner", "Гарант", tracking=True,
                                help="Банк або страховик, що видав гарантію.")
    contract_id = fields.Many2one(
        "ua.contract", "Договір", index=True, tracking=True, check_company=True,
        domain="[('partner_id', '=', commercial_partner_id)]")
    commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id")
    procurement_ref = fields.Char("Закупівля", help="Ідентифікатор закупівлі для тендерного забезпечення.")
    date_issue = fields.Date("Дата видачі", required=True, default=fields.Date.context_today)
    date_expiry = fields.Date("Діє до", required=True, tracking=True)
    currency_id = fields.Many2one("res.currency", "Валюта", required=True,
                                  default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary("Сума", required=True, tracking=True)
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    amount_company = fields.Monetary(
        "Сума, грн", compute="_compute_amount_company", store=True, currency_field="company_currency_id",
        help="У валюті компанії за курсом на дату видачі.")
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True, index=True)
    release_date = fields.Date("Дата повернення", readonly=True, copy=False)
    claim_date = fields.Date("Дата вимоги", copy=False, tracking=True)
    claim_amount = fields.Monetary("Сума вимоги", copy=False, tracking=True)
    notify_days = fields.Integer("Нагадати за, днів", default=30,
                                 help="За скільки днів до кінця строку поставити нагадування.")
    user_id = fields.Many2one("res.users", "Відповідальний", default=lambda self: self.env.user,
                              tracking=True)
    note = fields.Text("Примітки")

    off_balance_code = fields.Char("Рахунок", compute="_compute_off_balance_code",
                                   help="Позабалансовий рахунок: 05 - надані, 06 - отримані.")
    days_left = fields.Integer("Днів до кінця", compute="_compute_days_left")
    contract_percent = fields.Float("% від суми договору", compute="_compute_contract_terms",
                                    digits=(16, 2))
    shorter_than_contract = fields.Boolean(
        "Діє менше за договір", compute="_compute_contract_terms",
        help="Строк гарантії закінчується раніше за строк договору.")

    _name_partner_uniq = models.Constraint(
        "UNIQUE(company_id, direction, partner_id, name)",
        "Гарантія з таким номером у цього контрагента вже є.",
    )

    # ------------------------------------------------------------------
    @api.depends("amount", "currency_id", "date_issue", "company_id")
    def _compute_amount_company(self):
        for row in self:
            company = row.company_id or self.env.company
            if not row.currency_id or row.currency_id == company.currency_id:
                row.amount_company = row.amount
            else:
                row.amount_company = row.currency_id._convert(
                    row.amount, company.currency_id, company,
                    row.date_issue or fields.Date.context_today(row))

    @api.depends("direction")
    def _compute_off_balance_code(self):
        for row in self:
            row.off_balance_code = "05" if row.direction == "given" else "06"

    @api.depends("date_expiry")
    def _compute_days_left(self):
        today = fields.Date.context_today(self)
        for row in self:
            row.days_left = (row.date_expiry - today).days if row.date_expiry else 0

    @api.depends("amount", "currency_id", "date_expiry", "contract_id.amount",
                 "contract_id.currency_id", "contract_id.date_end")
    def _compute_contract_terms(self):
        for row in self:
            contract = row.contract_id
            row.contract_percent = (
                row.amount / contract.amount * 100.0
                if contract.amount and contract.currency_id == row.currency_id else 0.0)
            row.shorter_than_contract = bool(
                contract.date_end and row.date_expiry and row.date_expiry < contract.date_end)

    @api.onchange("contract_id")
    def _onchange_contract_id(self):
        contract = self.contract_id
        if not contract:
            return
        self.partner_id = contract.partner_id
        self.currency_id = contract.currency_id
        if contract.kind in ("sale", "purchase"):
            # з покупцем забезпечує підприємство, з постачальником - постачальник
            self.direction = "given" if contract.kind == "sale" else "received"

    @api.constrains("amount", "date_issue", "date_expiry", "claim_amount")
    def _check_values(self):
        for row in self:
            if row.currency_id.compare_amounts(row.amount, 0.0) <= 0:
                raise ValidationError(_("Сума гарантії має бути більша за нуль."))
            if row.date_issue and row.date_expiry and row.date_expiry < row.date_issue:
                raise ValidationError(_("Гарантія не може закінчуватися раніше, ніж її видано."))
            if row.claim_amount and row.currency_id.compare_amounts(row.claim_amount, row.amount) > 0:
                raise ValidationError(_("Вимога за гарантією %s більша за її суму.") % row.name)

    @api.constrains("contract_id", "partner_id")
    def _check_contract_partner(self):
        for row in self.filtered("contract_id"):
            if row.contract_id.partner_id != row.partner_id.commercial_partner_id:
                raise ValidationError(_("Договір гарантії %s укладено з іншим контрагентом.") % row.name)

    @api.depends("name", "issuer_id")
    def _compute_display_name(self):
        for row in self:
            text = _("Гарантія № %s") % (row.name or "")
            if row.issuer_id:
                text += ", %s" % row.issuer_id.name
            row.display_name = text

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------
    def action_activate(self):
        today = fields.Date.context_today(self)
        for row in self:
            if row.state != "draft":
                raise UserError(_("Гарантія %s уже не чернетка.") % row.name)
            if row.date_expiry < today:
                raise UserError(_("Строк гарантії %s уже минув.") % row.name)
        self.write({"state": "active"})
        return True

    def _ua_advance_left_without(self):
        """Аванс постачальника за договором, не покритий іншими діючими гарантіями повернення авансу."""
        self.ensure_one()
        contract = self.contract_id._ua_advance_fresh()
        others = contract.ua_guarantee_ids.filtered(
            lambda g: g != self and g.state == "active" and g.kind == "advance"
            and g.direction == "received")
        return contract.ua_advance_balance - sum(others.mapped("amount_company"))

    def action_release(self):
        for row in self:
            if row.state not in ("active", "expired"):
                raise UserError(_("Повернути можна діючу гарантію або гарантію з минулим строком."))
            if row.direction == "received" and row.kind == "advance" and row.contract_id:
                left = row._ua_advance_left_without()
                if row.company_currency_id.compare_amounts(left, 0.0) > 0:
                    raise UserError(_(
                        "Гарантію %(name)s не повертаємо: аванс за договором ще не відпрацьовано і "
                        "%(left)s грн лишаються без забезпечення. Поверніть її після поставки або "
                        "коли аванс покриє інша гарантія.",
                        name=row.name, left="{:,.2f}".format(left).replace(",", " ")))
        self.write({"state": "released", "release_date": fields.Date.context_today(self)})
        self.activity_unlink([TODO])
        return True

    def action_claim(self):
        for row in self:
            if row.state not in ("active", "expired"):
                raise UserError(_("Вимогу пред'являють за діючою гарантією."))
            if row.currency_id.compare_amounts(row.claim_amount, 0.0) <= 0:
                raise UserError(_("Вкажіть суму вимоги за гарантією %s.") % row.name)
        for row in self:
            row.write({"state": "claimed", "claim_date": row.claim_date or fields.Date.context_today(row)})
        return True

    def action_draft(self):
        self.write({"state": "draft", "release_date": False})
        return True

    # ------------------------------------------------------------------
    # Нагадування
    # ------------------------------------------------------------------
    @api.model
    def _ua_remind(self, record, summary, deadline, user):
        """Одне нагадування з таким текстом на запис: повтор не ставимо."""
        todo = self.env.ref(TODO)
        if record.activity_ids.filtered(lambda a: a.activity_type_id == todo and a.summary == summary):
            return False
        record.activity_schedule(TODO, date_deadline=deadline, summary=summary,
                                 user_id=(user or self.env.user).id)
        return True

    @api.model
    def _cron_reminders(self):
        """Щодня: строк минув - стан; кінець строку близько - нагадування; аванс прострочено - нагадування."""
        today = fields.Date.context_today(self)
        expired = self.search([("state", "=", "active"), ("date_expiry", "<", today)])
        for row in expired:
            row.write({"state": "expired"})
            row.message_post(body=_("Строк гарантії минув %s.") % row.date_expiry.strftime("%d.%m.%Y"))
        for row in self.search([("state", "=", "active"), ("date_expiry", ">=", today)]):
            if row.date_expiry <= today + timedelta(days=max(row.notify_days, 0)):
                self._ua_remind(row, _("Гарантія закінчується %s") % row.date_expiry.strftime("%d.%m.%Y"),
                                row.date_expiry, row.user_id)
        Contract = self.env["ua.contract"]
        for contract in Contract.search([("state", "=", "active"), ("ua_advance_due", "<", today)]):
            if not contract._ua_advance_fresh().ua_advance_overdue:
                continue
            self._ua_remind(contract, _("Аванс не відпрацьовано: строк %s")
                            % contract.ua_advance_due.strftime("%d.%m.%Y"),
                            today, contract.create_uid if contract.create_uid.active else None)
        return True
