from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_dps_partner_id = fields.Many2one("res.partner", "Партнер ДПС (податки, ЄСВ)", help="Контрагент для рядків 6411, 6415, 651 у проводках зарплати; створюється автоматично")
    ua_pfu_partner_id = fields.Many2one("res.partner", "Партнер ПФУ (лікарняні)", help="Контрагент для рядка 378 (лікарняні за рахунок ПФУ)")

    def _ua_partner(self, kind):
        self.ensure_one()
        field = "ua_dps_partner_id" if kind == "dps" else "ua_pfu_partner_id"
        if not self[field]:
            name = "ДПС (податки, ЄСВ)" if kind == "dps" else "Пенсійний фонд України (лікарняні)"
            partner = self.env["res.partner"].search([("name", "=", name), ("company_id", "in", (False, self.id))], limit=1)
            if not partner:
                partner = self.env["res.partner"].create({"name": name, "is_company": True, "company_id": self.id})
            self[field] = partner
        return self[field]
