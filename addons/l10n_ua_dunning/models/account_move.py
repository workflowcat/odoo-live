"""Слід нагадувань на рахунку, винятки контрагента, лист з картки договору."""
from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_dunning_level_id = fields.Many2one("ua.dunning.level", "Останнє нагадування", copy=False, readonly=True,
                                          help="Найвищий рівень, на якому покупцю вже нагадали про цей рахунок.")
    ua_dunning_date = fields.Date("Нагадано", copy=False, readonly=True)
    ua_dunning_hold = fields.Boolean("Не нагадувати", copy=False, tracking=True,
                                     help="Рахунок спірний або є домовленість про відстрочку.")


class ResPartner(models.Model):
    _inherit = "res.partner"

    ua_dunning_excluded = fields.Boolean("Не нагадувати про борг",
                                         help="Рахунки цього контрагента не потрапляють у нагадування.")


class UaContract(models.Model):
    _inherit = "ua.contract"

    def action_ua_dunning_letter(self):
        """Лист-нагадування за договором зараз: прострочені рахунки на сьогодні, без порогу рівнів."""
        self.ensure_one()
        Letter = self.env["ua.dunning.letter"]
        today = fields.Date.context_today(self)
        if not Letter._ua_groups(self.company_id, today, self.partner_id, self):
            raise UserError(_("За договором %s немає прострочених рахунків.") % self.name)
        letter = Letter.search([("company_id", "=", self.company_id.id), ("contract_id", "=", self.id),
                                ("state", "=", "draft")], limit=1)
        if not letter:
            letter = Letter.create({"company_id": self.company_id.id, "contract_id": self.id, "date": today,
                                    "partner_id": self.partner_id.commercial_partner_id.id})
        letter.action_refresh()
        return {"type": "ir.actions.act_window", "res_model": "ua.dunning.letter", "res_id": letter.id,
                "view_mode": "form", "target": "current"}
