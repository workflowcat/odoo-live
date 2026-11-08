"""Дорогоцінні метали у виробах.

Вміст - грами металу на одиницю виміру товару. На купований компонент його беруть з довідкових
даних виробника. Виріб зі специфікацією має вміст своїх складових на всіх рівнях (з урахуванням
кількості, на яку складена специфікація) плюс записане на сам виріб.

Відомість за період рахує рухи складу, перемножені на вміст товару за чинними даними:
надійшло від постачальників, витрачено у виробництві (компоненти), у випущених виробах,
відвантажено клієнтам (мінус повернення), списано (у втрати і брак), на складі зараз.
"""
from collections import defaultdict
from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_DEPTH = 20


def grams_text(value):
    """0.048 -> «0,048»: до мікрограма, без хвостових нулів."""
    text = ("%.6f" % (value or 0.0)).rstrip("0").rstrip(".")
    return (text if text not in ("", "-0") else "0").replace(".", ",")


class UaPreciousMetal(models.Model):
    _name = "ua.precious.metal"
    _description = "Дорогоцінний метал"
    _order = "sequence, id"

    name = fields.Char("Метал", required=True, translate=True)
    code = fields.Char("Символ", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("UNIQUE(code)", "Символ металу має бути унікальним.")


class UaPreciousContent(models.Model):
    _name = "ua.precious.content"
    _description = "Вміст дорогоцінного металу в товарі"
    _order = "product_tmpl_id, metal_id"

    product_tmpl_id = fields.Many2one("product.template", "Товар", required=True, index=True, ondelete="cascade")
    metal_id = fields.Many2one("ua.precious.metal", "Метал", required=True, ondelete="restrict")
    grams = fields.Float("Грамів на одиницю", required=True, digits=(16, 6))
    source = fields.Char("Джерело", help="Звідки число: довідкові дані виробника, креслення, паспорт.")

    _metal_uniq = models.Constraint("UNIQUE(product_tmpl_id, metal_id)", "Метал у товарі - одним рядком.")

    @api.constrains("grams")
    def _check_grams(self):
        for row in self:
            if row.grams <= 0:
                raise ValidationError(_("Вміст металу має бути більший за нуль."))


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_precious_ids = fields.One2many("ua.precious.content", "product_tmpl_id", "Дорогоцінні метали",
                                      help="Власний вміст товару, без складових специфікації.")
    ua_precious_summary = fields.Char("Дорогоцінні метали (разом)", compute="_compute_ua_precious_summary",
                                      help="Разом зі складовими специфікації, грамів на одиницю.")

    def _compute_ua_precious_summary(self):
        for template in self:
            variant = template.product_variant_ids[:1]
            content = variant.ua_precious_content() if variant else {}
            template.ua_precious_summary = "; ".join(
                "%s %s г" % (metal.code, grams_text(content[metal]))
                for metal in sorted(content, key=lambda m: (m.sequence, m.id)))


class ProductProduct(models.Model):
    _inherit = "product.product"

    def ua_precious_content(self, quantity=1.0, _path=()):
        """{метал: грами} у quantity одиниць товару, разом зі складовими специфікації."""
        self.ensure_one()
        if self.id in _path:
            raise UserError(_("Специфікація «%s» містить сама себе.") % self.display_name)
        if len(_path) >= MAX_DEPTH:
            raise UserError(_("Специфікація «%s» глибша за %s рівнів.") % (self.display_name, MAX_DEPTH))
        total = defaultdict(float)
        for row in self.product_tmpl_id.ua_precious_ids:
            total[row.metal_id] += row.grams * quantity
        bom = self.env["mrp.bom"]._bom_find(self).get(self)
        if bom and bom.type in ("normal", "phantom"):
            made = bom.product_uom_id._compute_quantity(bom.product_qty, self.uom_id) or 1.0
            ratio = quantity / made
            for line in bom.bom_line_ids:
                if line._skip_bom_line(self):
                    continue
                part_qty = line.product_uom_id._compute_quantity(line.product_qty, line.product_id.uom_id) * ratio
                for metal, grams in line.product_id.ua_precious_content(part_qty, _path + (self.id,)).items():
                    total[metal] += grams
        return {metal: grams for metal, grams in total.items() if grams}

    def ua_precious_rows(self):
        """Рядки розділу паспорта: метал, символ, грами на один виріб."""
        self.ensure_one()
        content = self.ua_precious_content()
        return [{"name": metal.name, "code": metal.code, "grams": grams_text(content[metal])}
                for metal in sorted(content, key=lambda m: (m.sequence, m.id))]


class StockLot(models.Model):
    _inherit = "stock.lot"

    def ua_precious_rows(self):
        self.ensure_one()
        return self.product_id.ua_precious_rows()


class UaPreciousReport(models.TransientModel):
    _name = "ua.precious.report"
    _description = "Відомість руху дорогоцінних металів"

    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda self: self.env.company)
    date_from = fields.Date("З", required=True,
                            default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date("По", required=True, default=fields.Date.context_today)

    COLUMNS = [("received", "Надійшло від постачальників"), ("consumed", "Витрачено у виробництві"),
               ("produced", "У випущених виробах"), ("shipped", "Відвантажено"), ("written_off", "Списано"),
               ("on_hand", "На складі зараз")]

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for report in self:
            if report.date_to < report.date_from:
                raise ValidationError(_("Кінець періоду раніше за початок."))

    def _ua_kind(self, move):
        source, dest = move.location_id.usage, move.location_dest_id.usage
        if move.raw_material_production_id:
            return "consumed", 1.0
        if move.production_id:
            return "produced", 1.0
        if source == "supplier" and dest == "internal":
            return "received", 1.0
        if dest == "supplier" and source == "internal":
            return "received", -1.0
        if dest == "customer" and source == "internal":
            return "shipped", 1.0
        if source == "customer" and dest == "internal":
            return "shipped", -1.0
        if dest == "inventory" and source == "internal":
            return "written_off", 1.0
        return None, 0.0

    def ua_rows(self):
        """Рядок на кожен метал, що трапився: {"metal", "code", колонка: текст грамів}."""
        self.ensure_one()
        cache = {}

        def content(product):
            if product not in cache:
                cache[product] = product.ua_precious_content()
            return cache[product]

        sums = defaultdict(lambda: defaultdict(float))
        start = datetime.combine(self.date_from, time.min)
        end = datetime.combine(self.date_to, time.max)
        moves = self.env["stock.move"].sudo().search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("date", ">=", start), ("date", "<=", end)])
        for move in moves:
            if not content(move.product_id):
                continue
            kind, sign = self._ua_kind(move)
            if not kind:
                continue
            quantity = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id) * sign
            for metal, grams in content(move.product_id).items():
                sums[metal][kind] += grams * quantity
        quants = self.env["stock.quant"].sudo().search([
            ("company_id", "=", self.company_id.id), ("location_id.usage", "=", "internal")])
        for quant in quants:
            for metal, grams in content(quant.product_id).items():
                sums[metal]["on_hand"] += grams * quant.quantity
        rows = []
        for metal in sorted(sums, key=lambda m: (m.sequence, m.id)):
            row = {"metal": metal.name, "code": metal.code}
            row.update({key: grams_text(sums[metal][key]) for key, _label in self.COLUMNS})
            rows.append(row)
        return rows

    def ua_date(self, day):
        return day.strftime("%d.%m.%Y") if day else ""

    def action_print(self):
        self.ensure_one()
        return self.env.ref("l10n_ua_precious_metals.action_report_ua_precious").report_action(self)
