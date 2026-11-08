#!/usr/bin/env python3
"""Класифікатор комплектуючих (addons/l10n_ua_component/data/classifier.json) без бази.

Перевіряє:
- коди характеристик, варіантів і видів унікальні, типи й одиниці відомі;
- вид посилається на наявну групу, рядки - на наявні характеристики, значення
  за замовчуванням - на наявні варіанти; рецепт і форма перерізу відомі ядру;
- шаблони назви й артикула містять лише характеристики свого виду, {prefix} і {pitch_fine};
- одиниця виду є серед позначень КСПОВО (l10n_ua_vat), коди ДК 021 є в довіднику;
- групи відповідностей мають щонайменше два наявні варіанти;
- кожен рядок data/samples.json розбирається в той самий вид, назву й артикул.

Запуск: python3 scripts/component_check.py"""
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "addons", "l10n_ua_component")
DK021 = os.path.join(ROOT, "addons", "l10n_ua_dk021", "data", "dk021_uk.json")
KSPOVO = os.path.join(ROOT, "addons", "l10n_ua_vat", "models", "uom_uom.py")
PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")
KINDS = {"number", "choice", "text", "bool"}
RULES = {"equal", "equivalent", "ge", "any"}
LEVELS = {"full", "check"}
MEASURES = {"piece", "mass", "length", "area", "volume"}
EXTRA_FIELDS = {"prefix", "pitch_fine"}


def load_core():
    spec = importlib.util.spec_from_file_location(
        "component_core", os.path.join(MODULE, "models", "component_core.py"))
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


def dk021_codes():
    with open(DK021, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data if isinstance(data, list) else data.get("items") or data.get("codes") or []
    codes = set()
    for row in rows:
        if isinstance(row, dict):
            codes.add(row.get("code"))
        elif isinstance(row, (list, tuple)) and row:
            codes.add(row[0])
    if isinstance(data, dict) and not codes:
        codes = set(data)
    return codes


def kspovo_shorts():
    with open(KSPOVO, encoding="utf-8") as fh:
        return set(re.findall(r'\("\d{4}", "([^"]+)"\)', fh.read()))


def main():
    core = load_core()
    with open(os.path.join(MODULE, "data", "classifier.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    errors = []
    err = errors.append

    attrs, choices = {}, {}
    for a in data.get("attributes") or []:
        code = a.get("code")
        if code in attrs:
            err("характеристика %s двічі" % code)
        attrs[code] = a
        if a.get("kind", "number") not in KINDS:
            err("%s: невідомий тип %r" % (code, a.get("kind")))
        if a.get("unit") and a["unit"] not in core.UNITS:
            err("%s: невідома одиниця %r" % (code, a["unit"]))
        if a.get("kind") == "choice" and not a.get("choices"):
            err("%s: вибір без варіантів" % code)
        seen = set()
        for c in a.get("choices") or []:
            if c["code"] in seen:
                err("%s: варіант %s двічі" % (code, c["code"]))
            seen.add(c["code"])
        choices[code] = seen

    classes = {}
    for c in data.get("classes") or []:
        if c["code"] in classes:
            err("вид %s двічі" % c["code"])
        classes[c["code"]] = c

    dk = dk021_codes()
    shorts = kspovo_shorts()
    shapes = set(core.SHAPES) | {core.SHEET}
    for code, c in classes.items():
        where = "вид %s" % code
        if c.get("parent") and c["parent"] not in classes:
            err("%s: немає групи %s" % (where, c["parent"]))
        if c.get("recipe") and c["recipe"] != "dims" and c["recipe"] not in core.RECIPES:
            err("%s: невідомий рецепт %s" % (where, c["recipe"]))
        if c.get("shape") and c["shape"] not in shapes:
            err("%s: невідома форма %s" % (where, c["shape"]))
        if c.get("measure") and c["measure"] not in MEASURES:
            err("%s: невідомий облік %s" % (where, c["measure"]))
        if c.get("uom") and c["uom"] not in shorts:
            err("%s: одиниці %r немає в КСПОВО" % (where, c["uom"]))
        if c.get("dk021") and c["dk021"] not in dk:
            err("%s: немає коду ДК 021 %s" % (where, c["dk021"]))
        own = set()
        for line in c.get("lines") or []:
            attr = line.get("attr")
            if attr not in attrs:
                err("%s: немає характеристики %s" % (where, attr))
                continue
            if attr in own:
                err("%s: характеристика %s двічі" % (where, attr))
            own.add(attr)
            if line.get("rule", "equal") not in RULES:
                err("%s/%s: невідоме правило %s" % (where, attr, line.get("rule")))
            default = line.get("default")
            if default is not None and attrs[attr].get("kind") == "choice" \
                    and default not in choices[attr]:
                err("%s/%s: немає варіанта %s" % (where, attr, default))
        for dim in (c.get("dims") or []):
            if dim not in own:
                err("%s: розмір %s не серед характеристик виду" % (where, dim))
        for tmpl_field in ("name_template", "code_template"):
            for field in PLACEHOLDER.findall(c.get(tmpl_field) or ""):
                if field not in own and field not in EXTRA_FIELDS:
                    err("%s: {%s} у шаблоні не серед характеристик виду" % (where, field))
        if c.get("lines") and not c.get("name_template"):
            err("%s: немає шаблону назви" % where)

    for a in data.get("attributes") or []:
        for c in a.get("choices") or []:
            if c.get("class") and c["class"] not in classes:
                err("%s/%s: немає виду %s" % (a["code"], c["code"], c["class"]))
            if c.get("dk021") and c["dk021"] not in dk:
                err("%s/%s: немає коду ДК 021 %s" % (a["code"], c["code"], c["dk021"]))

    equiv_codes = set()
    for e in data.get("equivalences") or []:
        where = "відповідність %s" % e.get("code")
        if e.get("code") in equiv_codes:
            err("%s двічі" % where)
        equiv_codes.add(e.get("code"))
        if e.get("attr") not in attrs:
            err("%s: немає характеристики %s" % (where, e.get("attr")))
            continue
        members = e.get("members") or []
        if len(set(members)) < 2:
            err("%s: менше двох варіантів" % where)
        for m in members:
            if m not in choices[e["attr"]]:
                err("%s: немає варіанта %s" % (where, m))
        if e.get("level", "check") not in LEVELS:
            err("%s: невідомий рівень %s" % (where, e.get("level")))

    spec = core.spec_from_data(data)
    with open(os.path.join(MODULE, "data", "samples.json"), encoding="utf-8") as fh:
        samples = json.load(fh)["samples"]
    for s in samples:
        result = core.parse(spec, s["text"])
        cls = spec.classes.get(result["class"]) or {}
        name = core.render(spec, cls.get("name_template"), result["values"]) if cls else ""
        code = core.render(spec, cls.get("code_template"), result["values"],
                           {"prefix": cls.get("prefix")}, for_code=True) if cls else ""
        got = (result["class"], name, code)
        want = (s["class"], s["name"], s["code"])
        if got != want:
            err("розбір «%s»: %s, очікувалось %s" % (s["text"], got, want))

    if errors:
        print("\n".join(errors))
        print("Помилок: %d." % len(errors))
        return 1
    print("Характеристик %d, видів %d, відповідностей %d, зразків розбору %d - усе гаразд."
          % (len(attrs), len(classes), len(equiv_codes), len(samples)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
