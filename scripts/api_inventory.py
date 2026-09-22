#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Опис ядра: усі публічні методи і поля, які бачить інтерфейс.

Читає САМІ ФАЙЛИ через `ast`. Стенд, база і запущений Odoo не потрібні - тому
ця ж перевірка працює в CI. Пише два файли контракту:

    docs/api/inventory.md    людська версія: область > модель > метод із підписом
    docs/api/inventory.json  машинна версія: те саме дерево + підсумки

Вміст детермінований: жодних дат, часу і шляхів машини, порядок скрізь сталий.
Через це `scripts/contract_check.py` може просто порівняти новий текст зі старим.

Що потрапляє в опис
-------------------
Модулі: наші (`l10n_ua_*`, `bp_*`), до яких дотягується `l10n_ua_navigation` -
верхній модуль продукту, той самий, що ставить усе. Договір описує те, що справді
їде клієнту: чернетка сусіднього агента, поки її не внесли в залежності навігації,
у контракт не потрапляє і не валить CI. Вендорований OCA (`addons/OCA_*.commit`,
теки без нашого префікса) і відкладені екрани - не наші взагалі.

Моделі: клас із `_name`, а без нього - перший рядок `_inherit`. Наша модель - та,
чия назва починається з `ua.`, `bp.` або `kyc.`; решта (hr.employee, res.company,
account.move) - ядро Odoo або OCA, яке ми лише доповнюємо.

Методи: публічні (без підкреслення на початку) і наші:
  * за назвою - `ua_*`, `action_*`, `run_action`, `plan*`, `ensure_*`, `get_*`,
    `explain`, `blocker_rows`, `checks`;
  * на НАШІЙ моделі - будь-який публічний метод, крім перекриттів ORM (create,
    write, read, search...). Без цього з контракту випали б `open_target`,
    `state_of`, `blockers`, `count_new` - те, чим інтерфейс справді користується.

Поля: лише ЗБЕРЕЖЕНІ поля, які ми додаємо на чужі моделі. Обчислювані без `store`
і `related` не показуємо: їх немає в базі, і UI читає їх лише разом із записом.
Поля наших власних моделей у переліку не потрібні - модель наша цілком, її склад
видно через `fields_get`.

