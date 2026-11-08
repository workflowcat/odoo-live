"""Характеристики на товарі: вид, значення, назва за шаблоном, відбиток, маса, одиниці.

Відбиток (ua_component_key) - вид і ключові характеристики в сталому вигляді. Два
товари з однаковим відбитком - дублі: «Болт М8х30 DIN933 8.8 оц» і «болт оцинк. M8*30
кл.8,8 DIN 933» мають один відбиток, хоч назви різні.

Маса прокату рахується з форми перерізу, розмірів і густини марки (теоретична, як у
довідниках сортаменту). З неї модуль робить одиниці конкретного товару: метр, пруток
мірної довжини, лист - щоб купувати в метрах чи листах, а облік вести в кілограмах.
Для кріплення з масою 1000 шт - кілограм, щоб порівнювати прайси в кг і в штуках.
"""
from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from . import component_core as core


class UaComponentValue(models.Model):
    _name = "ua.component.value"
    _description = "Значення характеристики товару"
    _order = "product_tmpl_id, sequence, id"

    product_tmpl_id = fields.Many2one("product.template", "Товар", required=True,
                                      ondelete="cascade", index=True)
    attribute_id = fields.Many2one("ua.component.attribute", "Характеристика", required=True,
                                   ondelete="restrict")
    sequence = fields.Integer(default=10)
    kind = fields.Selection(related="attribute_id.kind")
    unit = fields.Selection(related="attribute_id.unit")
    choice_id = fields.Many2one("ua.component.choice", "Варіант",
                                domain="[('attribute_id', '=', attribute_id)]")
    number = fields.Float("Число", digits=(16, 4))
    text = fields.Char("Текст")
    flag = fields.Boolean("Так")
    value_display = fields.Char("Значення", compute="_compute_value_display")

    _attr_uniq = models.Constraint("unique(product_tmpl_id, attribute_id)",
                                   "Характеристика на товарі вже є.")

    @api.depends("kind", "choice_id", "number", "text", "flag", "attribute_id.unit")
    def _compute_value_display(self):
        units = {code: sym for code, (sym, _d, _f) in core.UNITS.items()}
        for rec in self:
            if rec.kind == "choice":
                rec.value_display = rec.choice_id.name or ""
            elif rec.kind == "number":
                rec.value_display = ("%s %s" % (core.fmt_num(rec.number),
                                                units.get(rec.unit, ""))).strip()
            elif rec.kind == "bool":
                rec.value_display = "так" if rec.flag else "ні"
            else:
                rec.value_display = rec.text or ""

    def _ua_value(self):
        self.ensure_one()
        if self.kind == "choice":
            return self.choice_id.code or None
        if self.kind == "number":
            return self.number if self.number else None
        if self.kind == "bool":
            return self.flag
        return self.text or None


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_component_class_id = fields.Many2one("ua.component.class", "Вид комплектуючих",
                                            index="btree_not_null")
    ua_component_value_ids = fields.One2many("ua.component.value", "product_tmpl_id",
                                             "Характеристики", copy=True)
    ua_component_key = fields.Char(
        "Відбиток", compute="_compute_ua_component", store=True, index="btree_not_null",
        help="Вид і ключові характеристики: однаковий відбиток у двох товарів - це дублі.")
    ua_component_name = fields.Char("Назва за шаблоном", compute="_compute_ua_component",
                                    store=True)
    ua_component_code = fields.Char("Артикул за шаблоном", compute="_compute_ua_component",
                                    store=True)
    ua_component_missing = fields.Char("Бракує", compute="_compute_ua_component", store=True)
    ua_mass_per_m = fields.Float("Маса 1 м, кг", compute="_compute_ua_mass", store=True,
                                 digits=(12, 4))
    ua_mass_per_m2 = fields.Float("Маса 1 м², кг", compute="_compute_ua_mass", store=True,
                                  digits=(12, 4))
    ua_piece_mass = fields.Float("Маса штуки, кг", compute="_compute_ua_mass", store=True,
                                 digits=(12, 4),
                                 help="Пруток чи труба мірної довжини, лист, одна деталь "
                                      "кріплення (з маси 1000 шт).")
    ua_duplicate_count = fields.Integer("Дублів", compute="_compute_ua_duplicate_count")

    # ---------------------------------------------------------------- значення
    def _ua_values(self):
        """{код характеристики: значення} цього товару."""
        self.ensure_one()
        out = {}
        for line in self.ua_component_value_ids:
            value = line._ua_value()
            if value not in (None, "", False):
                out[line.attribute_id.code] = value
        return out

    def _ua_spec_cached(self):
        spec = self.env.context.get("ua_component_spec")
        return spec or self.env["ua.component.class"]._ua_spec()

    @api.depends("ua_component_class_id", "ua_component_class_id.name_template",
                 "ua_component_class_id.code_template", "ua_component_class_id.line_ids.key",
                 "ua_component_class_id.line_ids.required",
                 "ua_component_value_ids.choice_id", "ua_component_value_ids.number",
                 "ua_component_value_ids.text", "ua_component_value_ids.flag")
    def _compute_ua_component(self):
        todo = self.filtered("ua_component_class_id")
        (self - todo).update({"ua_component_key": False, "ua_component_name": False,
                              "ua_component_code": False, "ua_component_missing": False})
        if not todo:
            return
        spec = todo._ua_spec_cached()
        for tmpl in todo:
            cls = tmpl.ua_component_class_id
            values = tmpl._ua_values()
            keys = [line.attribute_id.code for line in cls.line_ids if line.key]
            tmpl.ua_component_key = core.component_key(cls.code, values, keys)
            tmpl.ua_component_name = core.render(spec, cls.name_template, values) or False
            tmpl.ua_component_code = core.render(
                spec, cls.code_template, values, {"prefix": cls._ua_inherited("prefix") or ""},
                for_code=True) or False
            missing = [line.attribute_id.name for line in cls.line_ids
                       if line.required and line.attribute_id.code not in values]
            tmpl.ua_component_missing = ", ".join(missing) or False

    @api.depends("ua_component_class_id", "ua_component_class_id.shape",
                 "ua_component_value_ids.choice_id", "ua_component_value_ids.number")
    def _compute_ua_mass(self):
        for tmpl in self:
            per_m = per_m2 = piece = 0.0
            cls = tmpl.ua_component_class_id
            if cls:
                values = tmpl._ua_values()
                shape = cls._ua_inherited("shape")
                material = tmpl.ua_component_value_ids.filtered(
                    lambda v: v.attribute_id.code == "material").choice_id
                density = material.density
                dims = {k: v for k, v in values.items() if isinstance(v, float)}
                try:
                    if shape == core.SHEET:
                        per_m2 = core.area_mass(dims.get("thickness"), density) or 0.0
                    elif shape:
                        per_m = core.linear_mass(shape, dims, density) or 0.0
                    if shape:
                        piece = core.piece_mass(shape, dims, density) or 0.0
                except ValueError:
                    per_m = per_m2 = piece = 0.0
                if not piece and values.get("mass_1000"):
                    piece = values["mass_1000"] / 1000.0
            tmpl.ua_mass_per_m = per_m
            tmpl.ua_mass_per_m2 = per_m2
            tmpl.ua_piece_mass = piece

    def _compute_ua_duplicate_count(self):
        keyed = self.filtered(lambda t: t.ua_component_key and t.id)
        (self - keyed).ua_duplicate_count = 0
        if not keyed:
            return
        groups = self.with_context(active_test=True)._read_group(
            [("ua_component_key", "in", keyed.mapped("ua_component_key"))],
            ["ua_component_key"], ["__count"])
        counts = dict(groups)
        for tmpl in keyed:
            tmpl.ua_duplicate_count = max(counts.get(tmpl.ua_component_key, 1) - 1, 0)

    # ---------------------------------------------------------------- запис значень
    def _ua_set_values(self, class_code, values, overwrite=False):
        """Ставить вид і значення з розбору ядра ({attr: choice code | число | текст})."""
        Class = self.env["ua.component.class"]
        Choice = self.env["ua.component.choice"]
        cls = Class.search([("code", "=", class_code)], limit=1)
        if not cls:
            raise UserError("Немає виду комплектуючих з кодом «%s»." % class_code)
        for tmpl in self:
            commands = []
            if tmpl.ua_component_class_id != cls:
                tmpl.ua_component_class_id = cls
            have = {v.attribute_id.code: v for v in tmpl.ua_component_value_ids}
            for seq, line in enumerate(cls.line_ids, start=1):
                code = line.attribute_id.code
                if code not in values:
                    continue
                if code in have and not overwrite:
                    continue
                attr = line.attribute_id
                raw = values[code]
                vals = {"attribute_id": attr.id, "sequence": seq * 10}
                if attr.kind == "choice":
                    choice = Choice.search([("attribute_id", "=", attr.id), ("code", "=", raw)],
                                           limit=1)
                    if not choice:
                        continue
                    vals["choice_id"] = choice.id
                elif attr.kind == "number":
                    vals["number"] = float(raw)
                elif attr.kind == "bool":
                    vals["flag"] = bool(raw)
                else:
                    vals["text"] = str(raw)
                if code in have:
                    commands.append(Command.update(have[code].id, vals))
                else:
                    commands.append(Command.create(vals))
            if commands:
                tmpl.ua_component_value_ids = commands
        return True

    def _ua_class_defaults(self):
        """Одиниця, партії, категорія і ДК 021 з виду, якщо на товарі їх ще немає."""
        for tmpl in self.filtered("ua_component_class_id"):
            cls = tmpl.ua_component_class_id
            vals = {}
            categ = cls._ua_inherited("categ_id")
            if categ and tmpl.categ_id != categ and tmpl.categ_id == self.env.ref(
                    "product.product_category_goods", raise_if_not_found=False):
                vals["categ_id"] = categ.id
            if "ua_dk021_id" in tmpl._fields and not tmpl.ua_dk021_id:
                material = tmpl.ua_component_value_ids.filtered(
                    lambda v: v.attribute_id.code == "material").choice_id
                dk = cls._ua_inherited("dk021_id") or material.dk021_id
                if dk:
                    vals["ua_dk021_id"] = dk.id
            tracking = cls._ua_inherited("tracking")
            if tracking and "tracking" in tmpl._fields and tmpl.tracking == "none" \
                    and tmpl.is_storable and tracking != "none":
                vals["tracking"] = tracking
            if vals:
                tmpl.write(vals)

    # ---------------------------------------------------------------- дії
    def action_ua_parse_name(self):
        """Розібрати назву товару в характеристики (порожні не перезаписує)."""
        spec = self.env["ua.component.class"]._ua_spec()
        found = 0
        for tmpl in self:
            result = core.parse(spec, tmpl.name or "")
            if not result["class"]:
                continue
            if tmpl.ua_component_class_id and tmpl.ua_component_class_id.code != result["class"]:
                continue
            tmpl._ua_set_values(result["class"], result["values"])
            tmpl._ua_class_defaults()
            found += 1
        return self._ua_notify("Розібрано назв: %d з %d." % (found, len(self)))

    def action_ua_apply_template(self):
        """Назву й артикул - за шаблоном виду (артикул лише якщо порожній)."""
        for tmpl in self.filtered("ua_component_name"):
            vals = {"name": tmpl.ua_component_name}
            if not tmpl.default_code and tmpl.ua_component_code:
                vals["default_code"] = tmpl.ua_component_code
            tmpl.write(vals)
        return True

    def action_ua_duplicates(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Дублі: %s" % (self.ua_component_name or self.name),
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("ua_component_key", "=", self.ua_component_key)],
        }

    def action_ua_units(self):
        """Одиниці конкретного товару з маси: метр, пруток, м², лист; кг для кріплення."""
        made = []
        for tmpl in self:
            made += tmpl._ua_make_units()
        if not made:
            raise UserError("Немає з чого рахувати одиниці: для прокату потрібні марка і "
                            "розміри (облік у кг), для кріплення - маса 1000 шт (облік у шт).")
        return self._ua_notify("Одиниці: %s." % ", ".join(made))

    def _ua_make_units(self):
        self.ensure_one()
        Uom = self.env["uom.uom"].sudo()
        kg = self.env.ref("uom.product_uom_kgm")
        unit = self.env.ref("uom.product_uom_unit")
        label = self.default_code or self.ua_component_code or self.name
        made = []

        def ensure(name, factor, relative):
            uom = Uom.search([("name", "=", name), ("relative_uom_id", "=", relative.id)],
                             limit=1)
            if uom:
                if abs(uom.relative_factor - factor) > 1e-9:
                    uom.relative_factor = factor
            else:
                uom = Uom.create({"name": name, "relative_factor": factor,
                                  "relative_uom_id": relative.id})
            if uom not in self.uom_ids:
                self.uom_ids = [Command.link(uom.id)]
            made.append(name)
            return uom

        values = self._ua_values()
        if self.uom_id == kg:
            if self.ua_mass_per_m:
                metre = ensure("м (%s)" % label, self.ua_mass_per_m, kg)
                if values.get("stock_length"):
                    ensure("шт %s мм (%s)" % (core.fmt_num(values["stock_length"]), label),
                           values["stock_length"] / 1000.0, metre)
            if self.ua_mass_per_m2:
                square = ensure("м² (%s)" % label, self.ua_mass_per_m2, kg)
                if values.get("width") and values.get("length"):
                    ensure("лист %s×%s (%s)" % (core.fmt_num(values["width"]),
                                                core.fmt_num(values["length"]), label),
                           values["width"] * values["length"] / 1e6, square)
        elif self.uom_id == unit and values.get("mass_1000"):
            ensure("кг (%s)" % label, 1000.0 / values["mass_1000"], unit)
        return made

    def _ua_notify(self, message):
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": message, "type": "info", "sticky": False}}

    def action_ua_analogs(self):
        self.ensure_one()
        finder = self.env["ua.component.analog.finder"].create({"product_tmpl_id": self.id})
        finder.action_search()
        return {
            "type": "ir.actions.act_window",
            "name": "Аналоги: %s" % self.display_name,
            "res_model": "ua.component.analog.finder",
            "res_id": finder.id,
            "view_mode": "form",
            "target": "new",
        }
