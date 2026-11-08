"""Типи цін і документ «Встановлення цін».

Тип цін - це прайс-лист з видом (роздрібна, оптова, закупівельна), націнкою від собівартості і
правилом округлення. Ціна товару в типі - фіксована ціна прайс-листа з датою початку: документ
створює нову з дати документа і закриває попередню на секунду раніше, тож ціна на будь-яку дату
видна з історії. Ціну з пізнішої дати документ не перекриває: спершу скасуйте той документ.
"""
import math
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_round

KINDS = [("retail", "Роздрібна"), ("wholesale", "Оптова"), ("purchase", "Закупівельна"), ("other", "Інша")]
ROUNDING = [("0.01", "До копійки"), ("0.1", "До 10 копійок"), ("1", "До гривні"), ("5", "До 5 гривень"),
            ("10", "До 10 гривень"), ("99", "Вгору до ,99")]
STATES = [("draft", "Чернетка"), ("done", "Проведено"), ("cancel", "Скасовано")]


def ua_round_price(price, rule):
    """Округлення ціни за правилом типу цін."""
    if not rule or price <= 0:
        return float_round(price, precision_digits=2)
    if rule == "99":
        return float_round(math.ceil(float_round(price, precision_digits=2) + 0.01) - 0.01, precision_digits=2)
    return float_round(float_round(price, precision_rounding=float(rule), rounding_method="HALF-UP"),
                       precision_digits=2)


def _start(day):
    return datetime.combine(day, time.min)


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    ua_price_kind = fields.Selection(KINDS, "Вид ціни")
    ua_markup = fields.Float("Націнка від собівартості, %", digits=(16, 2))
    ua_rounding = fields.Selection(ROUNDING, "Округлення", default="0.01")


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    ua_price_order_id = fields.Many2one("ua.price.order", "Встановлення цін", readonly=True, index=True,
                                        ondelete="set null")


