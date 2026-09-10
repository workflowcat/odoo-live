# -*- coding: utf-8 -*-
"""Індекси споживчих цін Держстату: один рядок на місяць.

Значення - індекс до попереднього місяця у відсотках, як публікує Держстат (наприклад 100,5).
Індексацію рахують за наростаючим підсумком цих індексів з місяця, наступного за базовим
(Постанова КМУ № 1078 від 17.07.2003).

Числа вносить бухгалтер: у системі немає джерела, яке можна довіряти автоматично.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}


class UaCpiIndex(models.Model):
    _name = "ua.cpi.index"
    _description = "Індекс споживчих цін за місяць"
    _order = "year desc, month desc"

    year = fields.Integer("Рік", required=True)
    month = fields.Integer("Місяць", required=True)
    value = fields.Float("Індекс, %", required=True, digits=(6, 2),
                         help="Індекс споживчих цін до попереднього місяця, як публікує Держстат. 100,0 - без зміни.")
    name = fields.Char("Період", compute="_compute_name", store=True)
    note = fields.Char("Джерело")

    _year_month_uniq = models.Constraint("UNIQUE(year, month)", "Індекс за цей місяць уже є.")

    @api.depends("year", "month")
    def _compute_name(self):
        for record in self:
            record.name = "%s %s" % (MONTHS_UA.get(record.month, record.month), record.year)

    @api.constrains("month", "value")
    def _check_values(self):
        for record in self:
            if not 1 <= record.month <= 12:
                raise ValidationError(self.env._("Місяць має бути від 1 до 12."))
            if record.value <= 0:
                raise ValidationError(self.env._("Індекс має бути більший за нуль (Держстат публікує близько 100)."))

    @api.model
    def get_map(self, date_from, date_to):
        """{(рік, місяць): індекс} за період включно."""
        records = self.search([
            "|", ("year", ">", date_from.year),
            "&", ("year", "=", date_from.year), ("month", ">=", date_from.month),
        ])
        out = {}
        for record in records:
            if (record.year, record.month) <= (date_to.year, date_to.month):
                out[(record.year, record.month)] = record.value
        return out
