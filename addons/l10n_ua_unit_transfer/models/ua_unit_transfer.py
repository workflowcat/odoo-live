"""Акт приймання-передачі виробів військовій частині поза державним контрактом.

Два випадки:
  fund     - покупець-благодійник (фонд, громада, компанія) купив вироби, а отримує їх
             військова частина: продаж іде покупцю, відвантаження - на адресу частини,
             акт підписують три сторони;
  donation - компанія передає власні вироби безоплатно: продажу немає, вартість в акті -
             балансова (собівартість виробу).
Затверджений акт ставить себе на серійні номери: паспорт виробу показує частину й акт, а
той самий номер вдруге не передати. Проведень і податкових сум модуль не робить: для
безоплатної передачі їх визначає бухгалтер за чинною редакцією ПКУ.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.l10n_ua_docs.models.tools import amount_in_words

KINDS = [("fund", "Оплатив благодійник, отримує частина"),
         ("donation", "Безоплатна передача від компанії")]


class ResPartner(models.Model):
    _inherit = "res.partner"

    ua_unit = fields.Boolean("Військова частина")
    ua_unit_number = fields.Char("Умовне найменування частини", help="Наприклад, А0000.")
    ua_unit_transfer_count = fields.Integer("Передачі", compute="_compute_ua_unit_transfer_count")

    def _compute_ua_unit_transfer_count(self):
        Transfer = self.env["ua.unit.transfer"]
        for partner in self:
            partner.ua_unit_transfer_count = Transfer.search_count(
                [("unit_id", "=", partner.id), ("state", "=", "done")]) \
                if partner.ua_unit and isinstance(partner.id, int) else 0

    def action_ua_unit_transfers(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "l10n_ua_unit_transfer.action_ua_unit_transfer")
        action["domain"] = [("unit_id", "=", self.id)]
        action["context"] = {"default_unit_id": self.id}
        return action


class StockLot(models.Model):
    _inherit = "stock.lot"

    ua_unit_transfer_id = fields.Many2one("ua.unit.transfer", "Передано за актом", readonly=True,
                                          copy=False, index="btree_not_null")
    ua_unit_id = fields.Many2one(related="ua_unit_transfer_id.unit_id", string="Військова частина")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ua_unit_transfer_ids = fields.One2many("ua.unit.transfer", "picking_id", "Акти передачі")

    def action_ua_unit_transfer(self):
        """Акт передачі з цього відвантаження: існуючий або новий, заповнений."""
        self.ensure_one()
        transfer = self.ua_unit_transfer_ids.filtered(lambda t: t.state != "cancel")[:1]
        if not transfer:
            if self.state != "done" or self.picking_type_code != "outgoing":
                raise UserError(_("Акт складають із проведеного відвантаження."))
            sale = self.sale_id
            unit = self.partner_id if self.partner_id.ua_unit else \
                self.partner_id.commercial_partner_id.filtered("ua_unit")
            transfer = self.env["ua.unit.transfer"].create({
                "company_id": self.company_id.id, "picking_id": self.id,
                "kind": "fund" if sale else "donation",
                "donor_id": sale.partner_id.commercial_partner_id.id if sale else False,
                "unit_id": unit.id or False,
                "date": fields.Date.context_today(self),
            })
            transfer.action_fill_from_picking()
        return {"type": "ir.actions.act_window", "res_model": "ua.unit.transfer",
                "res_id": transfer.id, "view_mode": "form"}


class UaUnitTransfer(models.Model):
    _name = "ua.unit.transfer"
    _description = "Акт передачі військовій частині"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    kind = fields.Selection(KINDS, "Підстава", required=True, default="fund", tracking=True)
    unit_id = fields.Many2one("res.partner", "Військова частина", tracking=True,
                              domain="[('ua_unit', '=', True)]", check_company=True)
    unit_number = fields.Char(related="unit_id.ua_unit_number")
    receiver = fields.Char("Від частини прийняв", tracking=True,
                           help="Посада, звання і прізвище того, хто приймав.")
    receiver_basis = fields.Char("Діє на підставі", help="Доручення, наказ чи довіреність: номер і дата.")
    donor_id = fields.Many2one("res.partner", "Благодійник (покупець)", tracking=True,
                               check_company=True)
    picking_id = fields.Many2one("stock.picking", "Відвантаження", check_company=True,
                                 domain="[('picking_type_code', '=', 'outgoing')]")
    sale_id = fields.Many2one(related="picking_id.sale_id", string="Замовлення")
    line_ids = fields.One2many("ua.unit.transfer.line", "transfer_id", "Вироби", copy=True)
    amount_total = fields.Monetary("Разом", compute="_compute_amount_total", store=True)
    purpose = fields.Char("Призначення", default="Для потреб оборони",
                          help="Друкується в акті після переліку виробів.")
    state = fields.Selection([("draft", "Чернетка"), ("done", "Затверджено"), ("cancel", "Скасовано")],
                             "Стан", default="draft", required=True, tracking=True, copy=False)
    note = fields.Text("Примітка")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].with_company(
                    vals.get("company_id") or self.env.company.id).next_by_code(
                    "ua.unit.transfer", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for transfer in self:
            transfer.amount_total = sum(transfer.line_ids.mapped("amount"))

    @api.constrains("kind", "donor_id", "unit_id")
    def _check_parties(self):
        for transfer in self:
            if transfer.unit_id and not transfer.unit_id.ua_unit:
                raise ValidationError(_("%s не позначено як військову частину.")
                                      % transfer.unit_id.display_name)
            if transfer.kind == "donation" and transfer.donor_id:
                raise ValidationError(_("Безоплатна передача від компанії йде без благодійника."))

    def unlink(self):
        if any(transfer.state == "done" for transfer in self):
            raise UserError(_("Затверджений акт не видаляють: його скасовують."))
        return super().unlink()

    @api.model
    def money(self, amount):
        """1 240,50 - сума для друку."""
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    def amount_words(self):
        self.ensure_one()
        return amount_in_words(self.currency_id, self.amount_total)

    def action_fill_from_picking(self):
        """Рядки з відвантаження: виріб, кількість, серійні номери, ціна."""
        for transfer in self:
            if not transfer.picking_id:
                raise UserError(_("Оберіть відвантаження."))
            rows = []
            for move in transfer.picking_id.move_ids.filtered(lambda m: m.state == "done"):
                price = move.sale_line_id.price_unit if transfer.kind == "fund" and \
                    move.sale_line_id else move.product_id.standard_price
                rows.append((0, 0, {
                    "product_id": move.product_id.id, "quantity": move.quantity,
                    "lot_ids": [(6, 0, move.move_line_ids.lot_id.ids)], "price_unit": price}))
            transfer.line_ids = [(5, 0, 0)] + rows
        return True

    def action_done(self):
        for transfer in self:
            if transfer.state != "draft":
                raise UserError(_("Затвердити можна лише чернетку."))
            if not transfer.unit_id:
                raise UserError(_("Вкажіть військову частину."))
            if transfer.kind == "fund" and not transfer.donor_id:
                raise UserError(_("Вкажіть благодійника, який оплатив вироби."))
            if not transfer.line_ids:
                raise UserError(_("В акті немає виробів."))
            for line in transfer.line_ids:
                if line.product_id.tracking == "serial" and len(line.lot_ids) != line.quantity:
                    raise UserError(_(
                        "%(product)s: серійних номерів %(lots)s, а кількість %(qty)s.",
                        product=line.product_id.display_name, lots=len(line.lot_ids),
                        qty=line.quantity))
            lots = transfer.line_ids.lot_ids
            given = lots.filtered(lambda lot: lot.ua_unit_transfer_id
                                  and lot.ua_unit_transfer_id != transfer)
            if given:
                raise UserError(_("Уже передано за іншим актом: %s.") % ", ".join(
                    "%s (%s)" % (lot.name, lot.ua_unit_transfer_id.name) for lot in given))
            lots.write({"ua_unit_transfer_id": transfer.id})
            transfer.state = "done"
        return True

    def action_cancel(self):
        for transfer in self:
            transfer.line_ids.lot_ids.filtered(
                lambda lot: lot.ua_unit_transfer_id == transfer).write({"ua_unit_transfer_id": False})
        self.write({"state": "cancel"})
        return True

    def action_reset_draft(self):
        self.filtered(lambda t: t.state == "cancel").write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_unit_transfer.action_report_ua_unit_transfer") \
            .report_action(self)


class UaUnitTransferLine(models.Model):
    _name = "ua.unit.transfer.line"
    _description = "Рядок акта передачі військовій частині"
    _order = "transfer_id, sequence, id"

    transfer_id = fields.Many2one("ua.unit.transfer", "Акт", required=True, index=True,
                                  ondelete="cascade")
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="transfer_id.company_id", store=True)
    currency_id = fields.Many2one(related="transfer_id.currency_id")
    product_id = fields.Many2one("product.product", "Виріб", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    quantity = fields.Float("Кількість", required=True, default=1.0, digits="Product Unit of Measure")
    lot_ids = fields.Many2many("stock.lot", string="Серійні номери",
                               domain="[('product_id', '=', product_id)]")
    price_unit = fields.Monetary("Ціна", help="Ціна продажу благодійнику або балансова вартість.")
    amount = fields.Monetary("Сума", compute="_compute_amount", store=True)

    @api.depends("quantity", "price_unit")
    def _compute_amount(self):
        for line in self:
            line.amount = line.currency_id.round(line.quantity * line.price_unit) \
                if line.currency_id else line.quantity * line.price_unit

    def lot_names(self):
        return ", ".join(self.lot_ids.sorted("name").mapped("name"))