class UaPriceOrder(models.Model):
    _name = "ua.price.order"
    _description = "Встановлення цін"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", default="/", copy=False, readonly=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    date = fields.Date("Ціни діють з", required=True, default=fields.Date.context_today, tracking=True)
    pricelist_ids = fields.Many2many("product.pricelist", string="Типи цін", required=True, check_company=True)
    basis = fields.Char("Підстава", help="Наказ, зміна закупівельних цін, акція.")
    categ_id = fields.Many2one("product.category", "Категорія для заповнення")
    picking_id = fields.Many2one("stock.picking", "Надходження для заповнення", check_company=True,
                                 domain="[('picking_type_code', '=', 'incoming'), ('state', '=', 'done')]")
    line_ids = fields.One2many("ua.price.order.line", "order_id", "Ціни", copy=True)
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True)
    responsible_id = fields.Many2one("res.users", "Відповідальний", default=lambda self: self.env.user)
    note = fields.Text("Примітка")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.price.order") or "/"
        return super().create(vals_list)

    # ------------------------------------------------------------------ заповнення
    def _ua_add_products(self, products):
        self.ensure_one()
        have = {(line.pricelist_id.id, line.product_id.id) for line in self.line_ids}
        vals = [{"pricelist_id": pricelist.id, "product_id": product.id}
                for pricelist in self.pricelist_ids for product in products
                if (pricelist.id, product.id) not in have]
        self.line_ids = [(0, 0, v) for v in vals]
        self.line_ids._ua_fill_old()

    def _ua_check_draft(self):
        if any(order.state != "draft" for order in self):
            raise UserError(_("Змінювати можна лише чернетку."))
        if any(not order.pricelist_ids for order in self):
            raise UserError(_("Оберіть типи цін."))

    def action_fill_category(self):
        self._ua_check_draft()
        for order in self:
            if not order.categ_id:
                raise UserError(_("Оберіть категорію."))
            products = self.env["product.product"].search([("categ_id", "child_of", order.categ_id.id),
                                                           ("sale_ok", "=", True)], order="default_code, name")
            order._ua_add_products(products)
        return True

    def action_fill_picking(self):
        self._ua_check_draft()
        for order in self:
            if not order.picking_id:
                raise UserError(_("Оберіть надходження."))
            order._ua_add_products(order.picking_id.move_ids.product_id)
        return True

    def action_fill_pricelist(self):
        """Товари, які вже мають ціну в обраних типах цін."""
        self._ua_check_draft()
        for order in self:
            items = self.env["product.pricelist.item"].search([
                ("pricelist_id", "in", order.pricelist_ids.ids), ("compute_price", "=", "fixed"),
                ("applied_on", "in", ("0_product_variant", "1_product"))])
            products = items.product_id | items.filtered(lambda i: not i.product_id).product_tmpl_id.product_variant_ids
            order._ua_add_products(products.sorted(lambda p: (p.default_code or "", p.name)))
        return True

    def action_compute(self):
        """Нова ціна = собівартість x (1 + націнка типу) з округленням типу."""
        self._ua_check_draft()
        for line in self.line_ids:
            if line.cost > 0:
                line.new_price = ua_round_price(line.cost * (1 + line.pricelist_id.ua_markup / 100.0),
                                                line.pricelist_id.ua_rounding)
        return True

    # ------------------------------------------------------------------ проведення
    def _ua_check_rights(self):
        if not (self.env.su or self.env.user.has_group("stock.group_stock_manager")):
            raise AccessError(_("Встановлювати ціни може лише керівник складу або комерційний директор."))

    def action_done(self):
        self._ua_check_rights()
        Item = self.env["product.pricelist.item"].sudo()
        for order in self:
            order._ua_check_draft()
            lines = order.line_ids.filtered(lambda l: l.new_price > 0)
            if not lines:
                raise UserError(_("Немає нових цін."))
            start = _start(order.date)
            for line in lines:
                later = line._ua_items().filtered(lambda i: i.date_start and i.date_start > start)
                if later:
                    raise UserError(_("%(product)s: у типі «%(pricelist)s» уже є ціна з %(date)s. Спершу "
                                      "скасуйте той документ.", product=line.product_id.display_name,
                                      pricelist=line.pricelist_id.name,
                                      date=fields.Date.to_string(later[:1].date_start.date())))
            for line in lines:
                previous = line._ua_items().filtered(
                    lambda i: (not i.date_start or i.date_start <= start) and (not i.date_end or i.date_end >= start))
                same_day = previous.filtered(lambda i: i.date_start == start)
                if same_day:
                    raise UserError(_("%(product)s: ціна з цієї дати в типі «%(pricelist)s» вже встановлена.",
                                      product=line.product_id.display_name, pricelist=line.pricelist_id.name))
                prev = previous.sorted(lambda i: i.date_start or datetime.min)[-1:]
                line.write({"prev_item_id": prev.id, "prev_date_end": prev.date_end})
                if prev:
                    prev.date_end = start - timedelta(seconds=1)
                item = Item.create({
                    "pricelist_id": line.pricelist_id.id, "applied_on": "0_product_variant",
                    "product_id": line.product_id.id, "product_tmpl_id": line.product_id.product_tmpl_id.id,
                    "compute_price": "fixed", "fixed_price": line.new_price, "date_start": start,
                    "ua_price_order_id": order.id})
                line.item_id = item
            order.state = "done"
        return True

    def action_cancel(self):
        """Скасувати: прибрати ціни документа і повернути попереднім їхній кінець."""
        self._ua_check_rights()
        for order in self:
            if order.state != "done":
                raise UserError(_("Скасувати можна проведений документ."))
            for line in order.line_ids.filtered("item_id"):
                newer = line._ua_items().filtered(lambda i: i.date_start and i.date_start > line.item_id.date_start)
                if newer:
                    raise UserError(_("%s: після цього документа ціну вже змінено. Спершу скасуйте новіший.")
                                    % line.product_id.display_name)
            for line in order.line_ids.filtered("item_id"):
                line.item_id.sudo().unlink()
                if line.prev_item_id:
                    line.prev_item_id.sudo().date_end = line.prev_date_end
            order.state = "cancel"
        return True

    def action_draft(self):
        for order in self:
            if order.state != "cancel":
                raise UserError(_("У чернетку повертають скасований документ."))
        self.write({"state": "draft"})
        self.line_ids.write({"item_id": False, "prev_item_id": False, "prev_date_end": False})
        return True

    def action_labels(self):
        self.ensure_one()
        products = self.line_ids.filtered(lambda l: l.new_price > 0).product_id
        retail = self.pricelist_ids.filtered(lambda p: p.ua_price_kind == "retail")[:1] or self.pricelist_ids[:1]
        return {"type": "ir.actions.act_window", "res_model": "ua.price.label.wizard", "view_mode": "form",
                "target": "new", "name": _("Цінники"),
                "context": {"active_model": "product.product", "active_ids": products.ids,
                            "default_pricelist_id": retail.id}}

    def action_print(self):
        return self.env.ref("l10n_ua_price_set.action_report_ua_price_order").report_action(self)

    def ua_date(self, day):
        return day.strftime("%d.%m.%Y") if day else ""

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if any(order.state == "done" for order in self):
            raise UserError(_("Проведене встановлення цін не видаляють: скасуйте його."))


