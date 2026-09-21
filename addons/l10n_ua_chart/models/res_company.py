# -*- coding: utf-8 -*-
"""Валюта компанії змінилася - типовий прайс-лист іде за нею.

`product` створює прайс-лист «Default» у валюті компанії на момент створення і більше до
цього не повертається. На чистій базі порядок звичайний: спершу ставлять модулі (компанія
ще в доларі, прайс-лист створюється доларовим), потім завантажують план ua_psbo, і валютою
компанії стає гривня. Прайс-лист лишається доларовим, а валюта замовлення на продаж -
related до прайс-листа, тому кожне замовлення мовчки виходить у доларах.

Ловимо це там, де воно стається: у момент запису валюти. Стару валюту тут ще видно, тому
переводимо рівно ті прайс-листи, які були в ній і не мають жодного правила. Експортний
прайс-лист в іншій валюті (його заводять свідомо) лишається як є.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    def write(self, vals):
        before = {}
        if vals.get("currency_id") and "product.pricelist" in self.env:
            before = {company.id: company.currency_id for company in self}
        result = super().write(vals)
        for company in self:
            old = before.get(company.id)
            if not old or old == company.currency_id or not company.currency_id:
                continue
            stale = self.env["product.pricelist"].sudo().with_context(active_test=False).search([
                ("company_id", "=", company.id),
                ("currency_id", "=", old.id),
                ("item_ids", "=", False),
            ])
            if stale:
                stale.currency_id = company.currency_id
                _logger.info("Прайс-листів переведено з %s у %s: %d",
                             old.name, company.currency_id.name, len(stale))
        return result
