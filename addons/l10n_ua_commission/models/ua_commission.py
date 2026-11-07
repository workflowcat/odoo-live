"""Комісійна торгівля (договір комісії, глава 69 ЦКУ) і товар на реалізацію.

Дві ролі компанії:

in  - компанія комісіонер. Товар комітента приходить на «Склад» з власником-комітентом
      (`owner_id`): Odoo не оцінює чужий товар, тож ні вартості запасів, ні проводки на 28
      немає. Продається він звичайними замовленнями: склад сам резервує чужі залишки.
      Звіт комітенту за період бере проведені відвантаження покупцям, де власник - комітент,
      і, коли його проведуть, створює:
        * рахунок від комітента на продане (виручка - його, не компанії);
        * рахунок комітенту на винагороду (відсоток від продажу);
        * взаємозалік між ними: комітенту лишається сплатити виручку мінус винагороду.
      Рядки рахунку від комітента йдуть на «рахунок виручки комітента»: за замовчуванням це
      рахунок доходу товару, тож дохід від чужого товару згортається в нуль, а в доходах
      лишається тільки винагорода. ПДВ - за звичайними правилами: компанія нараховує його з
      продажу покупцю, комітент - на компанію; спірні випадки визначає бухгалтер за чинною
      редакцією ПКУ.

out - компанія комітент. Товар переміщується на окреме місце «На комісії: <комісіонер>»
      поруч зі «Складом» і лишається своїм (оціненим). Звіт комісіонера вносять з його
      паперового звіту; проведений, він:
        * відвантажує продане з місця комісіонера покупцям (собівартість - як при продажу);
        * створює рахунок комісіонеру за продане;
        * рахунок від комісіонера на винагороду;
        * взаємозалік між ними.

Ціноутворення: «відсоток» - ціна продажу і винагорода у відсотках; «ціна комітента» - товар
на реалізацію за ціною з договору, без окремої винагороди (різниця - заробіток продавця).
Повернення покупців у звіт не входять: їх відображає бухгалтер окремо.
"""
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.l10n_ua_docs.models.tools import amount_in_words

ROLES = [("in", "Компанія - комісіонер (чужий товар)"),
         ("out", "Компанія - комітент (свій товар у комісіонера)")]
PRICING = [("percent", "Відсоток винагороди"), ("price", "Ціна комітента (на реалізацію)")]
STATES = [("draft", "Чернетка"), ("open", "Діє"), ("closed", "Закрито")]


class StockLocation(models.Model):
    _inherit = "stock.location"

    ua_commission_partner_id = fields.Many2one(
        "res.partner", "Комісіонер", index="btree_not_null", readonly=True,
        help="Місце, де лежить свій товар, переданий цьому комісіонеру.")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ua_commission_id = fields.Many2one("ua.commission.agreement", "Договір комісії",
                                       index="btree_not_null", readonly=True, copy=False)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    ua_commission_report_id = fields.Many2one(
        "ua.commission.report", "Звіт комісіонера", index="btree_not_null", readonly=True,
        copy=False, help="Продаж чужого товару, уже включений у звіт комітенту.")


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_commission_report_id = fields.Many2one("ua.commission.report", "Звіт комісіонера",
                                              index="btree_not_null", readonly=True, copy=False)


