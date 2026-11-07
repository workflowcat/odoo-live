"""Попит з графіків поставки оборонних контрактів для OCA mrp_multi_level.

Невиконане за рядком графіка рахується так (окремо для кожного контракту і виробу):

    виконано  = більше з двох: прийнято за актами, відвантажено покупцю за контрактом;
    у дорозі  = відкриті відвантаження за замовленнями цього контракту (MRP і так бачить
                їх як попит, тож вдруге не рахуємо);
    покрито   = виконано + у дорозі, розкладається на рядки графіка від найранішого;
    попит     = те, що в рядку лишилось непокритим.

Попит іде в одну зону MRP компанії: позначену «Попит з оборонних контрактів», а якщо таких
немає - у першу зону компанії. Так одна й та сама кількість не потрапляє в розрахунок двічі.
"""
from odoo import _, api, fields, models


class MrpArea(models.Model):
    _inherit = "mrp.area"

    ua_defense_demand = fields.Boolean(
        "Попит з оборонних контрактів",
        help="Графіки поставки оборонних контрактів компанії плануються в цій зоні. Якщо не "
             "позначено жодну зону, береться перша зона компанії.")

    @api.model
    def ua_defense_area(self, company):
        areas = self.search([("company_id", "=", company.id)], order="id")
        return areas.filtered("ua_defense_demand")[:1] or areas[:1]


class UaDefenseSchedule(models.Model):
    _inherit = "ua.defense.schedule"

    @api.model
    def ua_open_demand(self, product, company):
        """Непокрита частина графіків: [(дата, кількість, контракт)], від найранішого."""
        lines = self.search([
            ("product_id", "=", product.id), ("company_id", "=", company.id),
            ("contract_id.state", "=", "active"), ("contract_id.ua_defense", "=", True)])
        rows = []
        Move = self.env["stock.move"]
        rounding = product.uom_id
        for contract in lines.contract_id:
            moves = Move.search([
                ("product_id", "=", product.id), ("state", "!=", "cancel"),
                ("sale_line_id.order_id.ua_contract_id", "=", contract.id),
                ("location_dest_id.usage", "=", "customer")])
            delivered = sum(moves.filtered(lambda m: m.state == "done").mapped("product_qty"))
            in_flight = sum(moves.filtered(lambda m: m.state != "done").mapped("product_qty"))
            covered = max(contract._ua_accepted_qty(product), delivered) + in_flight
            for line in lines.filtered(lambda l, c=contract: l.contract_id == c).sorted(
                    lambda l: (l.date, l.id)):
                take = min(line.quantity, covered)
                covered -= take
                left = line.quantity - take
                if rounding.compare(left, 0.0) > 0:
                    rows.append((line.date, left, contract))
        return sorted(rows, key=lambda row: row[0])


class MrpMultiLevel(models.TransientModel):
    _inherit = "mrp.multi.level"

    @api.model
    def _init_mrp_move_from_forecast(self, product_mrp_area):
        result = super()._init_mrp_move_from_forecast(product_mrp_area)
        area = product_mrp_area.mrp_area_id
        company = area.company_id or product_mrp_area.company_id
        if not company or area != self.env["mrp.area"].ua_defense_area(company):
            return result
        product = product_mrp_area.product_id
        today = area._datetime_to_date_tz()
        values = []
        for date, qty, contract in self.env["ua.defense.schedule"].ua_open_demand(product, company):
            values.append({
                "product_id": product.id, "product_mrp_area_id": product_mrp_area.id,
                "production_id": None, "purchase_order_id": None, "purchase_line_id": None,
                "stock_move_id": None, "parent_product_id": None,
                "mrp_qty": -qty, "current_qty": -qty,
                "mrp_date": max(date, today), "current_date": date,
                "mrp_type": "d", "mrp_origin": "fc", "mrp_order_number": contract.name,
                "name": _("Графік оборонного контракту %s") % contract.name,
                "origin": contract.ua_procurement_ref or contract.name, "state": "confirmed",
            })
        if values:
            self.env["mrp.move"].create(values)
        return result
