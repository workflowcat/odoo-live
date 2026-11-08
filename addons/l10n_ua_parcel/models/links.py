"""Відправлення в замовленні постачальнику і складському документі."""
from odoo import _, fields, models

from . import parcel_core as core


class _ParcelLinks(models.AbstractModel):
    _name = "ua.parcel.links"
    _description = "Відправлення в документі"

    ua_parcel_count = fields.Integer("Відправлень", compute="_compute_ua_parcels")
    ua_parcel_summary = fields.Char("Відправлення", compute="_compute_ua_parcels")

    def _ua_parcels(self):
        raise NotImplementedError

    def _compute_ua_parcels(self):
        for doc in self:
            parcels = doc._ua_parcels()
            doc.ua_parcel_count = len(parcels)
            counts = {}
            for parcel in parcels:
                counts[parcel.state] = counts.get(parcel.state, 0) + 1
            doc.ua_parcel_summary = ", ".join(
                "%s: %s" % (label, counts[code]) for code, label in core.STATES if counts.get(code)) or False

    def action_ua_parcels(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_parcel.action_ua_parcel")
        action["domain"] = [("id", "in", self._ua_parcels().ids)]
        action["context"] = self._ua_parcel_defaults()
        return action

    def action_ua_parcel_add(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Додати відправлення"), "res_model": "ua.parcel.add",
            "view_mode": "form", "target": "new", "context": self._ua_parcel_defaults(),
        }


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "ua.parcel.links"]

    ua_parcel_ids = fields.One2many("ua.parcel", "purchase_id", "Відправлення")

    def _ua_parcels(self):
        return self.ua_parcel_ids

    def _ua_parcel_defaults(self):
        return {"default_purchase_id": self.id, "default_partner_id": self.partner_id.id,
                "default_direction": "in"}


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "ua.parcel.links"]

    ua_parcel_ids = fields.One2many("ua.parcel", "picking_id", "Відправлення")

    def _ua_parcels(self):
        # Номер, який постачальник дав до приходу товару, лежить на замовленні.
        return self.ua_parcel_ids | self.purchase_id.ua_parcel_ids.filtered(lambda p: not p.picking_id)

    def _ua_parcel_defaults(self):
        return {"default_picking_id": self.id, "default_partner_id": self.partner_id.id,
                "default_purchase_id": self.purchase_id.id,
                "default_direction": "out" if self.picking_type_code == "outgoing" else "in"}
