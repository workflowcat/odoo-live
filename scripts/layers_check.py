#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка поділу на логіку і інтерфейс. Стенд не потрібен - читаємо самі файли.

Від 2026-09-22 продукт іде голим Odoo: власних екранів немає, уся робота йде через
стандартні списки, форми, кнопки і чарівники. Відкладені екрани лежать поза addons/,
у shelved/addons-owl/, і Odoo їх не бачить.

Правила:
  1. жоден НЕ-UI модуль не залежить від UI-модуля - ні прямо, ні через ланцюг;
  2. жоден НЕ-UI модуль не посилається в XML на ідентифікатор UI-модуля
     (пункт меню під чужим розділом падає на порожній базі);
  3. у addons/ немає жодного власного static/src - екранів ми більше не пишемо;
     тема прийде окремим модулем, тоді це правило перепишемо разом із нею;
  4. жоден модуль у addons/ не згадує відкладений екран (shelved/addons-owl);
  5. єдиний UI-модуль - l10n_ua_navigation - справді везе меню.

Запуск: python3 scripts/layers_check.py"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "addons")
SHELVED = os.path.join(ROOT, "shelved", "addons-owl")

# Модуль інтерфейсу рівно один: власник меню. Йому можна залежати від будь-чого.
UI_MODULES = {"l10n_ua_navigation"}
OURS = re.compile(r"^(l10n_ua_|bp_)")

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def manifests():
    out = {}
    for name in sorted(os.listdir(ADDONS)):
        path = os.path.join(ADDONS, name, "__manifest__.py")
        if not os.path.isfile(path):
            continue
        try:
            out[name] = ast.literal_eval(open(path, encoding="utf-8").read())
        except Exception as error:
            check(f"{name}: маніфест читається", False, str(error))
            out[name] = {}
    return out


MANIFESTS = manifests()
DEPENDS = {name: list(data.get("depends") or []) for name, data in MANIFESTS.items()}
# Відкладені екрани переїхали в репозиторій odoo-ui (reference/owl-2026-09-22); тут лишається
# лише перелік їхніх назв, щоб жоден модуль ядра на них не посилався.
SHELVED_MODULES = sorted([
    "l10n_ua_bank_ui", "l10n_ua_card_ui", "l10n_ua_dashboard", "l10n_ua_hire_ui", "l10n_ua_home",
    "l10n_ua_papers", "l10n_ua_payroll_ui", "l10n_ua_people", "l10n_ua_period",
    "l10n_ua_reporting_ui", "l10n_ua_setup_ui", "l10n_ua_shell",
] + [name for name in (os.listdir(SHELVED) if os.path.isdir(SHELVED) else [])
     if os.path.isdir(os.path.join(SHELVED, name))])


def chain_to_ui(module, seen=None, path=None):
    """Найкоротший ланцюг залежностей від module до UI-модуля, або None."""
    seen = seen if seen is not None else set()
    path = path or [module]
    for dep in DEPENDS.get(module, []):
        if dep in UI_MODULES:
            return path + [dep]
        if dep in seen or dep not in DEPENDS:
            continue
        seen.add(dep)
        found = chain_to_ui(dep, seen, path + [dep])
        if found:
            return found
    return None


def files_of(name, suffixes):
    for base, _dirs, file_names in os.walk(os.path.join(ADDONS, name)):
        if "__pycache__" in base:
            continue
        for file_name in file_names:
            if file_name.endswith(suffixes):
                yield os.path.join(base, file_name)


def read_no_comments(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith(".xml"):
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


# 1. залежності
for name in sorted(DEPENDS):
    if name in UI_MODULES:
        continue
    chain = chain_to_ui(name)
    check(f"{name} не залежить від інтерфейсу", chain is None, " -> ".join(chain or []))

# 2. посилання в XML на ідентифікатори UI-модулів
XMLID = re.compile(r"\b(%s)\.[a-zA-Z0-9_]+" % "|".join(sorted(UI_MODULES)))
for name in sorted(MANIFESTS):
    if name in UI_MODULES or not OURS.match(name):
        continue
    hits = []
    for path in files_of(name, (".xml",)):
        for match in XMLID.finditer(read_no_comments(path)):
            hits.append("%s: %s" % (os.path.relpath(path, ADDONS), match.group(0)))
    check(f"{name}: XML не посилається на інтерфейс", not hits, "; ".join(hits[:4]))

# 3. static/src у addons/ більше немає взагалі - вендорований OCA не рахуємо
for name in sorted(MANIFESTS):
    if not OURS.match(name):
        continue
    has_assets = os.path.isdir(os.path.join(ADDONS, name, "static", "src"))
    check(f"{name}: без static/src", not has_assets, "є static/src" if has_assets else "")

# 4. жодного ЖИВОГО посилання на відкладений екран у addons/
#    Живе посилання - це depends у маніфесті, ідентифікатор у XML, env.ref або import
#    у Python. Згадка в коментарі чи в тексті міграції, яка саме прибирає старий модуль,
#    посиланням не є: теки migrations/ пропускаємо, у Python дивимось лише на ref/import.
if SHELVED_MODULES:
    names = "|".join(SHELVED_MODULES)
    XML_REF = re.compile(r"\b(%s)\.[a-zA-Z0-9_]+" % names)
    PY_REF = re.compile(r"""(?:env\.ref\(\s*["']|odoo\.addons\.)(%s)\b""" % names)
    for name in sorted(MANIFESTS):
        if not OURS.match(name):
            continue
        hits = [dep for dep in DEPENDS.get(name, []) if dep in SHELVED_MODULES]
        for path in files_of(name, (".xml", ".py")):
            if os.sep + "migrations" + os.sep in path:
                continue
            text = read_no_comments(path)
            finder = XML_REF if path.endswith(".xml") else PY_REF
            for match in finder.finditer(text):
                hits.append("%s: %s" % (os.path.relpath(path, ADDONS), match.group(0)))
        check(f"{name}: не посилається на відкладені екрани", not hits, "; ".join(hits[:4]))
else:
    check("тека відкладених екранів на місці", False, SHELVED)

# 5. модуль інтерфейсу справді везе меню
for name in sorted(UI_MODULES):
    if name not in MANIFESTS:
        check(f"{name}: модуль є в addons/", False)
        continue
    data = MANIFESTS[name].get("data") or []
    check(f"{name}: модуль інтерфейсу везе меню",
          any("menu" in f for f in data), str(data))

if errors:
    print(f"\nПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    for label in errors:
        print(f"  - {label}")
    sys.exit(1)
print(f"\nУсі перевірки пройдено ({total} з {total}).")
