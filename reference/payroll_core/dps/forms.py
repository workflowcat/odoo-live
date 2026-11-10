# -*- coding: utf-8 -*-
"""Тіло додатків Д1 (J0510111) і 4ДФ (J0510411).

Формат ДПС: значення однієї колонки йдуть підряд, кожне з атрибутом ROWNUM. Рядок
описується словником колонок; колонка «ознака» (G25 у Д1, G09 у 4ДФ) каже, це рядок
на введення (0) чи на вилучення (1). Підсумки рахуються зі знаком: вилучення віднімається.
"""
from . import xml

D1_COLS = ["G5", "G6", "G7S", "G8", "G9", "G101", "G102", "G111S", "G112S", "G113S", "G12", "G13",
           "G14", "G15", "G16", "G17", "G18", "G19", "G20", "G21", "G22", "G23", "G24", "G25", "G26"]
DF_COLS = ["G02", "G03A", "G03", "G04A", "G04", "G5A", "G5", "G05", "G06D", "G07D", "G08", "G09"]
D1_FLAG, DF_FLAG = "G25", "G09"   # графа 26 Д1 - нефіксований робочий час, не ознака рядка
D1_SUMS = [("R01G16", "G16"), ("R01G17", "G17"), ("R01G18", "G18"), ("R01G19", None), ("R01G20", "G20")]
DF_SUMS = [("R01G03A", "G03A"), ("R01G03", "G03"), ("R01G04A", "G04A"), ("R01G04", "G04"),
           ("R01G5A", "G5A"), ("R01G5", "G5")]

ESV_CAT = {"employment": "1", "disabled": "2", "gph": "26", "sick": "29", "mat": "42"}
INCOME_SIGN = {"employment": "101", "gph": "102", "fop": "157"}
PSP_CODE = {"none": None, "base": "01", "child": "04", "child150": "04", "s150": "02", "s200": "03"}


def r2(value):
    return round(float(value or 0.0) + 1e-9, 2)


def text_row(row, cols, flag="0"):
    """Рядок у тому вигляді, у якому він лягає в XML: усі колонки - текст."""
    out = {}
    for col in cols:
        if col in ("G111S", "G112S", "G113S") and "names" in row:
            value = row["names"][("G111S", "G112S", "G113S").index(col)]
        else:
            value = row.get(col)
        out[col] = "" if value is None or value == "" or value is False else xml.fmt(value)
    out[D1_FLAG if cols is D1_COLS else DF_FLAG] = flag
    return out


def signed_sum(rows, col, flag_col):
    """Підсумок колонки: рядок на вилучення входить зі знаком мінус."""
    total = 0.0
    for row in rows:
        value = row.get(col) or ""
        if not value:
            continue
        total += -float(value) if row.get(flag_col) == "1" else float(value)
    return r2(total)


def _head(company, doc_type, year, month):
    return [("HZ", doc_type == "HZ"), ("HZN", doc_type == "HZN"), ("HZU", doc_type == "HZU"),
            ("HZY", year), ("HZM", month)]


def _signers(company, fill_date):
    return [("HFILL", fill_date), ("HKBOS", company.director_rnokpp or ""),
            ("HBOS", company.director_name or ""),
            ("HKBUH", company.accountant_rnokpp or None), ("HBUH", company.accountant_name or None)]


def d1_body(company, year, month, rows, doc_type="HZ", fill_date=None):
    """Тіло Д1 з готових текстових рядків."""
    fields = _head(company, doc_type, year, month) + [("HNAME", company.name), ("HTIN", company.tin)]
    for col in D1_COLS:
        for index, row in enumerate(rows, 1):
            fields.append(("T1RXXXX%s" % col, row.get(col) or None, {"ROWNUM": index}))
    for tag, col in D1_SUMS:
        if col is None:
            fields.append((tag, 0.0))
            continue
        value = signed_sum(rows, col, D1_FLAG)
        fields.append((tag, value if (value or tag != "R01G18") else None))
    return fields + _signers(company, fill_date)


def df_body(company, year, month, rows, number=1, employment_count=0, gph_count=0,
            doc_type="HZ", fill_date=None):
    """Тіло 4ДФ з готових текстових рядків."""
    fields = _head(company, doc_type, year, month) + [
        ("HNUM", number), ("HNAME", company.name), ("HTIN", company.tin),
        ("HKATOTTG", company.katottg or "")]
    fields += [("R00G01I", employment_count), ("R00G02I", gph_count)]
    for col in DF_COLS:
        for index, row in enumerate(rows, 1):
            fields.append(("T1RXXXX%s" % col, row.get(col) or None, {"ROWNUM": index}))
    fields += [(tag, signed_sum(rows, col, DF_FLAG)) for tag, col in DF_SUMS]
    return fields + _signers(company, fill_date)


def build_d1(company, year, month, rows, doc_type="HZ", fill_date=None, number=1, stan=1):
    """Готовий файл Д1: (ім'я, bytes)."""
    text = [row if isinstance(row.get(D1_FLAG), str) else text_row(row, D1_COLS) for row in rows]
    return xml.build(company, "J05", "101", "11", 1, month, year,
                     d1_body(company, year, month, text, doc_type, fill_date),
                     c_doc_cnt=number, c_doc_stan=stan, fill_date=fill_date)


def build_4df(company, year, month, rows, employment_count=0, gph_count=0, doc_type="HZ",
              fill_date=None, number=1, stan=1):
    """Готовий файл 4ДФ: (ім'я, bytes)."""
    text = [row if isinstance(row.get(DF_FLAG), str) else text_row(row, DF_COLS) for row in rows]
    return xml.build(company, "J05", "104", "11", 1, month, year,
                     df_body(company, year, month, text, number, employment_count, gph_count,
                             doc_type, fill_date),
                     c_doc_cnt=number, c_doc_stan=stan, fill_date=fill_date)
