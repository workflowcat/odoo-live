# -*- coding: utf-8 -*-
"""Код одиниці виміру за КСПОВО (ДК 011-96) для граф 4 і 5 податкової накладної.

Графа 4 - умовне позначення українською («шт», «кг»), графа 5 - чотиризначний
код. Стандартним одиницям Odoo коди ставить `_ua_kspovo_seed` під час
встановлення і оновлення модуля, лише якщо поле порожнє: ручну правку не
перезаписує. Коди звірено з текстом ДК 011-96 у двох незалежних джерелах.

Послуга за вартістю - «грн», код 2454. Одиниці без коду в ПН не потрапляють
у графу 5, тому експорт підставляє «штуку» лише для товарів без власного коду.
"""
from odoo import api, fields, models

# xmlid одиниці Odoo -> (код КСПОВО, позначення українською).
UA_KSPOVO_BY_XMLID = {
    "uom.product_uom_unit": ("2009", "шт"),
    "uom.product_uom_dozen": ("2011", "дюж.шт"),
    "uom.product_uom_hour": ("0175", "год"),
    "uom.product_uom_day": ("0174", "доб"),
    "uom.product_uom_minute": ("0176", "хв"),
    "uom.product_uom_millimeter": ("0105", "мм"),
    "uom.product_uom_cm": ("0104", "см"),
    "uom.product_uom_meter": ("0101", "м"),
    "uom.product_uom_km": ("0102", "км"),
    "uom.product_uom_square_meter": ("0123", "м2"),
    "uom.product_uom_milliliter": ("0144", "мл"),
    "uom.product_uom_litre": ("0138", "л"),
    "uom.product_uom_cubic_meter": ("0134", "м3"),
    "uom.product_uom_gram": ("0303", "г"),
    "uom.product_uom_kgm": ("0301", "кг"),
    "uom.product_uom_ton": ("0306", "т"),
    "uom.product_uom_kwh": ("0415", "кВт·год"),
}


class UomUom(models.Model):
    _inherit = "uom.uom"

    ua_kspovo_code = fields.Char(
        "Код КСПОВО", size=4,
        help="Чотиризначний код за ДК 011-96, графа 5 податкової накладної. "
             "Штука 2009, кілограм 0301, година 0175, гривня 2454.")
    ua_kspovo_short = fields.Char(
        "Позначення КСПОВО",
        help="Умовне позначення українською для графи 4 податкової накладної: "
             "шт, кг, год. Порожньо - береться назва одиниці.")

    @api.model
    def _ua_kspovo_seed(self):
        """Ставить коди стандартним одиницям, якщо їх ще не заповнено."""
        for xmlid, (code, short) in UA_KSPOVO_BY_XMLID.items():
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if not uom:
                continue
            vals = {}
            if not uom.ua_kspovo_code:
                vals["ua_kspovo_code"] = code
            if not uom.ua_kspovo_short:
                vals["ua_kspovo_short"] = short
            if vals:
                uom.sudo().write(vals)
        return True

    def _ua_pn_unit(self, default_code="2009", default_short="шт"):
        """(позначення, код) для граф 4 і 5 ПН."""
        if not self:
            return default_short, default_code
        self.ensure_one()
        return (self.ua_kspovo_short or self.name or default_short,
                self.ua_kspovo_code or default_code)
