"""Акт зміни найменування та одиниці виміру запасу.

Три випадки на рядок:
- лише назва - нова назва в картці товару;
- одиниця виміру, руху ще не було - нова одиниця в картці;
- одиниця виміру, рух уже був - переведення: нова картка, залишок списується зі старої і
  приходує на нову через інвентаризацію з коефіцієнтом, собівартість одиниці ділиться на
  коефіцієнт, стара картка архівується.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MODES = [("rename", "Зміна назви"), ("uom", "Зміна одиниці"), ("convert", "Переведення на нову картку")]


class UaProductRename(models.Model):
    _name = "ua.product.rename"
    _inherit = ["mail.thread"]
    _description = "Акт зміни найменування та одиниці виміру"
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="/")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    reason = fields.Text("Підстава", help="Наприклад: уточнення назви за документами постачальника, облік у кілограмах.")
    state = fields.Selection([("draft", "Чернетка"), ("done", "Проведено"), ("cancel", "Скасовано")], "Стан",
                             default="draft", required=True, readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many("ua.product.rename.line", "act_id", "Товари", copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.product.rename") or "/"
        return super().create(vals_list)

    def action_done(self):
        for act in self:
            if act.state != "draft":
                raise UserError(_("Провести можна лише чернетку."))
            if not act.line_ids:
                raise UserError(_("Додайте товари."))
            for line in act.line_ids:
                line._ua_apply()
            act.state = "done"
        return True

    def action_cancel(self):
        self.filtered(lambda a: a.state == "draft").write({"state": "cancel"})
        return True

    def action_draft(self):
        self.filtered(lambda a: a.state == "cancel").write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_product_rename.action_report_ua_product_rename").report_action(self)


class UaProductRenameLine(models.Model):
    _name = "ua.product.rename.line"
    _description = "Рядок акта зміни найменування"

    act_id = fields.Many2one("ua.product.rename", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", "Товар", required=True, domain="[('type', '=', 'consu')]")
    old_name = fields.Char("Було: назва", readonly=True)
    new_name = fields.Char("Стало: назва")
    old_uom_id = fields.Many2one("uom.uom", "Було: одиниця", readonly=True)
    new_uom_id = fields.Many2one("uom.uom", "Стало: одиниця")
    factor = fields.Float("Коефіцієнт", digits=(12, 6), default=1.0,
                          help="Скільки нових одиниць в одній старій. Метри в кілограми для дроту 0,2 кг/м - 0,2.")
    mode = fields.Selection(MODES, "Що зроблено", readonly=True)
    quantity_old = fields.Float("Залишок до", digits="Product Unit", readonly=True)
    quantity_new = fields.Float("Залишок після", digits="Product Unit", readonly=True)
    cost_old = fields.Float("Собівартість до", digits="Product Price", readonly=True)
    cost_new = fields.Float("Собівартість після", digits="Product Price", readonly=True)
    new_product_id = fields.Many2one("product.product", "Нова картка", readonly=True)

    @api.onchange("product_id")
    def _onchange_product(self):
        if self.product_id:
            self.new_name = self.new_name or self.product_id.name
            self.new_uom_id = self.new_uom_id or self.product_id.uom_id

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            line.write({"old_name": line.product_id.name, "old_uom_id": line.product_id.uom_id.id,
                        "new_name": line.new_name or line.product_id.name,
                        "new_uom_id": (line.new_uom_id or line.product_id.uom_id).id})
        return lines

    @api.constrains("factor")
    def _check_factor(self):
        for line in self:
            if line.factor <= 0:
                raise ValidationError(_("Коефіцієнт має бути більшим за нуль."))

    def _ua_quants(self):
        return self.env["stock.quant"].search([
            ("product_id", "=", self.product_id.id), ("location_id.usage", "=", "internal"),
            ("company_id", "=", self.act_id.company_id.id), ("quantity", "!=", 0)])

    def _ua_apply(self):
        self.ensure_one()
        product = self.product_id.with_company(self.act_id.company_id)
        template = product.product_tmpl_id
        quants = self._ua_quants()
        values = {"old_name": product.name, "old_uom_id": product.uom_id.id, "cost_old": product.standard_price,
                  "quantity_old": sum(quants.mapped("quantity"))}
        new_name = (self.new_name or "").strip() or product.name
        if not self.new_uom_id or self.new_uom_id == product.uom_id:
            if new_name == product.name:
                raise UserError(_("У рядку %s нічого не змінюється.") % product.display_name)
            template.name = new_name
            values.update(mode="rename", quantity_new=values["quantity_old"], cost_new=product.standard_price)
        elif not self.env["stock.move"].search_count([("product_id", "=", product.id)], limit=1):
            template.write({"name": new_name, "uom_id": self.new_uom_id.id})
            values.update(mode="uom", quantity_new=values["quantity_old"], cost_new=product.standard_price)
        else:
            values.update(self._ua_convert(product, new_name, quants))
        self.write(values)

    def _ua_convert(self, product, new_name, quants):
        if any(quants.mapped("reserved_quantity")):
            raise UserError(_("Товар %s зарезервовано в документах. Зніміть резерв, потім проводьте акт.")
                            % product.display_name)
        if any(q.quantity < 0 for q in quants):
            raise UserError(_("Залишок %s від'ємний. Спершу виправте його.") % product.display_name)
        template = product.product_tmpl_id
        new_template = template.copy({"name": new_name, "uom_id": self.new_uom_id.id})
        new_product = new_template.product_variant_id.with_company(self.act_id.company_id)
        cost = product.standard_price / self.factor
        new_product.standard_price = cost
        Quant = self.env["stock.quant"].with_context(inventory_mode=True, inventory_name=self.act_id.name)
        Lot = self.env["stock.lot"]
        moved = Quant.browse()
        total = 0.0
        for quant in quants:
            quantity = self.new_uom_id.round(quant.quantity * self.factor)
            lot = Lot.browse()
            if quant.lot_id:
                lot = (Lot.search([("product_id", "=", new_product.id), ("name", "=", quant.lot_id.name)], limit=1)
                       or Lot.create({"product_id": new_product.id, "name": quant.lot_id.name,
                                      "company_id": quant.company_id.id}))
            vals = {"product_id": new_product.id, "location_id": quant.location_id.id, "inventory_quantity": quantity}
            if lot:
                vals["lot_id"] = lot.id
            new_quant = Quant.create(vals)
            quant.with_context(inventory_mode=True).inventory_quantity = 0.0
            moved |= quant | new_quant
            total += quantity
        if moved:
            moved.with_context(inventory_name=self.act_id.name).action_apply_inventory()
        template.active = False
        return {"mode": "convert", "new_product_id": new_product.id, "quantity_new": total, "cost_new": cost}