class UaCommissionAgreement(models.Model):
    _name = "ua.commission.agreement"
    _description = "Договір комісії"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    role = fields.Selection(ROLES, "Роль компанії", required=True, default="in", tracking=True)
    partner_id = fields.Many2one("res.partner", "Контрагент", required=True, tracking=True,
                                 domain="[('parent_id', '=', False)]",
                                 help="Комітент, якщо компанія комісіонер; комісіонер, якщо комітент.")
    contract_id = fields.Many2one("ua.contract", "Договір", check_company=True,
                                  domain="[('partner_id', '=', partner_id)]",
                                  help="Договір комісії в реєстрі договорів: іде на рахунки.")
    pricing = fields.Selection(PRICING, "Розрахунок", required=True, default="percent",
                               tracking=True)
    commission_percent = fields.Float("Винагорода, %", digits=(5, 2), tracking=True)
    warehouse_id = fields.Many2one(
        "stock.warehouse", "Склад", required=True, check_company=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1))
    location_id = fields.Many2one("stock.location", "Місце «На комісії»", readonly=True,
                                  check_company=True, copy=False,
                                  help="Свій товар у комісіонера (лише коли компанія комітент).")
    proceeds_account_id = fields.Many2one(
        "account.account", "Рахунок виручки комітента", check_company=True,
        help="Куди йдуть рядки рахунку від комітента. Порожньо - рахунок доходу товару, тож "
             "дохід від чужого товару згортається в нуль.")
    line_ids = fields.One2many("ua.commission.agreement.line", "agreement_id", "Товари", copy=True)
    picking_ids = fields.One2many("stock.picking", "ua_commission_id", "Переміщення")
    report_ids = fields.One2many("ua.commission.report", "agreement_id", "Звіти")
    picking_count = fields.Integer("Переміщення", compute="_compute_counts")
    report_count = fields.Integer("Звіти", compute="_compute_counts")
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True, copy=False)
    note = fields.Text("Примітка")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].with_company(
                    vals.get("company_id") or self.env.company.id).next_by_code(
                    "ua.commission.agreement", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    def _compute_counts(self):
        for agreement in self:
            agreement.picking_count = len(agreement.picking_ids)
            agreement.report_count = len(agreement.report_ids)

    @api.constrains("pricing", "commission_percent")
    def _check_percent(self):
        for agreement in self:
            if not 0.0 <= agreement.commission_percent < 100.0:
                raise ValidationError(_("Винагорода - від 0 до 100 відсотків."))
            if agreement.pricing == "percent" and not agreement.commission_percent:
                raise ValidationError(_("Вкажіть відсоток винагороди або оберіть ціну комітента."))

    def unlink(self):
        if self.filtered(lambda a: a.state != "draft"):
            raise UserError(_("Чинний договір комісії не видаляють: його закривають."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Склад
    # ------------------------------------------------------------------
    def _ua_location(self):
        """Місце «На комісії» поруч зі «Складом»: свій товар, який лежить у комісіонера."""
        self.ensure_one()
        Location = self.env["stock.location"].sudo()
        parent = self.warehouse_id.view_location_id
        location = Location.search([("location_id", "=", parent.id),
                                    ("ua_commission_partner_id", "=", self.partner_id.id)], limit=1)
        if not location:
            location = Location.create({
                "name": _("На комісії: %s") % self.partner_id.display_name,
                "location_id": parent.id, "usage": "internal", "company_id": self.company_id.id,
                "ua_commission_partner_id": self.partner_id.id})
        return location.sudo(False)

    def _stock_domain(self):
        """Залишки за договором: чужий товар на складі або свій у комісіонера."""
        self.ensure_one()
        if self.role == "in":
            return [("location_id", "child_of", self.warehouse_id.view_location_id.id),
                    ("location_id.usage", "=", "internal"), ("owner_id", "=", self.partner_id.id)]
        return [("location_id", "=", self.location_id.id)]

    def balance_rows(self):
        """Що зараз лежить за договором: [{product, quantity, price}]."""
        self.ensure_one()
        if self.role == "out" and not self.location_id:
            return []
        rows = {}
        for quant in self.env["stock.quant"].search(self._stock_domain()):
            row = rows.setdefault(quant.product_id, {"product": quant.product_id, "quantity": 0.0})
            row["quantity"] += quant.quantity
        prices = {line.product_id: line.price_unit for line in self.line_ids}
        result = []
        for product, row in rows.items():
            if product.uom_id.compare(row["quantity"], 0.0) > 0:
                row["price"] = prices.get(product, 0.0)
                result.append(row)
        return sorted(result, key=lambda r: r["product"].display_name)

    def action_open(self):
        for agreement in self:
            if agreement.state != "draft":
                continue
            values = {"state": "open"}
            if agreement.role == "out":
                values["location_id"] = agreement._ua_location().id
            agreement.write(values)
        return True

    def action_close(self):
        for agreement in self:
            if agreement.balance_rows():
                raise UserError(_("За договором ще лежить товар: поверніть його перед закриттям."))
            if agreement.report_ids.filtered(lambda r: r.state == "draft"):
                raise UserError(_("Є непроведені звіти за договором."))
        self.write({"state": "closed"})
        return True

    def _check_open(self):
        for agreement in self:
            if agreement.state != "open":
                raise UserError(_("Договір %s не діє.") % agreement.name)

    def _picking(self, picking_type, source, destination, items, owner):
        self.ensure_one()
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id, "partner_id": self.partner_id.id,
            "location_id": source.id, "location_dest_id": destination.id,
            "owner_id": owner.id or False, "origin": self.name, "ua_commission_id": self.id,
            "company_id": self.company_id.id,
            "move_ids": [(0, 0, {
                "product_id": product.id, "product_uom_qty": qty, "product_uom": product.uom_id.id,
                "location_id": source.id, "location_dest_id": destination.id,
                "company_id": self.company_id.id, "restrict_partner_id": owner.id or False,
            }) for product, qty in items],
        })
        picking.action_confirm()
        if picking.location_id.usage == "internal":
            picking.action_assign()
        return picking

    @staticmethod
    def _open_record(record):
        return {"type": "ir.actions.act_window", "res_model": record._name, "res_id": record.id,
                "view_mode": "form", "target": "current"}

    def action_transfer(self):
        """Прийняти товар від комітента (in) або передати комісіонеру (out): кількості з
        рядків договору «До передачі»."""
        self.ensure_one()
        self._check_open()
        items = [(line.product_id, line.product_qty) for line in self.line_ids if line.product_qty > 0]
        if not items:
            raise UserError(_("Вкажіть у рядках договору кількість до передачі."))
        warehouse = self.warehouse_id
        if self.role == "in":
            vendors = self.env.ref("stock.stock_location_suppliers")
            picking = self._picking(warehouse.in_type_id, vendors, warehouse.lot_stock_id, items,
                                    self.partner_id)
        else:
            picking = self._picking(warehouse.int_type_id, warehouse.lot_stock_id, self.location_id,
                                    items, self.env["res.partner"])
        self.line_ids.write({"product_qty": 0.0})
        return self._open_record(picking)

    def action_return(self):
        """Повернути все непродане: комітенту (in) або від комісіонера на склад (out)."""
        self.ensure_one()
        self._check_open()
        items = [(row["product"], row["quantity"]) for row in self.balance_rows()]
        if not items:
            raise UserError(_("За договором немає залишку."))
        warehouse = self.warehouse_id
        if self.role == "in":
            vendors = self.env.ref("stock.stock_location_suppliers")
            picking = self._picking(warehouse.out_type_id, warehouse.lot_stock_id, vendors, items,
                                    self.partner_id)
        else:
            picking = self._picking(warehouse.int_type_id, self.location_id, warehouse.lot_stock_id,
                                    items, self.env["res.partner"])
        return self._open_record(picking)

    def action_new_report(self):
        self.ensure_one()
        self._check_open()
        last = self.report_ids.filtered(lambda r: r.state == "done").sorted("date_to")[-1:]
        today = fields.Date.context_today(self)
        report = self.env["ua.commission.report"].create({
            "agreement_id": self.id,
            "date_from": min(last.date_to + timedelta(days=1), today) if last else today.replace(day=1),
            "date_to": today,
        })
        if self.role == "in":
            report._fill()
        return self._open_record(report)

    def action_open_pickings(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Переміщення"), "res_model": "stock.picking",
                "view_mode": "list,form", "domain": [("ua_commission_id", "=", self.id)]}

    def action_open_reports(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Звіти"), "res_model": "ua.commission.report",
                "view_mode": "list,form", "domain": [("agreement_id", "=", self.id)],
                "context": {"default_agreement_id": self.id}}


class UaCommissionAgreementLine(models.Model):
    _name = "ua.commission.agreement.line"
    _description = "Товар договору комісії"
    _order = "agreement_id, sequence, id"

    agreement_id = fields.Many2one("ua.commission.agreement", "Договір", required=True, index=True,
                                   ondelete="cascade")
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="agreement_id.company_id", store=True)
    currency_id = fields.Many2one(related="agreement_id.currency_id")
    product_id = fields.Many2one("product.product", "Товар", required=True,
                                 domain="[('is_storable', '=', True)]")
    price_unit = fields.Monetary("Ціна за договором",
                                 help="Ціна комітента без ПДВ: за нею рахують продане, коли "
                                      "розрахунок за ціною комітента, і вона ж підставляється в звіт.")
    product_qty = fields.Float("До передачі", digits="Product Unit of Measure",
                               help="Скільки прийняти чи передати наступним переміщенням.")

    _product_unique = models.Constraint("UNIQUE(agreement_id, product_id)",
                                        "Товар уже є в договорі.")


