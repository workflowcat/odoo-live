#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка договору `docs/api`: опис ядра не розійшовся з кодом.

Стенд не потрібен - усе читається з файлів і з git, тому це перша перевірка в
`scripts/check_all.sh` і єдина, яку можна ганяти в CI без бази.

Три пункти:

  1. `docs/api/inventory.md` збігається з тим, що зараз дає `api_inventory.py`;
  2. `docs/api/inventory.json` - так само;
  3. якщо порівняно з комітом HEAD із опису ЗНИК або перейменувався публічний метод
     чи поле, у цьому ж робочому дереві має бути зачеплений `docs/api/CHANGELOG.md`.
     Додавання нового методу нічого не вимагає - інтерфейс від нього не ламається.

Перейменування ядро бачить як зникнення старої назви і появу нової, тому окремого
правила для нього немає: стара назва зникла, отже потрібен рядок у CHANGELOG.

Запуск: python3 scripts/contract_check.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api_inventory                                             # noqa: E402

MD = os.path.join(ROOT, "docs", "api", "inventory.md")
JSON = os.path.join(ROOT, "docs", "api", "inventory.json")
CHANGELOG = "docs/api/CHANGELOG.md"

errors = []
total = 0


def check(label, ok, detail=""):
    """Один пункт. Подробиця показується лише коли пункт провалено."""
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        errors.append(label)


def git(*args):
    try:
        out = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def read(path):
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else None


def first_difference(new, old):
    """Перший рядок, де тексти розходяться - щоб не друкувати весь diff."""
    new_lines, old_lines = new.splitlines(), (old or "").splitlines()
    for i in range(max(len(new_lines), len(old_lines))):
        a = new_lines[i] if i < len(new_lines) else "(кінець файлу)"
        b = old_lines[i] if i < len(old_lines) else "(кінець файлу)"
        if a != b:
            return "рядок %s: у файлі «%s», має бути «%s»" % (i + 1, b[:90], a[:90])
    return ""


def names(payload):
    """Пласка множина публічних імен опису: модель.метод() і модель.поле."""
    out = set()
    for area in payload.get("areas", []):
        for model in area.get("models", []):
            for method in model.get("methods", []):
                out.add("%s.%s()" % (model["model"], method["name"]))
            for field in model.get("fields", []):
                out.add("%s.%s" % (model["model"], field["name"]))
    return out


# ------------------------------------------------------------------ 1-2. опис свіжий
fresh_md, fresh_json, sums = api_inventory.build()

committed_md = read(MD)
check("docs/api/inventory.md збігається з кодом", committed_md == fresh_md,
      "перегенеруйте: python3 scripts/api_inventory.py"
      + (" · " + first_difference(fresh_md, committed_md) if committed_md else " · файлу немає"))

committed_json = read(JSON)
check("docs/api/inventory.json збігається з кодом", committed_json == fresh_json,
      "перегенеруйте: python3 scripts/api_inventory.py"
      + ("" if committed_json else " · файлу немає"))

# ------------------------------------------------------------------ 3. зникле - у CHANGELOG
head_json = git("show", "HEAD:docs/api/inventory.json")
if head_json is None:
    check("опис у HEAD є (перший коміт договору пропускає перевірку зниклого)", True)
else:
    try:
        before = names(json.loads(head_json))
    except ValueError as error:
        before = set()
        check("опис у HEAD читається", False, str(error))
    gone = sorted(before - names(json.loads(fresh_json)))
    if not gone:
        check("нічого публічного не зникло", True)
    else:
        touched = set((git("diff", "--name-only", "HEAD") or "").split())
        touched |= set((git("status", "--porcelain", "--", CHANGELOG) or "").split())
        check("зникле описане в %s" % CHANGELOG, CHANGELOG in touched,
              "зникло: %s%s" % (", ".join(gone[:6]), " …" if len(gone) > 6 else ""))

if errors:
    print(f"\nПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    for label in errors:
        print(f"  - {label}")
    sys.exit(1)
print("\nМодулів: %s, моделей: %s, методів: %s, полів: %s."
      % (sums["modules"], sums["models"], sums["methods"], sums["fields"]))
print(f"Усі перевірки пройдено ({total} з {total}).")
