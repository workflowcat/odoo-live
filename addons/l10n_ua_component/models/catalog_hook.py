"""Галузеві пакети з характеристиками: товар у пакеті описується видом і значеннями.

    {"key": "b_m8x30", "component": {"parse": "Болт М8х30 DIN 933 8.8 цинк"}}
    {"key": "rod40", "component": {"class": "bar_round",
                                   "values": {"material": "d16t", "diameter": 40}}}

Назва, якщо її немає в пакеті, складається за шаблоном виду; значення ставляться на
товар разом з одиницею обліку, партіями і ДК 021 з виду.
"""
from odoo import api, models
from odoo.exceptions import UserError

from . import component_core as core


class UaCatalog(models.AbstractModel):
    _inherit = "ua.catalog"

    @api.model
    def _ua_pack_component(self, pack, item):
        comp = item.get("component") or {}
        spec = self.env["ua.component.class"]._ua_spec()
        cls = comp.get("class")
        values = {}
        if comp.get("parse"):
            result = core.parse(spec, comp["parse"])
            cls = cls or result["class"]
            values.update(result["values"])
        values.update(comp.get("values") or {})
        if cls not in spec.classes:
            raise UserError("Пакет %s, товар «%s»: вид комплектуючих не визначено."
                            % (pack, item.get("key")))
        return spec, cls, values

    @api.model
    def _ua_pack_product_name(self, pack, item):
        if item.get("component") and not item.get("name"):
            spec, cls, values = self._ua_pack_component(pack, item)
            name = core.render(spec, spec.classes[cls]["name_template"], values)
            if name:
                return name
        return super()._ua_pack_product_name(pack, item)

    @api.model
    def _ua_pack_product_after(self, tmpl, item, mode):
        if item.get("component"):
            _spec, cls, values = self._ua_pack_component("", item)
            tmpl._ua_set_values(cls, values, overwrite=(mode == "update"))
            tmpl._ua_class_defaults()
        return super()._ua_pack_product_after(tmpl, item, mode)
