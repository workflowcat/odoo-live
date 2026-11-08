"""Законодавчі числа ФОП з датою початку дії.

Мінімальна зарплата, ставки ЄП, ВЗ і ЄСВ, множник річного ліміту - усе це
змінюється законом раз на рік або частіше. Тому воно лежить тут датованими
записами, а не константами в коді: новий рік - новий рядок даних.
Модель повторює контракт ua.payroll.param із l10n_ua_payroll_rules, але
залежності від зарплати немає: ФОП ставиться сам по собі.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class UaFopParam(models.Model):
    _name = "ua.fop.param"
    _description = "Параметр ФОП (Україна)"
    _order = "key, valid_from desc"

    key = fields.Char("Код", required=True, index=True)
    name = fields.Char("Назва", required=True)
    valid_from = fields.Date("Діє з", required=True, index=True)
    value = fields.Float("Значення", digits=(16, 4), required=True)
    source = fields.Char("Підстава", help="Закон або стаття, яка встановила значення")
    company_id = fields.Many2one("res.company", "Компанія", help="Порожньо = для всіх компаній")

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
        # Значення компанії б'є загальне. Не сортуємо за company_id: у PostgreSQL порожні
        # значення при DESC ідуть першими, і загальний запис перемагав би.
        rec = self.sudo().search(domain, order="valid_from desc, id desc")
        rec = rec.filtered("company_id")[:1] or rec[:1]
        if not rec:
            raise UserError(
                "Немає параметра ФОП «%s» на дату %s. Додайте його в "
                "Бухгалтерія → ФОП → Параметри." % (key, on_date)
            )
        return rec.value
