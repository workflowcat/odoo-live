"""Рекламації на серійному номері: лічильник на картці і історія в паспорті."""
from odoo import fields, models

from .ua_claim import CAUSES, DECISIONS, STATES

CLAIM_USER = "l10n_ua_claim.group_ua_claim_user"


class StockLot(models.Model):
    _inherit = "stock.lot"

    ua_claim_count = fields.Integer("Рекламації", compute="_compute_ua_claim_count",
                                    groups=CLAIM_USER)

    def _compute_ua_claim_count(self):
        Claim = self.env["ua.claim"].sudo()
        for lot in self:
            lot.ua_claim_count = Claim.search_count([("lot_id", "=", lot.id)]) \
                if isinstance(lot.id, int) else 0

    def _ua_claim_rows(self):
        """Рекламації для паспорта: усі, крім скасованих, від найстарішої."""
        self.ensure_one()
        claims = self.env["ua.claim"].sudo().search(
            [("lot_id", "=", self.id), ("state", "!=", "cancel")], order="date_received, id")
        causes, decisions, states = dict(CAUSES), dict(DECISIONS), dict(STATES)
        return [{
            "name": claim.name,
            "date": claim.date_received.strftime("%d.%m.%Y"),
            "symptom": claim.symptom or "",
            "cause": causes.get(claim.cause, ""),
            "decision": decisions.get(claim.decision, ""),
            "state": states[claim.state],
        } for claim in claims]

    def action_ua_claims(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Рекламації", "res_model": "ua.claim",
            "view_mode": "list,form", "domain": [("lot_id", "=", self.id)],
            "context": {"default_lot_id": self.id},
        }
