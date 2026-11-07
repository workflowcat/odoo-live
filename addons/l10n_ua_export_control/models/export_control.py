"""Експортний контроль: контрольовані товари, дозволи, перевірка відвантаження.

Товар військового призначення або подвійного використання позначається на виробі з
позицією контрольного списку. Класифікацію робить підприємство за чинними списками;
модуль її не вгадує.

Відвантаження за кордон - вихідне переміщення клієнту, чия країна відрізняється від
країни компанії. Якщо в ньому є контрольований товар, потрібен чинний дозвіл: на цього
контрагента (імпортера), його країну, з цим товаром і залишком кількості. Дозвіл ставиться
на відвантаження сам, якщо підходить рівно один; кілька - обирає людина. Без країни в
контрагента контрольований товар не відвантажується: перевірити нема з чим.

Використано за дозволом - проведені відвантаження з цим дозволом.
"""
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TODO = "mail.mail_activity_data_todo"

CONTROL_KINDS = [("military", "Військового призначення"), ("dual_use", "Подвійного використання")]
PERMIT_KINDS = [
    ("export", "Експорт"),
    ("temporary_export", "Тимчасовий експорт"),
    ("reexport", "Реекспорт"),
    ("other", "Інша передача"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_export_controlled = fields.Boolean(
        "Під експортним контролем", tracking=True,
        help="Товар військового призначення або подвійного використання: відвантаження за кордон лише з дозволом.")
    ua_control_kind = fields.Selection(CONTROL_KINDS, "Категорія контролю")
    ua_control_ref = fields.Char("Позиція контрольного списку",
                                 help="Код позиції в чинному контрольному списку.")


class UaExportPermit(models.Model):
    _name = "ua.export.permit"
    _description = "Дозвіл на міжнародну передачу товарів"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_expiry desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер дозволу", required=True, tracking=True)
    kind = fields.Selection(PERMIT_KINDS, "Вид", required=True, default="export")
    authority = fields.Char("Хто видав", default="Державна служба експортного контролю України")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    partner_id = fields.Many2one("res.partner", "Імпортер", required=True, index=True, tracking=True)
    end_user_id = fields.Many2one("res.partner", "Кінцевий користувач", tracking=True)
    end_use = fields.Char("Кінцеве використання")
    country_id = fields.Many2one("res.country", "Країна призначення", required=True, tracking=True)
    date_issue = fields.Date("Дата видачі", required=True, default=fields.Date.context_today)
    date_expiry = fields.Date("Діє до", required=True, tracking=True)
    state = fields.Selection([("draft", "Чернетка"), ("active", "Діє"), ("closed", "Закрито"),
                              ("expired", "Строк минув")], "Стан", required=True, default="draft",
                             tracking=True, index=True)
    line_ids = fields.One2many("ua.export.permit.line", "permit_id", "Товари", copy=True)
    picking_ids = fields.One2many("stock.picking", "ua_export_permit_id", "Відвантаження")
    user_id = fields.Many2one("res.users", "Відповідальний", default=lambda self: self.env.user)
    notify_days = fields.Integer("Нагадати за, днів", default=30)
    note = fields.Text("Умови дозволу")

    @api.constrains("date_issue", "date_expiry")
    def _check_dates(self):
        for permit in self:
            if permit.date_expiry < permit.date_issue:
                raise ValidationError(_("Дозвіл не може закінчуватися раніше, ніж його видано."))

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id.country_id and not self.country_id:
            self.country_id = self.partner_id.commercial_partner_id.country_id

    def ua_used(self):
        """{виріб: відвантажено} - проведені вихідні переміщення з цим дозволом."""
        self.ensure_one()
        used = defaultdict(float)
        moves = self.env["stock.move"].sudo().search([
            ("picking_id.ua_export_permit_id", "=", self.id), ("state", "=", "done"),
            ("location_dest_id.usage", "=", "customer")])
        for move in moves:
            used[move.product_id] += move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
        return used

    def ua_shipments(self):
        """Рядки звіту: проведені відвантаження з дозволом, за датою."""
        self.ensure_one()
        moves = self.env["stock.move"].sudo().search([
            ("picking_id.ua_export_permit_id", "=", self.id), ("state", "=", "done"),
            ("location_dest_id.usage", "=", "customer")], order="date, id")
        return [{"date": move.date.strftime("%d.%m.%Y"), "picking": move.picking_id.name,
                 "product": move.product_id.display_name,
                 "quantity": "%g" % move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id),
                 "uom": move.product_id.uom_id.name} for move in moves]

    def ua_kind_label(self):
        self.ensure_one()
        return dict(PERMIT_KINDS).get(self.kind, "")

    def ua_date(self, day):
        return day.strftime("%d.%m.%Y") if day else ""

    def _ua_covers(self, partner, country, day):
        self.ensure_one()
        return (self.state == "active" and self.partner_id.commercial_partner_id == partner
                and self.country_id == country and self.date_issue <= day <= self.date_expiry)

    def action_activate(self):
        today = fields.Date.context_today(self)
        for permit in self:
            if not permit.line_ids:
                raise UserError(_("У дозволі %s немає товарів.") % permit.name)
            if permit.date_expiry < today:
                raise UserError(_("Строк дозволу %s уже минув.") % permit.name)
        self.write({"state": "active"})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        self.activity_unlink([TODO])
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_export_control.action_report_ua_export_permit").report_action(self)

    @api.model
    def _cron_reminders(self):
        today = fields.Date.context_today(self)
        for permit in self.search([("state", "=", "active"), ("date_expiry", "<", today)]):
            permit.write({"state": "expired"})
            permit.message_post(body=_("Строк дозволу минув %s.") % permit.date_expiry.strftime("%d.%m.%Y"))
        todo = self.env.ref(TODO)
        for permit in self.search([("state", "=", "active")]):
            if permit.date_expiry > today + timedelta(days=max(permit.notify_days, 0)):
                continue
            summary = _("Дозвіл %(name)s діє до %(date)s",
                        name=permit.name, date=permit.date_expiry.strftime("%d.%m.%Y"))
            if permit.activity_ids.filtered(lambda a: a.activity_type_id == todo and a.summary == summary):
                continue
            permit.activity_schedule(TODO, date_deadline=permit.date_expiry, summary=summary,
                                     user_id=(permit.user_id or self.env.user).id)
        return True


class UaExportPermitLine(models.Model):
    _name = "ua.export.permit.line"
    _description = "Товар у дозволі на міжнародну передачу"
    _order = "permit_id, id"

    permit_id = fields.Many2one("ua.export.permit", "Дозвіл", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", "Товар", required=True)
    control_ref = fields.Char(related="product_id.ua_control_ref", string="Позиція списку")
    quantity = fields.Float("Кількість", required=True, digits="Product Unit")
    uom_id = fields.Many2one(related="product_id.uom_id", string="Одиниця")
    currency_id = fields.Many2one("res.currency", "Валюта")
    amount = fields.Monetary("Вартість за дозволом")
    used_qty = fields.Float("Відвантажено", compute="_compute_used", digits="Product Unit")
    remaining_qty = fields.Float("Залишок", compute="_compute_used", digits="Product Unit")

    _product_uniq = models.Constraint("UNIQUE(permit_id, product_id)", "Товар у дозволі - одним рядком.")

    def _compute_used(self):
        cache = {}
        for line in self:
            permit = line.permit_id
            if not isinstance(permit.id, int):
                line.used_qty, line.remaining_qty = 0.0, line.quantity
                continue
            if permit not in cache:
                cache[permit] = permit.ua_used()
            used = cache[permit].get(line.product_id, 0.0)
            line.used_qty = used
            line.remaining_qty = line.quantity - used

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Кількість у дозволі має бути більша за нуль."))


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ua_export_permit_id = fields.Many2one(
        "ua.export.permit", "Дозвіл на передачу", index="btree_not_null", copy=False, tracking=True,
        check_company=True, domain="[('state', '=', 'active')]")
    ua_export_needed = fields.Boolean("Потрібен дозвіл", compute="_compute_ua_export_needed")

    def _ua_is_export(self):
        self.ensure_one()
        return self.picking_type_code == "outgoing" and self.location_dest_id.usage == "customer"

    def _ua_controlled_moves(self):
        return self.move_ids.filtered(lambda m: m.state != "cancel" and m.product_id.ua_export_controlled)

    @api.depends("partner_id", "move_ids.product_id", "picking_type_id")
    def _compute_ua_export_needed(self):
        for picking in self:
            country = picking.partner_id.commercial_partner_id.country_id
            picking.ua_export_needed = bool(
                picking._ua_is_export() and picking._ua_controlled_moves()
                and country != picking.company_id.country_id)

    def _ua_check_export(self):
        """Перед проведенням: дозвіл на кожен контрольований товар відвантаження за кордон."""
        today = fields.Date.context_today(self)
        pending = defaultdict(float)  # кілька відвантажень за одним дозволом в одному проведенні
        for picking in self.filtered(lambda p: p._ua_is_export()):
            moves = picking._ua_controlled_moves()
            if not moves:
                continue
            partner = picking.partner_id.commercial_partner_id
            country = partner.country_id
            if not country:
                raise UserError(_(
                    "%(picking)s: «%(products)s» під експортним контролем, а в контрагента %(partner)s не "
                    "вказано країну. Заповніть країну.", picking=picking.name,
                    products=", ".join(moves.product_id.mapped("display_name")), partner=partner.display_name))
            if country == picking.company_id.country_id:
                continue
            need = defaultdict(float)
            for move in moves:
                need[move.product_id] += move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            permit = picking.ua_export_permit_id
            if not permit:
                candidates = self.env["ua.export.permit"].search([
                    ("company_id", "=", picking.company_id.id), ("state", "=", "active"),
                    ("country_id", "=", country.id)]).filtered(
                    lambda p: p._ua_covers(partner, country, today)
                    and set(need) <= set(p.line_ids.product_id))
                if len(candidates) > 1:
                    raise UserError(_("%(picking)s: підходять кілька дозволів (%(names)s). Оберіть дозвіл у "
                                      "відвантаженні.", picking=picking.name,
                                      names=", ".join(candidates.mapped("name"))))
                permit = candidates
            if not permit:
                raise UserError(_(
                    "%(picking)s: немає чинного дозволу на передачу «%(products)s» контрагенту %(partner)s "
                    "(%(country)s). Відвантаження товарів під експортним контролем за кордон - лише за дозволом.",
                    picking=picking.name, products=", ".join(p.display_name for p in need),
                    partner=partner.display_name, country=country.name))
            if not permit._ua_covers(partner, country, today):
                raise UserError(_("%(picking)s: дозвіл %(permit)s не діє для %(partner)s (%(country)s) на сьогодні.",
                                  picking=picking.name, permit=permit.name, partner=partner.display_name,
                                  country=country.name))
            permit.line_ids.invalidate_recordset(["used_qty", "remaining_qty"])
            lines = {line.product_id: line for line in permit.line_ids}
            for product, quantity in need.items():
                line = lines.get(product)
                if not line:
                    raise UserError(_("%(picking)s: «%(product)s» немає в дозволі %(permit)s.",
                                      picking=picking.name, product=product.display_name, permit=permit.name))
                left = line.remaining_qty - pending[line]
                if product.uom_id.compare(quantity, left) > 0:
                    raise UserError(_(
                        "%(picking)s: «%(product)s» відвантажується %(qty)s, а за дозволом %(permit)s лишилось "
                        "%(left)s.", picking=picking.name, product=product.display_name, qty="%g" % quantity,
                        permit=permit.name, left="%g" % left))
                pending[line] += quantity
            if picking.ua_export_permit_id != permit:
                picking.ua_export_permit_id = permit

    def _action_done(self):
        self._ua_check_export()
        return super()._action_done()
