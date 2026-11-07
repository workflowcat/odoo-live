"""Замовлення на переробку давальницької сировини.

Давалець (замовник) передає сировину, ми виготовляємо з неї продукцію і повертаємо її разом
із невикористаним залишком; платить давалець лише за переробку. Сировина весь час належить
йому: в обліку це позабалансовий рахунок 023, а не запаси.

У складі Odoo це так:

- у кожного давальця на складі своє місце зберігання поруч зі «Складом» (не всередині нього):
  інші замовлення на виробництво і відвантаження його сировину не бачать;
- прихід туди йде з власником = давалець (`owner_id`): Odoo не оцінює чужий товар, тож ні
  вартості, ні проводки на 20 не виникає;
- у виробничому замовленні переробки давальницькі компоненти списуються з місця давальця,
  власні (кріплення, фарба) - зі складу, як звичайно;
- готова продукція йде на склад і відвантажується давальцю; рахунок - за послугу переробки.

Звіт переробника рахує по кожному матеріалу: отримано, норма на випущену кількість за
специфікацією, фактично витрачено, відхилення від норми, повернено, залишок.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("open", "У роботі"), ("done", "Завершено"),
          ("cancel", "Скасовано")]


class UaTollingOrder(models.Model):
    _name = "ua.tolling.order"
    _description = "Замовлення на переробку давальницької сировини"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    partner_id = fields.Many2one("res.partner", "Давалець", required=True, tracking=True,
                                 check_company=True)
    contract_id = fields.Many2one(
        "ua.contract", "Договір", check_company=True, tracking=True,
        domain="[('partner_id', '=', partner_id), ('kind', '=', 'sale')]")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True,
                             copy=False)
    warehouse_id = fields.Many2one(
        "stock.warehouse", "Склад", required=True, check_company=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1))
    location_id = fields.Many2one("stock.location", "Місце зберігання сировини", readonly=True,
                                  copy=False, check_company=True)

    product_id = fields.Many2one("product.product", "Продукція", required=True,
                                 check_company=True, domain="[('is_storable', '=', True)]")
    product_qty = fields.Float("Кількість", required=True, default=1.0, digits="Product Unit")
    product_uom_id = fields.Many2one(related="product_id.uom_id", string="Одиниця")
    bom_id = fields.Many2one("mrp.bom", "Специфікація", check_company=True,
                             compute="_compute_bom_id", store=True, readonly=False,
                             domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id")
    price_unit = fields.Monetary("Ціна переробки за одиницю", currency_field="currency_id",
                                 tracking=True)
    note = fields.Text("Примітка")

    line_ids = fields.One2many("ua.tolling.order.line", "order_id", "Давальницька сировина",
                               copy=True)
    picking_ids = fields.One2many("stock.picking", "ua_tolling_id", "Переміщення")
    production_ids = fields.One2many("mrp.production", "ua_tolling_id", "Виробничі замовлення")
    invoice_ids = fields.One2many("account.move", "ua_tolling_id", "Рахунки")

    qty_produced = fields.Float("Виготовлено", compute="_compute_quantities", digits="Product Unit")
    qty_delivered = fields.Float("Передано давальцю", compute="_compute_quantities",
                                 digits="Product Unit")
    qty_invoiced = fields.Float("Виставлено рахунків", compute="_compute_quantities",
                                digits="Product Unit")
    picking_count = fields.Integer(compute="_compute_counts")
    production_count = fields.Integer(compute="_compute_counts")
    invoice_count = fields.Integer(compute="_compute_counts")

    _name_company_uniq = models.Constraint("unique(name, company_id)",
                                           "Номер замовлення на переробку вже є.")
    _qty_positive = models.Constraint("CHECK (product_qty > 0)",
                                      "Кількість продукції має бути більшою за нуль.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.tolling.order") or "/"
        return super().create(vals_list)

    @api.depends("product_id", "company_id")
    def _compute_bom_id(self):
        for order in self:
            if order.product_id and not order.bom_id:
                order.bom_id = self.env["mrp.bom"]._bom_find(
                    order.product_id, company_id=order.company_id.id,
                    bom_type="normal")[order.product_id]

    # ------------------------------------------------------------------ кількості
    def _uom_qty(self, move):
        return move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)

    def _done_moves(self):
        self.ensure_one()
        return (self.picking_ids.move_ids | self.production_ids.move_raw_ids
                | self.production_ids.move_finished_ids).filtered(lambda m: m.state == "done")

    @api.depends("picking_ids.state", "production_ids.state", "invoice_ids.state")
    def _compute_quantities(self):
        for order in self:
            moves = order._done_moves() if order.id else self.env["stock.move"]
            finished = moves.filtered(lambda m: m.product_id == order.product_id)
            order.qty_produced = sum(order._uom_qty(m) for m in finished
                                     if m.production_id and m.location_dest_id.usage == "internal")
            out = sum(order._uom_qty(m) for m in finished
                      if m.picking_id and m.location_dest_id.usage == "customer")
            back = sum(order._uom_qty(m) for m in finished
                       if m.picking_id and m.location_id.usage == "customer")
            order.qty_delivered = out - back
            lines = order.invoice_ids.filtered(lambda i: i.state == "posted").invoice_line_ids
            order.qty_invoiced = sum(line.quantity * (-1 if line.move_id.move_type == "out_refund"
                                                      else 1)
                                     for line in lines if line.ua_tolling_qty)

    def _compute_counts(self):
        for order in self:
            order.picking_count = len(order.picking_ids)
            order.production_count = len(order.production_ids)
            order.invoice_count = len(order.invoice_ids)

    def material_rows(self):
        """Рядки звіту переробника по кожному матеріалу давальця.

        received, consumed, returned, balance, norm (витрата за специфікацією на виготовлену
        кількість), deviation (витрачено мінус норма; плюс - перевитрата)."""
        self.ensure_one()
        received, consumed, returned = defaultdict(float), defaultdict(float), defaultdict(float)
        location = self.location_id
        for move in self._done_moves():
            qty = self._uom_qty(move)
            product = move.product_id
            if move.location_dest_id == location and move.location_id.usage == "customer":
                received[product] += qty
            elif move.location_id == location and move.location_dest_id.usage == "customer":
                returned[product] += qty
            elif move.location_id == location and move.raw_material_production_id:
                consumed[product] += qty
            elif move.location_dest_id == location and move.raw_material_production_id:
                consumed[product] -= qty  # повернення з виробництва
        norm = self._norm(self.qty_produced)
        rows = []
        for line in self.line_ids:
            product = line.product_id
            row = {
                "product": product, "uom": product.uom_id, "planned": line.product_qty,
                "received": received[product], "consumed": consumed[product],
                "returned": returned[product], "norm": norm.get(product, 0.0),
            }
            row["balance"] = row["received"] - row["consumed"] - row["returned"]
            row["deviation"] = row["consumed"] - row["norm"]
            rows.append(row)
        return rows

    def _norm(self, quantity):
        """{матеріал: витрата за специфікацією на `quantity` одиниць продукції}."""
        self.ensure_one()
        if not self.bom_id or not quantity:
            return {}
        bom_qty = self.product_id.uom_id._compute_quantity(quantity, self.bom_id.product_uom_id)
        _boms, lines = self.bom_id.explode(self.product_id, bom_qty / self.bom_id.product_qty)
        result = defaultdict(float)
        for bom_line, data in lines:
            result[bom_line.product_id] += bom_line.product_uom_id._compute_quantity(
                data["qty"], bom_line.product_id.uom_id)
        return result

    # ------------------------------------------------------------------ дії
    def action_fill_from_bom(self):
        """Сировина давальця за специфікацією на всю кількість. Власні матеріали з переліку
        видаляють руками: тут лише те, що передає давалець."""
        for order in self:
            if order.state != "draft":
                raise UserError(_("Перелік сировини заповнюють у чернетці."))
            if not order.bom_id:
                raise UserError(_("У продукції «%s» немає специфікації.")
                                % order.product_id.display_name)
            norm = order._norm(order.product_qty)
            order.line_ids = [(5, 0, 0)] + [
                (0, 0, {"product_id": product.id, "product_qty": qty})
                for product, qty in norm.items() if product.is_storable]
        return True

    def _ua_location(self):
        """Місце зберігання давальця на складі: поруч зі «Складом», не всередині нього."""
        self.ensure_one()
        Location = self.env["stock.location"].sudo()
        parent = self.warehouse_id.view_location_id
        location = Location.search([("location_id", "=", parent.id),
                                    ("ua_tolling_partner_id", "=", self.partner_id.id)], limit=1)
        if not location:
            location = Location.create({
                "name": _("Давальницька: %s") % self.partner_id.display_name,
                "location_id": parent.id, "usage": "internal",
                "company_id": self.company_id.id,
                "ua_tolling_partner_id": self.partner_id.id,
            })
        return location.sudo(False)

    def action_confirm(self):
        for order in self:
            if order.state != "draft":
                continue
            if not order.line_ids:
                raise UserError(_("Додайте сировину давальця (кнопка «За специфікацією»)."))
            order.write({"state": "open", "location_id": order._ua_location().id})
        return True

    def _check_open(self):
        for order in self:
            if order.state != "open":
                raise UserError(_("Замовлення %s не в роботі.") % order.name)

    def _picking(self, picking_type, source, destination, items, owner=True):
        self.ensure_one()
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "partner_id": self.partner_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "owner_id": self.partner_id.id if owner else False,
            "origin": self.name,
            "ua_tolling_id": self.id,
            "company_id": self.company_id.id,
            "move_ids": [(0, 0, {
                "product_id": product.id, "product_uom_qty": qty,
                "product_uom": product.uom_id.id, "location_id": source.id,
                "location_dest_id": destination.id, "company_id": self.company_id.id,
                "restrict_partner_id": self.partner_id.id if owner else False,
            }) for product, qty in items],
        })
        picking.action_confirm()
        if picking_type.code == "outgoing":
            picking.action_assign()
        return picking

    def _open_record(self, record):
        return {"type": "ir.actions.act_window", "res_model": record._name, "res_id": record.id,
                "view_mode": "form", "target": "current"}

    def action_receive(self):
        """Прийом сировини: на місце давальця, з давальцем як власником."""
        self.ensure_one()
        self._check_open()
        rows = {row["product"]: row for row in self.material_rows()}
        pending = self.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel") and p.location_dest_id == self.location_id
        ).move_ids
        items = []
        for line in self.line_ids:
            waiting = sum(pending.filtered(lambda m: m.product_id == line.product_id)
                          .mapped("product_uom_qty"))
            qty = line.product_qty - rows[line.product_id]["received"] - waiting
            if qty > 0:
                items.append((line.product_id, qty))
        if not items:
            raise UserError(_("Уся сировина за замовленням уже надійшла або чекає приходу."))
        customers = self.env.ref("stock.stock_location_customers")
        picking = self._picking(self.warehouse_id.in_type_id, customers, self.location_id, items)
        return self._open_record(picking)

    def action_produce(self):
        """Виробниче замовлення на ще не виготовлену кількість: давальницькі компоненти - з
        місця давальця, власні - зі складу."""
        self.ensure_one()
        self._check_open()
        if not self.bom_id:
            raise UserError(_("У продукції «%s» немає специфікації.") % self.product_id.display_name)
        running = sum(self.production_ids.filtered(
            lambda p: p.state not in ("done", "cancel")).mapped("product_qty"))
        qty = self.product_qty - self.qty_produced - running
        if qty <= 0:
            raise UserError(_("Уся кількість уже виготовлена або у виробництві."))
        production = self.env["mrp.production"].create({
            "product_id": self.product_id.id, "product_qty": qty, "bom_id": self.bom_id.id,
            "product_uom_id": self.product_id.uom_id.id,
            "picking_type_id": self.warehouse_id.manu_type_id.id,
            "company_id": self.company_id.id, "origin": self.name, "ua_tolling_id": self.id,
        })
        supplied = self.line_ids.product_id
        production.move_raw_ids.filtered(lambda m: m.product_id in supplied).write({
            "location_id": self.location_id.id})
        production.action_confirm()
        production.action_assign()
        return self._open_record(production)

    def action_deliver(self):
        """Відвантаження готової продукції давальцю."""
        self.ensure_one()
        self._check_open()
        pending = sum(self.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel") and p.picking_type_id.code == "outgoing"
        ).move_ids.filtered(lambda m: m.product_id == self.product_id).mapped("product_uom_qty"))
        qty = self.qty_produced - self.qty_delivered - pending
        if qty <= 0:
            raise UserError(_("Немає виготовленої продукції, яку ще не передано давальцю."))
        customers = self.env.ref("stock.stock_location_customers")
        picking = self._picking(self.warehouse_id.out_type_id, self.warehouse_id.lot_stock_id,
                                customers, [(self.product_id, qty)], owner=False)
        return self._open_record(picking)

    def action_return_materials(self):
        """Повернення невикористаної сировини давальцю."""
        self.ensure_one()
        self._check_open()
        pending = self.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel") and p.location_id == self.location_id
        ).move_ids
        items = []
        for row in self.material_rows():
            waiting = sum(pending.filtered(lambda m: m.product_id == row["product"])
                          .mapped("product_uom_qty"))
            qty = row["balance"] - waiting
            if qty > 0:
                items.append((row["product"], qty))
        if not items:
            raise UserError(_("Залишку сировини давальця за цим замовленням немає."))
        customers = self.env.ref("stock.stock_location_customers")
        picking = self._picking(self.warehouse_id.out_type_id, self.location_id, customers, items)
        return self._open_record(picking)

    def _service_taxes(self):
        product = self.env.ref("l10n_ua_tolling.product_tolling_service")
        taxes = product.taxes_id.filtered(lambda t: t.company_id == self.company_id)
        return taxes or self.company_id.account_sale_tax_id

    def action_invoice(self):
        """Рахунок за переробку на виготовлену, ще не виставлену кількість."""
        self.ensure_one()
        if self.state not in ("open", "done"):
            raise UserError(_("Рахунок виставляють за замовленням у роботі."))
        qty = self.qty_produced - self.qty_invoiced - sum(
            self.invoice_ids.filtered(lambda i: i.state == "draft").invoice_line_ids
            .filtered("ua_tolling_qty").mapped("quantity"))
        if qty <= 0:
            raise UserError(_("Немає виготовленої продукції без рахунку."))
        service = self.env.ref("l10n_ua_tolling.product_tolling_service")
        vals = {
            "move_type": "out_invoice", "partner_id": self.partner_id.id,
            "company_id": self.company_id.id, "invoice_origin": self.name,
            "ua_tolling_id": self.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": service.id, "quantity": qty, "price_unit": self.price_unit,
                "name": _("Переробка давальницької сировини: %(product)s, замовлення %(order)s",
                          product=self.product_id.display_name, order=self.name),
                "tax_ids": [(6, 0, self._service_taxes().ids)],
                "ua_tolling_qty": True,
            })],
        }
        if self.contract_id and "ua_contract_id" in self.env["account.move"]._fields:
            vals["ua_contract_id"] = self.contract_id.id
        invoice = self.env["account.move"].with_company(self.company_id).create(vals)
        return self._open_record(invoice)

    def action_done(self):
        for order in self:
            order._check_open()
            def still_open(records):
                return records.filtered(lambda r: r.state not in ("done", "cancel"))

            names = still_open(order.picking_ids).mapped("name") \
                + still_open(order.production_ids).mapped("name")
            if names:
                raise UserError(_("Спершу завершіть або скасуйте: %s.") % ", ".join(names))
            left = [row for row in order.material_rows()
                    if row["product"].uom_id.compare(row["balance"], 0.0) > 0]
            if left:
                raise UserError(_("У давальця лишається сировина: %s. Поверніть її (кнопка "
                                  "«Повернути залишок») - вона не наша.") % ", ".join(
                    "%s %s %s" % (row["product"].display_name, row["balance"], row["uom"].name)
                    for row in left))
            order.state = "done"
        return True

    def action_cancel(self):
        for order in self:
            if order._done_moves():
                raise UserError(_("За замовленням %s уже є проведені переміщення - скасувати "
                                  "можна лише чернетку або замовлення без руху.") % order.name)
            for records in (order.production_ids, order.picking_ids):
                records.filtered(lambda r: r.state not in ("done", "cancel")).action_cancel()
            order.state = "cancel"
        return True

    def action_draft(self):
        self.filtered(lambda o: o.state == "cancel").state = "draft"
        return True

    def _open_list(self, records, name):
        return {"type": "ir.actions.act_window", "res_model": records._name, "name": name,
                "domain": [("id", "in", records.ids)], "view_mode": "list,form"}

    def action_open_pickings(self):
        return self._open_list(self.picking_ids, _("Переміщення"))

    def action_open_productions(self):
        return self._open_list(self.production_ids, _("Виробничі замовлення"))

    def action_open_invoices(self):
        return self._open_list(self.invoice_ids, _("Рахунки"))

    def action_print(self):
        return self.env.ref("l10n_ua_tolling.action_report_ua_tolling").report_action(self)

    def unlink(self):
        if any(order.state not in ("draft", "cancel") for order in self):
            raise UserError(_("Видалити можна лише чернетку або скасоване замовлення."))
        return super().unlink()


class UaTollingOrderLine(models.Model):
    _name = "ua.tolling.order.line"
    _description = "Сировина замовлення на переробку"
    _order = "order_id, id"

    order_id = fields.Many2one("ua.tolling.order", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="order_id.company_id", store=True)
    product_id = fields.Many2one("product.product", "Матеріал", required=True,
                                 domain="[('is_storable', '=', True)]")
    product_qty = fields.Float("Передає давалець", required=True, digits="Product Unit")
    product_uom_id = fields.Many2one(related="product_id.uom_id", string="Одиниця")

    _product_uniq = models.Constraint("unique(order_id, product_id)",
                                      "Матеріал уже є в переліку сировини.")


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    ua_tolling_qty = fields.Boolean(
        "Кількість переробки", copy=True,
        help="Рядок рахунку за переробку: його кількість - виготовлена продукція замовлення.")
