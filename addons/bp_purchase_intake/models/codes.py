"""Checksums and parsing for Ukrainian requisites. Pure functions, no Odoo."""
import re
from datetime import date

MONTHS = {"січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6, "липня": 7,
          "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12}


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def edrpou_valid(code):
    """ЄДРПОУ: 8 digits, check digit by the Мінстат algorithm (two passes of weights)."""
    code = digits(code)
    if len(code) != 8:
        return False
    d = [int(c) for c in code]
    n = int(code)
    w = [7, 1, 2, 3, 4, 5, 6] if 30000000 <= n < 60000000 else [1, 2, 3, 4, 5, 6, 7]
    s = sum(a * b for a, b in zip(d[:7], w)) % 11
    if s == 10:
        s = sum(a * (b + 2) for a, b in zip(d[:7], w)) % 11
        s = 0 if s == 10 else s
    return s == d[7]


def rnokpp_valid(code):
    """РНОКПП: 10 digits, weights -1 5 7 9 4 6 10 5 7, (sum mod 11) mod 10."""
    code = digits(code)
    if len(code) != 10:
        return False
    d = [int(c) for c in code]
    s = sum(a * b for a, b in zip(d[:9], [-1, 5, 7, 9, 4, 6, 10, 5, 7]))
    return (s % 11) % 10 == d[9]


def party_code_valid(code):
    code = digits(code)
    return edrpou_valid(code) if len(code) == 8 else rnokpp_valid(code) if len(code) == 10 else False


def iban_normalize(iban):
    return re.sub(r"\s", "", str(iban or "")).upper()


def iban_valid(iban):
    iban = iban_normalize(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    if iban.startswith("UA") and len(iban) != 29:
        return False
    num = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(num) % 97 == 1


def parse_date(value):
    s = str(value or "").strip().lower()
    if not s:
        return False
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
        if m:
            d, mo, y = map(int, m.groups())
        else:
            m = re.search(r"(\d{1,2})\s+([а-яіїєґ']+)\s+(\d{4})", s)
            if not m or m.group(2) not in MONTHS:
                return False
            d, mo, y = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return False


def to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d,.\-]", "", str(value or "")).replace(",", ".")
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return 0.0


def name_key(name):
    """Company name without legal form and quotes, for a loose comparison with ЄДР."""
    s = str(name or "").upper().replace("Ґ", "Г")
    for form in ["ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ", "ПРИВАТНЕ АКЦІОНЕРНЕ ТОВАРИСТВО",
                 "АКЦІОНЕРНЕ ТОВАРИСТВО", "ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ", "ФІЗИЧНА ОСОБА - ПІДПРИЄМЕЦЬ",
                 "ПРИВАТНЕ ПІДПРИЄМСТВО", "ТОВ", "ПАТ", "ПРАТ", "АТ", "ФОП", "ПП"]:
        s = re.sub(rf"(^|\W){form}(\W|$)", " ", s)
    return re.sub(r"[^A-ZА-ЯІЇЄ0-9]", "", s)
