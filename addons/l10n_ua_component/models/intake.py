"""Розбір номенклатури: з наявних товарів або з файла 1С - у класифікатор.

Перший крок прийому компанії: номенклатура з 1С зазвичай має дублі («Болт М8х30
DIN933 8.8 оц» і «болт оцинк. M8*30 кл.8,8 DIN 933»), різні написання і порожні
характеристики. Документ розбору:
1. «Розібрати» - кожна назва йде через розбір ядра: вид, характеристики, назва й
   артикул за шаблоном, відбиток; рядки з однаковим відбитком - одна група, перший -
   основний, решта - дублі; наявний товар з тим самим відбитком теж ловиться.
2. Людина переглядає: знімає позначку «Застосувати» з сумнівних рядків.
3. «Застосувати» - для товарів ставить вид і характеристики (за бажанням і назву за
   шаблоном), дублі без руху архівує; для файла - створює товари, крім дублів і вже
   наявних.
Документ лишається як протокол: що було, що стало, що треба доробити руками.
"""
import base64
import json

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import component_core as core
from . import table_io

STATES = [("draft", "Чернетка"), ("parsed", "Розібрано"), ("applied", "Застосовано")]
STATUSES = [("ok", "Розібрано"), ("partial", "Частково"), ("unknown", "Не розібрано"),
            ("duplicate", "Дубль"), ("exists", "Вже є")]
NAME_WORDS = ("найменування", "наименование", "назва", "название", "номенклатура", "товар",
              "name")
CODE_WORDS = ("артикул", "код", "sku", "code")
UNIT_WORDS = ("од.", "од", "одиниц", "ед.", "ед", "единиц", "unit")


