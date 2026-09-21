from odoo import fields, models


class UaPartnerEdrWizard(models.TransientModel):
    _name = "ua.partner.edr.wizard"
    _description = "Новий контрагент з ЄДР"

    code = fields.Char("ЄДРПОУ або РНОКПП", required=True)

    def action_create(self):
        self.ensure_one()
        code = "".join(ch for ch in self.code if ch.isdigit())
        partner = self.env["res.partner"].search([("company_registry", "=", code)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create({"name": code, "company_registry": code, "is_company": True})
        partner.action_fill_from_edr()
        return {"type": "ir.actions.act_window", "res_model": "res.partner", "res_id": partner.id, "view_mode": "form"}
