"""Купівля і продаж безготівкової валюти через банк.

Курс угоди - курс банку, за яким він купив або продав валюту. Курс НБУ - з курсів валют Odoo на
дату угоди (їх оновлює l10n_ua_nbu); його можна вписати вручну. Проводки (рахунок грошей у дорозі
типово 333):

Купівля 1 000 USD за 41,50, НБУ 41,20, комісія 100 грн:
    Дт 333 Кт 311   41 600   гривні в банк (з комісією)          - лише без виписок
    Дт 312 Кт 333   41 200   валюта за курсом НБУ (1 000 USD)    - лише без виписок
    Дт 942 Кт 333      300   курс угоди вищий за НБУ (якщо нижчий - Дт 333 Кт 711)
    Дт 92  Кт 333      100   комісія банку
Продаж 1 000 USD за 41,00, НБУ 41,20, комісія 100 грн:
    Дт 333 Кт 312   41 200   валюта в банк за курсом НБУ          - лише без виписок
    Дт 311 Кт 333   40 900   гривні від банку без комісії         - лише без виписок
    Дт 333 Кт 711   41 000   дохід від продажу валюти
    Дт 942 Кт 333   41 200   собівартість проданої валюти
    Дт 92  Кт 333      100   комісія банку
Сальдо 333 після обох рядків виписок - нуль.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round


def _money(value):
    return float_round(value or 0.0, 2)


class UaFxDeal(models.Model):
    _name = "ua.fx.deal"
    _inherit = ["mail.thread"]
    _description = "Купівля-продаж валюти"
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Гривня")
    kind = fields.Selection([("buy", "Купівля валюти"), ("sell", "Продаж валюти")], "Операція", required=True,
                            default="buy", tracking=True)
    date = fields.Date("Дата угоди", required=True, default=fields.Date.context_today, tracking=True)
    currency_id = fields.Many2one("res.currency", "Валюта", required=True, tracking=True,
                                  domain="[('id', '!=', company_currency_id)]")
    amount_currency = fields.Monetary("Сума у валюті", currency_field="currency_id", required=True, tracking=True)
    deal_rate = fields.Float("Курс угоди, грн", digits=(12, 6), required=True, tracking=True,
                             help="Курс банку за одиницю валюти: купівлі - за скільки банк продав вам, "
                                  "продажу - за скільки купив у вас.")
    nbu_rate = fields.Float("Курс НБУ, грн", digits=(12, 6), compute="_compute_nbu_rate", store=True,
                            readonly=False, tracking=True,
                            help="Курс НБУ на дату угоди з курсів валют. 0 - курсу на дату немає: оновіть курси "
                                 "або впишіть вручну.")
    commission = fields.Monetary("Комісія банку, грн", currency_field="company_currency_id", tracking=True)
    uah_journal_id = fields.Many2one("account.journal", "Гривневий рахунок", required=True, check_company=True,
                                     domain="[('type', '=', 'bank'), ('currency_id', 'in', (False, company_currency_id))]")
    fx_journal_id = fields.Many2one("account.journal", "Валютний рахунок", required=True, check_company=True,
                                    domain="[('type', '=', 'bank'), ('currency_id', '=', currency_id)]")
    post_bank_legs = fields.Boolean(
        "Проводити рух грошей", tracking=True,
        help="Увімкніть, якщо банківські виписки не завантажуються: документ сам проведе списання і "
             "надходження на рахунках. Якщо виписки є - лишіть вимкненим і звіряйте їхні рядки з "
             "рахунком грошей у дорозі.")
    transit_account_id = fields.Many2one("account.account", "Гроші в дорозі", required=True, check_company=True,
                                         default=lambda s: s._default_account("333", "377"))
    income_account_id = fields.Many2one("account.account", "Дохід від операцій з валютою", required=True,
                                        check_company=True, default=lambda s: s._default_account("711"))
    expense_account_id = fields.Many2one("account.account", "Собівартість валюти, втрати", required=True,
                                         check_company=True, default=lambda s: s._default_account("942"))
    fee_account_id = fields.Many2one("account.account", "Рахунок комісії", check_company=True,
                                     default=lambda s: s._default_account("92"))
    journal_id = fields.Many2one("account.journal", "Журнал проводки", check_company=True,
                                 domain="[('type', '=', 'general')]",
                                 help="Порожньо - журнал «Валютні операції» (створюється сам).")

    amount_deal = fields.Monetary("За курсом угоди, грн", currency_field="company_currency_id",
                                  compute="_compute_amounts", store=True)
    amount_nbu = fields.Monetary("За курсом НБУ, грн", currency_field="company_currency_id",
                                 compute="_compute_amounts", store=True)
    difference = fields.Monetary("Різниця, грн", currency_field="company_currency_id", compute="_compute_amounts",
                                 store=True, help="Купівля: плюс - переплата банку понад НБУ (942), мінус - дохід (711). "
                                                  "Продаж: плюс - дохід понад НБУ, мінус - втрата.")
    state = fields.Selection([("draft", "Чернетка"), ("posted", "Проведено"), ("cancel", "Скасовано")], "Стан",
                             default="draft", required=True, readonly=True, copy=False, tracking=True)
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)
    note = fields.Text("Примітка")

    @api.model
    def _default_account(self, *codes):
        company = self.env.company
        Account = self.env["account.account"].with_company(company)
        for code in codes:
            account = (Account.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1)
                       or Account.search([("code", "=like", code + "%"), ("company_ids", "in", company.id)],
                                         order="code", limit=1))
            if account:
                return account
        return Account

    @api.depends("currency_id", "date", "company_id")
    def _compute_nbu_rate(self):
        for deal in self:
            deal.nbu_rate = deal._nbu_rate()

    def _nbu_rate(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        if not self.currency_id or not self.date or self.currency_id == company.currency_id:
            return 0.0
        has_rate = self.env["res.currency.rate"].sudo().search_count([
            ("currency_id", "=", self.currency_id.id), ("name", "<=", self.date),
            "|", ("company_id", "=", False), ("company_id", "=", company.root_id.id)])
        if not has_rate:
            return 0.0
        return self.env["res.currency"]._get_conversion_rate(self.currency_id, company.currency_id, company, self.date)

    @api.depends("amount_currency", "deal_rate", "nbu_rate")
    def _compute_amounts(self):
        for deal in self:
            deal.amount_deal = _money(deal.amount_currency * deal.deal_rate)
            deal.amount_nbu = _money(deal.amount_currency * deal.nbu_rate)
            deal.difference = _money(deal.amount_deal - deal.amount_nbu)

    @api.constrains("amount_currency", "deal_rate", "commission")
    def _check_positive(self):
        for deal in self:
            if deal.amount_currency < 0 or deal.deal_rate < 0 or deal.commission < 0:
                raise ValidationError(_("Сума, курс і комісія не бувають від'ємними."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.fx.deal") or "/"
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda d: d.state == "posted"):
            raise UserError(_("Проведений документ не видаляється: спершу скасуйте його."))

    # ---- проведення ------------------------------------------------------------------
    def _journal(self):
        self.ensure_one()
        if self.journal_id:
            return self.journal_id
        Journal = self.env["account.journal"]
        journal = Journal.search([("code", "=", "ВАЛ"), ("company_id", "=", self.company_id.id)], limit=1)
        return journal or Journal.create({"name": "Валютні операції", "code": "ВАЛ", "type": "general",
                                          "company_id": self.company_id.id})

    def _line(self, account, debit, credit, label, currency_amount=None):
        vals = {"account_id": account.id, "debit": _money(debit), "credit": _money(credit), "name": label}
        if currency_amount is not None:
            vals.update(currency_id=self.currency_id.id, amount_currency=currency_amount)
        return (0, 0, vals)

    def _move_lines(self):
        """Рядки проводки; кожна пара - дебет і кредит однієї суми."""
        self.ensure_one()
        transit, lines = self.transit_account_id, []
        uah = self.uah_journal_id.default_account_id
        fx = self.fx_journal_id.default_account_id
        cur = "%s %s" % (self.amount_currency, self.currency_id.name)
        if self.kind == "buy":
            if self.post_bank_legs:
                paid = self.amount_deal + self.commission
                lines += [self._line(transit, paid, 0, _("Гривні на купівлю %s") % cur),
                          self._line(uah, 0, paid, _("Гривні на купівлю %s") % cur),
                          self._line(fx, self.amount_nbu, 0, _("Куплена валюта %s") % cur, self.amount_currency),
                          self._line(transit, 0, self.amount_nbu, _("Куплена валюта %s") % cur)]
            if self.difference > 0:
                label = _("Купівля %s дорожче за курс НБУ") % cur
                lines += [self._line(self.expense_account_id, self.difference, 0, label),
                          self._line(transit, 0, self.difference, label)]
            elif self.difference < 0:
                label = _("Купівля %s дешевше за курс НБУ") % cur
                lines += [self._line(transit, -self.difference, 0, label),
                          self._line(self.income_account_id, 0, -self.difference, label)]
        else:
            if self.post_bank_legs:
                received = self.amount_deal - self.commission
                lines += [self._line(transit, self.amount_nbu, 0, _("Валюта на продаж %s") % cur),
                          self._line(fx, 0, self.amount_nbu, _("Валюта на продаж %s") % cur, -self.amount_currency),
                          self._line(uah, received, 0, _("Гривні від продажу %s") % cur),
                          self._line(transit, 0, received, _("Гривні від продажу %s") % cur)]
            label = _("Продаж %s") % cur
            lines += [self._line(transit, self.amount_deal, 0, label),
                      self._line(self.income_account_id, 0, self.amount_deal, label),
                      self._line(self.expense_account_id, self.amount_nbu, 0, _("Собівартість проданої валюти %s") % cur),
                      self._line(transit, 0, self.amount_nbu, _("Собівартість проданої валюти %s") % cur)]
        if self.commission:
            label = _("Комісія банку за операцію з валютою")
            lines += [self._line(self.fee_account_id, self.commission, 0, label),
                      self._line(transit, 0, self.commission, label)]
        return lines

    def action_post(self):
        for deal in self:
            if deal.state != "draft":
                raise UserError(_("Провести можна лише чернетку."))
            if not deal.amount_currency or not deal.deal_rate:
                raise UserError(_("Впишіть суму у валюті і курс угоди."))
            if not deal.nbu_rate:
                raise UserError(_("Немає курсу НБУ %s на %s. Оновіть курси або впишіть курс вручну.")
                                % (deal.currency_id.name, deal.date.strftime("%d.%m.%Y")))
            if deal.commission and not deal.fee_account_id:
                raise UserError(_("Вкажіть рахунок комісії."))
            if deal.fx_journal_id.currency_id != deal.currency_id:
                raise UserError(_("Валюта рахунку %s не збігається з валютою угоди.") % deal.fx_journal_id.name)
            move = self.env["account.move"].with_company(deal.company_id).create({
                "journal_id": deal._journal().id, "date": deal.date, "move_type": "entry",
                "ref": "%s: %s" % (deal.name, dict(deal._fields["kind"].selection)[deal.kind]),
                "line_ids": deal._move_lines()})
            move.action_post()
            deal.write({"state": "posted", "move_id": move.id})
        return True

    def action_cancel(self):
        for deal in self.filtered(lambda d: d.state == "posted" and d.move_id):
            move = deal.move_id
            move._reverse_moves([{"date": move.date, "ref": _("Скасування: %s") % move.ref}], cancel=True)
        self.write({"state": "cancel"})
        return True

    def action_draft(self):
        self.filtered(lambda d: d.state == "cancel").write({"state": "draft", "move_id": False})
        return True

    def action_refresh_rate(self):
        for deal in self.filtered(lambda d: d.state == "draft"):
            deal.nbu_rate = deal._nbu_rate()
        return True
