"""Гранти і цільове фінансування.

Грант - угода з грантодавцем: сума, строк, кошторис за статтями. Облік:

- надходження: кредит рахунку цільового фінансування (484) з аналітикою гранту. Банк
  аналітики не знає, тож кнопка «Знайти надходження» позначає грантом кредитові рядки
  484 від грантодавця, що ще без аналітики;
- використання: рядки проводок з аналітикою гранту на рахунках статті кошторису. Стаття
  без рахунків нічого не рахує, а один рахунок у двох статтях - помилка налаштування;
- дохід: цільове фінансування визнається доходом у тих періодах, коли понесено витрати,
  на які його отримано (НП(С)БО 15). Визнаємо використане, але не більше отриманого:
  Дт 484 Кт 718 на різницю з уже визнаним.

Рахунки - налаштування гранту з типовими значеннями плану ua_psbo; перевірте з бухгалтером,
як ваш грантодавець і облікова політика визначають статті та рахунки.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _share(line, analytic):
    """Частка рядка проводки, що припадає на аналітичний рахунок, за розподілом рядка."""
    share = 0.0
    for key, percent in (line.analytic_distribution or {}).items():
        if str(analytic.id) in key.split(","):
            share += percent
    return share / 100.0


class AccountMove(models.Model):
    _inherit = "account.move"

    # copy=True: сторно визнання лишається проводкою гранту і зменшує визнане
    ua_grant_id = fields.Many2one("ua.grant", "Грант (визнання доходу)", readonly=True,
                                  index="btree_not_null")


MONEY_FIELDS = ["budget_total", "received", "spent", "recognized", "to_recognize", "remaining", "over_budget"]


class UaGrant(models.Model):
    _name = "ua.grant"
    _description = "Грант або цільове фінансування"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Угода №", required=True, tracking=True)
    date = fields.Date("Дата угоди", required=True, default=fields.Date.context_today)
    program = fields.Char("Програма", help="Наприклад: грантова програма, донорський проєкт, державна субсидія.")
    grantor_id = fields.Many2one("res.partner", "Грантодавець", required=True, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary("Сума гранту", required=True, tracking=True,
                             help="У гривні. Грант у валюті - за курсом угоди; курсові різниці - окремо.")
    date_start = fields.Date("Початок", required=True, default=fields.Date.context_today)
    date_end = fields.Date("Кінець", tracking=True)
    report_due = fields.Date("Звіт до", tracking=True, help="Коли звітувати грантодавцю.")
    state = fields.Selection([("draft", "Чернетка"), ("active", "Діє"), ("closed", "Закрито")],
                             "Стан", required=True, default="draft", tracking=True)
    funding_account_id = fields.Many2one(
        "account.account", "Рахунок цільового фінансування", required=True, check_company=True,
        default=lambda self: self._ua_default_account("484"))
    income_account_id = fields.Many2one(
        "account.account", "Рахунок доходу", required=True, check_company=True,
        default=lambda self: self._ua_default_account("718"),
        help="718 - для поточних витрат; для необоротних активів дохід визнають у міру амортизації (745).")
    journal_id = fields.Many2one(
        "account.journal", "Журнал", required=True, check_company=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.env.company.id)], limit=1))
    analytic_account_id = fields.Many2one("account.analytic.account", "Аналітичний рахунок", readonly=True,
                                          copy=False, check_company=True)
    line_ids = fields.One2many("ua.grant.line", "grant_id", "Кошторис", copy=True)
    move_ids = fields.One2many("account.move", "ua_grant_id", "Визнання доходу")
    note = fields.Html("Умови гранту")

    budget_total = fields.Monetary("За кошторисом", compute="_compute_money")
    received = fields.Monetary("Отримано", compute="_compute_money")
    spent = fields.Monetary("Використано", compute="_compute_money")
    recognized = fields.Monetary("Визнано доходом", compute="_compute_money")
    to_recognize = fields.Monetary("Визнати", compute="_compute_money",
                                   help="Використане, але не більше отриманого, мінус уже визнане.")
    remaining = fields.Monetary("Залишок гранту", compute="_compute_money",
                                help="Отримано мінус використано.")
    over_budget = fields.Boolean("Є перевитрата статей", compute="_compute_money")

    @api.model
    def _ua_default_account(self, code):
        return self.env["account.account"].search([
            *self.env["account.account"]._check_company_domain(self.env.company),
            ("code", "=like", code + "%")], limit=1, order="code")

    @api.model_create_multi
    def create(self, vals_list):
        grants = super().create(vals_list)
        grants._ua_ensure_analytic()
        return grants

    def _ua_ensure_analytic(self):
        plan = self.env.ref("l10n_ua_grant.analytic_plan_grants", raise_if_not_found=False)
        if not plan:
            plan = self.env["account.analytic.plan"].sudo().create({"name": "Гранти"})
        for grant in self.filtered(lambda g: not g.analytic_account_id):
            grant.analytic_account_id = self.env["account.analytic.account"].sudo().create({
                "name": _("Грант %(name)s, %(grantor)s", name=grant.name, grantor=grant.grantor_id.name),
                "code": grant.name, "plan_id": plan.id, "company_id": grant.company_id.id,
                "partner_id": grant.grantor_id.id})

    def ua_analytic_distribution(self):
        """Розподіл для рядків документів, що йдуть у грант."""
        self.ensure_one()
        return {str(self.analytic_account_id.id): 100}

    # ------------------------------------------------------------------
    # Гроші
    # ------------------------------------------------------------------
    def _ua_lines(self, accounts):
        """Проведені рядки з аналітикою гранту на рахунках."""
        self.ensure_one()
        if not self.analytic_account_id or not accounts:
            return self.env["account.move.line"]
        lines = self.env["account.move.line"].sudo().search([
            ("parent_state", "=", "posted"), ("company_id", "=", self.company_id.id),
            ("account_id", "in", accounts.ids),
            ("analytic_distribution", "in", [self.analytic_account_id.id])])
        return lines

    def _ua_amount(self, lines):
        analytic = self.analytic_account_id
        return sum(line.balance * _share(line, analytic) for line in lines)

    @api.depends("amount", "line_ids.amount", "line_ids.spent")
    def _compute_money(self):
        for grant in self:
            currency = grant.currency_id
            if not isinstance(grant.id, int):
                grant.budget_total = sum(grant.line_ids.mapped("amount"))
                grant.received = grant.spent = grant.recognized = 0.0
                grant.to_recognize = grant.remaining = 0.0
                grant.over_budget = False
                continue
            funding = grant._ua_lines(grant.funding_account_id)
            recognition = funding.filtered(lambda l: l.move_id.ua_grant_id == grant)
            # надходження мінус повернення грантодавцю; визнання - дебет 484 проводками гранту
            received = -grant._ua_amount(funding - recognition)
            recognized = grant._ua_amount(recognition)
            spent = sum(grant.line_ids.mapped("spent"))
            grant.budget_total = sum(grant.line_ids.mapped("amount"))
            grant.received = currency.round(received)
            grant.spent = currency.round(spent)
            grant.recognized = currency.round(recognized)
            grant.to_recognize = currency.round(max(0.0, min(spent, received) - recognized))
            grant.remaining = currency.round(received - spent)
            grant.over_budget = any(line.over_budget for line in grant.line_ids)

    @api.constrains("line_ids")
    def _check_line_accounts(self):
        for grant in self:
            seen = {}
            for line in grant.line_ids:
                for account in line.account_ids:
                    if account in seen:
                        raise ValidationError(_(
                            "Рахунок %(account)s є і в статті «%(one)s», і в статті «%(two)s»: витрати "
                            "порахувались би двічі.", account=account.code, one=seen[account], two=line.name))
                    seen[account] = line.name

    @api.constrains("amount", "date_start", "date_end")
    def _check_values(self):
        for grant in self:
            if grant.currency_id.compare_amounts(grant.amount, 0.0) <= 0:
                raise ValidationError(_("Сума гранту має бути більша за нуль."))
            if grant.date_end and grant.date_end < grant.date_start:
                raise ValidationError(_("Грант не може закінчуватися раніше, ніж почався."))

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------
    def ua_fresh(self):
        """Суми з проводок, а не з кешу: проводки не є залежністю полів."""
        self.invalidate_recordset(MONEY_FIELDS)
        self.line_ids.invalidate_recordset(["spent", "remaining", "over_budget"])
        return self

    def action_activate(self):
        self.ua_fresh()
        for grant in self:
            if not grant.line_ids:
                raise UserError(_("Заповніть кошторис гранту %s.") % grant.name)
            if grant.currency_id.compare_amounts(grant.budget_total, grant.amount) > 0:
                raise UserError(_("Кошторис гранту %s більший за суму гранту.") % grant.name)
        self.write({"state": "active"})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_find_receipts(self):
        """Позначити грантом кредитові рядки 484 від грантодавця, що ще без аналітики."""
        self.ensure_one()
        lines = self.env["account.move.line"].search([
            ("parent_state", "=", "posted"), ("company_id", "=", self.company_id.id),
            ("account_id", "=", self.funding_account_id.id),
            ("partner_id", "child_of", self.grantor_id.commercial_partner_id.id),
            ("credit", ">", 0), ("analytic_distribution", "=", False),
            ("move_id.ua_grant_id", "=", False)])
        if not lines:
            raise UserError(_("Нових надходжень від %s на рахунку %s немає.")
                            % (self.grantor_id.display_name, self.funding_account_id.code))
        lines.write({"analytic_distribution": self.ua_analytic_distribution()})
        self.message_post(body=_("Позначено надходжень: %(count)s на суму %(amount)s.",
                                 count=len(lines), amount=self.money(sum(lines.mapped("credit")))))
        return True

    def action_recognize(self, date=None):
        """Визнати доходом використане, але не більше отриманого."""
        self.ua_fresh()
        for grant in self:
            amount = grant.to_recognize
            if grant.currency_id.compare_amounts(amount, 0.0) <= 0:
                raise UserError(_("За грантом %s визнавати доходом нічого: використане вже визнано "
                                  "або коштів ще не отримано.") % grant.name)
            distribution = grant.ua_analytic_distribution()
            move = self.env["account.move"].create({
                "move_type": "entry", "journal_id": grant.journal_id.id,
                "date": date or fields.Date.context_today(grant), "ua_grant_id": grant.id,
                "ref": _("Визнання доходу за грантом %s") % grant.name,
                "line_ids": [
                    (0, 0, {"account_id": grant.funding_account_id.id, "debit": amount,
                            "partner_id": grant.grantor_id.id, "analytic_distribution": distribution,
                            "name": _("Використано коштів гранту %s") % grant.name}),
                    (0, 0, {"account_id": grant.income_account_id.id, "credit": amount,
                            "partner_id": grant.grantor_id.id,
                            "name": _("Дохід від цільового фінансування, грант %s") % grant.name}),
                ]})
            move.action_post()
        return True

    def action_view_moves(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Проводки гранту"), "res_model": "account.move.line",
                "view_mode": "list", "domain": [("analytic_distribution", "in", [self.analytic_account_id.id])],
                "context": {"create": False}}

    def action_print(self):
        return self.env.ref("l10n_ua_grant.action_report_ua_grant").report_action(self)

    @staticmethod
    def money(value):
        text = "{:,.2f}".format(value or 0.0)
        return text.replace(",", " ").replace(".", ",")


class UaGrantLine(models.Model):
    _name = "ua.grant.line"
    _description = "Стаття кошторису гранту"
    _order = "grant_id, sequence, id"

    grant_id = fields.Many2one("ua.grant", "Грант", required=True, index=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char("Стаття", required=True)
    amount = fields.Monetary("За кошторисом")
    currency_id = fields.Many2one(related="grant_id.currency_id")
    account_ids = fields.Many2many("account.account", string="Рахунки витрат",
                                   help="Проводки на цих рахунках з аналітикою гранту - використання статті.")
    spent = fields.Monetary("Використано", compute="_compute_spent")
    remaining = fields.Monetary("Залишок", compute="_compute_spent")
    over_budget = fields.Boolean("Перевитрата", compute="_compute_spent")

    @api.constrains("account_ids", "grant_id")
    def _check_accounts(self):
        self.grant_id._check_line_accounts()

    @api.depends("amount", "account_ids")
    def _compute_spent(self):
        for line in self:
            grant = line.grant_id
            spent = grant._ua_amount(grant._ua_lines(line.account_ids)) if isinstance(grant.id, int) else 0.0
            line.spent = line.currency_id.round(spent)
            line.remaining = line.currency_id.round(line.amount - spent)
            line.over_budget = line.currency_id.compare_amounts(spent, line.amount) > 0
