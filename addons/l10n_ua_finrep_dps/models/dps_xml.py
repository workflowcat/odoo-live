# -*- coding: utf-8 -*-
"""Каркас XML за форматом ДПС: DECLAR / DECLARHEAD / DECLARBODY, ім'я файлу, перевірка схемою.

Порядок тегів тіла і формат чисел беруться зі схеми форми (XSD поруч із модулем, що її подає), а
готовий документ перевіряється тією самою схемою: файл, який схема відхилить, назовні не йде.
Спільне для фінзвітності і декларації з прибутку; інші форми можуть брати так само.
"""
import os
import re

from lxml import etree

XS = "{http://www.w3.org/2001/XMLSchema}"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SOFTWARE = "odoo-live"

_SCHEMAS = {}


def schema(path):
    """(XMLSchema, [(тег, тип)] тіла DBody по порядку); читається один раз на шлях."""
    if path not in _SCHEMAS:
        tree = etree.parse(path)
        body = tree.find(".//%scomplexType[@name='DBody']/%ssequence" % (XS, XS))
        elements = [(el.get("name"), el.get("type")) for el in body.iter(XS + "element")
                    if el.get("name")]
        _SCHEMAS[path] = (etree.XMLSchema(tree), elements)
    return _SCHEMAS[path]


def schema_path(module_file, form):
    """Шлях до schemas/<форма>.xsd модуля, з файлу якого викликають."""
    return os.path.join(os.path.dirname(os.path.dirname(module_file)), "schemas", "%s.xsd" % form)


def number(value, type_name):
    """Число за типом схеми."""
    if type_name == "DGdecimal0":
        return "%d" % round(value)
    if type_name == "DGdecimal1":
        return "%.1f" % round(value, 1)
    return "%.2f" % round(value, 2)


def _cell(value, type_name):
    """Текст клітинки таблиці (тег з ROWNUM) або None, якщо клітинку не пишемо."""
    if value is None or value is False or value == "":
        return None
    if isinstance(value, bool):
        return "1"
    if isinstance(value, (int, float)):
        digits = re.search(r"Decimal(\d)", type_name or "")
        if digits:
            if not round(value, 2):
                return None
            return "%.*f" % (int(digits.group(1)), round(value, int(digits.group(1))))
        return "%d" % value
    return str(value)


def file_name(form, sti, tin, period_type, month, year, count=1, state=1, doc_type=0):
    """Ім'я файлу: ДПІ(4) ЄДРПОУ(10) форма(8) стан(1) тип(2) номер(7) період(1) місяць(2) рік(4) ДПІ(4)."""
    return "%s%s%s%d%02d%07d%d%02d%d%s.XML" % (
        sti, tin.rjust(10, "0"), form, state, doc_type, count, period_type, month, year, sti)


def build(path, form, sti, tin, period_type, month, year, fill_date, values, linked=(), state=1, doc_type=0):
    """(ім'я файлу, байти windows-1251). Порожні значення не пишуться; помилка схеми - ValueError.

    values: {тег: значення}; числа форматуються за типом тегу у схемі, позначки (DGchk) - «1».
    Колонка таблиці - список [(номер рядка, значення)]: кожна клітинка - тег з ROWNUM.
    linked: [(форма, ім'я файлу, тип зв'язку)] для LINKED_DOCS; пов'язані документи подаються
    разом, тож мають той самий стан і номер.
    state, doc_type: C_DOC_STAN і C_DOC_TYPE - 1 і 0 для звітного, 2 і номер для звітного нового.
    """
    xml_schema, elements = schema(path)
    root = etree.Element("DECLAR", nsmap={"xsi": XSI})
    root.set("{%s}noNamespaceSchemaLocation" % XSI, "%s.xsd" % form)
    head = etree.SubElement(root, "DECLARHEAD")
    for tag, value in [
        ("TIN", tin), ("C_DOC", form[:3]), ("C_DOC_SUB", form[3:6]), ("C_DOC_VER", str(int(form[6:8]))),
        ("C_DOC_TYPE", str(doc_type)), ("C_DOC_CNT", "1"), ("C_REG", str(int(sti[:2]))),
        ("C_RAJ", str(int(sti[2:4]))), ("PERIOD_MONTH", str(month)), ("PERIOD_TYPE", str(period_type)),
        ("PERIOD_YEAR", str(year)), ("C_STI_ORIG", sti), ("C_DOC_STAN", str(state)),
    ]:
        etree.SubElement(head, tag).text = value
    docs = etree.SubElement(head, "LINKED_DOCS")
    if not linked:
        docs.set("{%s}nil" % XSI, "true")
    for num, (other, other_name, link_type) in enumerate(linked, start=1):
        doc = etree.SubElement(docs, "DOC", NUM=str(num), TYPE=str(link_type))
        for tag, value in [("C_DOC", other[:3]), ("C_DOC_SUB", other[3:6]), ("C_DOC_VER", str(int(other[6:8]))),
                           ("C_DOC_TYPE", str(doc_type)), ("C_DOC_CNT", "1"), ("C_DOC_STAN", str(state)),
                           ("FILENAME", other_name)]:
            etree.SubElement(doc, tag).text = value
    etree.SubElement(head, "D_FILL").text = fill_date.strftime("%d%m%Y")
    etree.SubElement(head, "SOFTWARE").text = SOFTWARE

    body = etree.SubElement(root, "DECLARBODY")
    for name, type_name in elements:
        value = values.get(name)
        if value is None or value is False or value == "":
            continue
        if isinstance(value, (list, tuple)):
            for rownum, cell in value:
                text = _cell(cell, type_name)
                if text is not None:
                    etree.SubElement(body, name, ROWNUM=str(rownum)).text = text
            continue
        if isinstance(value, bool) or type_name == "DGchk":
            text = "1"
        elif isinstance(value, (int, float)) and type_name and type_name.startswith(("DGdecimal", "DGpercent")):
            if not round(value, 2):
                continue
            text = number(value, type_name)
        else:
            text = str(value)
        etree.SubElement(body, name).text = text
    data = etree.tostring(root, xml_declaration=True, encoding="windows-1251", pretty_print=True)
    document = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    if not xml_schema.validate(document):
        raise ValueError("\n".join("- %s" % error.message for error in list(xml_schema.error_log)[:5]))
    return file_name(form, sti, tin, period_type, month, year, state=state, doc_type=doc_type), data