Запуск: python3 scripts/api_inventory.py [--stdout]
"""
import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "addons")
OUT_MD = os.path.join(ROOT, "docs", "api", "inventory.md")
OUT_JSON = os.path.join(ROOT, "docs", "api", "inventory.json")

OURS_MODULE = re.compile(r"^(l10n_ua_|bp_)")
OURS_MODEL = ("ua.", "bp.", "kyc.")
SKIP_DIRS = {"__pycache__", "tests", "migrations", "static", "i18n"}

# Назви, які ми вважаємо нашим публічним договором незалежно від моделі.
NAME_PATTERN = re.compile(
    r"^(ua_|action_|run_action$|plan|ensure_|get_|explain$|blocker_rows$|checks$)")

# Перекриття ORM: публічні, але це Odoo, а не ми. На нашій моделі їх не показуємо.
ORM_OVERRIDES = {
    "create", "write", "unlink", "copy", "copy_data", "read", "search", "search_read",
    "search_count", "search_fetch", "browse", "default_get", "fields_get", "fields_view_get",
    "name_create", "name_search", "name_get", "web_search_read", "web_read", "web_read_group",
    "read_group", "formatted_read_group", "onchange", "get_views", "get_view", "new", "init",
    "load", "export_data", "check_access", "check_access_rights", "check_access_rule",
    "toggle_active", "action_archive", "action_unarchive", "mapped", "filtered", "sorted",
    "exists", "ensure_one", "flush_model", "invalidate_model",
}

# Область продукту - той самий поділ, що й розділи меню в l10n_ua_navigation.
AREA_ORDER = [
    "Зарплата", "Кадри", "Звітність і контроль", "Бухоблік",
    "Контрагенти і закупівлі", "Спільне",
]
AREA_OF_MODULE = {
    "l10n_ua_payroll_rules": "Зарплата",
    "l10n_ua_payroll_account": "Зарплата",
    "l10n_ua_payroll_reports": "Зарплата",
    "l10n_ua_payroll_tests": "Зарплата",
    "l10n_ua_average": "Зарплата",
    "l10n_ua_index": "Зарплата",
    "l10n_ua_gph": "Зарплата",
    "l10n_ua_payments": "Зарплата",
    "l10n_ua_explain": "Зарплата",
    "l10n_ua_hr_card": "Кадри",
    "l10n_ua_hr_orders": "Кадри",
    "l10n_ua_hr_docs": "Кадри",
    "l10n_ua_military": "Кадри",
    "l10n_ua_kp": "Кадри",
    "l10n_ua_onboarding": "Кадри",
    "l10n_ua_hire": "Кадри",
    "l10n_ua_reporting": "Звітність і контроль",
    "l10n_ua_changes": "Звітність і контроль",
    "l10n_ua_setup": "Звітність і контроль",
    "l10n_ua_chart": "Бухоблік",
    "l10n_ua_vat": "Бухоблік",
    "l10n_ua_ledger": "Бухоблік",
    "l10n_ua_finrep": "Бухоблік",
    "l10n_ua_assets": "Бухоблік",
    "l10n_ua_nbu": "Бухоблік",
    "l10n_ua_cash": "Бухоблік",
    "l10n_ua_bank": "Бухоблік",
    "l10n_ua_bank_online": "Бухоблік",
    "l10n_ua_docs": "Бухоблік",
    "l10n_ua_docs_sale": "Бухоблік",
    "l10n_ua_docs_stock": "Бухоблік",
    "l10n_ua_stock_docs": "Бухоблік",
    "l10n_ua_fop": "Бухоблік",
    "l10n_ua_migrate": "Бухоблік",
    "l10n_ua_group": "Бухоблік",
    "l10n_ua_mrp": "Бухоблік",
    "l10n_ua_profit_tax": "Бухоблік",
    "l10n_ua_partner_edr": "Контрагенти і закупівлі",
    "l10n_ua_purchase": "Контрагенти і закупівлі",
    "bp_kyc": "Контрагенти і закупівлі",
    "bp_purchase_intake": "Контрагенти і закупівлі",
    "l10n_ua_screen": "Спільне",
    "l10n_ua_api": "Спільне",
    "l10n_ua_navigation": "Спільне",
    "l10n_ua_setup_ui": "Спільне",
    "bp_bridge": "Спільне",
}
DEFAULT_AREA = "Спільне"


# ---------------------------------------------------------------- вибір модулів
TOP_MODULE = "l10n_ua_navigation"


def manifest(name):
    path = os.path.join(ADDONS, name, "__manifest__.py")
    if not os.path.isfile(path):
        return None
    try:
        data = ast.literal_eval(open(path, encoding="utf-8").read())
    except (ValueError, SyntaxError) as error:
        print("маніфест не читається: %s (%s)" % (name, error), file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def modules():
    """Наші модулі із залежностей `l10n_ua_navigation`, включно з ним самим."""
    seen, stack = set(), [TOP_MODULE]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        data = manifest(name)
        if data is None:
            continue                     # модуль Odoo або OCA - глибше не йдемо
        seen.add(name)
        stack.extend(data.get("depends") or [])
    return sorted(name for name in seen if OURS_MODULE.match(name))


# ---------------------------------------------------------------- читання класів
def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def class_model(node):
    """Модель класу: `_name`, інакше перший рядок `_inherit`."""
    name = inherit = None
    for stmt in node.body:
        if not isinstance(stmt, ast.Assign) or not stmt.targets:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "_name":
            value = literal(stmt.value)
            if isinstance(value, str):
                name = value
        elif target.id == "_inherit":
            value = literal(stmt.value)
            if isinstance(value, str):
                inherit = value
            elif isinstance(value, (list, tuple)) and value and isinstance(value[0], str):
                inherit = value[0]
    return name or inherit


def signature(func):
    """Підпис методу без self/cls, із типовими значеннями як у коді."""
    args = func.args
    names = [a.arg for a in args.posonlyargs + args.args]
    defaults = list(args.defaults)
    pad = len(names) - len(defaults)
    parts = []
    for i, arg in enumerate(names):
        if i == 0 and arg in ("self", "cls"):
            continue
        if i >= pad:
            parts.append("%s=%s" % (arg, ast.unparse(defaults[i - pad])))
        else:
            parts.append(arg)
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append("%s=%s" % (arg.arg, ast.unparse(default)) if default else arg.arg)
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    return "%s(%s)" % (func.name, ", ".join(parts))


def first_doc_line(func):
    doc = ast.get_docstring(func) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def decorators(func):
    out = []
    for node in func.decorator_list:
        try:
            out.append(ast.unparse(node))
        except Exception:
            pass
    return sorted(out)


def field_info(stmt):
    """(назва, тип, підпис, збережене?, групи) з рядка `x = fields.Char(...)`."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name) or not isinstance(stmt.value, ast.Call):
        return None
    func = stmt.value.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "fields"):
        return None
    kwargs = {kw.arg: kw.value for kw in stmt.value.keywords if kw.arg}
    label = ""
    if stmt.value.args:
        value = literal(stmt.value.args[0])
        if isinstance(value, str):
            label = value
    if not label and "string" in kwargs:
        value = literal(kwargs["string"])
        if isinstance(value, str):
            label = value
    stored = literal(kwargs["store"]) if "store" in kwargs else None
    if "related" in kwargs or "compute" in kwargs:
        is_stored = bool(stored)
    else:
        is_stored = True
    groups = literal(kwargs["groups"]) if "groups" in kwargs else ""
    return target.id, func.attr, label, is_stored, groups if isinstance(groups, str) else ""


