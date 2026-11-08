"""Класифікатор комплектуючих: характеристики, варіанти, види, відповідності.

Аналог видів номенклатури і додаткових реквізитів 1С/BAS: вид каже, які
характеристики має виріб, як скласти назву й артикул, у чому його обліковувати.
Довідник спільний для всіх компаній (як ДК 021): болт М8×30 DIN 933 однаковий скрізь.

Базовий довідник лежить у data/classifier.json і завантажується під час встановлення та
оновлення модуля: записи з файла оновлюються з файла, власні записи (з кодом, якого
у файлі немає) не чіпаються.
"""
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import file_path

from . import component_core as core

SOURCE = "l10n_ua_component/data/classifier.json"

KINDS = [("number", "Число"), ("choice", "Вибір"), ("text", "Текст"), ("bool", "Так/ні")]
UNIT_SELECTION = [(code, sym) for code, (sym, _dim, _f) in core.UNITS.items()]
MEASURES = [("piece", "Штуки"), ("mass", "Маса"), ("length", "Довжина"),
            ("area", "Площа"), ("volume", "Об'єм")]
SHAPES = [("round", "Круг"), ("hex", "Шестигранник"), ("square", "Квадрат"),
          ("flat", "Смуга"), ("sheet", "Лист"), ("pipe", "Труба кругла"),
          ("rect_pipe", "Труба профільна"), ("angle", "Кутник"), ("wire", "Дріт")]
RECIPE_LABELS = {
    "thread_length": "Різьба і довжина (М10х40)",
    "tap": "Різьба мітчика",
    "sheet": "Лист: товщина, ширина, довжина",
    "angle": "Кутник: полиці і товщина",
    "rivet": "Заклепка: діаметр і довжина",
    "drill": "Свердло: діаметр",
    "endmill": "Фреза: діаметр, зуби, радіус",
    "insert": "Пластина за ISO 1832",
    "disc": "Круг: діаметр, товщина, отвір",
    "bearing": "Підшипник: номер і ущільнення",
    "oring": "Кільце: діаметр і переріз",
    "motor": "Мотор: статор і KV",
    "prop": "Пропелер: діаметр, крок, лопаті",
    "battery": "Батарея: банки, ємність, віддача",
    "esc": "Регулятор: струм",
    "awg": "Провід: переріз AWG",
    "cable": "Кабель: жили і переріз",
    "range": "Діапазон вимірювання і ціна поділки",
}
RECIPES = [("dims", "Розміри підряд")] + [(k, RECIPE_LABELS.get(k, k)) for k in sorted(core.RECIPES)]
RULES = [("equal", "Має збігатися"), ("equivalent", "Збіг або відповідник"),
         ("ge", "Не нижче"), ("any", "Не важливо")]
LEVELS = [("full", "Повна заміна"), ("check", "Заміна з перевіркою")]


def _split(text):
    return [w.strip() for w in (text or "").replace("\n", ",").split(",") if w.strip()]


class _SpecReset(models.AbstractModel):
    """Зміна довідника в цьому процесі одразу скидає кеш Spec (див. _ua_spec)."""
    _name = "ua.component.spec.reset"
    _description = "Скидання кешу класифікатора"

    def _ua_reset(self):
        self.pool._ua_component_spec = None

    @api.model_create_multi
    def create(self, vals_list):
        self._ua_reset()
        return super().create(vals_list)

    def write(self, vals):
        self._ua_reset()
        return super().write(vals)

    def unlink(self):
        self._ua_reset()
        return super().unlink()


class UaComponentAttribute(models.Model):
    _name = "ua.component.attribute"
    _inherit = ["ua.component.spec.reset"]
    _description = "Характеристика комплектуючих"
    _order = "sequence, id"
    _rec_names_search = ["name", "code"]

    code = fields.Char("Код", required=True, index=True,
                       help="Латиницею, без пробілів: на нього посилаються шаблони назв {code}.")
    name = fields.Char("Назва", required=True)
    kind = fields.Selection(KINDS, "Тип", required=True, default="number")
    unit = fields.Selection(UNIT_SELECTION, "Одиниця")
    digits = fields.Integer("Знаків після коми", default=3)
    note = fields.Text("Пояснення")
    choice_ids = fields.One2many("ua.component.choice", "attribute_id", "Варіанти")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    from_file = fields.Boolean("З базового довідника", readonly=True)

    _code_uniq = models.Constraint("unique(code)", "Характеристика з таким кодом уже є.")

    @api.depends("name", "unit")
    def _compute_display_name(self):
        for rec in self:
            unit = dict(UNIT_SELECTION).get(rec.unit)
            rec.display_name = "%s, %s" % (rec.name, unit) if unit else rec.name


