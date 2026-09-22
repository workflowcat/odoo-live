"""Законодавчі числа податку на прибуток із датою початку дії.

Ставка податку і поріг малодохідника змінюються законом, тому лежать
датованими записами, а не константами в коді: новий закон - новий рядок
даних. Контракт той самий, що в ua.fop.param із l10n_ua_fop і в
ua.payroll.param із l10n_ua_payroll_rules, але залежності між ними немає:
податок на прибуток ставиться сам по собі.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError


class UaProfitParam(models.Model):
    _name = "ua.profit.param"
    _description = "Параметр податку на прибуток (Україна)"
    _order = "key, valid_from desc"

    key = fields.Char("Код", required=True, index=True)
    name = fields.Char("Назва", required=True)
    valid_from = fields.Date("Діє з", required=True, index=True)
    value = fields.Float("Значення", digits=(16, 4), required=True)
    source = fields.Char("Підстава", help="Стаття ПКУ або закон, який встановив значення")
    company_id = fields.Many2one(
        "res.company", "Компанія", help="Порожньо = для всіх компаній")

    _key_from_company_uniq = models.Constraint(
        "unique(key, valid_from, company_id)", "Один параметр на дату."
    )

    @api.model
    def get(self, key, on_date=None, company=None):
        """Значення параметра, чинне на дату. Значення компанії б'є загальне."""
        on_date = on_date or fields.Date.context_today(self)
        domain = [("key", "=", key), ("valid_from", "<=", on_date)]
        if company:
            domain += ["|", ("company_id", "=", company.id), ("company_id", "=", False)]
        record = self.sudo().search(
            domain, order="company_id desc, valid_from desc", limit=1)
        if not record:
            raise UserError(
                "Немає параметра податку на прибуток «%s» на дату %s. Додайте "
                "його в Бухгалтерія → Податок на прибуток → Параметри." % (key, on_date))
        return record.value