class UaPriceOrderLine(models.Model):
    _name = "ua.price.order.line"
    _description = "Рядок встановлення цін"
    _order = "pricelist_id, product_id, id"

    order_id = fields.Many2one("ua.price.order", required=True, index=True, ondelete="cascade")
    state = fields.Selection(related="order_id.state")
    pricelist_id = fields.Many2one("product.pricelist", "Тип цін", required=True)
    currency_id = fields.Many2one(related="pricelist_id.currency_id")
    product_id = fields.Many2one("product.product", "Товар", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id")
    cost = fields.Float("Собівартість", digits="Product Price", readonly=True)
    old_price = fields.Float("Була ціна", digits="Product Price", readonly=True)
    new_price = fields.Float("Нова ціна", digits="Product Price")
    markup = fields.Float("Націнка, %", compute="_compute_change", digits=(16, 2))
    change = fields.Float("Зміна, %", compute="_compute_change", digits=(16, 2))
    item_id = fields.Many2one("product.pricelist.item", "Ціна в прайс-листі", readonly=True, copy=False)
    prev_item_id = fields.Many2one("product.pricelist.item", "Попередня ціна", readonly=True, copy=False)
    prev_date_end = fields.Datetime("Попередня діяла до", readonly=True, copy=False)

    @api.depends("cost", "old_price", "new_price")
    def _compute_change(self):
        for line in self:
            line.markup = (line.new_price / line.cost - 1) * 100.0 if line.cost and line.new_price else 0.0
            line.change = (line.new_price / line.old_price - 1) * 100.0 if line.old_price and line.new_price else 0.0

    def _ua_fill_old(self):
        """Собівартість і чинна ціна на день перед датою документа."""
        for line in self:
            moment = _start(line.order_id.date) - timedelta(seconds=1)
            line.write({"cost": line.product_id.standard_price,
                        "old_price": line.pricelist_id._get_product_price(line.product_id, 1.0, date=moment)})

    def _ua_items(self):
        """Фіксовані ціни саме цього товару в цьому типі цін."""
        self.ensure_one()
        return self.env["product.pricelist.item"].sudo().search([
            ("pricelist_id", "=", self.pricelist_id.id), ("compute_price", "=", "fixed"),
            ("applied_on", "=", "0_product_variant"), ("product_id", "=", self.product_id.id)])

    def ua_changed(self):
        self.ensure_one()
        return float_compare(self.new_price, self.old_price, precision_digits=2) != 0