class UaComponentChoice(models.Model):
    _name = "ua.component.choice"
    _inherit = ["ua.component.spec.reset"]
    _description = "Варіант характеристики"
    _order = "attribute_id, sequence, id"
    _rec_names_search = ["name", "code", "aliases"]

    attribute_id = fields.Many2one("ua.component.attribute", "Характеристика", required=True,
                                   ondelete="cascade", index=True)
    code = fields.Char("Код", required=True)
    name = fields.Char("Назва", required=True)
    code_text = fields.Char("В артикулі", help="Як варіант пишеться в артикулі; порожньо - код.")
    number = fields.Float("Числове значення", digits=(12, 4),
                          help="Номінал різьби, клас міцності числом: по ньому порівнюють "
                               "«не нижче» і шукають крок різьби.")
    density = fields.Float("Густина, кг/м³", help="Для марок: з неї рахується маса прокату.")
    aliases = fields.Char("Як ще пишуть",
                          help="Через кому. Зірочка в кінці - початок слова: «оцинк*» "
                               "знайде «оцинкований».")
    class_hint_id = fields.Many2one("ua.component.class", "Вказує на вид",
                                    help="Стандарт, який однозначно каже, що це за виріб: "
                                         "DIN 934 - гайка.")
    spanner = fields.Selection([("iso", "ISO"), ("din", "DIN / ГОСТ")], "Розміри під ключ",
                               help="Таблиця розмірів під ключ для порівняння DIN і ISO.")
    dk021_id = fields.Many2one("ua.dk021", "Код ДК 021",
                               help="Для марок: код прокату з цієї марки (сталь, алюміній).")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    from_file = fields.Boolean("З базового довідника", readonly=True)

    _code_uniq = models.Constraint("unique(attribute_id, code)",
                                   "У характеристики вже є варіант з таким кодом.")