class UaComponentIntake(models.Model):
    _name = "ua.component.intake"
    _description = "Розбір номенклатури"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Номер", required=True, default="Новий розбір", tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    source = fields.Selection([("products", "Наявні товари"), ("file", "Файл з 1С чи Excel")],
                              "Що розбираємо", default="products", required=True)
    categ_id = fields.Many2one("product.category", "Лише категорія")
    only_unclassified = fields.Boolean("Лише без виду", default=True)
    file = fields.Binary("Файл", attachment=False)
    file_name = fields.Char("Назва файла")
    rename = fields.Boolean("Перейменувати за шаблоном",
                            help="Назва товару стане назвою за шаблоном виду, порожній "
                                 "артикул - артикулом за шаблоном.")
    archive_duplicates = fields.Boolean(
        "Архівувати дублі без руху",
        help="Дубль, на якому немає складського руху, закупівель і специфікацій, "
             "архівується. Дублі з рухом лишаються - їх об'єднують вручну.")
    min_confidence = fields.Float("Застосовувати від", default=1.0,
                                  help="Частка обов'язкових характеристик, яку розбір "
                                       "мусить знайти, щоб рядок позначився до застосування.")
    line_ids = fields.One2many("ua.component.intake.line", "intake_id", "Рядки")
    count_total = fields.Integer("Усього", compute="_compute_counts")
    count_ok = fields.Integer("Розібрано", compute="_compute_counts")
    count_partial = fields.Integer("Частково", compute="_compute_counts")
    count_unknown = fields.Integer("Не розібрано", compute="_compute_counts")
    count_duplicate = fields.Integer("Дублів", compute="_compute_counts")
    summary = fields.Text("Підсумок", readonly=True)

    @api.depends("line_ids.status")
    def _compute_counts(self):
        for rec in self:
            statuses = rec.line_ids.mapped("status")
            rec.count_total = len(statuses)
            rec.count_ok = statuses.count("ok")
            rec.count_partial = statuses.count("partial")
            rec.count_unknown = statuses.count("unknown")
            rec.count_duplicate = statuses.count("duplicate") + statuses.count("exists")

    # ---------------------------------------------------------------- джерела
    def _ua_source_rows(self):
        """[(назва, артикул, одиниця, товар або None)]."""
        self.ensure_one()
        if self.source == "products":
            domain = [("company_id", "in", [self.company_id.id, False])]
            if self.categ_id:
                domain.append(("categ_id", "child_of", self.categ_id.id))
            if self.only_unclassified:
                domain.append(("ua_component_class_id", "=", False))
            products = self.env["product.template"].search(domain, order="id")
            return [(p.name, p.default_code or "", p.uom_id.name, p) for p in products]
        if not self.file:
            raise UserError("Додайте файл: вивантаження номенклатури з 1С (CSV) чи Excel.")
        rows, header = table_io.read_table(base64.b64decode(self.file), self.file_name)
        if header is None:
            col_name, col_code, col_unit, body = 0, None, None, rows
        else:
            head = rows[header]
            col_name = table_io.guess_column(head, NAME_WORDS)
            col_code = table_io.guess_column(head, CODE_WORDS, {col_name})
            col_unit = table_io.guess_column(head, UNIT_WORDS, {col_name, col_code})
            if col_name is None:
                raise UserError("Не знайшов колонку з назвою: назвіть її «Найменування».")
            body = rows[header + 1:]

        def cell(row, i):
            return row[i].strip() if i is not None and i < len(row) and row[i] else ""

        return [(cell(r, col_name), cell(r, col_code), cell(r, col_unit), None)
                for r in body if cell(r, col_name)]

    # ---------------------------------------------------------------- розбір
    def action_parse(self):
        for intake in self:
            intake._ua_parse()
        return True

    def _ua_parse(self):
        self.ensure_one()
        spec = self.env["ua.component.class"]._ua_spec()
        classes = {c.code: c for c in self.env["ua.component.class"].search([])}
        self.line_ids.unlink()
        vals_list = []
        for seq, (name, code, unit, product) in enumerate(self._ua_source_rows(), start=1):
            result = core.parse(spec, name)
            cls = classes.get(result["class"])
            vals = {"intake_id": self.id, "sequence": seq, "raw_name": name[:250],
                    "raw_code": code or False, "raw_unit": unit or False,
                    "product_tmpl_id": product.id if product else False,
                    "confidence": result["confidence"]}
            if cls:
                values = result["values"]
                keys = [line.attribute_id.code for line in cls.line_ids if line.key]
                vals.update({
                    "class_id": cls.id,
                    "values_json": json.dumps(values, ensure_ascii=False, sort_keys=True),
                    "proposed_name": core.render(spec, cls.name_template, values) or False,
                    "proposed_code": core.render(
                        spec, cls.code_template, values,
                        {"prefix": cls._ua_inherited("prefix") or ""}, for_code=True) or False,
                    "key": core.component_key(cls.code, values, keys),
                    "missing": ", ".join(
                        (spec.attributes.get(a) or {}).get("name", a)
                        for a in result["missing"]) or False,
                    "status": "ok" if result["confidence"] >= 1.0 else "partial",
                })
            else:
                vals["status"] = "unknown"
            vals["apply"] = vals["status"] == "ok" or (
                vals["status"] == "partial" and result["confidence"] >= self.min_confidence)
            vals_list.append(vals)
        lines = self.env["ua.component.intake.line"].create(vals_list)
        self._ua_mark_duplicates(lines)
        self.state = "parsed"
        self.summary = self._ua_summary()
        return True

    def _ua_mark_duplicates(self, lines):
        """Групи з однаковим відбитком: перший рядок основний, решта - дублі."""
        keyed = lines.filtered("key")
        Tmpl = self.env["product.template"]
        existing = {}
        for tmpl in Tmpl.search([("ua_component_key", "in", list(set(keyed.mapped("key")))),
                                 ("company_id", "in", [self.company_id.id, False])],
                                order="id"):
            existing.setdefault(tmpl.ua_component_key, tmpl)
        first = {}
        for line in keyed.sorted("sequence"):
            same_product = existing.get(line.key)
            if same_product and same_product != line.product_tmpl_id:
                line.write({"status": "exists", "duplicate_of_id": same_product.id,
                            "apply": True})
                continue
            if line.key in first:
                line.write({"status": "duplicate", "duplicate_line_id": first[line.key].id,
                            "apply": True})
            else:
                first[line.key] = line
        for key, line in first.items():
            line.group_size = len(keyed.filtered(lambda x, k=key: x.key == k))

    def _ua_summary(self):
        self.ensure_one()
        by_class = {}
        for line in self.line_ids.filtered("class_id"):
            by_class[line.class_id.complete_name] = by_class.get(line.class_id.complete_name, 0) + 1
        rows = ["%s: %d" % (name, n) for name, n in sorted(by_class.items(), key=lambda x: -x[1])]
        head = ("Рядків %d: розібрано %d, частково %d, не розібрано %d, дублів %d."
                % (self.count_total, self.count_ok, self.count_partial, self.count_unknown,
                   self.count_duplicate))
        return "\n".join([head] + rows)

    # ---------------------------------------------------------------- застосування
    def action_apply(self):
        for intake in self:
            if intake.state != "parsed":
                raise UserError("Спершу розберіть номенклатуру.")
            if intake.source == "products":
                intake._ua_apply_products()
            else:
                intake._ua_apply_file()
            intake.state = "applied"
            intake.summary = intake._ua_summary() + "\n" + intake._ua_result_summary()
        return True

    def _ua_spec_env(self):
        return self.env["product.template"].with_context(
            ua_component_spec=self.env["ua.component.class"]._ua_spec())

    def _ua_apply_products(self):
        Tmpl = self._ua_spec_env()
        for line in self.line_ids.filtered(lambda x: x.apply and x.class_id and x.product_tmpl_id):
            tmpl = Tmpl.browse(line.product_tmpl_id.id)
            if line.status in ("duplicate", "exists"):
                target = line.duplicate_of_id or line.duplicate_line_id.product_tmpl_id
                tmpl._ua_set_values(line.class_id.code, line._ua_values())
                if self.archive_duplicates and target and not tmpl._ua_has_activity():
                    tmpl.active = False
                    line.result = "архівовано: дубль «%s»" % target.display_name
                else:
                    line.result = "дубль «%s»%s" % (
                        target.display_name if target else "",
                        ": є рух, об'єднайте вручну" if tmpl._ua_has_activity() else "")
                continue
            tmpl._ua_set_values(line.class_id.code, line._ua_values())
            tmpl._ua_class_defaults()
            if self.rename and tmpl.ua_component_name:
                tmpl.action_ua_apply_template()
            line.result = "вид і характеристики поставлено"

    def _ua_apply_file(self):
        Tmpl = self._ua_spec_env()
        unit = self.env.ref("uom.product_uom_unit")
        for line in self.line_ids.filtered(lambda x: x.apply).sorted("sequence"):
            if line.status == "exists":
                line.product_tmpl_id = line.duplicate_of_id
                line.result = "вже є: %s" % line.duplicate_of_id.display_name
                continue
            if line.status == "duplicate":
                main = line.duplicate_line_id
                if not main.product_tmpl_id:
                    line.result = "дубль рядка %d, який не застосовано" % main.sequence
                    continue
                line.product_tmpl_id = main.product_tmpl_id
                line.result = "дубль рядка %d" % main.sequence
                continue
            uom = line.class_id._ua_inherited("uom_id") or unit if line.class_id else unit
            name = line.proposed_name if (self.rename and line.proposed_name) else line.raw_name
            vals = {"name": name, "company_id": self.company_id.id, "uom_id": uom.id,
                    "type": "consu", "default_code": line.raw_code or (
                        line.proposed_code if self.rename else False) or False}
            if "is_storable" in Tmpl._fields:
                vals["is_storable"] = True
            tmpl = Tmpl.create(vals)
            if line.class_id:
                tmpl._ua_set_values(line.class_id.code, line._ua_values())
                tmpl._ua_class_defaults()
            line.product_tmpl_id = tmpl
            line.result = "створено"

    def _ua_result_summary(self):
        results = self.line_ids.filtered("result").mapped("result")
        created = sum(1 for r in results if r == "створено")
        archived = sum(1 for r in results if r.startswith("архівовано"))
        manual = sum(1 for r in results if "вручну" in r)
        return "Створено %d, архівовано дублів %d, дублів з рухом %d." % (created, archived, manual)

    def action_lines(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.name,
                "res_model": "ua.component.intake.line", "view_mode": "list",
                "domain": [("intake_id", "=", self.id)]}


