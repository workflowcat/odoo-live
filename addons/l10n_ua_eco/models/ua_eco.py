"""Повідомлення про зміну (ПЗ) - конструкторська зміна виробу.

Чинна специфікація не правиться руками. Зміна описується рядками «було / стало»:

    додати      новий компонент і кількість
    вилучити    компонент чинної специфікації
    замінити    компонент чинної специфікації на інший (кількість - та сама або нова)
    кількість   той самий компонент, нова кількість

Порядок:

    чернетка -> на погодженні -> погоджено -> застосовано
                            \\-> відхилено (з причиною) -> чернетка -> нове подання

Погоджують ролі: технолог і ВТК завжди, військове представництво - якщо виріб роблять за
оборонним контрактом (або позначено вручну). Порядок ролей довільний, автор не погоджує.

Застосування (у «Діє з» або пізніше): копія чинної специфікації з номером зміни +1, рядки ПЗ
внесено, нова специфікація стає першою, стара йде в архів. Якщо чинну специфікацію тим часом
змінило інше ПЗ, застосувати не можна: складають нове від актуальної ревізії.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

STATES = [
    ("draft", "Чернетка"),
    ("review", "На погодженні"),
    ("approved", "Погоджено"),
    ("applied", "Застосовано"),
    ("rejected", "Відхилено"),
    ("cancel", "Скасовано"),
]
REASONS = [
    ("defect", "Усунення дефекту"),
    ("supply", "Заміна комплектуючих (постачання)"),
    ("improvement", "Покращення характеристик"),
    ("customer", "Вимога замовника"),
    ("cost", "Зниження собівартості"),
    ("technology", "Технологічність"),
]
STOCK_POLICIES = [
    ("use_up", "Використати наявний заділ"),
    ("rework", "Доробити заділ"),
    ("scrap", "Списати заділ"),
]
ROLES = [("technology", "Технолог"), ("quality", "ВТК"),
         ("military", "Військове представництво")]
ROLE_GROUPS = {
    "technology": "l10n_ua_eco.group_ua_eco_technology",
    "quality": "l10n_ua_eco.group_ua_eco_quality",
    "military": "l10n_ua_eco.group_ua_eco_military",
}
ACTIONS = [("add", "Додати"), ("remove", "Вилучити"), ("replace", "Замінити"),
           ("qty", "Змінити кількість")]


def revision_label(number):
    return _("зм. %s") % number


class UaEco(models.Model):
    _name = "ua.eco"
    _description = "Повідомлення про зміну"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True,
                             copy=False, index=True)
    user_id = fields.Many2one("res.users", "Автор", required=True, readonly=True,
                              default=lambda self: self.env.user, copy=False)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    product_tmpl_id = fields.Many2one("product.template", "Виріб", required=True,
                                      tracking=True, check_company=True)
    bom_id = fields.Many2one(
        "mrp.bom", "Чинна специфікація", required=True, tracking=True, check_company=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        compute="_compute_bom_id", store=True, readonly=False, precompute=True)
    revision_from = fields.Integer("Було: зміна №", related="bom_id.ua_revision")
    new_bom_id = fields.Many2one("mrp.bom", "Нова специфікація", readonly=True, copy=False)
    reason = fields.Selection(REASONS, "Причина", required=True, default="improvement")
    description = fields.Text("Суть зміни", required=True)
    effective_date = fields.Date("Діє з", required=True, default=fields.Date.context_today,
                                 tracking=True)
    date_applied = fields.Date("Застосовано", readonly=True, copy=False)
    stock_policy = fields.Selection(STOCK_POLICIES, "Заділ і запаси", required=True,
                                    default="use_up")
    retrofit = fields.Boolean("Доробити випущені вироби")
    retrofit_lot_ids = fields.Many2many("stock.lot", string="Вироби для доробки",
                                        domain="[('product_id.product_tmpl_id', '=', product_tmpl_id)]")
    need_military = fields.Boolean(
        "Погодження військового представництва", compute="_compute_need_military", store=True,
        readonly=False,
        help="Ставиться само, якщо виріб робили за оборонним контрактом.")
    line_ids = fields.One2many("ua.eco.line", "eco_id", "Було / стало", copy=True)
    approval_ids = fields.One2many("ua.eco.approval", "eco_id", "Погодження", readonly=True,
                                   copy=False)
    approval_round = fields.Integer("Подання", readonly=True, copy=False)
    roles_required = fields.Char("Погоджують", compute="_compute_roles")
    roles_pending = fields.Char("Ще чекаємо", compute="_compute_roles")
    can_approve = fields.Boolean(compute="_compute_roles")
    reject_reason = fields.Text("Причина відхилення", copy=False)
    open_production_count = fields.Integer("Відкриті замовлення за старою ревізією",
                                           compute="_compute_open_productions")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.eco") or "/"
        return super().create(vals_list)

    @api.depends("product_tmpl_id")
    def _compute_bom_id(self):
        for eco in self:
            if eco.bom_id.product_tmpl_id != eco.product_tmpl_id:
                eco.bom_id = self.env["mrp.bom"].search([
                    ("product_tmpl_id", "=", eco.product_tmpl_id.id),
                    ("company_id", "in", (False, eco.company_id.id))], limit=1) \
                    if eco.product_tmpl_id else False

    @api.depends("product_tmpl_id")
    def _compute_need_military(self):
        Production = self.env["mrp.production"].sudo()
        for eco in self:
            eco.need_military = bool(eco.product_tmpl_id) and bool(Production.search_count([
                ("product_id.product_tmpl_id", "=", eco.product_tmpl_id.id),
                ("ua_contract_id.ua_defense", "=", True)], limit=1))

    def _roles(self):
        self.ensure_one()
        return ["technology", "quality"] + (["military"] if self.need_military else [])

    def _current_approvals(self):
        self.ensure_one()
        return self.approval_ids.filtered(lambda a: a.submission == self.approval_round)

    def _pending_roles(self):
        done = self._current_approvals().filtered(lambda a: a.decision == "approve").mapped("role")
        return [role for role in self._roles() if role not in done]

    def _my_role(self):
        """Роль, у якій поточний користувач може погодити зараз, або нічого."""
        self.ensure_one()
        if self.state != "review" or self.env.user == self.user_id:
            return False
        for role in self._pending_roles():
            if self.env.user.has_group(ROLE_GROUPS[role]):
                return role
        return False

    @api.depends("need_military", "approval_ids", "state", "approval_round")
    @api.depends_context("uid")
    def _compute_roles(self):
        labels = dict(ROLES)
        for eco in self:
            eco.roles_required = ", ".join(labels[r] for r in eco._roles())
            pending = eco._pending_roles() if eco.state == "review" else []
            eco.roles_pending = ", ".join(labels[r] for r in pending)
            eco.can_approve = bool(eco._my_role())

    @api.depends("bom_id")
    def _compute_open_productions(self):
        Production = self.env["mrp.production"].sudo()
        for eco in self:
            eco.open_production_count = Production.search_count([
                ("bom_id", "=", eco.bom_id.id),
                ("state", "not in", ("done", "cancel"))]) if eco.bom_id else 0

    # ------------------------------------------------------------ було / стало
    def diff_rows(self):
        """[{action, product, new_product, old_qty, new_qty, uom, note}] по рядках ПЗ."""
        self.ensure_one()
        return [line._row() for line in self.line_ids]

    def _check_lines(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Повідомлення %s без рядків «було / стало».") % self.name)
        for line in self.line_ids:
            line._check_against_bom()

    def _build_bom(self):
        """Нова ревізія: копія чинної специфікації з внесеними рядками ПЗ."""
        self.ensure_one()
        old = self.bom_id.sudo()
        new = old.copy({
            "active": False, "ua_revision": old.ua_revision + 1, "ua_eco_id": self.id,
            "ua_previous_bom_id": old.id, "sequence": max(old.sequence - 1, 0),
        })
        for line in self.line_ids:
            bom_line = new.bom_line_ids.filtered(lambda l: l.product_id == line.product_id)[:1]
            if line.action == "add":
                same = new.bom_line_ids.filtered(lambda l: l.product_id == line.new_product_id)[:1]
                if same:
                    same.product_qty += line.new_qty
                else:
                    new.bom_line_ids = [(0, 0, {
                        "product_id": line.new_product_id.id, "product_qty": line.new_qty,
                        "product_uom_id": (line.uom_id or line.new_product_id.uom_id).id})]
            elif line.action == "remove":
                bom_line.unlink()
            elif line.action == "replace":
                bom_line.write({"product_id": line.new_product_id.id,
                                "product_qty": line.new_qty or bom_line.product_qty,
                                "product_uom_id": (line.uom_id or line.new_product_id.uom_id).id})
            elif line.action == "qty":
                bom_line.product_qty = line.new_qty
        return new

    # ------------------------------------------------------------ дії
    def action_submit(self):
        for eco in self:
            if eco.state not in ("draft", "rejected"):
                raise UserError(_("На погодження подають чернетку або відхилене повідомлення."))
            eco._check_lines()
            eco.write({"state": "review", "approval_round": eco.approval_round + 1,
                       "reject_reason": False})
            eco.message_post(body=_("Подано на погодження: %s.") % eco.roles_required)
        return True

    def action_approve(self):
        for eco in self:
            role = eco._my_role()
            if not role:
                raise UserError(_("Погодити %s ви зараз не можете: автор не погоджує, а ваша "
                                  "роль уже погодила або не потрібна.") % eco.name)
            self.env["ua.eco.approval"].create({
                "eco_id": eco.id, "role": role, "decision": "approve",
                "submission": eco.approval_round})
            eco.invalidate_recordset(["can_approve", "roles_pending"])
            if not eco._pending_roles():
                eco.state = "approved"
                eco.message_post(body=_("Погоджено всіма: %s.") % eco.roles_required)
        return True

    def action_reject(self):
        for eco in self:
            role = eco._my_role()
            if not role:
                raise UserError(_("Відхилити %s ви зараз не можете.") % eco.name)
            reason = (eco.reject_reason or "").strip()
            if not reason:
                raise UserError(_("Напишіть причину відхилення."))
            self.env["ua.eco.approval"].create({
                "eco_id": eco.id, "role": role, "decision": "reject", "note": reason,
                "submission": eco.approval_round})
            eco.state = "rejected"
            eco.message_post(body=_("Відхилено: %s") % reason)
        return True

    def action_draft(self):
        for eco in self:
            if eco.state not in ("rejected", "cancel"):
                raise UserError(_("У чернетку повертають відхилене або скасоване повідомлення."))
            eco.state = "draft"
        return True

    def action_cancel(self):
        for eco in self:
            if eco.state == "applied":
                raise UserError(_("Застосовану зміну не скасовують - складіть нове повідомлення."))
            eco.state = "cancel"
        return True

    def action_apply(self):
        today = fields.Date.context_today(self)
        for eco in self:
            if eco.state != "approved":
                raise UserError(_("Застосовують лише погоджене повідомлення."))
            if eco.effective_date > today:
                raise UserError(_("Зміна діє з %s - її застосує планувальник того дня.")
                                % eco.effective_date.strftime("%d.%m.%Y"))
            eco._apply()
        return True

    def _apply(self):
        self.ensure_one()
        old = self.bom_id.sudo()
        if not old.active:
            raise UserError(_("Специфікацію %(bom)s уже замінено (%(eco)s). Складіть нове "
                              "повідомлення від чинної ревізії.", bom=old.display_name,
                              eco=old.ua_successor_eco_id.name or "-"))
        self._check_lines()
        new = self._build_bom()
        new.active = True
        old.write({"active": False, "ua_successor_eco_id": self.id})
        self.write({"state": "applied", "date_applied": fields.Date.context_today(self),
                    "new_bom_id": new.id})
        note = _("Нова ревізія %(rev)s: специфікація %(bom)s.", rev=revision_label(new.ua_revision),
                 bom=new.display_name)
        if self.open_production_count:
            note += " " + _("Відкритих замовлень за старою ревізією: %s - вони лишаються за "
                            "старою, нові підуть за новою.") % self.open_production_count
        self.message_post(body=note)

    @api.model
    def _cron_apply_due(self):
        today = fields.Date.context_today(self)
        for eco in self.search([("state", "=", "approved"), ("effective_date", "<=", today)]):
            try:
                with self.env.cr.savepoint():
                    eco._apply()
            except UserError as error:
                eco.message_post(body=_("Не застосовано: %s") % error)

    def action_print(self):
        return self.env.ref("l10n_ua_eco.action_report_ua_eco").report_action(self)

    def unlink(self):
        if any(eco.state not in ("draft", "cancel") for eco in self):
            raise UserError(_("Видалити можна лише чернетку або скасоване повідомлення."))
        return super().unlink()


class UaEcoLine(models.Model):
    _name = "ua.eco.line"
    _description = "Рядок повідомлення про зміну"
    _order = "eco_id, sequence, id"

    eco_id = fields.Many2one("ua.eco", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    action = fields.Selection(ACTIONS, "Що робимо", required=True, default="replace")
    product_id = fields.Many2one("product.product", "Було: компонент",
                                 help="Компонент чинної специфікації.")
    new_product_id = fields.Many2one("product.product", "Стало: компонент")
    old_qty = fields.Float("Було, к-сть", compute="_compute_old_qty", digits="Product Unit")
    new_qty = fields.Float("Стало, к-сть", digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", "Одиниця")
    note = fields.Char("Примітка")

    @api.depends("product_id", "eco_id.bom_id")
    def _compute_old_qty(self):
        for line in self:
            bom_line = line.eco_id.bom_id.sudo().bom_line_ids.filtered(
                lambda l: l.product_id == line.product_id)[:1] if line.product_id else False
            line.old_qty = bom_line.product_qty if bom_line else 0.0

    @api.constrains("action", "product_id", "new_product_id", "new_qty")
    def _check_fields(self):
        for line in self:
            if line.action in ("remove", "replace", "qty") and not line.product_id:
                raise ValidationError(_("Вкажіть, який компонент змінюється."))
            if line.action in ("add", "replace") and not line.new_product_id:
                raise ValidationError(_("Вкажіть новий компонент."))
            if line.action in ("add", "qty") and line.new_qty <= 0:
                raise ValidationError(_("Нова кількість має бути більшою за нуль."))
            if line.action == "replace" and line.new_qty < 0:
                raise ValidationError(_("Кількість не буває від'ємною."))

    def _check_against_bom(self):
        self.ensure_one()
        components = self.eco_id.bom_id.sudo().bom_line_ids.product_id
        if self.action in ("remove", "replace", "qty") and self.product_id not in components:
            raise UserError(_("%(product)s немає в чинній специфікації %(bom)s.",
                              product=self.product_id.display_name,
                              bom=self.eco_id.bom_id.display_name))

    def _row(self):
        self.ensure_one()
        return {
            "action": self.action, "action_label": dict(ACTIONS)[self.action],
            "product": self.product_id.display_name or "",
            "new_product": (self.new_product_id or (self.product_id if self.action == "qty"
                                                    else self.env["product.product"])).display_name
            or "",
            "old_qty": self.old_qty if self.action != "add" else 0.0,
            "new_qty": 0.0 if self.action == "remove" else (self.new_qty or self.old_qty),
            "uom": (self.uom_id or self.new_product_id.uom_id or self.product_id.uom_id).name or "",
            "note": self.note or "",
        }


class UaEcoApproval(models.Model):
    _name = "ua.eco.approval"
    _description = "Погодження повідомлення про зміну"
    _order = "eco_id, id"

    eco_id = fields.Many2one("ua.eco", required=True, ondelete="cascade", index=True)
    submission = fields.Integer("Подання", required=True, default=1)
    role = fields.Selection(ROLES, "Роль", required=True)
    decision = fields.Selection([("approve", "Погоджено"), ("reject", "Відхилено")], "Рішення",
                                required=True)
    user_id = fields.Many2one("res.users", "Хто", required=True, default=lambda s: s.env.user)
    date = fields.Datetime("Коли", required=True, default=fields.Datetime.now)
    note = fields.Text("Коментар")
