from odoo import api, fields, models
from odoo.exceptions import UserError


class UaPayrollParam(models.Model):
    """Законодавчі параметри з датою початку дії. Код читає їх, ніколи не зашиває."""
    _name = "ua.payroll.param"
    _description = "Параметр зарплати (Україна)"
    _order = "key, valid_from desc"

    key = fields.Char("Код", required=True, index=True)
    name = fields.Char("Назва", required=True)
    valid_from = fields.Date("Діє з", required=True, index=True)
    value = fields.Float("Значення", digits=(16, 4), required=True)
    source = fields.Char("Підстава", help="Закон, постанова або наказ, який встановив значення")
    company_id = fields.Many2one("res.company", "Компанія", help="Порожньо = для всіх компаній")

    _key_from_company_uniq = models.Constraint("unique(key, valid_from, company_id)", "Один параметр на дату.")

    @api.model
    def get(self, key, date=None, company=None):
        date = date or fields.Date.context_today(self)
        domain = [("key", "=", key), ("valid_from", "<=", date)]
        if company:
            domain += ["|", ("company_id", "=", company.id), ("company_id", "=", False)]
        rec = self.search(domain, order="company_id desc, valid_from desc", limit=1)
        if not rec:
            raise UserError(f"Немає параметра «{key}» на дату {date}. Додайте його в Зарплата → Параметри (Україна).")
        return rec.value

    @api.model
    def get_all(self, date=None, company=None):
        keys = set(self.search([]).mapped("key"))
        return {k: self.get(k, date, company) for k in keys}