class UaComponentClass(models.Model):
    _name = "ua.component.class"
    _inherit = ["ua.component.spec.reset"]
    _description = "Вид комплектуючих"
    _order = "complete_name"
    _parent_store = True
    _rec_name = "complete_name"
    _rec_names_search = ["complete_name", "code", "keywords"]

    code = fields.Char("Код", required=True, index=True)
    name = fields.Char("Назва", required=True)
    complete_name = fields.Char("Повна назва", compute="_compute_complete_name",
                                recursive=True, store=True)
    parent_id = fields.Many2one("ua.component.class", "Група", index=True, ondelete="restrict")
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("ua.component.class", "parent_id", "Підвиди")
    prefix = fields.Char("Префікс артикула")
    measure = fields.Selection(MEASURES, "Облік у", help="Порожньо - як у групи.")
    uom_id = fields.Many2one("uom.uom", "Одиниця обліку", help="Порожньо - як у групи.")
    tracking = fields.Selection([("none", "Без обліку партій"), ("lot", "Партії"),
                                 ("serial", "Серійні номери")], "Партії")
    shape = fields.Selection(SHAPES, "Форма перерізу", help="Для прокату: з неї рахується маса.")
    recipe = fields.Selection(RECIPES, "Як читати розмір з назви", default="dims")
    dims = fields.Char("Розміри підряд", help="Коди характеристик через кому: «40x4» для смуги - "
                                              "width, thickness.")
    sort_desc = fields.Boolean("Більший розмір першим")
    switch_dims = fields.Char("Інший вид за кількістю розмірів",
                              help="«3=rect_pipe»: три розміри в назві труби - профільна труба.")
    keywords = fields.Text("Ключові слова", help="Через кому: як цей виріб називають у прайсах "
                                                  "і в 1С. Довше слово важить більше.")
    name_template = fields.Char("Шаблон назви",
                                help="{код} - значення характеристики; [ ... ] - частина, яка "
                                     "з'являється лише коли всі поля в ній заповнені. "
                                     "Приклад: Болт {thread}×{length} {standard}[ {grade}]")
    code_template = fields.Char("Шаблон артикула", help="Як шаблон назви; {prefix} - префікс.")
    dk021_id = fields.Many2one("ua.dk021", "Код ДК 021",
                               help="Порожньо - з групи або з марки матеріалу.")
    categ_id = fields.Many2one("product.category", "Категорія товарів",
                               help="Куди класти товари цього виду під час розбору номенклатури.")
    line_ids = fields.One2many("ua.component.class.line", "class_id", "Характеристики", copy=True)
    product_count = fields.Integer("Товарів", compute="_compute_product_count")
    note = fields.Text("Примітка")
    active = fields.Boolean(default=True)
    from_file = fields.Boolean("З базового довідника", readonly=True)

    _code_uniq = models.Constraint("unique(code)", "Вид з таким кодом уже є.")

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for rec in self:
            rec.complete_name = "%s / %s" % (rec.parent_id.complete_name, rec.name) \
                if rec.parent_id else rec.name

    def _compute_product_count(self):
        groups = self.env["product.template"]._read_group(
            [("ua_component_class_id", "in", self.ids)], ["ua_component_class_id"], ["__count"])
        counts = {cls.id: n for cls, n in groups}
        for rec in self:
            rec.product_count = counts.get(rec.id, 0)

    @api.constrains("parent_id")
    def _check_parent(self):
        if self._has_cycle():
            raise ValidationError("Вид не може бути групою сам собі.")

    # ---------------------------------------------------------------- успадкування
    def _ua_inherited(self, field):
        """Значення поля з виду або найближчої групи, де воно задане."""
        self.ensure_one()
        rec = self
        while rec:
            if rec[field]:
                return rec[field]
            rec = rec.parent_id
        return self[field]

    def action_ua_products(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("ua_component_class_id", "child_of", self.id)],
            "context": {"default_ua_component_class_id": self.id},
        }

    # ---------------------------------------------------------------- довідник для розбору
    @api.model
    def _ua_spec(self):
        """Spec ядра з усього активного довідника бази.

        Збирати Spec - це сотні регулярних виразів, тому він кешується в реєстрі під
        відбитком довідника (кількість і час останньої зміни чотирьох таблиць): зміна в
        будь-якому процесі сервера одразу дає новий відбиток.
        """
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT (SELECT count(*) || '/' || coalesce(max(write_date)::text, '')
                      FROM ua_component_attribute),
                   (SELECT count(*) || '/' || coalesce(max(write_date)::text, '')
                      FROM ua_component_choice),
                   (SELECT count(*) || '/' || coalesce(max(write_date)::text, '')
                      FROM ua_component_class),
                   (SELECT count(*) || '/' || coalesce(max(write_date)::text, '')
                      FROM ua_component_class_line)""")
        stamp = self.env.cr.fetchone()
        cached = getattr(self.pool, "_ua_component_spec", None)
        if cached and cached[0] == stamp:
            return cached[1]
        spec = self._ua_spec_build()
        self.pool._ua_component_spec = (stamp, spec)
        return spec

    @api.model
    def _ua_spec_build(self):
        attributes = {}
        for attr in self.env["ua.component.attribute"].search([]):
            choices = {}
            for c in attr.choice_ids.filtered("active"):
                choices[c.code] = {
                    "name": c.name, "code_text": c.code_text or c.code,
                    "number": c.number or None, "density": c.density or None,
                    "aliases": _split(c.aliases), "spanner": c.spanner or None,
                    "class": c.class_hint_id.code or None,
                }
            attributes[attr.code] = {"name": attr.name, "kind": attr.kind, "unit": attr.unit,
                                     "choices": choices}
        classes = {}
        for cls in self.search([]):
            lines = {}
            for line in cls.line_ids:
                lines[line.attribute_id.code] = {
                    "required": line.required, "key": line.key, "rule": line.rule,
                    "default": line._ua_default(),
                }
            switch = {}
            for part in _split(cls.switch_dims):
                if "=" in part:
                    n, target = part.split("=", 1)
                    switch[n.strip()] = target.strip()
            classes[cls.code] = {
                "code": cls.code, "name": cls.name, "parent": cls.parent_id.code or None,
                "keywords": _split(cls.keywords), "recipe": cls.recipe or "dims",
                "dims": _split(cls.dims), "sort_desc": cls.sort_desc, "switch_dims": switch,
                "lines": lines, "prefix": cls._ua_inherited("prefix") or "",
                "name_template": cls.name_template, "code_template": cls.code_template,
            }
        return core.Spec(classes, attributes)

    @api.model
    def _ua_groups(self):
        """Відповідності для пошуку аналогів: {attr: [(set кодів, рівень, примітка)]}."""
        groups = {}
        for eq in self.env["ua.component.equivalence"].search([]):
            groups.setdefault(eq.attribute_id.code, []).append(
                (set(eq.choice_ids.mapped("code")), eq.level, eq.note or ""))
        return groups

    # ---------------------------------------------------------------- завантаження з файла
    @api.model
    def _ua_load_classifier(self, path=None):
        """Базовий довідник з data/classifier.json; повторний запуск лише оновлює."""
        with open(path or file_path(SOURCE), encoding="utf-8") as fh:
            data = json.load(fh)
        env = self.env(context=dict(self.env.context, active_test=False))
        Attr = env["ua.component.attribute"].sudo()
        Choice = env["ua.component.choice"].sudo()
        Class = env["ua.component.class"].sudo()
        Line = env["ua.component.class.line"].sudo()
        Equiv = env["ua.component.equivalence"].sudo()
        Dk = env["ua.dk021"].sudo()
        Uom = env["uom.uom"].sudo()

        def dk(code):
            return Dk.search([("code", "=", code)], limit=1).id if code else False

        attrs = {a.code: a for a in Attr.search([])}
        hints = []
        for seq, a in enumerate(data.get("attributes") or [], start=1):
            vals = {"code": a["code"], "name": a["name"], "kind": a.get("kind", "number"),
                    "unit": a.get("unit") or False, "digits": a.get("digits", 3),
                    "note": a.get("help") or False, "sequence": seq * 10, "from_file": True}
            rec = attrs.get(a["code"])
            if rec:
                if rec.from_file:
                    rec.write(vals)
            else:
                rec = attrs[a["code"]] = Attr.create(vals)
            existing = {c.code: c for c in rec.choice_ids}
            for cseq, c in enumerate(a.get("choices") or [], start=1):
                cvals = {"attribute_id": rec.id, "code": c["code"], "name": c["name"],
                         "code_text": c.get("code_text") or False,
                         "number": c.get("number") or 0.0, "density": c.get("density") or 0.0,
                         "aliases": ", ".join(c.get("aliases") or []) or False,
                         "spanner": c.get("spanner") or False, "dk021_id": dk(c.get("dk021")),
                         "sequence": cseq * 10, "from_file": True}
                choice = existing.get(c["code"])
                if choice:
                    if choice.from_file:
                        choice.write(cvals)
                else:
                    choice = Choice.create(cvals)
                if c.get("class"):
                    hints.append((choice, c["class"]))

        classes = {c.code: c for c in Class.search([])}
        for item in data.get("classes") or []:
            uom = False
            if item.get("uom"):
                uom = Uom.search([("ua_kspovo_short", "=", item["uom"])], limit=1).id \
                    if "ua_kspovo_short" in Uom._fields else False
            vals = {
                "code": item["code"], "name": item["name"], "prefix": item.get("prefix") or False,
                "measure": item.get("measure") or False, "uom_id": uom,
                "tracking": item.get("tracking") or False, "shape": item.get("shape") or False,
                "recipe": item.get("recipe") or "dims", "dims": ", ".join(item.get("dims") or []),
                "sort_desc": bool(item.get("sort_desc")),
                "switch_dims": ", ".join("%s=%s" % kv for kv in (item.get("switch_dims") or {}).items())
                or False,
                "keywords": ", ".join(item.get("keywords") or []) or False,
                "name_template": item.get("name_template") or False,
                "code_template": item.get("code_template") or False,
                "dk021_id": dk(item.get("dk021")), "from_file": True,
            }
            rec = classes.get(item["code"])
            if rec:
                if rec.from_file:
                    rec.write(vals)
            else:
                rec = classes[item["code"]] = Class.create(vals)
        for item in data.get("classes") or []:
            rec = classes[item["code"]]
            if not rec.from_file:
                continue
            parent = classes.get(item.get("parent")) if item.get("parent") else Class
            if rec.parent_id != parent:
                rec.parent_id = parent.id or False
            have = {line.attribute_id.code: line for line in rec.line_ids}
            for seq, line in enumerate(item.get("lines") or [], start=1):
                lvals = {"class_id": rec.id, "attribute_id": attrs[line["attr"]].id,
                         "sequence": seq * 10, "required": bool(line.get("required")),
                         "key": line.get("key", True), "rule": line.get("rule", "equal"),
                         "default_value": "" if line.get("default") is None
                         else str(line["default"])}
                if line["attr"] in have:
                    have[line["attr"]].write(lvals)
                else:
                    Line.create(lvals)
        for choice, class_code in hints:
            if choice.from_file and class_code in classes:
                choice.class_hint_id = classes[class_code]

        equivs = {e.code: e for e in Equiv.search([])}
        for item in data.get("equivalences") or []:
            attr = attrs[item["attr"]]
            choices = Choice.search([("attribute_id", "=", attr.id),
                                     ("code", "in", item["members"])])
            vals = {"code": item["code"], "attribute_id": attr.id,
                    "level": item.get("level", "check"), "note": item.get("note") or False,
                    "choice_ids": [(6, 0, choices.ids)], "from_file": True}
            rec = equivs.get(item["code"])
            if rec:
                if rec.from_file:
                    rec.write(vals)
            else:
                Equiv.create(vals)
        return True


class UaComponentClassLine(models.Model):
    _name = "ua.component.class.line"
    _inherit = ["ua.component.spec.reset"]
    _description = "Характеристика виду"
    _order = "class_id, sequence, id"

    class_id = fields.Many2one("ua.component.class", "Вид", required=True, ondelete="cascade",
                               index=True)
    attribute_id = fields.Many2one("ua.component.attribute", "Характеристика", required=True,
                                   ondelete="restrict")
    kind = fields.Selection(related="attribute_id.kind")
    unit = fields.Selection(related="attribute_id.unit")
    sequence = fields.Integer(default=10)
    required = fields.Boolean("Обов'язкова")
    key = fields.Boolean("Визначає виріб", default=True,
                         help="Входить у відбиток: два товари з однаковими ключовими "
                              "характеристиками - дублі.")
    rule = fields.Selection(RULES, "Для аналога", default="equal", required=True,
                            help="Як порівнювати з можливою заміною: має збігатися; збіг або "
                                 "відповідний стандарт чи марка; не нижче (клас міцності); "
                                 "не важливо.")
    default_value = fields.Char("За замовчуванням")

    _attr_uniq = models.Constraint("unique(class_id, attribute_id)",
                                   "Характеристика вже є у цього виду.")

    def _ua_default(self):
        self.ensure_one()
        raw = (self.default_value or "").strip()
        if not raw:
            return None
        if self.attribute_id.kind == "number":
            try:
                return float(raw.replace(",", "."))
            except ValueError:
                return None
        return raw


class UaComponentEquivalence(models.Model):
    _name = "ua.component.equivalence"
    _description = "Відповідність стандартів і марок"
    _order = "attribute_id, code"
    _rec_name = "code"

    code = fields.Char("Код", required=True)
    attribute_id = fields.Many2one("ua.component.attribute", "Характеристика", required=True,
                                   ondelete="cascade", domain=[("kind", "=", "choice")])
    choice_ids = fields.Many2many("ua.component.choice", string="Рівноцінні варіанти",
                                  domain="[('attribute_id', '=', attribute_id)]")
    level = fields.Selection(LEVELS, "Заміна", required=True, default="check")
    note = fields.Char("Що звірити")
    from_file = fields.Boolean("З базового довідника", readonly=True)

    _code_uniq = models.Constraint("unique(code)", "Відповідність з таким кодом уже є.")

    @api.constrains("choice_ids", "attribute_id")
    def _check_choices(self):
        for rec in self:
            if rec.choice_ids.filtered(lambda c: c.attribute_id != rec.attribute_id):
                raise ValidationError("У відповідності лише варіанти однієї характеристики.")
            if len(rec.choice_ids) < 2:
                raise ValidationError("Відповідність - це щонайменше два варіанти.")

    @api.depends("code", "choice_ids")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " = ".join(rec.choice_ids.mapped("name")) or rec.code
