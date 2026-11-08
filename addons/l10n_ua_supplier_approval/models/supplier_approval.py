"""Погоджені постачальники критичних комплектуючих.

Критичний товар купують лише в постачальника з чинним погодженням: стан «погоджено», дата
погодження настала, строк (якщо є) не минув, і обсяг покриває товар - сам товар, його категорію
(з підкатегоріями) або все. Перевірка - під час підтвердження замовлення постачальнику і під час
проведення приймання від постачальника. Призупинене чи відкликане погодження не діє.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TODO = "mail.mail_activity_data_todo"
STATES = [("draft", "Чернетка"), ("approved", "Погоджено"), ("suspended", "Призупинено"),
          ("withdrawn", "Відкликано"), ("expired", "Строк минув")]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_approved_only = fields.Boolean(
        "Лише від погоджених постачальників", tracking=True,
        help="Критичний товар: замовлення і приймання - лише від постачальника з чинним погодженням.")


class UaSupplierApproval(models.Model):
    _name = "ua.supplier.approval"
    _description = "Погодження постачальника"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "partner_id, date_approved desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер рішення", required=True, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    partner_id = fields.Many2one("res.partner", "Постачальник", required=True, index=True, tracking=True,
                                 domain="[('is_company', '=', True)]")
    scope = fields.Selection([("products", "Окремі товари"), ("categories", "Категорії"), ("all", "Усі товари")],
                             "Обсяг", required=True, default="products", tracking=True)
    product_tmpl_ids = fields.Many2many("product.template", string="Товари")
    categ_ids = fields.Many2many("product.category", string="Категорії")
    manufacturer = fields.Char("Виробник", help="Якщо постачальник - дистриб'ютор: чиє виробництво погоджено.")
    date_approved = fields.Date("Погоджено", required=True, default=fields.Date.context_today, tracking=True)
    date_until = fields.Date("Діє до", tracking=True, help="Порожньо - безстроково.")
    approved_by = fields.Char("Ким погоджено", help="Служба якості, представник замовника, комісія.")
    basis = fields.Char("Підстава", help="Акт аудиту, протокол випробувань, рішення.")
    state = fields.Selection(STATES, "Стан", required=True,
                             default="draft", tracking=True, index=True)
    reason = fields.Char("Причина призупинення чи відкликання", tracking=True)
    user_id = fields.Many2one("res.users", "Відповідальний", default=lambda self: self.env.user)
    notify_days = fields.Integer("Нагадати за, днів", default=30)
    note = fields.Text("Умови")

    @api.constrains("date_approved", "date_until")
    def _check_dates(self):
        for approval in self:
            if approval.date_until and approval.date_until < approval.date_approved:
                raise ValidationError(_("Строк погодження не може закінчуватися раніше, ніж його дано."))

    @api.constrains("scope", "product_tmpl_ids", "categ_ids")
    def _check_scope(self):
        for approval in self:
            if approval.scope == "products" and not approval.product_tmpl_ids:
                raise ValidationError(_("Погодження %s: оберіть товари.") % approval.name)
            if approval.scope == "categories" and not approval.categ_ids:
                raise ValidationError(_("Погодження %s: оберіть категорії.") % approval.name)

    def ua_covers(self, product, day):
        """Чи діє погодження на товар у цей день."""
        self.ensure_one()
        if self.state != "approved" or day < self.date_approved or (self.date_until and day > self.date_until):
            return False
        template = product.product_tmpl_id
        if self.scope == "all":
            return True
        if self.scope == "products":
            return template in self.product_tmpl_ids
        path = set((template.categ_id.parent_path or "").split("/"))
        return any(str(categ.id) in path for categ in self.categ_ids)

    @api.model
    def ua_find(self, partner, product, company, day):
        """Чинне погодження постачальника на товар або порожньо."""
        approvals = self.search([("company_id", "=", company.id), ("state", "=", "approved"),
                                 ("partner_id", "=", partner.commercial_partner_id.id)])
        return approvals.filtered(lambda a: a.ua_covers(product, day))[:1]

    @api.model
    def ua_check(self, partner, products, company, day, what):
        """UserError, якщо хоч один критичний товар не має чинного погодження в постачальника."""
        missing = products.filtered(lambda p: p.ua_approved_only and not self.ua_find(partner, p, company, day))
        if missing:
            raise UserError(_(
                "%(what)s: %(partner)s не має чинного погодження на «%(products)s». Критичні комплектуючі - "
                "лише від погоджених постачальників (Закупівлі > Погоджені постачальники).",
                what=what, partner=partner.commercial_partner_id.display_name,
                products=", ".join(missing.mapped("display_name"))))

    def action_approve(self):
        today = fields.Date.context_today(self)
        for approval in self:
            if approval.date_until and approval.date_until < today:
                raise UserError(_("Строк погодження %s уже минув.") % approval.name)
        self.write({"state": "approved", "reason": False})
        return True

    def action_suspend(self, reason=None):
        for approval in self:
            if approval.state != "approved":
                raise UserError(_("Призупинити можна лише чинне погодження."))
        self.write({"state": "suspended", "reason": reason or _("призупинено")})
        return True

    def action_withdraw(self, reason=None):
        self.write({"state": "withdrawn", "reason": reason or _("відкликано")})
        self.activity_unlink([TODO])
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_supplier_approval.action_report_ua_supplier_approval").report_action(self)

    def ua_scope_text(self):
        self.ensure_one()
        if self.scope == "all":
            return _("усі товари")
        if self.scope == "categories":
            return ", ".join(self.categ_ids.mapped("display_name"))
        return ", ".join(self.product_tmpl_ids.mapped("display_name"))

    def ua_state_label(self):
        self.ensure_one()
        return dict(STATES).get(self.state, "")

    def ua_date(self, day):
        return day.strftime("%d.%m.%Y") if day else ""

    @api.model
    def _cron_reminders(self):
        today = fields.Date.context_today(self)
        for approval in self.search([("state", "=", "approved"), ("date_until", "<", today)]):
            approval.write({"state": "expired"})
            approval.message_post(body=_("Строк погодження минув %s.") % approval.ua_date(approval.date_until))
        todo = self.env.ref(TODO)
        for approval in self.search([("state", "=", "approved"), ("date_until", "!=", False)]):
            if approval.date_until > today + timedelta(days=max(approval.notify_days, 0)):
                continue
            summary = _("Погодження %(name)s (%(partner)s) діє до %(date)s", name=approval.name,
                        partner=approval.partner_id.display_name, date=approval.ua_date(approval.date_until))
            if approval.activity_ids.filtered(lambda a: a.activity_type_id == todo and a.summary == summary):
                continue
            approval.activity_schedule(TODO, date_deadline=approval.date_until, summary=summary,
                                       user_id=(approval.user_id or self.env.user).id)
        return True


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        Approval = self.env["ua.supplier.approval"]
        for order in self:
            day = fields.Date.context_today(self)
            products = order.order_line.filtered(lambda line: not line.display_type).product_id
            Approval.ua_check(order.partner_id, products, order.company_id, day, order.name)
        return super().button_confirm()


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    ua_supplier_unapproved = fields.Boolean("Постачальник не погоджений", compute="_compute_ua_supplier_unapproved")

    @api.depends("product_id", "order_id.partner_id")
    def _compute_ua_supplier_unapproved(self):
        Approval = self.env["ua.supplier.approval"]
        day = fields.Date.context_today(self)
        for line in self:
            product = line.product_id
            line.ua_supplier_unapproved = bool(
                product.ua_approved_only and line.order_id.partner_id
                and not Approval.ua_find(line.order_id.partner_id, product, line.order_id.company_id, day))


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        Approval = self.env["ua.supplier.approval"]
        for picking in self:
            if picking.location_id.usage != "supplier" or picking.location_dest_id.usage == "supplier":
                continue
            products = picking.move_ids.filtered(lambda m: m.state != "cancel").product_id
            if not products.filtered("ua_approved_only"):
                continue
            if not picking.partner_id:
                raise UserError(_("%s: приймання критичних комплектуючих - вкажіть постачальника.") % picking.name)
            Approval.ua_check(picking.partner_id, products, picking.company_id,
                              fields.Date.context_today(self), picking.name)
        return super()._action_done()
