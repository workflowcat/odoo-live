"""Аванс за договором і його забезпечення.

Аванс - це сальдо розрахунків договору «не в той бік»: за договором з покупцем кредитове
сальдо (покупець заплатив більше, ніж отримав), за договором з постачальником - дебетове
(підприємство заплатило більше, ніж отримало). Сальдо береться з проводок на рахунках
розрахунків, як в акті звірки.

Покриття - діючі гарантії повернення авансу за договором: для договору з покупцем - надані
підприємством, для договору з постачальником - отримані від постачальника.
"""
from collections.abc import Iterable

from odoo import _, api, fields, models

from odoo.addons.l10n_ua_contract.models.tools import settlement_accounts


ADVANCE_FIELDS = ["ua_advance_balance", "ua_advance_cover", "ua_advance_uncovered",
                  "ua_advance_open", "ua_advance_unsecured", "ua_advance_overdue"]


class UaContract(models.Model):
    _name = "ua.contract"
    _inherit = ["ua.contract", "mail.activity.mixin"]

    ua_guarantee_ids = fields.One2many("ua.guarantee", "contract_id", "Гарантії")
    ua_guarantee_count = fields.Integer("Гарантії", compute="_compute_ua_guarantee_count")
    ua_advance_due = fields.Date(
        "Аванс відпрацювати до", tracking=True,
        help="Дата, до якої аванс має бути закрито поставкою. Умова договору або нормативного акта "
             "для державних і оборонних закупівель - перевірте чинну редакцію.")
    ua_advance_balance = fields.Monetary(
        "Аванс", compute="_compute_ua_advance", currency_field="company_currency_id",
        help="Отриманий від покупця або виданий постачальнику аванс, ще не закритий поставкою.")
    ua_advance_cover = fields.Monetary(
        "Покрито гарантіями", compute="_compute_ua_advance", currency_field="company_currency_id")
    ua_advance_uncovered = fields.Monetary(
        "Без забезпечення", compute="_compute_ua_advance", currency_field="company_currency_id")
    ua_advance_open = fields.Boolean(
        "Є аванс", compute="_compute_ua_advance", search="_search_ua_advance_open")
    ua_advance_unsecured = fields.Boolean(
        "Аванс без забезпечення", compute="_compute_ua_advance", search="_search_ua_advance_unsecured")
    ua_advance_overdue = fields.Boolean(
        "Аванс прострочено", compute="_compute_ua_advance", search="_search_ua_advance_overdue")

    def _compute_ua_guarantee_count(self):
        counts = dict(self.env["ua.guarantee"]._read_group(
            [("contract_id", "in", self.ids)], ["contract_id"], ["__count"]))
        for contract in self:
            contract.ua_guarantee_count = counts.get(contract, 0)

    def _ua_balances(self):
        """{id договору: сальдо розрахунків} одним запитом на компанію."""
        result = {}
        records = self.filtered(lambda c: isinstance(c.id, int))
        for company in records.company_id:
            contracts = records.filtered(lambda c: c.company_id == company)
            groups = self.env["account.move.line"].sudo()._read_group([
                ("ua_contract_id", "in", contracts.ids),
                ("parent_state", "=", "posted"),
                ("account_id", "in", settlement_accounts(self.env, company).ids),
            ], ["ua_contract_id"], ["balance:sum"])
            result.update({contract.id: balance for contract, balance in groups})
        return result

    @api.depends("kind", "ua_advance_due", "ua_guarantee_ids.state", "ua_guarantee_ids.kind",
                 "ua_guarantee_ids.direction", "ua_guarantee_ids.amount_company")
    def _compute_ua_advance(self):
        balances = self._ua_balances()
        today = fields.Date.context_today(self)
        for contract in self:
            balance = balances.get(contract.id, 0.0)
            if contract.kind == "sale":
                advance, direction = max(0.0, -balance), "given"
            elif contract.kind == "purchase":
                advance, direction = max(0.0, balance), "received"
            else:
                advance, direction = 0.0, False
            cover = sum(contract.ua_guarantee_ids.filtered(
                lambda g: g.state == "active" and g.kind == "advance" and g.direction == direction
            ).mapped("amount_company"))
            currency = contract.company_currency_id
            contract.ua_advance_balance = currency.round(advance)
            contract.ua_advance_cover = currency.round(cover)
            contract.ua_advance_uncovered = currency.round(max(0.0, advance - cover))
            contract.ua_advance_open = currency.compare_amounts(advance, 0.0) > 0
            contract.ua_advance_unsecured = currency.compare_amounts(advance, cover) > 0
            contract.ua_advance_overdue = bool(
                contract.ua_advance_open and contract.ua_advance_due and contract.ua_advance_due < today)

    # ------------------------------------------------------------------
    # Пошук: аванс рахується з проводок, тож фільтр перебирає чинні договори
    # ------------------------------------------------------------------
    def _ua_search_by(self, operator, value, field):
        if operator in ("in", "not in"):
            # Odoo 19 передає значення як OrderedSet: будь-яка колекція, крім рядка
            values = list(value) if isinstance(value, Iterable) and not isinstance(value, str) else [value]
            want = (True in values) == (operator == "in")
        elif operator in ("=", "!="):
            want = bool(value) == (operator == "=")
        else:
            raise NotImplementedError(_("Пошук за авансом: лише так або ні."))
        contracts = self.search([("state", "!=", "closed"), ("kind", "in", ("sale", "purchase"))])
        ids = contracts.filtered(field).ids
        return [("id", "in" if want else "not in", ids)]

    def _search_ua_advance_open(self, operator, value):
        return self._ua_search_by(operator, value, "ua_advance_open")

    def _search_ua_advance_unsecured(self, operator, value):
        return self._ua_search_by(operator, value, "ua_advance_unsecured")

    def _search_ua_advance_overdue(self, operator, value):
        return self._ua_search_by(operator, value, "ua_advance_overdue")

    def _ua_advance_fresh(self):
        """Аванс з проводок, а не з кешу: проводки не є залежністю поля."""
        self.invalidate_recordset(ADVANCE_FIELDS)
        return self

    def action_ua_guarantees(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_guarantee.action_ua_guarantee")
        action["domain"] = [("contract_id", "=", self.id)]
        action["context"] = {"default_contract_id": self.id, "default_partner_id": self.partner_id.id,
                             "default_currency_id": self.currency_id.id,
                             "default_direction": "received" if self.kind == "purchase" else "given"}
        return action
