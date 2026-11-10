"""Введення нематеріального активу в експлуатацію: вартість проєкту з рахунку 154 стає активом.

Вартість - сальдо рахунку джерела (типово 154) з аналітикою проєкту на дату документа: зарплата
і ЄСВ розробників, що ліг туди розподілом, послуги підрядників, ліцензії на інструменти.
Проведення: Дт рахунок активу з профілю (12х) Кт 154, обидва рядки з аналітикою проєкту. Рядок
дебету несе профіль активу, тож картку активу створює OCA account_asset_management; документ
одразу її затверджує, і амортизація йде з наступного місяця (l10n_ua_assets).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .ua_payroll_allocation import _analytic


class UaIaCapitalization(models.Model):
    _name = "ua.ia.capitalization"
    _inherit = ["mail.thread"]
    _description = "Введення нематеріального активу в експлуатацію"
    _order = "date desc, id desc"

    name = fields.Char("Назва активу", required=True, tracking=True,
                       help="Так буде названо картку активу, напр. «Програма обліку замовлень, версія 1».")
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("Дата введення", required=True, default=fields.Date.context_today, tracking=True)
    analytic_account_id = fields.Many2one("account.analytic.account", "Проєкт", required=True,
                                          check_company=True, tracking=True)
    source_account_id = fields.Many2one(
        "account.account", "Рахунок вкладень", required=True, check_company=True, tracking=True,
        default=lambda s: s._default_source_account(),
        help="Де збиралася вартість проєкту: типово 154 «Придбання (створення) нематеріальних активів».")
    profile_id = fields.Many2one(
        "account.asset.profile", "Група НМА", required=True, check_company=True, tracking=True,
        domain="[('ua_tax_group', '=like', 'nma_%')]",
        help="Профіль активу: рахунок 12х, рахунок зносу 133, строк корисного використання.")
    amount = fields.Monetary("Вартість", currency_field="currency_id", readonly=True,
                             help="Сальдо рахунку вкладень з аналітикою проєкту на дату. Рахується кнопкою "
                                  "«Порахувати» і ще раз під час проведення.")
    state = fields.Selection([("draft", "Чернетка"), ("posted", "Проведено"), ("cancel", "Скасовано")], "Стан",
                             default="draft", required=True, readonly=True, copy=False, tracking=True)
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)
    asset_id = fields.Many2one("account.asset", "Актив", readonly=True, copy=False)
    note = fields.Text("Примітка")

    @api.model
    def _default_source_account(self):
        company = self.env.company
        Account = self.env["account.account"].with_company(company)
        domain = [("company_ids", "in", company.id)]
        return (Account.search(domain + [("code", "=", "154")], limit=1)
                or Account.search(domain + [("code", "=like", "154%")], order="code", limit=1))

    # ---- сума ------------------------------------------------------------------------
    @api.model
    def _analytic_balance(self, account, analytic, company, day, exclude_moves=None):
        """Сальдо рахунку на дату з аналітикою: кожен рядок важить свою частку цієї аналітики."""
        domain = [("account_id", "=", account.id), ("company_id", "=", company.id),
                  ("parent_state", "=", "posted"), ("date", "<=", day)]
        if exclude_moves:
            domain.append(("move_id", "not in", exclude_moves.ids))
        key = str(analytic.id)
        total = 0.0
        for line in self.env["account.move.line"].search(domain):
            share = sum(percent for ids, percent in (line.analytic_distribution or {}).items()
                        if key in str(ids).split(","))
            total += line.balance * share / 100.0
        return company.currency_id.round(total)

    def _compute_amount(self):
        for doc in self:
            doc.amount = self._analytic_balance(doc.source_account_id, doc.analytic_account_id,
                                                doc.company_id, doc.date)

    def action_compute(self):
        self.filtered(lambda d: d.state == "draft")._compute_amount()
        return True

    # ---- проведення ------------------------------------------------------------------
    def action_post(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Провести можна лише чернетку."))
            doc._compute_amount()
            if doc.company_id.currency_id.compare_amounts(doc.amount, 0.0) <= 0:
                raise UserError(_("На рахунку %(account)s немає вартості проєкту «%(project)s» на %(date)s.",
                                  account=doc.source_account_id.code, project=doc.analytic_account_id.name,
                                  date=doc.date.strftime("%d.%m.%Y")))
            profile = doc.profile_id
            if not (profile.account_asset_id and profile.journal_id):
                raise UserError(_("У профілі %s немає рахунку активу або журналу.") % profile.name)
            analytic = _analytic(doc.analytic_account_id)
            move = self.env["account.move"].with_company(doc.company_id).create({
                "journal_id": profile.journal_id.id, "date": doc.date, "move_type": "entry",
                "ref": _("Введення НМА в експлуатацію: %s") % doc.name,
                "line_ids": [
                    (0, 0, {"name": doc.name, "account_id": profile.account_asset_id.id, "debit": doc.amount,
                            "credit": 0.0, "asset_profile_id": profile.id, "analytic_distribution": analytic}),
                    (0, 0, {"name": doc.name, "account_id": doc.source_account_id.id, "debit": 0.0,
                            "credit": doc.amount, "analytic_distribution": analytic}),
                ]})
            move.action_post()
            asset = move.line_ids.asset_id[:1]
            if asset and asset.state == "draft":
                asset.validate()
            doc.write({"state": "posted", "move_id": move.id, "asset_id": asset.id})
        return True

    def action_cancel(self):
        for doc in self.filtered(lambda d: d.state == "posted"):
            asset = doc.asset_id
            if asset and asset.depreciation_line_ids.filtered(lambda l: l.type == "depreciate" and l.move_check):
                raise UserError(_("Актив %s уже амортизується: спершу скасуйте проводки амортизації.") % asset.name)
            if asset:
                asset.set_to_draft()
            move = doc.move_id
            if move:
                # Сторно, а не видалення: слід у журналі лишається. OCA сам прибирає актив,
                # коли сторнується проводка, що його створила.
                move._reverse_moves([{"date": move.date, "ref": _("Скасування: %s") % move.ref}], cancel=True)
            if asset.exists():
                asset.unlink()
        self.write({"state": "cancel", "asset_id": False})
        return True

    def action_draft(self):
        self.filtered(lambda d: d.state == "cancel").write({"state": "draft"})
        return True
