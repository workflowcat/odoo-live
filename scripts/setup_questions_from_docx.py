#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Зібрати каталог питань анкети з файла Лани у дані модуля.

Джерело: «Анкета (фінанси) — питання.docx». Скрипт не вигадує питань: він переносить
текст як є, розставляє розділи за першим питанням кожного і позначає обов'язкові (⚠).

Запуск: python3 scripts/setup_questions_from_docx.py "<шлях до .docx>"
Результат: addons/l10n_ua_setup/data/ua_setup_question_data.xml
"""
import html
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "addons", "l10n_ua_setup", "data", "ua_setup_question_data.xml")

# Розділ починається з питання, текст якого наведено ключем.
SECTIONS = [
    ("Яка назва компанії?", "1. Компанія"),
    ("⚠ Яку систему оподаткування використовує компанія?", "2. Система оподаткування"),
    ("⚠ Хто ваші клієнти?", "3. Клієнти і валюта"),
    ("Скільки рахунків відкрито в банках?", "4. Банк і підписи"),
    ("Скільки людей залучено зараз?", "5. Люди і форми залучення"),
    ("Чи не плануєте оклади не нижче мінімалки (8 647 грн у 2026)?", "6. Зарплата"),
    ("⚠ Чи плануєте бронювання працівників?", "7. Військовий облік і бронювання"),
    ("Хто веде облік?", "8. Облік і Дія.City"),
    ("Чи будуть передані вхідні залишки (гроші, дебіторка/кредиторка, основні засоби, розрахунки з людьми)?",
     "9. Вхідні залишки і історія"),
    ("Хто директор / підписант компанії?", "10. Ролі і відповідальні"),
    ("Який пріоритет на найближчі 3–6 місяців? (позначте головне)", "11. Плани"),
]


def paragraphs(path):
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    out = []
    for block in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = html.unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.S))).strip()
        if text:
            out.append(text)
    return out


def parse(lines):
    """Питання, варіанти і підказки в порядку документа."""
    questions, current, section = [], None, ""
    starts = dict(SECTIONS)
    for line in lines:
        if re.match(r"^\d+\.\s", line) and len(line) < 60:      # заголовок розділу в документі
            continue
        if line in starts:
            section = starts[line]
        if line.startswith("☐"):
            if current:
                current["options"].append(line.lstrip("☐ ").strip())
            continue
        if "?" in line and "→" not in line:          # питання може мати хвіст «(позначте все)»
            current = {"section": section or "1. Компанія", "title": line.lstrip("⚠ ").strip(),
                       "required": line.startswith("⚠"), "options": [], "fields": [], "hint": ""}
            questions.append(current)
            continue
        if "→" in line and current:
            label = line.split("→")[0].strip()
            current["fields"].append(label or "Відповідь")
            continue
        if current and not line.startswith("Питання з позначкою"):
            current["hint"] = (current["hint"] + " " + line).strip()
    return questions


def kind_of(question):
    if question["options"] and any(word in question["title"].lower() for word in ("позначте все", "враховуємо все")):
        return "multi"
    if question["options"]:
        return "choice"
    return "text"


def escape(value):
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/Downloads/Анкета (фінанси) — питання (1).docx")
    questions = parse(paragraphs(path))
    rows = []
    for index, question in enumerate(questions, 1):
        code = "q%03d" % index
        options = " | ".join(question["options"] + ["%s: ___" % f for f in question["fields"]])
        rows.append(
            '    <record id="question_%s" model="ua.setup.question">\n'
            '      <field name="code">%s</field>\n'
            '      <field name="sequence">%s</field>\n'
            '      <field name="section">%s</field>\n'
            '      <field name="name">%s</field>\n'
            '      <field name="kind">%s</field>\n'
            '      <field name="required" eval="%s"/>\n'
            '      <field name="options">%s</field>\n'
            '      <field name="hint">%s</field>\n'
            '    </record>' % (
                code, code, index * 10, escape(question["section"]), escape(question["title"]),
                kind_of(question), "True" if question["required"] else "False",
                escape(options), escape(question["hint"])))
    body = "\n".join(rows)
    with open(OUT, "w", encoding="utf-8") as stream:
        stream.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<!-- Каталог питань анкети. Створено скриптом scripts/setup_questions_from_docx.py\n"
            "     з файла бухгалтера. Текст питань не змінюємо: анкету звіряють з оригіналом. -->\n"
            "<odoo>\n  <data noupdate=\"0\">\n%s\n  </data>\n</odoo>\n" % body)
    required = sum(1 for q in questions if q["required"])
    sections = sorted({q["section"] for q in questions})
    print("питань: %s, обов'язкових: %s" % (len(questions), required))
    print("розділів: %s" % len(sections))
    for s in sections:
        print("  %s — %s" % (s, sum(1 for q in questions if q["section"] == s)))
    print("файл:", OUT)


if __name__ == "__main__":
    main()