def python_files(module):
    out = []
    for base, dirs, names in os.walk(os.path.join(ADDONS, module)):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name.endswith(".py"):
                out.append(os.path.join(base, name))
    return sorted(out)


# ---------------------------------------------------------------- збирання
def collect():
    data = {}          # model -> {"ours": bool, "methods": [...], "fields": [...], "modules": set}
    for module in modules():
        area = AREA_OF_MODULE.get(module, DEFAULT_AREA)
        for path in python_files(module):
            rel = os.path.relpath(path, ROOT)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            except SyntaxError as error:
                print("не читається: %s (%s)" % (rel, error), file=sys.stderr)
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                model = class_model(node)
                if not model:
                    continue
                ours = model.startswith(OURS_MODEL)
                entry = data.setdefault(model, {
                    "model": model, "ours": ours, "area": area,
                    "modules": set(), "methods": [], "fields": [],
                })
                entry["modules"].add(module)
                # область моделі - за модулем, який її ОГОЛОСИВ (_name), інакше за першим
                if any(isinstance(s, ast.Assign) and getattr(s.targets[0], "id", "") == "_name"
                       for s in node.body if isinstance(s, ast.Assign) and s.targets):
                    entry["area"] = area
                for stmt in node.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = stmt.name
                        if name.startswith("_"):
                            continue
                        keep = bool(NAME_PATTERN.match(name)) or (ours and name not in ORM_OVERRIDES)
                        if not keep:
                            continue
                        entry["methods"].append({
                            "name": name,
                            "signature": signature(stmt),
                            "doc": first_doc_line(stmt),
                            "module": module,
                            "file": rel,
                            "decorators": decorators(stmt),
                        })
                        continue
                    if ours:
                        continue          # склад наших моделей читається через fields_get
                    info = field_info(stmt)
                    if not info:
                        continue
                    name, kind, label, is_stored, groups = info
                    if not is_stored:
                        continue
                    entry["fields"].append({
                        "name": name, "type": kind, "label": label,
                        "module": module, "file": rel, "groups": groups,
                    })
    return data