class UaComponentIntakeLine(models.Model):
    _name = "ua.component.intake.line"
    _description = "Рядок розбору номенклатури"
    _order = "intake_id, sequence, id"

    intake_id = fields.Many2one("ua.component.intake", required=True, ondelete="cascade",
                                index=True)
    sequence = fields.Integer("№")
    raw_name = fields.Char("Назва як була", required=True)
    raw_code = fields.Char("Артикул як був")
    raw_unit = fields.Char("Одиниця як була")
    product_tmpl_id = fields.Many2one("product.template", "Товар")
    class_id = fields.Many2one("ua.component.class", "Вид")
    values_json = fields.Text("Характеристики (JSON)")
    values_display = fields.Char("Характеристики", compute="_compute_values_display")
    confidence = fields.Float("Повнота", digits=(3, 2))
    missing = fields.Char("Бракує")
    proposed_name = fields.Char("Назва за шаблоном")
    proposed_code = fields.Char("Артикул за шаблоном")
    key = fields.Char("Відбиток", index=True)
    status = fields.Selection(STATUSES, "Результат розбору")
    duplicate_line_id = fields.Many2one("ua.component.intake.line", "Дубль рядка")
    duplicate_of_id = fields.Many2one("product.template", "Дубль товару")
    group_size = fields.Integer("Написань")
    apply = fields.Boolean("Застосувати")
    result = fields.Char("Що зроблено", readonly=True)

    def _ua_values(self):
        self.ensure_one()
        try:
            return json.loads(self.values_json or "{}")
        except ValueError:
            return {}

    @api.depends("values_json")
    def _compute_values_display(self):
        for line in self:
            values = line._ua_values()
            line.values_display = "; ".join(
                "%s=%s" % (k, core.fmt_num(v) if isinstance(v, float) else v)
                for k, v in sorted(values.items())) or False


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _ua_has_activity(self):
        """Чи є на товарі рух: склад, закупівлі, продажі, специфікації."""
        self.ensure_one()
        variants = self.with_context(active_test=False).product_variant_ids.ids
        checks = [("stock.move", "product_id"), ("purchase.order.line", "product_id"),
                  ("sale.order.line", "product_id"), ("mrp.bom.line", "product_id"),
                  ("account.move.line", "product_id")]
        for model, field in checks:
            if model in self.env and self.env[model].sudo().search_count(
                    [(field, "in", variants)], limit=1):
                return True
        if "mrp.bom" in self.env and self.env["mrp.bom"].sudo().search_count(
                [("product_tmpl_id", "=", self.id)], limit=1):
            return True
        return False
