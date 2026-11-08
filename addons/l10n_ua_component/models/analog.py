"""Аналоги (заміни) комплектуючих: пошук за характеристиками і перелік погоджених.

Пошук бере товари того ж виду і порівнює ключові характеристики за правилом рядка виду:
- «має збігатися» - різьба, довжина;
- «збіг або відповідник» - стандарт чи марка з однієї групи відповідностей
  (DIN 933 = ISO 4017, 40Х = 41Cr4);
- «не нижче» - клас міцності 10.9 замість 8.8, струмовіддача батареї;
- «не важливо» - не порівнюється.
Рівень: «повна заміна» - усе збіглося або відповідник повний; «з перевіркою» - є
що звірити (розмір під ключ DIN 933 і ISO 4017 для М10, вища міцність, примітка групи).

Знайдене можна зберегти в перелік аналогів (аналог 1С «Аналоги номенклатури») і
запропонувати на рядки специфікацій, якщо стоїть l10n_ua_mrp_substitute: там заміну
погоджує керівник виробництва, тут вона лише пропонується.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from . import component_core as core
from .classifier import LEVELS


class UaComponentAnalog(models.Model):
    _name = "ua.component.analog"
    _description = "Аналог комплектуючого"
    _order = "product_tmpl_id, sequence, id"

    product_tmpl_id = fields.Many2one("product.template", "Товар", required=True,
                                      ondelete="cascade", index=True)
    analog_tmpl_id = fields.Many2one("product.template", "Аналог", required=True,
                                     ondelete="cascade", index=True)
    sequence = fields.Integer("Пріоритет", default=10)
    level = fields.Selection(LEVELS, "Заміна", required=True, default="check")
    reason = fields.Text("Що звірити")
    source = fields.Selection([("rule", "За характеристиками"), ("manual", "Вручну"),
                               ("supplier", "Від постачальника")], "Звідки", default="manual",
                              required=True)
    note = fields.Char("Підстава", help="Лист конструктора, рішення представника замовника.")

    _pair_uniq = models.Constraint("unique(product_tmpl_id, analog_tmpl_id)",
                                   "Такий аналог уже записано.")

    @api.constrains("product_tmpl_id", "analog_tmpl_id")
    def _check_self(self):
        for rec in self:
            if rec.product_tmpl_id == rec.analog_tmpl_id:
                raise UserError("Товар не може бути аналогом сам собі.")


class UaComponentAnalogFinder(models.TransientModel):
    _name = "ua.component.analog.finder"
    _description = "Пошук аналогів"

    product_tmpl_id = fields.Many2one("product.template", "Товар", required=True)
    line_ids = fields.One2many("ua.component.analog.finder.line", "finder_id", "Можливі заміни")
    include_check = fields.Boolean("Показувати заміни з перевіркою", default=True)

    def action_search(self):
        self.ensure_one()
        self.line_ids.unlink()
        rows = self.product_tmpl_id._ua_find_analogs(include_check=self.include_check)
        self.line_ids = [(0, 0, row) for row in rows]
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}


class UaComponentAnalogFinderLine(models.TransientModel):
    _name = "ua.component.analog.finder.line"
    _description = "Можлива заміна"
    _order = "level desc, qty_available desc, id"

    finder_id = fields.Many2one("ua.component.analog.finder", required=True, ondelete="cascade")
    analog_tmpl_id = fields.Many2one("product.template", "Аналог", required=True)
    level = fields.Selection(LEVELS, "Заміна")
    reason = fields.Text("Що звірити")
    source = fields.Selection([("rule", "За характеристиками"), ("manual", "Вручну"),
                               ("supplier", "Від постачальника")], "Звідки")
    qty_available = fields.Float("Залишок", digits="Product Unit")
    saved = fields.Boolean("У переліку")

    def action_save(self):
        """Записати в перелік аналогів товару (і зворотний запис для повної заміни)."""
        Analog = self.env["ua.component.analog"]
        for line in self:
            tmpl = line.finder_id.product_tmpl_id
            pairs = [(tmpl, line.analog_tmpl_id)]
            if line.level == "full":
                pairs.append((line.analog_tmpl_id, tmpl))
            for a, b in pairs:
                if not Analog.search_count([("product_tmpl_id", "=", a.id),
                                            ("analog_tmpl_id", "=", b.id)]):
                    Analog.create({"product_tmpl_id": a.id, "analog_tmpl_id": b.id,
                                   "level": line.level, "reason": line.reason or False,
                                   "source": "rule" if line.source == "rule" else line.source})
            line.saved = True
        return self.finder_id.action_search()

    def action_propose_bom(self):
        """Запропонувати аналог на рядки специфікацій з цим товаром (без погодження)."""
        if "ua.bom.substitute" not in self.env:
            raise UserError("Аналоги в специфікаціях веде модуль «погоджені аналоги компонентів "
                            "у виробництві» (l10n_ua_mrp_substitute): встановіть його.")
        Sub = self.env["ua.bom.substitute"]
        added = 0
        for line in self:
            tmpl = line.finder_id.product_tmpl_id
            bom_lines = self.env["mrp.bom.line"].search(
                [("product_id", "in", tmpl.product_variant_ids.ids)])
            analog = line.analog_tmpl_id.product_variant_id
            for bom_line in bom_lines:
                if Sub.search_count([("bom_line_id", "=", bom_line.id),
                                     ("product_id", "=", analog.id)]):
                    continue
                Sub.create({"bom_line_id": bom_line.id, "product_id": analog.id,
                            "factor": 1.0, "sequence": 50,
                            "note": (line.reason or "")[:250] or False})
                added += 1
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": "Запропоновано на рядках специфікацій: %d. "
                                      "Заміну погоджує керівник виробництва." % added,
                           "type": "info", "sticky": False}}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_analog_ids = fields.One2many("ua.component.analog", "product_tmpl_id", "Аналоги")

    def _ua_find_analogs(self, include_check=True):
        """Можливі заміни товару: правила виду + записаний перелік. Список словників."""
        self.ensure_one()
        rows = {}
        for analog in self.ua_analog_ids:
            rows[analog.analog_tmpl_id.id] = {
                "analog_tmpl_id": analog.analog_tmpl_id.id, "level": analog.level,
                "reason": analog.reason or False, "source": analog.source, "saved": True}
        cls = self.ua_component_class_id
        if cls:
            Class = self.env["ua.component.class"]
            spec = Class._ua_spec()
            groups = Class._ua_groups()
            lines = {line.attribute_id.code: {"rule": line.rule, "key": line.key}
                     for line in cls.line_ids}
            mine = self._ua_values()
            company = self.company_id or self.env.company
            candidates = self.search([
                ("ua_component_class_id", "=", cls.id), ("id", "!=", self.id),
                ("company_id", "in", [company.id, False])])
            for cand in candidates:
                if cand.id in rows:
                    continue
                result = core.compare(spec, lines, mine, cand._ua_values(), groups)
                if not result:
                    continue
                level, reasons = result
                if cand.ua_component_key and cand.ua_component_key == self.ua_component_key:
                    reasons = ["той самий виріб під іншою назвою (дубль)"] + reasons
                if level == "check" and not include_check:
                    continue
                rows[cand.id] = {"analog_tmpl_id": cand.id, "level": level,
                                 "reason": "\n".join(reasons) or False, "source": "rule",
                                 "saved": False}
        stock = "qty_available" in self._fields
        out = []
        for row in rows.values():
            tmpl = self.browse(row["analog_tmpl_id"])
            row["qty_available"] = tmpl.qty_available if stock else 0.0
            out.append(row)
        out.sort(key=lambda r: (r["level"] != "full", -r["qty_available"]))
        return out
