# -*- coding: utf-8 -*-
"""Інвентаризація необоротних активів (Положення про інвентаризацію, наказ Мінфіну № 879).

Опис - активи реєстру OCA, що на дату інвентаризації в експлуатації (стан «діючий» чи «замортизований»,
дата введення не пізніше дати), з балансовою вартістю на дату: первісна, знос з проведених рядків
амортизації (і початкового зносу) до дати, залишкова. Комісія відмічає наявність, фактичне місце,
МВО і стан, дописує лишки з оцінкою.

Затвердження результатів:
- нестача - актив знімається з обліку майстром OCA (режим «залишкова вартість») із залишковою
  вартістю на рахунок нестач (типово 947); сума, визнана винною особою, - Дт 375 Кт 716;
- лишок - Дт рахунок активу профілю Кт 746 (оцінка); картку активу створює OCA під час проведення;
- нове місце і МВО з опису записуються в картку активу.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("done", "Результати відображено")]
KINDS = [("book", "За даними обліку"), ("surplus", "Лишок")]
CONDITIONS = [
    ("used", "Використовується"),
    ("idle", "Не використовується"),
    ("repair", "Потребує ремонту"),
    ("unfit", "Непридатний, до списання"),
]
DEFAULT_ACCOUNTS = {"shortage": "947", "surplus": "746", "culprit": "375", "culprit_income": "716"}


class UaAssetInventory(models.Model):
    _name = "ua.asset.inventory"
    _description = "Інвентаризація необоротних активів"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("Дата інвентаризації", required=True, default=fields.Date.context_today, tracking=True)
    date_post = fields.Date("Дата відображення результатів", tracking=True,
                            help="Порожньо - дата інвентаризації. Не раніше останнього проведеного зносу.")
    order_ref = fields.Char("Наказ про інвентаризацію", help="Номер і дата наказу.")
    commission = fields.Text("Склад комісії", help="По одному на рядок: посада, прізвище та ініціали.")
    filter_responsible = fields.Char("МВО (відбір)", help="Лише активи цієї матеріально відповідальної особи.")
    filter_location = fields.Char("Місце (відбір)", help="Лише активи, у місці яких є цей текст.")
    filter_profile_ids = fields.Many2many("account.asset.profile", string="Профілі (відбір)")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.asset.inventory.line", "inventory_id", "Рядки",
                               domain=[("kind", "=", "book")])
    surplus_ids = fields.One2many("ua.asset.inventory.line", "inventory_id", "Лишки",
                                  domain=[("kind", "=", "surplus")])
    shortage_account_id = fields.Many2one(
        "account.account", "Рахунок нестач", check_company=True,
        default=lambda s: s._ua_default_account("shortage"))
    surplus_account_id = fields.Many2one(
        "account.account", "Рахунок доходу від лишків", check_company=True,
        default=lambda s: s._ua_default_account("surplus"))
    culprit_account_id = fields.Many2one(
        "account.account", "Рахунок розрахунків з винними", check_company=True,
        default=lambda s: s._ua_default_account("culprit"))
    culprit_income_account_id = fields.Many2one(
        "account.account", "Рахунок доходу від відшкодування", check_company=True,
        default=lambda s: s._ua_default_account("culprit_income"))
    journal_id = fields.Many2one(
        "account.journal", "Журнал", check_company=True,
        domain="[('type', '=', 'general')]",
        default=lambda s: s.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", s.env.company.id)], limit=1))
    move_ids = fields.Many2many("account.move", string="Проводки", readonly=True, copy=False)
    count_book = fields.Integer("Об'єктів за обліком", compute="_compute_totals")
    count_found = fields.Integer("Виявлено", compute="_compute_totals")
    count_missing = fields.Integer("Нестача, об'єктів", compute="_compute_totals")
    count_surplus = fields.Integer("Лишки, об'єктів", compute="_compute_totals")
    residual_book = fields.Monetary("Залишкова вартість за обліком", compute="_compute_totals")
    residual_missing = fields.Monetary("Нестача за залишковою вартістю", compute="_compute_totals")
    culprit_total = fields.Monetary("З винних осіб", compute="_compute_totals")
    surplus_total = fields.Monetary("Лишки за оцінкою", compute="_compute_totals")

    @api.depends("date")
    def _compute_name(self):
        for inv in self:
            inv.name = _("Інвентаризація необоротних активів %s") % (
                inv.date.strftime("%d.%m.%Y") if inv.date else "")

    @api.depends("line_ids.found", "line_ids.residual", "line_ids.culprit_amount",
                 "surplus_ids.value")
    def _compute_totals(self):
        for inv in self:
            missing = inv.line_ids.filtered(lambda l: not l.found)
            inv.count_book = len(inv.line_ids)
            inv.count_found = len(inv.line_ids) - len(missing)
            inv.count_missing = len(missing)
            inv.count_surplus = len(inv.surplus_ids)
            inv.residual_book = sum(inv.line_ids.mapped("residual"))
            inv.residual_missing = sum(missing.mapped("residual"))
            inv.culprit_total = sum(missing.mapped("culprit_amount"))
            inv.surplus_total = sum(inv.surplus_ids.mapped("value"))

    @api.model
    def _ua_default_account(self, key, company=None):
        company = company or self.env.company
        return self.env["account.account"].with_company(company).search(
            [("company_ids", "in", company.id), ("code", "=like", DEFAULT_ACCOUNTS[key] + "%")],
            order="code", limit=1)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(inv.state != "draft" for inv in self):
            raise UserError(_("Видалити можна лише чернетку: результати вже відображено в обліку."))

    # ------------------------------------------------------------------ опис
    @api.model
    def _ua_book_values(self, asset, day):
        """Первісна вартість, знос і залишкова вартість активу на дату з рядків амортизації OCA."""
        depreciated = sum(line.amount for line in asset.depreciation_line_ids
                          if line.type == "depreciate" and (line.move_check or line.init_entry)
                          and line.line_date <= day)
        return asset.purchase_value, depreciated, asset.purchase_value - depreciated

    def _ua_assets(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id), ("state", "in", ("open", "close")),
                  ("date_start", "<=", self.date)]
        if self.filter_profile_ids:
            domain.append(("profile_id", "in", self.filter_profile_ids.ids))
        if self.filter_responsible:
            domain.append(("ua_responsible", "=ilike", self.filter_responsible.strip()))
        if self.filter_location:
            domain.append(("ua_location", "ilike", self.filter_location.strip()))
        return self.env["account.asset"].search(domain, order="code, name, id")

    def action_fill(self):
        """Заповнити опис з реєстру: рядки за обліком перестворюються, лишки лишаються."""
        for inv in self:
            if inv.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            inv.line_ids.unlink()
            values = []
            for seq, asset in enumerate(inv._ua_assets(), 1):
                cost, depreciated, residual = self._ua_book_values(asset, inv.date)
                values.append({
                    "inventory_id": inv.id, "kind": "book", "sequence": seq * 10, "asset_id": asset.id,
                    "name": asset.name, "inventory_number": asset.code, "profile_id": asset.profile_id.id,
                    "factory_number": asset.ua_factory_number, "date_start": asset.date_start,
                    "location_book": asset.ua_location, "responsible_book": asset.ua_responsible,
                    "location_fact": asset.ua_location, "responsible_fact": asset.ua_responsible,
                    "cost": cost, "depreciation": depreciated, "residual": residual,
                })
            self.env["ua.asset.inventory.line"].create(values)
        return True

    # ------------------------------------------------------------------ результати
    def _ua_check_before_post(self):
        self.ensure_one()
        errors = []
        if not self.line_ids and not self.surplus_ids:
            errors.append(_("Опис порожній: заповніть його з реєстру."))
        missing = self.line_ids.filtered(lambda l: not l.found)
        if missing and not self.shortage_account_id:
            errors.append(_("Не вказано рахунок нестач."))
        if missing.filtered("culprit_amount") and not (self.culprit_account_id and self.culprit_income_account_id):
            errors.append(_("Не вказано рахунки для суми з винних осіб."))
        for line in missing.filtered(lambda l: l.culprit_amount and not l.culprit_partner_id):
            errors.append(_("%s: сума з винної особи без самої особи.") % line.name)
        for line in self.surplus_ids:
            if not line.profile_id or self.currency_id.compare_amounts(line.value, 0) <= 0:
                errors.append(_("Лишок «%s»: потрібні профіль активу й оцінка більше нуля.") % line.name)
        if self.surplus_ids and not self.surplus_account_id:
            errors.append(_("Не вказано рахунок доходу від лишків."))
        if (missing.filtered("culprit_amount") or self.surplus_ids) and not self.journal_id:
            errors.append(_("Не вказано журнал."))
        if errors:
            raise UserError("\n".join(errors))

    def action_post(self):
        """Відобразити результати в обліку: нестачі, суми з винних, лишки, нові місця і МВО."""
        for inv in self:
            if inv.state != "draft":
                raise UserError(_("Результати вже відображено."))
            inv._ua_check_before_post()
            day = inv.date_post or inv.date
            moves = self.env["account.move"]
            for line in inv.line_ids.filtered(lambda l: not l.found):
                moves |= inv._ua_post_shortage(line, day)
            for line in inv.surplus_ids:
                moves |= inv._ua_post_surplus(line, day)
            for line in inv.line_ids.filtered("found"):
                changes = {}
                if (line.location_fact or "") != (line.asset_id.ua_location or ""):
                    changes["ua_location"] = line.location_fact
                if (line.responsible_fact or "") != (line.asset_id.ua_responsible or ""):
                    changes["ua_responsible"] = line.responsible_fact
                if changes:
                    line.asset_id.write(changes)
            inv.write({"state": "done", "move_ids": [(6, 0, moves.ids)]})
            inv.message_post(body=_("Результати відображено: нестач %(missing)s, лишків %(surplus)s, проводок %(moves)s.")
                             % {"missing": inv.count_missing, "surplus": inv.count_surplus, "moves": len(moves)})
        return True

    def _ua_post_shortage(self, line, day):
        asset = line.asset_id
        wizard = self.env["account.asset.remove"].with_company(self.company_id).with_context(
            active_id=asset.id, active_ids=asset.ids, active_model="account.asset").create({
                "date_remove": day,
                "posting_regime": "residual_value",
                "account_residual_value_id": self.shortage_account_id.id,
                "note": _("Нестача за інвентаризацією: %s") % self.name,
            })
        wizard.remove()
        # OCA лишає проводку списання чернеткою - проводимо її тут.
        moves = asset.depreciation_line_ids.filtered(lambda l: l.type == "remove").move_id[-1:]
        moves.filtered(lambda m: m.state == "draft").action_post()
        line.removal_move_id = moves
        if line.culprit_amount:
            culprit = self.env["account.move"].create({
                "move_type": "entry", "date": day, "journal_id": self.journal_id.id,
                "ref": _("Нестача %(asset)s, %(doc)s") % {"asset": asset.name, "doc": self.name},
                "line_ids": [
                    (0, 0, {"account_id": self.culprit_account_id.id, "partner_id": line.culprit_partner_id.id,
                            "name": _("Визнано винною особою: %s") % asset.name, "debit": line.culprit_amount}),
                    (0, 0, {"account_id": self.culprit_income_account_id.id,
                            "partner_id": line.culprit_partner_id.id,
                            "name": _("Відшкодування нестачі: %s") % asset.name, "credit": line.culprit_amount}),
                ]})
            culprit.action_post()
            line.culprit_move_id = culprit
            moves |= culprit
        return moves

    def _ua_post_surplus(self, line, day):
        profile = line.profile_id
        move = self.env["account.move"].create({
            "move_type": "entry", "date": day, "journal_id": self.journal_id.id,
            "ref": _("Лишок за інвентаризацією: %s") % self.name,
            "line_ids": [
                (0, 0, {"account_id": profile.account_asset_id.id, "asset_profile_id": profile.id,
                        "name": line.name, "debit": line.value}),
                (0, 0, {"account_id": self.surplus_account_id.id,
                        "name": _("Лишок: %s") % line.name, "credit": line.value}),
            ]})
        move.action_post()
        asset = move.line_ids.asset_id[:1]
        if asset:
            values = {"ua_location": line.location_fact, "ua_responsible": line.responsible_fact,
                      "ua_factory_number": line.factory_number}
            if line.inventory_number:
                values["code"] = line.inventory_number
            asset.write({k: v for k, v in values.items() if v})
        line.write({"asset_id": asset.id, "removal_move_id": move.id})
        return move

    def action_print(self):
        return self.env.ref("l10n_ua_asset_inventory.action_report_ua_asset_inventory").report_action(self)

    def ua_money(self, value):
        """Сума для друку: пробіл між тисячами, кома, нуль - прочерк."""
        self.ensure_one()
        if self.currency_id.is_zero(value or 0.0):
            return "-"
        return "{:,.2f}".format(value).replace(",", " ").replace(".", ",")

    def ua_condition(self, line):
        return dict(CONDITIONS).get(line.condition, "")


class UaAssetInventoryLine(models.Model):
    _name = "ua.asset.inventory.line"
    _description = "Рядок інвентаризації необоротних активів"
    _order = "kind, sequence, id"

    inventory_id = fields.Many2one("ua.asset.inventory", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="inventory_id.company_id", store=True)
    currency_id = fields.Many2one(related="inventory_id.currency_id")
    kind = fields.Selection(KINDS, "Вид", required=True, default="surplus")
    sequence = fields.Integer(default=10)
    asset_id = fields.Many2one("account.asset", "Актив", readonly=True)
    name = fields.Char("Найменування", required=True)
    inventory_number = fields.Char("Інвентарний номер")
    factory_number = fields.Char("Заводський номер")
    profile_id = fields.Many2one("account.asset.profile", "Профіль (група)")
    date_start = fields.Date("Введено в експлуатацію", readonly=True)
    location_book = fields.Char("Місце за обліком", readonly=True)
    responsible_book = fields.Char("МВО за обліком", readonly=True)
    location_fact = fields.Char("Місце фактично")
    responsible_fact = fields.Char("МВО фактично")
    cost = fields.Monetary("Первісна вартість", readonly=True)
    depreciation = fields.Monetary("Знос", readonly=True)
    residual = fields.Monetary("Залишкова вартість", readonly=True)
    found = fields.Boolean("Наявний", default=True)
    condition = fields.Selection(CONDITIONS, "Стан", default="used")
    value = fields.Monetary("Оцінка лишку", help="Справедлива вартість об'єкта, виявленого понад облік.")
    culprit_partner_id = fields.Many2one("res.partner", "Винна особа")
    culprit_amount = fields.Monetary("Сума з винної особи")
    note = fields.Char("Примітка")
    removal_move_id = fields.Many2one("account.move", "Проводка", readonly=True)
    culprit_move_id = fields.Many2one("account.move", "Проводка винної особи", readonly=True)
