"""Читання таблиць з файла (CSV з 1С чи прайсу, XLSX) без Odoo.

1С і постачальники віддають CSV у windows-1251 з «;», Excel - XLSX. Тут одна
функція read_table(): байти файла -> список рядків (списки рядків тексту) і номер
рядка заголовка. Заголовок шукаємо серед перших 15 рядків: рядок, де найбільше клітинок
схожі на назви колонок (найменування, назва, артикул, ціна).
"""
import csv
import re
import io

HEADER_WORDS = ("найменування", "наименование", "назва", "название", "товар", "номенклатура",
                "артикул", "код", "ціна", "цена", "price", "name", "sku")


def _decode(raw):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _delimiter(text):
    """Роздільник CSV: той, що дає найбільше клітинок у рядках однакової ширини
    (рядків такої ширини x ширина); за рівності - «;». csv.Sniffer тут не годиться: у
    рядку «Ціна, грн» і в цінах «396,00» кома трапляється в кожному рядку однаково, і він
    обирає кому."""
    lines = [line for line in text[:8192].splitlines() if line.strip()][:30]
    best, best_score = ";", (0, 0)
    for delimiter in (";", "\t", ","):
        widths = [len(row) for row in csv.reader(lines, delimiter=delimiter)]
        common = max(set(widths), key=widths.count) if widths else 0
        if common < 2:
            continue
        score = (widths.count(common) * common, common)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def read_table(raw, filename=""):
    """-> (rows, header_index). rows - список списків тексту; header_index або None."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or raw[:2] == b"PK":
        import openpyxl  # noqa: PLC0415 - важка бібліотека, потрібна лише для XLSX
        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = book.worksheets[0]
        rows = [["" if v is None else str(v).strip() for v in row]
                for row in sheet.iter_rows(values_only=True)]
    else:
        text = _decode(raw)
        rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text),
                                                               delimiter=_delimiter(text))]
    rows = [r for r in rows if any(c for c in r)]
    # Заголовок - рядок, де найбільше клітинок схожі на назви колонок. Рядок-титул
    # «Номенклатура за 2026-11-01» має одну таку клітинку, справжній заголовок - кілька.
    header, best = None, 0
    for i, row in enumerate(rows[:15]):
        hits = sum(1 for c in row if c and any(w in c.lower() for w in HEADER_WORDS))
        if hits > best:
            header, best = i, hits
    return rows, header


def guess_column(header_row, words, exclude=()):
    """Номер колонки, назва якої найкраще збігається з одним зі слів, або None.

    Спершу точний збіг («Од» для «од»), далі слово на початку чи окремим словом
    («Од. вим.»), і лише тоді частина слова: так «Код» не стає колонкою одиниці.
    """
    best = None
    for i, cell in enumerate(header_row or []):
        if i in exclude:
            continue
        low = (cell or "").lower().strip()
        tokens = [t.rstrip(".") for t in re.findall(r"[\w.]+", low)]
        for rank, word in enumerate(words):
            bare = word.strip().rstrip(".")
            if not bare:
                continue
            if low.rstrip(". ") == bare:
                score = 0
            elif low.startswith(word.strip()) or bare in tokens:
                score = 1
            elif bare in low:
                score = 2
            else:
                continue
            key = (score, rank, i)
            if best is None or key < best[0]:
                best = (key, i)
    return best[1] if best else None


def to_float(text):
    """«1 234,50 грн» -> 1234.5; порожньо чи не число -> None."""
    s = (text or "").replace(" ", "").replace(" ", "").replace(",", ".")
    s = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    if s.count(".") > 1:
        head, _sep, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return float(s) if s not in ("", ".", "-") else None
    except ValueError:
        return None
