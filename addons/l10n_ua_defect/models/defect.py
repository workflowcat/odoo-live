# -*- coding: utf-8 -*-
"""Акт про брак у виробництві (рахунок 24 «Брак у виробництві», П(С)БО 16).

Брак виявляють у цеху до здачі продукції на склад. Акт фіксує, що зіпсовано, скільки, чому і хто
винен, і розносить втрати:

    Дт 24  Кт 23 (або інший)     - собівартість невиправного браку;
    Дт 24  Кт рахунки витрат     - витрати на виправлення виправного браку (рядки акта);
    Дт 209 Кт 24                 - відходи від браку за ціною можливого використання;
    Дт 375 Кт 24                 - відшкодування винною особою;
    Дт 374 Кт 24                 - претензія постачальнику, якщо брак через його матеріал;
    Дт 23 (або 94) Кт 24         - решта, втрати від браку.

Після проведення рахунок 24 за актом закритий. Повернення в чернетку сторнує проводку. Утримання
з працівника робить зарплата за окремим наказом (ст. 127-136 КЗпП); акт дає суму і підставу.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

KINDS = [("final", "Невиправний"), ("fixable", "Виправний")]
CAUSES = [
    ("worker", "Помилка працівника"),
    ("material", "Матеріал постачальника"),
    ("equipment", "Обладнання, оснастка"),
    ("design", "Конструкторська документація"),
    ("process", "Технологія"),
    ("other", "Інше"),
]
STATES = [("draft", "Чернетка"), ("posted", "Проведено"), ("cancel", "Скасовано")]
LOSS_TO = [("production", "У собівартість продукції (23)"), ("expense", "На інші витрати (94)")]


class UaDefectAct(models.Model):
    _name = "ua.defect.act"
    _description = "Акт про брак у виробництві"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", default="/", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection(STATES, string="Стан", default="draft", required=True, tracking=True)
    production_id = fields.Many2one("mrp.production", string="Виробниче замовлення", check_company=True)
    workcenter_id = fields.Many2one("mrp.workcenter", string="Дільниця, де виявлено")
    product_id = fields.Many2one("product.product", string="Виріб", required=True)
    lot_ids = fields.Many2many("stock.lot", string="Серійні номери")
    qty = fields.Float("Кількість", required=True, default=1.0, digits="Product Unit")
    kind = fields.Selection(KINDS, string="Вид браку", required=True, default="final", tracking=True)
    cause = fields.Selection(CAUSES, string="Причина", required=True, default="worker", tracking=True)
    description = fields.Text("Опис дефекту", required=True)
    culprit_id = fields.Many2one("hr.employee", string="Винна особа")
    supplier_id = fields.Many2one("res.partner", string="Постачальник матеріалу")
    unit_cost = fields.Monetary(
        "Собівартість одиниці", currency_field="currency_id",
        help="Для невиправного браку: витрати на одиницю, що вже в незавершеному виробництві.")
    cost_amount = fields.Monetary("Собівартість браку", currency_field="currency_id",
                                  compute="_compute_amounts", store=True)
    fix_line_ids = fields.One2many("ua.defect.fix.line", "act_id", string="Витрати на виправлення")
    fix_amount = fields.Monetary("Витрати на виправлення", currency_field="currency_id",
                                 compute="_compute_amounts", store=True)
    total_amount = fields.Monetary("Разом на 24", currency_field="currency_id",
                                   compute="_compute_amounts", store=True)
    salvage_amount = fields.Monetary("Відходи за ціною використання", currency_field="currency_id")
    culprit_amount = fields.Monetary("Утримати з винної особи", currency_field="currency_id")
    supplier_amount = fields.Monetary("Претензія постачальнику", currency_field="currency_id")
    loss_amount = fields.Monetary("Втрати від браку", currency_field="currency_id",
                                  compute="_compute_amounts", store=True)
    loss_to = fields.Selection(LOSS_TO, string="Втрати списати", default="production", required=True)
    journal_id = fields.Many2one(
        "account.journal", string="Журнал", required=True, check_company=True,
        default=lambda self: self.env["account.journal"].search(
            [*self.env["account.journal"]._check_company_domain(self.env.company), ("type", "=", "general")],
            limit=1))
    defect_account_id = fields.Many2one(
        "account.account", string="Рахунок браку", check_company=True,
        default=lambda self: self._ua_default_account(("24",)))
    wip_account_id = fields.Many2one(
        "account.account", string="Звідки собівартість", check_company=True,
        default=lambda self: self._ua_default_account(("231", "23")))
    salvage_account_id = fields.Many2one(
        "account.account", string="Рахунок відходів", check_company=True,
        default=lambda self: self._ua_default_account(("209", "20")))
    culprit_account_id = fields.Many2one(
        "account.account", string="Рахунок відшкодування", check_company=True,
        default=lambda self: self._ua_default_account(("375",)))
    supplier_account_id = fields.Many2one(
        "account.account", string="Рахунок претензій", check_company=True,
        default=lambda self: self._ua_default_account(("374",)))
    expense_account_id = fields.Many2one(
        "account.account", string="Рахунок інших витрат", check_company=True,
        default=lambda self: self._ua_default_account(("949", "94")))
    move_id = fields.Many2one("account.move", string="Проводка", readonly=True, copy=False)

    @api.model
    def _ua_default_account(self, prefixes, company=None):
        Account = self.env["account.account"]
        for prefix in prefixes:
            account = Account.search([*Account._check_company_domain(company or self.env.company),
                                      ("code", "=like", prefix + "%")], limit=1, order="code")
            if account:
                return account
        return Account

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.defect.act") or "/"
        return super().create(vals_list)

    @api.depends("kind", "qty", "unit_cost", "fix_line_ids.amount", "salvage_amount", "culprit_amount",
                 "supplier_amount")
    def _compute_amounts(self):
        for act in self:
            cost = act.currency_id.round(act.qty * act.unit_cost) if act.kind == "final" else 0.0
            fix = sum(act.fix_line_ids.mapped("amount"))
            total = cost + fix
            act.cost_amount = cost
            act.fix_amount = fix
            act.total_amount = total
            act.loss_amount = total - act.salvage_amount - act.culprit_amount - act.supplier_amount

    @api.onchange("production_id")
    def _onchange_production_id(self):
        if self.production_id:
            self.product_id = self.production_id.product_id
            self.unit_cost = self.production_id.ua_defect_unit_cost()

    @api.constrains("qty", "salvage_amount", "culprit_amount", "supplier_amount")
    def _check_amounts(self):
        for act in self:
            if act.qty <= 0:
                raise ValidationError(_("Кількість браку більша за нуль."))
            if min(act.salvage_amount, act.culprit_amount, act.supplier_amount) < 0:
                raise ValidationError(_("Суми відшкодувань і відходів не від'ємні."))

    # ------------------------------------------------------------------ дії
    def _ua_check_post(self):
        self.ensure_one()
        cur = self.currency_id
        if float_is_zero(self.total_amount, precision_rounding=cur.rounding):
            raise UserError(_("Немає суми браку: собівартості або витрат на виправлення."))
        if cur.compare_amounts(self.loss_amount, 0.0) < 0:
            raise UserError(_("Відходи й відшкодування (%(back).2f) більші за суму браку (%(total).2f).") % {
                "back": self.total_amount - self.loss_amount, "total": self.total_amount})
        if not cur.is_zero(self.culprit_amount) and not self.culprit_id:
            raise UserError(_("Вкажіть винну особу, з якої утримати %.2f.") % self.culprit_amount)
        if not cur.is_zero(self.supplier_amount) and not self.supplier_id:
            raise UserError(_("Вкажіть постачальника для претензії."))
        needed = [self.defect_account_id]
        if self.kind == "final":
            needed.append(self.wip_account_id)
        for amount, account in ((self.salvage_amount, self.salvage_account_id),
                                (self.culprit_amount, self.culprit_account_id),
                                (self.supplier_amount, self.supplier_account_id)):
            if not cur.is_zero(amount):
                needed.append(account)
        if any(not account for account in needed) or self.fix_line_ids.filtered(lambda l: not l.account_id):
            raise UserError(_("Не всі рахунки акта заповнено."))

    def _ua_move_lines(self):
        self.ensure_one()
        cur, label = self.currency_id, _("Брак: %s") % self.name
        defect = self.defect_account_id
        lines = []

        def pair(debit_account, credit_account, amount, text, partner=False):
            if cur.is_zero(amount):
                return
            lines.append((0, 0, {"name": text, "account_id": debit_account.id, "debit": amount,
                                 "partner_id": partner}))
            lines.append((0, 0, {"name": text, "account_id": credit_account.id, "credit": amount,
                                 "partner_id": partner}))

        if self.kind == "final":
            pair(defect, self.wip_account_id, self.cost_amount, "%s, собівартість" % label)
        for fix in self.fix_line_ids:
            pair(defect, fix.account_id, fix.amount, "%s, виправлення: %s" % (label, fix.name))
        pair(self.salvage_account_id, defect, self.salvage_amount, "%s, відходи" % label)
        culprit_partner = self.culprit_id.sudo().work_contact_id.id if self.culprit_id else False
        pair(self.culprit_account_id, defect, self.culprit_amount, "%s, відшкодування" % label, culprit_partner)
        pair(self.supplier_account_id, defect, self.supplier_amount, "%s, претензія" % label,
             self.supplier_id.id or False)
        loss_account = self.wip_account_id if self.loss_to == "production" else self.expense_account_id
        if not loss_account:
            raise UserError(_("Вкажіть рахунок, на який списати втрати."))
        pair(loss_account, defect, self.loss_amount, "%s, втрати" % label)
        return lines

    def action_post(self):
        for act in self:
            if act.state != "draft":
                raise UserError(_("Проводять чернетку акта."))
            act._ua_check_post()
            move = self.env["account.move"].create({
                "move_type": "entry", "journal_id": act.journal_id.id, "date": act.date, "ref": act.name,
                "line_ids": act._ua_move_lines()})
            move.action_post()
            act.write({"state": "posted", "move_id": move.id})
        return True

    def action_draft(self):
        for act in self:
            if act.move_id.state == "posted":
                act.move_id._reverse_moves([{"ref": _("Сторно: %s") % act.name, "date": act.date}], cancel=True)
            act.write({"state": "draft", "move_id": False})
        return True

    def action_cancel(self):
        for act in self:
            if act.state == "posted":
                raise UserError(_("Проведений акт спершу поверніть у чернетку."))
            act.state = "cancel"
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_defect.action_report_ua_defect").report_action(self)

    def ua_kind_label(self):
        return dict(KINDS).get(self.kind, "")

    def ua_cause_label(self):
        return dict(CAUSES).get(self.cause, "")

    def ua_loss_label(self):
        return dict(LOSS_TO).get(self.loss_to, "")


class UaDefectFixLine(models.Model):
    _name = "ua.defect.fix.line"
    _description = "Витрати на виправлення браку"

    act_id = fields.Many2one("ua.defect.act", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="act_id.company_id", store=True)
    currency_id = fields.Many2one(related="act_id.currency_id")
    name = fields.Char("Витрати", required=True)
    account_id = fields.Many2one(
        "account.account", string="Кредит рахунку", required=True,
        default=lambda self: self.env["ua.defect.act"]._ua_default_account(("231", "23")),
        help="Звідки витрати: 23 - роботи цеху, 20 - матеріали, 66 - зарплата, 65 - ЄСВ.")
    amount = fields.Monetary("Сума", currency_field="currency_id")


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ua_defect_act_ids = fields.One2many("ua.defect.act", "production_id", string="Акти про брак")
    ua_defect_count = fields.Integer("Брак", compute="_compute_ua_defect_count")

    @api.depends("ua_defect_act_ids")
    def _compute_ua_defect_count(self):
        for production in self:
            production.ua_defect_count = len(production.ua_defect_act_ids)

    def ua_defect_unit_cost(self):
        """Матеріали замовлення на одиницю виробу за обліковою ціною компонентів."""
        self.ensure_one()
        qty = self.product_qty or 1.0
        materials = sum(move.product_id.standard_price * move.product_uom_qty for move in self.move_raw_ids)
        return self.company_id.currency_id.round(materials / qty)

    def action_ua_defect_act(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Акт про брак"), "res_model": "ua.defect.act",
            "view_mode": "form",
            "context": {"default_production_id": self.id, "default_product_id": self.product_id.id,
                        "default_unit_cost": self.ua_defect_unit_cost(),
                        "default_company_id": self.company_id.id},
        }

    def action_ua_open_defects(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Акти про брак"), "res_model": "ua.defect.act",
            "view_mode": "list,form", "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id, "default_product_id": self.product_id.id},
        }
