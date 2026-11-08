#!/usr/bin/env python3
"""Перевірка галузевих пакетів addons/*/catalog/*.json без бази.

Ловить те, що інакше впало б лише під час завантаження в Odoo:
- формат: schema 1, id пакета збігається з іменем файла, відомі розділи і ключі;
- посилання: кожне "@key" вказує на ключ, оголошений раніше в порядку завантаження;
- одиниці: позначення КСПОВО з l10n_ua_vat, xmlid uom.* або ключ з uoms[];
- коди: УКТ ЗЕД - 10 цифр, ДК 021 - є у словнику, штрихкод - EAN-13 з правильною
  контрольною цифрою і префіксом 20 (внутрішній обіг, не чужий товар);
- залежності: робочі центри і специфікації вимагають mrp, серійні номери - stock;
- специфікації без циклів, операції з робочим центром і часом;
- публічний репозиторій: жодних адрес пошти, крім доменів .example.

Запуск: python3 scripts/catalog_check.py [шлях до пакета ...]
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDONS = os.path.join(ROOT, "addons")
DK021 = os.path.join(ADDONS, "l10n_ua_dk021", "data", "dk021_uk.json")
UOM_SEED = os.path.join(ADDONS, "l10n_ua_vat", "models", "uom_uom.py")
COMPONENT_DIR = os.path.join(ADDONS, "l10n_ua_component")


def component_spec():
    """Ядро розбору і довідник l10n_ua_component без Odoo: (core, spec) або (None, None)."""
    core_path = os.path.join(COMPONENT_DIR, "models", "component_core.py")
    data_path = os.path.join(COMPONENT_DIR, "data", "classifier.json")
    if not (os.path.exists(core_path) and os.path.exists(data_path)):
        return None, None
    import importlib.util
    spec = importlib.util.spec_from_file_location("ua_component_core", core_path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    with open(data_path, encoding="utf-8") as fh:
        return core, core.spec_from_data(json.load(fh))


CORE, SPEC = component_spec()

PACK_ID = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
SECTIONS = ("groups", "uoms", "categories", "workcenters", "products", "boms", "records")
TOP_KEYS = {"schema", "pack", "name", "summary", "industry", "requires", "sources", "notes"} | set(SECTIONS)
INDUSTRIES = {"defense", "manufacturing", "procurement", "retail", "services", "trade", "other"}
ODOO_CORE = {"product", "uom", "stock", "mrp", "purchase", "sale", "sale_management", "account",
             "point_of_sale", "mrp_account", "stock_account", "purchase_stock", "sale_stock",
             "hr", "project", "repair", "quality", "maintenance", "fleet"}
ITEM_KEYS = {
    "uoms": ({"key", "name"}, {"short", "kspovo", "relative_factor", "relative_uom"}),
    "categories": ({"key", "name"}, {"parent"}),
    "workcenters": ({"key", "name"}, {"code", "costs_hour", "fields"}),
    "products": ({"key"}, {"name", "code", "category", "type", "storable", "uom", "tracking", "cost",
                           "price", "barcode", "uktzed", "dk021", "sale_ok", "purchase_ok",
                           "description", "fields", "component"}),
    "boms": ({"key", "product"}, {"qty", "code", "type", "lines", "operations", "byproducts"}),
    "records": ({"key", "model", "values"}, {"match", "company_bound"}),
}
COST_ITEMS = {"01", "02", "03"}
EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.)+[\w-]+")


def kspovo_shorts():
    """Позначення одиниць, які засіває l10n_ua_vat (друге значення кортежу)."""
    try:
        text = open(UOM_SEED, encoding="utf-8").read()
    except OSError:
        return set()
    return set(re.findall(r'\("\d{4}", "([^"]+)"\)', text))


def component_values(comp):
    """Вид і характеристики з component{}: розбір «parse» плюс явні values."""
    values = {}
    cls = comp.get("class")
    if comp.get("parse") and CORE:
        result = CORE.parse(SPEC, comp["parse"])
        cls = cls or result["class"]
        values.update(result["values"])
    values.update(comp.get("values") or {})
    return cls, values


def ean13_ok(code):
    if not re.fullmatch(r"\d{13}", code or ""):
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


class Pack:
    def __init__(self, path, dk021, shorts, addons):
        self.path = path
        self.rel = os.path.relpath(path, ROOT)
        self.dk021 = dk021
        self.shorts = shorts
        self.addons = addons
        self.problems = []
        self.keys = {}

    def bad(self, msg):
        self.problems.append("%s: %s" % (self.rel, msg))

    def component(self, comp, where, requires):
        """component{}: вид з довідника, відомі характеристики, повний розбір назви."""
        if "l10n_ua_component" not in requires:
            self.bad("%s: component потребує requires: l10n_ua_component" % where)
        extra = set(comp) - {"class", "values", "parse"}
        if extra:
            self.bad("%s: component - невідомі поля %s" % (where, ", ".join(sorted(extra))))
        if not SPEC:
            return
        cls, values = component_values(comp)
        if cls not in SPEC.classes:
            self.bad("%s: вид «%s» не знайдено (розбір: %r)" % (where, cls, comp.get("parse")))
            return
        lines = SPEC.classes[cls]["lines"]
        for attr, value in values.items():
            if attr not in lines:
                self.bad("%s: у виду %s немає характеристики %s" % (where, cls, attr))
            elif isinstance(value, str) and (SPEC.attributes[attr].get("kind") == "choice") \
                    and value not in SPEC.attributes[attr]["choices"]:
                self.bad("%s: %s - немає варіанта «%s»" % (where, attr, value))
        missing = [a for a, line in lines.items() if line.get("required") and a not in values]
        if missing:
            self.bad("%s: не заповнено %s" % (where, ", ".join(missing)))

    def ref(self, value, where, kinds=None):
        if not isinstance(value, str) or not value.startswith("@"):
            self.bad("%s: очікували посилання @key, а є %r" % (where, value))
            return None
        key = value[1:]
        if key not in self.keys:
            self.bad("%s: ключ «%s» не оголошено раніше" % (where, key))
            return None
        if kinds and self.keys[key] not in kinds:
            self.bad("%s: «%s» - це %s, а потрібно %s" % (where, key, self.keys[key], "/".join(kinds)))
        return key

    def uom(self, value, where, own):
        if not value:
            return
        if value.startswith("@"):
            self.ref(value, where, ("uoms",))
        elif value.startswith("uom."):
            return
        elif value not in self.shorts and value not in own:
            self.bad("%s: невідома одиниця «%s»" % (where, value))

    def check(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            self.bad("не читається як JSON: %s" % exc)
            return
        stem = os.path.splitext(os.path.basename(self.path))[0]
        if data.get("schema") != 1:
            self.bad("schema має бути 1")
        if data.get("pack") != stem or not PACK_ID.match(stem):
            self.bad("pack «%s» має збігатися з іменем файла «%s» (a-z, 0-9, _)" % (data.get("pack"), stem))
        for field in ("name", "summary"):
            if not str(data.get(field) or "").strip():
                self.bad("порожнє поле %s" % field)
        if data.get("industry") not in INDUSTRIES:
            self.bad("industry має бути одним із %s" % ", ".join(sorted(INDUSTRIES)))
        unknown = set(data) - TOP_KEYS
        if unknown:
            self.bad("невідомі розділи: %s" % ", ".join(sorted(unknown)))
        requires = data.get("requires") or []
        for module in requires:
            if module not in ODOO_CORE and module not in self.addons:
                self.bad("requires: модуля «%s» немає ні в addons/, ні серед відомих модулів Odoo" % module)
        for src in data.get("sources") or []:
            if not str(src.get("url", "")).startswith("https://"):
                self.bad("джерело без адреси https: %r" % src)
        for match in EMAIL.finditer(json.dumps(data, ensure_ascii=False)):
            if not match.group(0).endswith(".example"):
                self.bad("адреса пошти в публічному пакеті: %s" % match.group(0))

        for section in SECTIONS[1:]:
            items = data.get(section) or []
            required, optional = ITEM_KEYS[section]
            for i, item in enumerate(items):
                where = "%s[%d]" % (section, i)
                missing = required - set(item)
                extra = set(item) - required - optional
                if missing:
                    self.bad("%s: бракує %s" % (where, ", ".join(sorted(missing))))
                if extra:
                    self.bad("%s: невідомі поля %s" % (where, ", ".join(sorted(extra))))
                key = item.get("key", "")
                if not KEY.match(key):
                    self.bad("%s: ключ «%s» не підходить (a-z, 0-9, _)" % (where, key))
                elif key in self.keys:
                    self.bad("%s: ключ «%s» повторюється" % (where, key))
        if (data.get("workcenters") or data.get("boms")) and "mrp" not in requires:
            self.bad("робочі центри і специфікації потребують requires: mrp")

        own_uoms = set()
        for item in data.get("uoms") or []:
            if item.get("kspovo") and not re.fullmatch(r"\d{4}", item["kspovo"]):
                self.bad("uoms «%s»: код КСПОВО - 4 цифри" % item.get("key"))
            if item.get("relative_uom"):
                self.uom(item["relative_uom"], "uoms «%s»" % item.get("key"), own_uoms)
            if item.get("short"):
                own_uoms.add(item["short"])
            self.keys[item.get("key")] = "uoms"
        for item in data.get("categories") or []:
            if item.get("parent"):
                self.ref(item["parent"], "categories «%s»" % item.get("key"), ("categories",))
            self.keys[item.get("key")] = "categories"
        for item in data.get("workcenters") or []:
            fields = item.get("fields") or {}
            for name in ("ua_wage_hour", "ua_energy_hour"):
                if name in fields and not isinstance(fields[name], (int, float)):
                    self.bad("workcenters «%s»: %s має бути числом" % (item.get("key"), name))
            self.keys[item.get("key")] = "workcenters"

        tracked = False
        barcodes = set()
        for item in data.get("products") or []:
            where = "products «%s»" % item.get("key")
            if not item.get("name") and not item.get("component"):
                self.bad("%s: бракує name (або component, з якого назва складеться)" % where)
            if item.get("component"):
                self.component(item["component"], where, requires)
            if item.get("category"):
                self.ref(item["category"], where, ("categories",))
            self.uom(item.get("uom"), where, own_uoms)
            if item.get("type", "consu") not in ("consu", "service", "combo"):
                self.bad("%s: type має бути consu, service або combo" % where)
            if item.get("tracking", "none") not in ("none", "lot", "serial"):
                self.bad("%s: tracking має бути none, lot або serial" % where)
            if item.get("tracking") in ("lot", "serial"):
                tracked = True
                if item.get("type", "consu") != "consu" or item.get("storable") is False:
                    self.bad("%s: партії і серійні номери - лише для складського товару" % where)
            for field in ("cost", "price"):
                if field in item and (not isinstance(item[field], (int, float)) or item[field] < 0):
                    self.bad("%s: %s - невід'ємне число" % (where, field))
            if item.get("uktzed") and not re.fullmatch(r"\d{10}", item["uktzed"]):
                self.bad("%s: код УКТ ЗЕД - 10 цифр без пропусків" % where)
            if item.get("dk021") and self.dk021 is not None and item["dk021"] not in self.dk021:
                self.bad("%s: коду ДК 021 «%s» немає у словнику" % (where, item["dk021"]))
            barcode = item.get("barcode")
            if barcode:
                if not ean13_ok(barcode):
                    self.bad("%s: штрихкод %s - не EAN-13 або хибна контрольна цифра" % (where, barcode))
                elif not barcode.startswith("20"):
                    self.bad("%s: у пакеті лише внутрішні штрихкоди з префіксом 20" % where)
                if barcode in barcodes:
                    self.bad("%s: штрихкод %s повторюється" % (where, barcode))
                barcodes.add(barcode)
            cost_item = (item.get("fields") or {}).get("ua_cost_item")
            if cost_item is not None and cost_item not in COST_ITEMS:
                self.bad("%s: ua_cost_item має бути 01, 02 або 03" % where)
            self.keys[item.get("key")] = "products"
        if tracked and "stock" not in requires and "mrp" not in requires:
            self.bad("партії і серійні номери потребують requires: stock")

        products = {i.get("key"): i for i in data.get("products") or []}
        graph = {}
        for item in data.get("boms") or []:
            where = "boms «%s»" % item.get("key")
            head = self.ref(item.get("product"), where, ("products",))
            if item.get("type", "normal") not in ("normal", "phantom"):
                self.bad("%s: type має бути normal або phantom" % where)
            if not item.get("lines"):
                self.bad("%s: специфікація без складу" % where)
            children = set()
            for j, line in enumerate((item.get("lines") or []) + (item.get("byproducts") or [])):
                key = self.ref(line.get("product"), "%s рядок %d" % (where, j + 1), ("products",))
                if not isinstance(line.get("qty", 1), (int, float)) or line.get("qty", 1) <= 0:
                    self.bad("%s рядок %d: кількість має бути більше нуля" % (where, j + 1))
                self.uom(line.get("uom"), "%s рядок %d" % (where, j + 1), own_uoms)
                if key and products.get(key, {}).get("type", "consu") == "service":
                    self.bad("%s рядок %d: послуга не може бути складовою" % (where, j + 1))
                if key and line in (item.get("lines") or []):
                    children.add(key)
            if head in children:
                self.bad("%s: виріб у власному складі" % where)
            for op in item.get("operations") or []:
                self.ref(op.get("workcenter"), "%s операція «%s»" % (where, op.get("name")), ("workcenters",))
                if not op.get("name"):
                    self.bad("%s: операція без назви" % where)
                if not isinstance(op.get("minutes"), (int, float)) or op["minutes"] <= 0:
                    self.bad("%s операція «%s»: minutes має бути більше нуля" % (where, op.get("name")))
            if head:
                graph.setdefault(head, set()).update(children)
            self.keys[item.get("key")] = "boms"
        self._cycles(graph)

        for item in data.get("records") or []:
            if not re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", item.get("model", "")):
                self.bad("records «%s»: model має вигляд a.b" % item.get("key"))
            self.keys[item.get("key")] = "records"

    def _cycles(self, graph):
        state = {}

        def visit(node, trail):
            if state.get(node) == 1:
                self.bad("цикл у специфікаціях: %s" % " -> ".join(trail + [node]))
                return
            if state.get(node) == 2:
                return
            state[node] = 1
            for child in sorted(graph.get(node, ())):
                visit(child, trail + [node])
            state[node] = 2

        for node in sorted(graph):
            visit(node, [])


def main(argv):
    paths = argv or sorted(glob.glob(os.path.join(ADDONS, "*", "catalog", "*.json")))
    try:
        dk021 = set(json.load(open(DK021, encoding="utf-8")))
    except (OSError, ValueError):
        dk021 = None
    shorts = kspovo_shorts()
    addons = {d for d in os.listdir(ADDONS) if os.path.isfile(os.path.join(ADDONS, d, "__manifest__.py"))}
    problems, ids, records = [], {}, 0
    for path in paths:
        pack = Pack(path, dk021, shorts, addons)
        pack.check()
        problems += pack.problems
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in ids:
            problems.append("пакет «%s» є і в %s, і в %s" % (stem, ids[stem], pack.rel))
        ids[stem] = pack.rel
        records += len(pack.keys)
    for line in problems:
        print("FAIL", line)
    if problems:
        print("Пакетів: %d, проблем: %d." % (len(paths), len(problems)))
        return 1
    print("Пакетів: %d, записів: %d, усе гаразд." % (len(paths), records))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
