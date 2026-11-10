"""Сканер штрихкодів у переміщенні і замовленні на виробництво.

Сканер вводить код як клавіатура; віджет `barcode_handler` з модуля barcodes ловить його у
відкритій формі і викликає `on_barcode_scanned`. Уся робота - у `_ua_scan(code)`: той самий метод
кличе API або інший інтерфейс. Код шукаємо так: штрихкод товару, артикул, назва партії чи
серійного номера. Повертає None або попередження у формі onchange.
"""
from odoo import _, api, fields, models


def _warn(message):
    return {"warning": {"title": _("Сканування"), "message": message}}


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _ua_by_code(self, code):
        """Товар за штрихкодом, потім за артикулом."""
        return (self.search([("barcode", "=", code)], limit=1)
                or self.search([("default_code", "=", code)], limit=1))


class StockMove(models.Model):
    _inherit = "stock.move"

    def _ua_one(self):
        """Одна одиниця товару в одиницях рядка."""
        return self.product_id.uom_id._compute_quantity(1.0, self.product_uom)

    def _ua_start(self):
        """Перший скан рядка: резерв не є відібраним товаром, тож рахунок іде з нуля."""
        if not any(self.move_line_ids.mapped("picked")):
            self.move_line_ids.unlink()

    def _ua_add_one(self):
        self.ensure_one()
        if self.has_tracking != "none":
            return _warn(_("%s обліковується за партіями: скануйте партію або серійний номер.")
                         % self.product_id.display_name)
        self._ua_start()
        self._set_quantity_done(self.quantity + self._ua_one())
        self.picked = True
        return None

    def _ua_scan_lot(self, lot):
        """Партія або серійний номер: +1 до рядка з цією партією або новий рядок."""
        self.ensure_one()
        self._ua_start()
        same = self.move_line_ids.filtered(lambda l: l.lot_id == lot)[:1]
        if same and self.has_tracking == "serial":
            return _warn(_("Серійний номер %s уже відскановано.") % lot.name)
        if same:
            same.quantity += same.product_id.uom_id._compute_quantity(1.0, same.product_uom_id)
        else:
            self.env["stock.move.line"].create({
                "move_id": self.id, "picking_id": self.picking_id.id, "product_id": self.product_id.id,
                "product_uom_id": self.product_uom.id, "lot_id": lot.id, "quantity": self._ua_one(),
                "location_id": self.location_id.id, "location_dest_id": self.location_dest_id.id})
        self.picked = True
        return None


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "barcodes.barcode_events_mixin"]

    def on_barcode_scanned(self, barcode):
        return self._ua_scan(barcode)

    def _ua_scan(self, code):
        self.ensure_one()
        code = (code or "").strip()
        if not code:
            return None
        if self.state in ("done", "cancel"):
            return _warn(_("Документ %s уже закрито.") % self.name)
        moves = self.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        product = self.env["product.product"]._ua_by_code(code)
        if product:
            move = moves.filtered(lambda m: m.product_id == product)[:1]
            if not move:
                return _warn(_("Товару %s немає в документі %s.") % (product.display_name, self.name))
            return move._ua_add_one()
        lot = self.env["stock.lot"].search([("name", "=", code), ("product_id", "in", moves.product_id.ids)], limit=1)
        if lot:
            return moves.filtered(lambda m: m.product_id == lot.product_id)[:1]._ua_scan_lot(lot)
        return _warn(_("Код %s не знайдено серед товарів і партій цього документа.") % code)


class MrpProduction(models.Model):
    _name = "mrp.production"
    _inherit = ["mrp.production", "barcodes.barcode_events_mixin"]

    def on_barcode_scanned(self, barcode):
        return self._ua_scan(barcode)

    def _ua_scan(self, code):
        """Готова продукція - +1 до випуску (компоненти за специфікацією); компонент - +1 до витрати."""
        self.ensure_one()
        code = (code or "").strip()
        if not code:
            return None
        if self.state == "draft":
            return _warn(_("Спершу підтвердьте замовлення %s.") % self.name)
        if self.state in ("done", "cancel"):
            return _warn(_("Замовлення %s уже закрито.") % self.name)
        raws = self.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        product = self.env["product.product"]._ua_by_code(code)
        if product and product == self.product_id:
            self.qty_producing += self.product_id.uom_id._compute_quantity(1.0, self.product_uom_id)
            self._set_qty_producing()
            return None
        if product:
            move = raws.filtered(lambda m: m.product_id == product)[:1]
            if not move:
                return _warn(_("Компонента %s немає в замовленні %s.") % (product.display_name, self.name))
            move.manual_consumption = True
            return move._ua_add_one()
        products = raws.product_id | self.product_id
        lot = self.env["stock.lot"].search([("name", "=", code), ("product_id", "in", products.ids)], limit=1)
        if lot and lot.product_id == self.product_id:
            if lot in self.lot_producing_ids:
                return _warn(_("Партію %s уже додано до випуску.") % lot.name)
            self.lot_producing_ids |= lot
            return None
        if lot:
            move = raws.filtered(lambda m: m.product_id == lot.product_id)[:1]
            move.manual_consumption = True
            return move._ua_scan_lot(lot)
        return _warn(_("Код %s не знайдено серед продукції, компонентів і партій замовлення.") % code)


class UaScanStart(models.TransientModel):
    _name = "ua.scan.start"
    _inherit = ["barcodes.barcode_events_mixin"]
    _description = "Сканування: відкрити документ за номером"

    code = fields.Char("Відскановано", readonly=True)
    picking_id = fields.Many2one("stock.picking", "Переміщення", readonly=True)
    production_id = fields.Many2one("mrp.production", "Замовлення на виробництво", readonly=True)
    message = fields.Char("Що знайдено", readonly=True)

    def on_barcode_scanned(self, barcode):
        self._ua_find(barcode)

    def _ua_find(self, code):
        code = (code or "").strip()
        picking = self.env["stock.picking"].search([("name", "=", code)], limit=1)
        production = not picking and self.env["mrp.production"].search([("name", "=", code)], limit=1)
        product = not picking and not production and self.env["product.product"]._ua_by_code(code)
        if picking:
            message = _("Переміщення %s: %s") % (picking.name, dict(picking._fields["state"]._description_selection(
                self.env)).get(picking.state))
        elif production:
            message = _("Замовлення на виробництво %s") % production.name
        elif product:
            message = _("Це товар %s. Відкрийте документ і скануйте товар у ньому.") % product.display_name
        else:
            message = _("Код %s не знайдено.") % code
        self.update({"code": code, "picking_id": picking.id if picking else False,
                     "production_id": production.id if production else False, "message": message})

    def action_open(self):
        self.ensure_one()
        record = self.picking_id or self.production_id
        if not record:
            return {"type": "ir.actions.act_window_close"}
        return {"type": "ir.actions.act_window", "res_model": record._name, "res_id": record.id,
                "view_mode": "form", "target": "current"}
