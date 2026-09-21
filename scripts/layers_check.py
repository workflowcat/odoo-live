#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка поділу на логіку і інтерфейс. Стенд не потрібен - читаємо самі файли.

Правило одне: логіка не знає про інтерфейс.
  1. жоден НЕ-UI модуль не залежить від UI-модуля - ні прямо, ні через ланцюг;
  2. жоден НЕ-UI модуль не посилається в XML на ідентифікатор UI-модуля
     (пункт меню під чужим розділом падає на порожній базі);
  3. свій НЕ-UI модуль (l10n_ua_*, bp_*) не везе static/src - екран є екран.

Винятків із правила 3 більше немає: останні чотири змішані модулі поділено на пару
«логіка + <модуль>_ui» (hire, reporting, setup, bank_online -> bank_ui). Модуль із
бізнес-моделлю, у якому з'явиться static/src, провалює перевірку.

Запуск: python3 scripts/layers_check.py"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "addons")

# Модулі інтерфейсу: меню, каркас, екрани. Їм можна залежати від будь-чого.
UI_MODULES = {
    "l10n_ua_shell",
    "l10n_ua_navigation",
    "l10n_ua_home",
    "l10n_ua_period",
    "l10n_ua_papers",
    "l10n_ua_people",
    "l10n_ua_dashboard",
    "l10n_ua_card_ui",
    "l10n_ua_payroll_ui",
    "l10n_ua_hire_ui",
    "l10n_ua_reporting_ui",
    "l10n_ua_setup_ui",
    "l10n_ua_bank_ui",
}
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
    for base, _dirs, files in os.walk(os.path.join(ADDONS, name)):
        for file_name in files:
            if not file_name.endswith(".xml"):
                continue
            path = os.path.join(base, file_name)
            text = open(path, encoding="utf-8", errors="replace").read()
            # коментарі не рахуємо: у них пояснення, а не посилання
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            for match in XMLID.finditer(text):
                hits.append("%s: %s" % (os.path.relpath(path, ADDONS), match.group(0)))
    check(f"{name}: XML не посилається на інтерфейс", not hits, "; ".join(hits[:4]))

# 3. static/src у своїх не-UI модулях - винятків немає
for name in sorted(MANIFESTS):
    if name in UI_MODULES or not OURS.match(name):
        continue
    has_assets = os.path.isdir(os.path.join(ADDONS, name, "static", "src"))
    check(f"{name}: логіка без static/src", not has_assets, "є static/src" if has_assets else "")

# 4. кожен модуль інтерфейсу справді везе екран або меню: назва _ui без static/src і без
#    даних меню означала б, що поділ зробили наполовину.
for name in sorted(UI_MODULES):
    if name not in MANIFESTS:
        continue
    assets = MANIFESTS[name].get("assets") or {}
    data = MANIFESTS[name].get("data") or []
    has_screen = bool(assets) or any(("menu" in f or "views" in f) for f in data)
    check(f"{name}: модуль інтерфейсу везе екран чи меню", has_screen)

if errors:
    print(f"\nПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    for label in errors:
        print(f"  - {label}")
    sys.exit(1)
print(f"\nУсі перевірки пройдено ({total} з {total}).")
