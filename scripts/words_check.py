#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слова в інтерфейсі: перевірка норми docs/payroll/words.md. Стенд не потрібен.

Що читаємо: XML власних модулів у теках views/ і wizards/ - те, що людина бачить на
екрані: назви пунктів меню, заголовки кнопок і сторінок, мітки полів, підказки,
підтвердження. Атрибути string, name (лише в menuitem), placeholder, help, confirm,
title, label.

Чого НЕ читаємо: report/ - друковані форми (НАКАЗ, ЗАТВЕРДЖУЮ великими літерами - це
бланк, а не крик) і data/ - дані та код правил.

Що забороняємо:
  1. розповідь від першої особи - «ми», «нам», «наш» у видимому рядку;
  2. слова-затички - «зараз», «просто», «тут ви бачите»;
  3. рядки, які замінено таблицею words.md («Що ставимо в цей папір», «Так це
     виглядатиме», «Скласти чернетку», «Правити рядки», «Друк пакета» тощо);
  4. нагнітання - знак оклику і слово ВЕЛИКИМИ літерами (від чотирьох літер);
  5. довге тире: у продукті його немає ніде;
  6. синоніми обраних слів (правило 4 words.md, «одне слово - одне значення»):
     на кожну дію в продукті одне ім'я, і NAMES нижче - його словник.

Запуск: python3 scripts/words_check.py"""
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "addons")
OURS = re.compile(r"^(l10n_ua_|bp_)")

# Атрибути, які людина читає на екрані.
VISIBLE_ATTRS = ("string", "placeholder", "help", "confirm", "title", "label", "sum", "avg")
# <menuitem name="..."> і <field name="назва поля"> - name значить різне; беремо лише меню.
MENU_TAGS = ("menuitem",)

RULES = [
    ("розповідь від першої особи", re.compile(r"\b(ми|нам|нами|наш|наша|наше|наші|нашого|нашій)\b", re.I)),
    ("слово-затичка", re.compile(r"\b(зараз|просто|тут ви бачите|будь ласка)\b", re.I)),
    ("рядок із таблиці замін words.md", re.compile(
        r"(що ставимо в цей папір|так це виглядатиме|зроблено раніше|скласти чернетку|"
        r"правити рядки|що ми вимагаємо|друк пакета|не принесла|принесла|зробили ми)", re.I)),
    ("нагнітання: знак оклику", re.compile(r"!")),
    ("нагнітання: ВЕЛИКІ ЛІТЕРИ", re.compile(r"\b[А-ЯЄІЇҐ]{4,}\b")),
    ("довге тире", re.compile("[\\u2014\\u2013]")),
]

# Одне слово - одне значення (words.md, правило 4). Ключ - обране слово, значення -
# синоніми, яких у продукті бути не має. Порівнюємо цілий рядок кнопки чи пункту меню,
# а не підрядок: «Виправити помилку» в підказці - нормальний текст, а кнопка
# «Виправити» замість «Редагувати» - розбіжність.
NAMES = {
    "Редагувати": ("Правити", "Змінити", "Виправити", "Коригувати"),
    "Створити": ("Завести", "Додати запис", "Новий запис", "Сформувати чернетку"),
    "Друк": ("Надрукувати", "Роздрукувати", "Вивести на друк"),
    "Затвердити": ("Підтвердити", "Провести документ", "Зафіксувати"),
    "Перерахувати": ("Оновити розрахунок", "Порахувати знову", "Перерахунок"),
    "Заповнити": ("Наповнити", "Підтягнути дані"),
    "Видалити": ("Знищити", "Стерти"),
    "Закрити": ("Вийти", "Відмінити", "Відміна"),
}
WRONG_NAMES = {
    wrong.lower(): right for right, wrongs in NAMES.items() for wrong in wrongs
}

# Абревіатури великими літерами - назви, не крик.
ALLOWED_CAPS = {
    "ПФУ", "ДПС", "ЄСВ", "ПДФО", "ПДВ", "ПРРО", "РНОКПП", "ЄДРПОУ", "ЄДР", "ТЦК", "МЗП", "ЦПХ",
    "ФОП", "КЗпП", "ОСВ", "КО", "ЄП", "ІПН", "МФО", "IBAN", "XML", "PDF", "CSV", "УБД",
    "ВПО", "СЗЧ", "ТОВ", "ПрАТ", "АТ", "ФО", "ЮО", "КВЕД", "ДРФО", "ПН", "РК", "ОЗ",
    "БАС", "НБУ", "ЗЕД", "ДК", "КП", "ЄРПН", "БПЛА", "ТМЦ", "ПММ",
}

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    if not ok:
        print(f"[FAIL] {label} - {detail}")
        errors.append(f"{label}: {detail}")


def strings_of(path):
    """Видимі рядки одного XML-файла: (номер рядка ≈, рядок)."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as error:
        check(f"{os.path.relpath(path, ROOT)}: XML читається", False, str(error))
        return
    for node in tree.iter():
        tag = node.tag if isinstance(node.tag, str) else ""
        for attr in VISIBLE_ATTRS:
            value = node.get(attr)
            if value and not value.startswith("{"):
                yield attr, value
        if tag in MENU_TAGS and node.get("name"):
            yield "name", node.get("name")


def visible_files():
    for name in sorted(os.listdir(ADDONS)):
        if not OURS.match(name):
            continue
        for base, _dirs, files in os.walk(os.path.join(ADDONS, name)):
            if "__pycache__" in base:
                continue
            # Тека майстрів зветься і "wizards", і "wizard" - читаємо обидві.
            if not base.endswith((os.sep + "views", os.sep + "wizards", os.sep + "wizard")):
                continue
            for file_name in sorted(files):
                if file_name.endswith(".xml"):
                    yield os.path.join(base, file_name)


def caps_ok(value):
    """Великі літери, яких немає в переліку абревіатур."""
    return [w for w in re.findall(r"\b[А-ЯЄІЇҐ]{2,}\b", value) if w not in ALLOWED_CAPS and len(w) >= 4]


scanned = 0
for path in visible_files():
    rel = os.path.relpath(path, ROOT)
    for where, value in strings_of(path):
        scanned += 1
        for label, pattern in RULES:
            if label == "нагнітання: ВЕЛИКІ ЛІТЕРИ":
                bad = caps_ok(value)
                check(f"{rel} [{where}] {label}", not bad, f"{bad}: «{value[:90]}»")
                continue
            hit = pattern.search(value)
            check(f"{rel} [{where}] {label}", not hit,
                  f"«{hit.group(0)}» у «{value[:90]}»" if hit else "")
        if where in ("string", "name"):
            right = WRONG_NAMES.get(value.strip().lower())
            check(f"{rel} [{where}] одне слово - одне значення", right is None,
                  f"«{value.strip()}» - у продукті це «{right}»")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} зауважень на {scanned} рядків інтерфейсу")
    sys.exit(1)
print(f"Усі перевірки пройдено ({scanned} рядків інтерфейсу, {total} перевірок).")