class UaCommissionReport(models.Model):
    _name = "ua.commission.report"
    _description = "Звіт комісіонера"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    agreement_id = fields.Many2one("ua.commission.agreement", "Договір комісії", required=True,
                                   index=True, check_company=True,
                                   domain="[('state', '=', 'open')]")
    company_id = fields.Many2one(related="agreement_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    role = fields.Selection(related="agreement_id.role")
    pricing = fields.Selection(related="agreement_id.pricing")
    partner_id = fields.Many2one(related="agreement_id.partner_id", store=True)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    date_from = fields.Date("Період з", required=True)
    date_to = fields.Date("по", required=True)
    partner_ref = fields.Char("Номер звіту комісіонера",
                             help="Номер паперового звіту, коли звіт складав комісіонер.")
    line_ids = fields.One2many("ua.commission.report.line", "report_id", "Продано", copy=False)
    stock_line_ids = fields.Many2many("stock.move.line", string="Відвантаження", copy=False,
                                      help="Продаж чужого товару, з якого заповнено звіт.")
    amount_total = fields.Monetary("Продано на суму", compute="_compute_totals", store=True)
    commission_total = fields.Monetary("Винагорода", compute="_compute_totals", store=True)
    amount_due = fields.Monetary("Належить комітенту", compute="_compute_totals", store=True)
    sale_total = fields.Monetary("Виручка від покупців", compute="_compute_totals", store=True,
                                 help="Лише коли компанія комісіонер: за скільки продано покупцям.")
    invoice_ids = fields.One2many("account.move", "ua_commission_report_id", "Рахунки")
    offset_id = fields.Many2one("ua.debt.offset", "Взаємозалік", readonly=True, copy=False)
    picking_id = fields.Many2one("stock.picking", "Відвантаження проданого", readonly=True, copy=False)
    state = fields.Selection([("draft", "Чернетка"), ("done", "Проведено"), ("cancel", "Скасовано")],
                             "Стан", required=True, default="draft", tracking=True, copy=False)
    note = fields.Text("Примітка")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                agreement = self.env["ua.commission.agreement"].browse(vals.get("agreement_id"))
                vals["name"] = self.env["ir.sequence"].with_company(
                    agreement.company_id.id or self.env.company.id).next_by_code(
                    "ua.commission.report", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    @api.depends("line_ids.amount", "line_ids.commission", "line_ids.sale_amount")
    def _compute_totals(self):
        for report in self:
            report.amount_total = sum(report.line_ids.mapped("amount"))
            report.commission_total = sum(report.line_ids.mapped("commission"))
            report.amount_due = report.amount_total - report.commission_total
            report.sale_total = sum(report.line_ids.mapped("sale_amount"))

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for report in self:
            if report.date_from > report.date_to:
                raise ValidationError(_("Початок періоду пізніше за кінець."))

    def unlink(self):
        if self.filtered(lambda r: r.state == "done"):
            raise UserError(_("Проведений звіт не видаляють: його скасовують."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Заповнення (компанія комісіонер)
    # ------------------------------------------------------------------
    def _sold_lines(self):
        """Проведені відвантаження покупцям чужого товару за період, ще не у звітах."""
        self.ensure_one()
        agreement = self.agreement_id
        start = datetime.combine(self.date_from, time.min)
        end = datetime.combine(self.date_to + timedelta(days=1), time.min)
        return self.env["stock.move.line"].search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("owner_id", "=", agreement.partner_id.id),
            ("location_id", "child_of", agreement.warehouse_id.view_location_id.id),
            ("location_dest_id.usage", "=", "customer"),
            ("date", ">=", start), ("date", "<", end),
            ("ua_commission_report_id", "=", False),
        ], order="date, id")

    @staticmethod
    def _sale_price(move):
        """Ціна продажу без ПДВ за одиницю товару з рядка замовлення."""
        line = move.sale_line_id
        if line and line.product_uom_qty:
            price = line.price_subtotal / line.product_uom_qty
            uom = line["product_uom_id" if "product_uom_id" in line._fields else "product_uom"]
            return uom._compute_price(price, move.product_id.uom_id) \
                if uom and uom != move.product_id.uom_id else price
        return move.product_id.lst_price

    def action_fill(self):
        for report in self:
            if report.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            if report.role != "in":
                raise UserError(_("Звіт комісіонера вносять з його паперового звіту: заповнення "
                                  "з відвантажень - лише коли комісіонер сама компанія."))
            if not report._fill():
                raise UserError(_("За період чужий товар цього комітента не продавався "
                                  "або вже увійшов у звіти."))
        return True

    def _fill(self):
        """Рядки з продажів чужого товару; повертає кількість рядків."""
        rows_count = 0
        for report in self:
            sold = report._sold_lines()
            rows = {}
            for move_line in sold:
                product = move_line.product_id
                qty = move_line.product_uom_id._compute_quantity(move_line.quantity, product.uom_id)
                row = rows.setdefault(product, {"quantity": 0.0, "sale": 0.0})
                row["quantity"] += qty
                row["sale"] += qty * report._sale_price(move_line.move_id)
            prices = {line.product_id: line.price_unit for line in report.agreement_id.line_ids}
            values = []
            for product, row in rows.items():
                sale_price = report.currency_id.round(row["sale"] / row["quantity"]) if row["quantity"] else 0.0
                values.append((0, 0, {
                    "product_id": product.id, "quantity": row["quantity"],
                    "price_unit": prices.get(product, sale_price) if report.pricing == "price" else sale_price,
                    "sale_amount": report.currency_id.round(row["sale"]),
                }))
            report.write({"line_ids": [(5, 0, 0)] + values, "stock_line_ids": [(6, 0, sold.ids)]})
            rows_count += len(values)
        return rows_count

    # ------------------------------------------------------------------
    # Проведення
    # ------------------------------------------------------------------
    def _taxes(self, product, kind):
        field = "taxes_id" if kind == "sale" else "supplier_taxes_id"
        taxes = product[field].filtered(lambda t: t.company_id == self.company_id)
        if not taxes and product == self.env.ref("l10n_ua_commission.product_commission_fee"):
            taxes = self.company_id["account_sale_tax_id" if kind == "sale" else "account_purchase_tax_id"]
        return taxes

    def _invoice(self, move_type, lines):
        self.ensure_one()
        vals = {
            "move_type": move_type, "partner_id": self.partner_id.id,
            "company_id": self.company_id.id, "invoice_date": self.date,
            "invoice_origin": self.name, "ua_commission_report_id": self.id,
            "ref": self.partner_ref or self.name if move_type == "in_invoice" else False,
            "invoice_line_ids": lines,
        }
        if self.agreement_id.contract_id:
            vals["ua_contract_id"] = self.agreement_id.contract_id.id
        move = self.env["account.move"].with_company(self.company_id).create(vals)
        move.action_post()
        return move

    def _fee_lines(self, kind):
        fee = self.env.ref("l10n_ua_commission.product_commission_fee")
        return [(0, 0, {
            "product_id": fee.id, "quantity": 1.0, "price_unit": self.commission_total,
            "name": _("Комісійна винагорода за звітом %(report)s, договір %(agreement)s",
                      report=self.name, agreement=self.agreement_id.name),
            "tax_ids": [(6, 0, self._taxes(fee, kind).ids)],
        })]

    def _goods_lines(self, kind):
        lines = []
        for line in self.line_ids:
            vals = {
                "product_id": line.product_id.id, "quantity": line.quantity,
                "price_unit": line.price_unit,
                "tax_ids": [(6, 0, self._taxes(line.product_id, kind).ids)],
            }
            if kind == "purchase" and self.pricing == "percent":
                account = self.agreement_id.proceeds_account_id or \
                    line.product_id.product_tmpl_id.get_product_accounts()["income"]
                if account:
                    vals["account_id"] = account.id
            lines.append((0, 0, vals))
        return lines

    def _offset(self, receivable_move, payable_move):
        """Зарахувати винагороду проти боргу за товар: одним документом взаємозаліку."""
        cur = self.currency_id
        rec = receivable_move.line_ids.filtered(
            lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled)
        pay = payable_move.line_ids.filtered(
            lambda l: l.account_id.account_type == "liability_payable" and not l.reconciled)
        total = min(sum(rec.mapped("amount_residual")), -sum(pay.mapped("amount_residual")))
        if cur.compare_amounts(total, 0.0) <= 0:
            return self.env["ua.debt.offset"]
        rows = []
        for side, lines in (("receivable", rec), ("payable", pay)):
            left = total
            for line in lines.sorted(lambda l: (l.date_maturity or l.date, l.id)):
                amount = min(abs(line.amount_residual), left)
                if cur.compare_amounts(amount, 0.0) <= 0:
                    break
                rows.append((0, 0, {"side": side, "move_line_id": line.id, "amount": amount}))
                left = cur.round(left - amount)
        offset = self.env["ua.debt.offset"].create({
            "company_id": self.company_id.id, "partner_id": self.partner_id.commercial_partner_id.id,
            "date": self.date, "line_ids": rows,
            "note": _("Винагорода за звітом комісіонера %s.") % self.name,
        })
        offset.action_post()
        return offset

    def _deliver_sold(self):
        """Компанія комітент: продане списується з місця комісіонера покупцям."""
        agreement = self.agreement_id
        on_hand = {row["product"]: row["quantity"] for row in agreement.balance_rows()}
        for line in self.line_ids:
            have = on_hand.get(line.product_id, 0.0)
            if line.product_id.uom_id.compare(line.quantity, have) > 0:
                raise UserError(_(
                    "%(product)s: у комісіонера %(have)s, а продано %(qty)s.",
                    product=line.product_id.display_name, have=have, qty=line.quantity))
        customers = self.env.ref("stock.stock_location_customers")
        picking = agreement._picking(
            agreement.warehouse_id.out_type_id, agreement.location_id, customers,
            [(line.product_id, line.quantity) for line in self.line_ids], self.env["res.partner"])
        picking.origin = "%s, %s" % (self.name, agreement.name)
        for move in picking.move_ids:
            if move.product_uom.compare(move.quantity, move.product_uom_qty) < 0:
                raise UserError(_("%s: не вдалося зарезервувати товар на місці комісіонера.")
                                % move.product_id.display_name)
            move.picked = True
        picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        if picking.state != "done":
            raise UserError(_("Відвантаження проданого не проведено."))
        return picking

    def action_done(self):
        for report in self:
            if report.state != "draft":
                raise UserError(_("Провести можна лише чернетку."))
            report.agreement_id._check_open()
            if not report.line_ids:
                raise UserError(_("У звіті немає проданого товару."))
            if report.role == "in":
                taken = report.stock_line_ids.filtered("ua_commission_report_id")
                if taken:
                    raise UserError(_("Частина продажів уже у звіті %s. Заповніть звіт знову.")
                                    % taken.ua_commission_report_id[:1].name)
                bill = report._invoice("in_invoice", report._goods_lines("purchase"))
                fee = report._invoice("out_invoice", report._fee_lines("sale")) \
                    if report.currency_id.compare_amounts(report.commission_total, 0.0) > 0 else None
                offset = report._offset(fee, bill) if fee else self.env["ua.debt.offset"]
                report.stock_line_ids.write({"ua_commission_report_id": report.id})
                report.write({"offset_id": offset.id, "state": "done"})
            else:
                picking = report._deliver_sold()
                invoice = report._invoice("out_invoice", report._goods_lines("sale"))
                fee = report._invoice("in_invoice", report._fee_lines("purchase")) \
                    if report.currency_id.compare_amounts(report.commission_total, 0.0) > 0 else None
                offset = report._offset(invoice, fee) if fee else self.env["ua.debt.offset"]
                report.write({"picking_id": picking.id, "offset_id": offset.id, "state": "done"})
        return True

    def _return_sold(self):
        """Скасування звіту компанії-комітента: продане повертається на місце комісіонера."""
        done = self.picking_id
        customers = self.env.ref("stock.stock_location_customers")
        agreement = self.agreement_id
        picking = self.env["stock.picking"].create({
            "picking_type_id": agreement.warehouse_id.in_type_id.id,
            "partner_id": agreement.partner_id.id, "location_id": customers.id,
            "location_dest_id": agreement.location_id.id, "origin": _("Скасування %s") % self.name,
            "ua_commission_id": agreement.id, "company_id": self.company_id.id,
            "move_ids": [(0, 0, {
                "product_id": move.product_id.id, "product_uom_qty": move.quantity,
                "product_uom": move.product_uom.id, "location_id": customers.id,
                "location_dest_id": agreement.location_id.id, "company_id": self.company_id.id,
            }) for move in done.move_ids if move.state == "done"],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            origin = done.move_ids.filtered(lambda m, p=move.product_id: m.product_id == p)
            move.move_line_ids.unlink()
            move.move_line_ids = [(0, 0, {
                "product_id": move.product_id.id, "lot_id": line.lot_id.id or False,
                "quantity": line.quantity, "product_uom_id": line.product_uom_id.id,
                "location_id": customers.id, "location_dest_id": agreement.location_id.id,
                "picking_id": picking.id, "company_id": self.company_id.id,
            }) for line in origin.move_line_ids]
            move.picked = True
        picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        return picking

    def action_cancel(self):
        for report in self:
            if report.state != "done":
                report.state = "cancel"
                continue
            if report.offset_id:
                report.offset_id.action_cancel()
            for move in report.invoice_ids.filtered(lambda m: m.state != "cancel"):
                if move.state == "posted":
                    move.button_draft()
                move.button_cancel()
            if report.role == "in":
                report.stock_line_ids.filtered(
                    lambda l, r=report: l.ua_commission_report_id == r).write(
                    {"ua_commission_report_id": False})
            elif report.picking_id:
                report._return_sold()
            report.write({"state": "cancel", "offset_id": False, "picking_id": False})
        return True

    def action_reset_draft(self):
        self.filtered(lambda r: r.state == "cancel").write({"state": "draft"})
        return True

    def action_open_invoices(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Рахунки"), "res_model": "account.move",
                "view_mode": "list,form", "domain": [("ua_commission_report_id", "=", self.id)]}

    def action_print(self):
        return self.env.ref("l10n_ua_commission.action_report_ua_commission").report_action(self)

    # ------------------------------------------------------------------
    # Друк
    # ------------------------------------------------------------------
    @api.model
    def money(self, amount):
        """1 240,50 - сума для друку."""
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    def amount_words(self, amount):
        self.ensure_one()
        return amount_in_words(self.currency_id, amount)

    def parties(self):
        """(комісіонер, комітент) для друку."""
        self.ensure_one()
        company = self.company_id.partner_id
        partner = self.partner_id.commercial_partner_id
        return (company, partner) if self.role == "in" else (partner, company)


class UaCommissionReportLine(models.Model):
    _name = "ua.commission.report.line"
    _description = "Рядок звіту комісіонера"
    _order = "report_id, sequence, id"

    report_id = fields.Many2one("ua.commission.report", "Звіт", required=True, index=True,
                                ondelete="cascade")
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="report_id.company_id", store=True)
    currency_id = fields.Many2one(related="report_id.currency_id")
    product_id = fields.Many2one("product.product", "Товар", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    quantity = fields.Float("Кількість", required=True, digits="Product Unit of Measure")
    price_unit = fields.Monetary("Ціна", help="Без ПДВ: ціна продажу або ціна комітента.")
    amount = fields.Monetary("Сума", compute="_compute_amounts", store=True)
    commission = fields.Monetary("Винагорода", compute="_compute_amounts", store=True)
    sale_amount = fields.Monetary("Продано покупцям", readonly=True,
                                  help="Компанія комісіонер: виручка від покупців без ПДВ.")

    @api.depends("quantity", "price_unit", "report_id.agreement_id.pricing",
                 "report_id.agreement_id.commission_percent")
    def _compute_amounts(self):
        for line in self:
            cur = line.currency_id
            amount = line.quantity * line.price_unit
            line.amount = cur.round(amount) if cur else amount
            agreement = line.report_id.agreement_id
            percent = agreement.commission_percent if agreement.pricing == "percent" else 0.0
            line.commission = cur.round(line.amount * percent / 100.0) if cur else 0.0

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Кількість проданого має бути більшою за нуль."))