def tree_of(data):
    areas = {}
    for model, entry in data.items():
        if not entry["methods"] and not entry["fields"]:
            continue
        areas.setdefault(entry["area"], []).append(entry)
    out = []
    for area in AREA_ORDER + sorted(set(areas) - set(AREA_ORDER)):
        if area not in areas:
            continue
        models = []
        for entry in sorted(areas[area], key=lambda e: (not e["ours"], e["model"])):
            models.append({
                "model": entry["model"],
                "ours": entry["ours"],
                "modules": sorted(entry["modules"]),
                "methods": sorted(entry["methods"], key=lambda m: (m["name"], m["file"])),
                "fields": sorted(entry["fields"], key=lambda f: (f["name"], f["file"])),
            })
        out.append({"area": area, "models": models})
    return out


def totals(tree):
    models = methods = fields = 0
    mods = set()
    for area in tree:
        for model in area["models"]:
            models += 1
            methods += len(model["methods"])
            fields += len(model["fields"])
            mods.update(model["modules"])
    return {"modules": len(mods), "models": models, "methods": methods, "fields": fields}


# ---------------------------------------------------------------- вивід
def markdown(tree, sums):
    lines = [
        "# Опис ядра для інтерфейсу",
        "",
        "Згенеровано `scripts/api_inventory.py`. Руками не правити: зміни в коді, потім",
        "`python3 scripts/api_inventory.py`. Що саме сюди потрапляє - у шапці скрипта.",
        "Як цим користуватися - `docs/api/README.md`, приклади викликів - `docs/api/screens.md`,",
        "прибрані й перейменовані методи - `docs/api/CHANGELOG.md`.",
        "",
        "Модулів: %s. Моделей: %s. Методів: %s. Збережених полів на чужих моделях: %s."
        % (sums["modules"], sums["models"], sums["methods"], sums["fields"]),
        "",
    ]
    for area in tree:
        lines += ["## %s" % area["area"], ""]
        for model in area["models"]:
            mark = "наша модель" if model["ours"] else "доповнена модель"
            lines += ["### `%s`" % model["model"], "",
                      "%s · %s" % (mark, ", ".join("`%s`" % m for m in model["modules"])), ""]
            if model["methods"]:
                lines += ["| Метод | Що робить | Модуль |", "| --- | --- | --- |"]
                for method in model["methods"]:
                    doc = method["doc"].replace("|", "\\|") or "-"
                    lines.append("| `%s` | %s | `%s` |" % (method["signature"], doc, method["module"]))
                lines.append("")
            if model["fields"]:
                lines += ["| Поле | Тип | Підпис | Модуль |", "| --- | --- | --- | --- |"]
                for field in model["fields"]:
                    lines.append("| `%s` | %s | %s | `%s` |" % (
                        field["name"], field["type"], field["label"].replace("|", "\\|") or "-",
                        field["module"]))
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def payload(tree, sums):
    return json.dumps({"totals": sums, "areas": tree}, ensure_ascii=False,
                      indent=2, sort_keys=False) + "\n"


def build():
    tree = tree_of(collect())
    sums = totals(tree)
    return markdown(tree, sums), payload(tree, sums), sums


def main():
    parser = argparse.ArgumentParser(description="Опис публічного договору ядра.")
    parser.add_argument("--stdout", action="store_true", help="не писати файли, показати markdown")
    args = parser.parse_args()

    md, js, sums = build()
    if args.stdout:
        sys.stdout.write(md)
        return 0
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w", encoding="utf-8").write(md)
    open(OUT_JSON, "w", encoding="utf-8").write(js)
    print("Записано %s і %s." % (os.path.relpath(OUT_MD, ROOT), os.path.relpath(OUT_JSON, ROOT)))
    print("Модулів: %s, моделей: %s, методів: %s, полів: %s."
          % (sums["modules"], sums["models"], sums["methods"], sums["fields"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
