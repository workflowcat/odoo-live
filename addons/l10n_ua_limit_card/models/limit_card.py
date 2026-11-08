"""Лімітно-забірна картка (типова форма М-8).

Картка - один матеріал, одне місце зберігання цеху, один місяць. Відпуск - проведене переміщення
зі складу в цех; повернення - назад. Відпущено за карткою = відпуски мінус повернення.
Понад ліміт відпускає лише керівник складу і лише з причиною; такий рядок позначається.
Ліміт - вручну або з потреби в матеріалі обраних виробничих замовлень (норми витрат специфікацій).
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class UaLimitCard(models.Model):
    _name = "ua.limit.card"
    _description = "Лімітно-забірна картка"
    _inherit = ["mail.thread"]
    _order = "date_from desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", required=True, copy=False, default="/", readonly=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    date_from = fields.Date("Місяць", required=True, tracking=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date("По", compute="_compute_date_to", store=True)
    product_id = fields.Many2one("product.product", "Матеріал", required=True, tracking=True,
                                 domain="[('is_storable', '=', True)]")
    uom_id = fields.Many2one(related="product_id.uom_id", string="Одиниця")
    location_id = fields.Many2one("stock.location", "Склад", required=True, check_company=True,
                                  domain="[('usage', '=', 'internal')]")
    location_dest_id = fields.Many2one("stock.location", "Цех (отримувач)", required=True, check_company=True,
                                       domain="[('usage', '=', 'internal')]")
    department = fields.Char("Структурний підрозділ")
    purpose = fields.Char("Призначення", help="Шифр затрат, виріб, замовлення.")
    production_ids = fields.Many2many("mrp.production", string="Планові виробничі замовлення",
                                      check_company=True)
    limit_qty = fields.Float("Ліміт", digits="Product Unit", tracking=True)
    line_ids = fields.One2many("ua.limit.card.line", "card_id", "Відпуски")
    issued_qty = fields.Float("Відпущено", digits="Product Unit", compute="_compute_totals", store=True)
    over_qty = fields.Float("Понад ліміт", digits="Product Unit", compute="_compute_totals", store=True)
    remaining_qty = fields.Float("Залишок ліміту", digits="Product Unit", compute="_compute_totals", store=True)
    state = fields.Selection([("draft", "Чернетка"), ("open", "Діє"), ("closed", "Закрито")], "Стан",
                             required=True, default="draft", tracking=True, index=True)

    @api.depends("date_from")
    def _compute_date_to(self):
        for card in self:
            card.date_to = card.date_from and card.date_from + relativedelta(day=31)

    @api.depends("limit_qty", "line_ids.quantity", "line_ids.over_limit")
    def _compute_totals(self):
        for card in self:
            card.issued_qty = sum(card.line_ids.mapped("quantity"))
            card.over_qty = sum(card.line_ids.filtered("over_limit").mapped("quantity"))
            card.remaining_qty = card.limit_qty - card.issued_qty

    @api.constrains("limit_qty")
    def _check_limit(self):
        for card in self:
            if card.limit_qty < 0:
                raise ValidationError(_("Ліміт не може бути від'ємним."))

    @api.constrains("location_id", "location_dest_id")
    def _check_locations(self):
        for card in self:
            if card.location_id == card.location_dest_id:
                raise ValidationError(_("Склад і цех - різні місця зберігання."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.limit.card", sequence_date=vals.get("date_from")) or "/"
        return super().create(vals_list)

    def unlink(self):
        if self.line_ids:
            raise UserError(_("За карткою вже відпускали матеріал: закрийте її, а не видаляйте."))
        return super().unlink()

    def action_fill_from_productions(self):
        """Ліміт = потреба в матеріалі за обраними виробничими замовленнями."""
        for card in self:
            if card.state == "closed":
                raise UserError(_("Картка %s закрита.") % card.name)
            if not card.production_ids:
                raise UserError(_("Оберіть планові виробничі замовлення."))
            moves = card.production_ids.move_raw_ids.filtered(
                lambda m: m.product_id == card.product_id and m.state != "cancel")
            if not moves:
                raise UserError(_("У замовленнях немає потреби в «%s».") % card.product_id.display_name)
            card.limit_qty = sum(m.product_uom._compute_quantity(m.product_uom_qty, card.uom_id) for m in moves)
        return True

    def action_open(self):
        for card in self:
            if card.limit_qty <= 0:
                raise UserError(_("Картка %s: задайте ліміт.") % card.name)
        self.write({"state": "open"})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    def action_reopen(self):
        self.write({"state": "open"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_limit_card.action_report_ua_limit_card").report_action(self)

    def _ua_move(self, source, destination, quantity):
        self.ensure_one()
        move = self.env["stock.move"].sudo().create({
            "product_id": self.product_id.id, "product_uom_qty": quantity, "product_uom": self.uom_id.id,
            "location_id": source.id, "location_dest_id": destination.id, "company_id": self.company_id.id,
            "origin": self.name, "ua_limit_card_id": self.id,
        })
        move._action_confirm()
        move._action_assign()
        if self.uom_id.compare(move.quantity, quantity) < 0:
            raise UserError(_("%(where)s: «%(product)s» є %(have)s, а треба %(need)s.",
                              where=source.display_name, product=self.product_id.display_name,
                              have="%g" % move.quantity, need="%g" % quantity))
        move.picked = True
        move._action_done()
        return move

    def action_issue(self, quantity, reason=None, receiver=None, day=None):
        """Відпустити в цех. Понад ліміт - лише керівник складу з причиною."""
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Картка %s не діє: відпуск неможливий.") % self.name)
        if self.uom_id.compare(quantity, 0.0) <= 0:
            raise UserError(_("Кількість має бути більша за нуль."))
        day = day or fields.Date.context_today(self)
        if not self.date_from <= day <= self.date_to:
            raise UserError(_("Картка %(name)s діє з %(start)s по %(end)s.", name=self.name,
                              start=self.date_from.strftime("%d.%m.%Y"), end=self.date_to.strftime("%d.%m.%Y")))
        over = self.uom_id.compare(quantity, self.remaining_qty) > 0
        if over:
            if not reason:
                raise UserError(_(
                    "%(name)s: просять %(qty)s, а в ліміті лишилось %(left)s. Понадлімітний відпуск - з "
                    "причиною і дозволом керівника складу.", name=self.name, qty="%g" % quantity,
                    left="%g" % self.remaining_qty))
            if not (self.env.su or self.env.user.has_group("stock.group_stock_manager")):
                raise UserError(_("Понадлімітний відпуск дозволяє лише керівник складу."))
        move = self._ua_move(self.location_id, self.location_dest_id, quantity)
        line = self.env["ua.limit.card.line"].sudo().create({
            "card_id": self.id, "date": day, "quantity": quantity, "move_id": move.id, "over_limit": over,
            "reason": reason or False, "receiver": receiver or False, "user_id": self.env.user.id})
        if over:
            self.message_post(body=_("Понадлімітний відпуск %(qty)s: %(reason)s", qty="%g" % quantity, reason=reason))
        return line

    def action_return(self, quantity, day=None):
        """Повернути невикористаний матеріал з цеху на склад."""
        self.ensure_one()
        if self.state == "draft":
            raise UserError(_("Картка %s ще не діє.") % self.name)
        if self.uom_id.compare(quantity, 0.0) <= 0:
            raise UserError(_("Кількість має бути більша за нуль."))
        if self.uom_id.compare(quantity, self.issued_qty) > 0:
            raise UserError(_("Повернути можна не більше відпущеного: %s.") % ("%g" % self.issued_qty))
        move = self._ua_move(self.location_dest_id, self.location_id, quantity)
        return self.env["ua.limit.card.line"].sudo().create({
            "card_id": self.id, "date": day or fields.Date.context_today(self), "quantity": -quantity,
            "move_id": move.id, "user_id": self.env.user.id})

    def ua_rows(self):
        """Рядки друку: дата, відпущено, повернуто, наростаючим підсумком, залишок ліміту."""
        self.ensure_one()
        rows, total = [], 0.0
        for line in self.line_ids.sorted(lambda l: (l.date, l.id)):
            total += line.quantity
            rows.append({
                "date": line.date.strftime("%d.%m.%Y"),
                "issued": "%g" % line.quantity if line.quantity > 0 else "",
                "returned": "%g" % -line.quantity if line.quantity < 0 else "",
                "total": "%g" % total, "left": "%g" % (self.limit_qty - total),
                "note": line.reason or "", "receiver": line.receiver or "",
            })
        return rows

    def ua_month(self):
        self.ensure_one()
        return self.date_from.strftime("%m.%Y")


class UaLimitCardLine(models.Model):
    _name = "ua.limit.card.line"
    _description = "Відпуск за лімітно-забірною карткою"
    _order = "date, id"

    card_id = fields.Many2one("ua.limit.card", "Картка", required=True, index=True, ondelete="cascade")
    date = fields.Date("Дата", required=True)
    quantity = fields.Float("Кількість", digits="Product Unit", help="Повернення - з мінусом.")
    over_limit = fields.Boolean("Понад ліміт")
    reason = fields.Char("Причина")
    receiver = fields.Char("Отримав")
    user_id = fields.Many2one("res.users", "Відпустив")
    move_id = fields.Many2one("stock.move", "Рух", readonly=True)


class StockMove(models.Model):
    _inherit = "stock.move"

    ua_limit_card_id = fields.Many2one("ua.limit.card", "Лімітно-забірна картка", index="btree_not_null",
                                       readonly=True)

    def _compute_reference(self):
        # рух без складського документа: Odoo 19 лишає посилання порожнім
        super()._compute_reference()
        for move in self:
            if not move.reference and move.ua_limit_card_id:
                move.reference = move.ua_limit_card_id.name
