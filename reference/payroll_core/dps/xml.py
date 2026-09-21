# -*- coding: utf-8 -*-
"""Каркас XML ДПС: DECLAR / DECLARHEAD / DECLARBODY, ім'я файлу, перевірка за XSD.

Наказ Мінфіну 729. Тіло кожної форми будує окремий модуль; тут лише спільна частина.
Єдина залежність - lxml.
"""
import os
from datetime import date

from lxml import etree

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")
NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


class Company:
    """Реквізити компанії, потрібні для шапки файлу."""

    def __init__(self, name, tin, sti_code, reg="00", raj="00", katottg="",
                 director_name="", director_rnokpp="", accountant_name="", accountant_rnokpp=""):
        self.name = name
        self.tin = str(tin).strip()
        self.sti_code = str(sti_code).strip()
        self.reg = reg
        self.raj = raj
        self.katottg = katottg
        self.director_name = director_name
        self.director_rnokpp = director_rnokpp
        self.accountant_name = accountant_name
        self.accountant_rnokpp = accountant_rnokpp


def fmt(value):
    """Значення у тому вигляді, у якому його чекає ДПС."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "%.2f" % value
    if isinstance(value, date):
        return value.strftime("%d%m%Y")
    return str(value)


def file_name(tin, sti, c_doc, c_doc_sub, c_doc_ver, c_doc_stan, c_doc_type, c_doc_cnt,
              period_type, month, year, sti_orig):
    """Ім'я файлу за форматом ДПС."""
    return ("%s%s%s%s%s%s%s%s%s%s%s%s.XML" % (
        str(sti).rjust(4, "0"), str(tin).rjust(10, "0"), c_doc, c_doc_sub, c_doc_ver, c_doc_stan,
        str(c_doc_type).rjust(2, "0"), str(c_doc_cnt).rjust(7, "0"), period_type,
        str(month).rjust(2, "0"), year, str(sti_orig).rjust(4, "0")))


def build(company, c_doc, c_doc_sub, c_doc_ver, period_type, month, year, body_fields,
          linked=None, c_doc_cnt=1, c_doc_type=0, c_doc_stan=1, fill_date=None):
    """body_fields: список (тег, значення[, атрибути]) у порядку схеми. Повертає (ім'я, bytes)."""
    if not company.tin or not company.sti_code:
        raise ValueError("Потрібні ЄДРПОУ і код ДПІ компанії.")
    name = file_name(company.tin, company.sti_code, c_doc, c_doc_sub, c_doc_ver, c_doc_stan,
                     c_doc_type, c_doc_cnt, period_type, month, year, company.sti_code)
    root = etree.Element("DECLAR", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation",
             "%s%s%s.xsd" % (c_doc, c_doc_sub, c_doc_ver))
    head = etree.SubElement(root, "DECLARHEAD")
    for tag, value in [("TIN", company.tin), ("C_DOC", c_doc), ("C_DOC_SUB", c_doc_sub),
                       ("C_DOC_VER", c_doc_ver), ("C_DOC_TYPE", c_doc_type), ("C_DOC_CNT", c_doc_cnt),
                       ("C_REG", company.reg or "00"), ("C_RAJ", company.raj or "00"),
                       ("PERIOD_MONTH", month), ("PERIOD_TYPE", period_type), ("PERIOD_YEAR", year),
                       ("C_STI_ORIG", company.sti_code), ("C_DOC_STAN", c_doc_stan)]:
        etree.SubElement(head, tag).text = str(value)
    if linked:
        holder = etree.SubElement(head, "LINKED_DOCS")
        for doc in linked:
            node = etree.SubElement(holder, "DOC", NUM=str(doc.get("num", 1)), TYPE=str(doc.get("type", 1)))
            for tag in ("C_DOC", "C_DOC_SUB", "C_DOC_VER", "C_DOC_TYPE", "C_DOC_CNT", "C_DOC_STAN", "FILENAME"):
                etree.SubElement(node, tag).text = str(doc[tag])
    etree.SubElement(head, "D_FILL").text = (fill_date or date.today()).strftime("%d%m%Y")
    etree.SubElement(head, "SOFTWARE").text = "payroll_core"
    body = etree.SubElement(root, "DECLARBODY")
    for item in body_fields:
        tag, value = item[0], item[1]
        attrs = item[2] if len(item) > 2 else {}
        empty = value is None or value == "" or value is False
        if empty and not attrs:
            continue                       # скалярне поле без значення пропускаємо
        node = etree.SubElement(body, tag, **{k: str(v) for k, v in attrs.items()})
        if empty:
            node.set(NIL, "true")          # порожня клітинка таблиці - xsi:nil
        else:
            node.text = fmt(value)
    return name, etree.tostring(root, xml_declaration=True, encoding="windows-1251", pretty_print=True)


def validate(data, schema_code):
    """Перевірка за XSD. Повертає список помилок; порожній список = файл валідний."""
    path = os.path.join(SCHEMAS_DIR, "%s.xsd" % schema_code)
    if not os.path.exists(path):
        return ["Схеми %s.xsd немає в пакеті" % schema_code]
    try:
        schema = etree.XMLSchema(etree.parse(path))
        schema.validate(etree.fromstring(data))
        return ["рядок %s: %s" % (e.line, e.message) for e in schema.error_log]
    except Exception as error:  # noqa: BLE001 - помилка схеми не має зупиняти формування
        return ["не вдалося перевірити за схемою: %s" % error]
