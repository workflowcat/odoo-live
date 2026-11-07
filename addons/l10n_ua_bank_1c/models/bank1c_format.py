"""Формат обміну з клієнт-банком 1CClientBankExchange: читання виписки і запис платіжок.

Чистий Python без Odoo, щоб формат можна було перевірити окремо від бази.

Файл - текст рядками «Ключ=Значення» між маркерами секцій:

    1CClientBankExchange
    ВерсияФормата=1.02
    Кодировка=Windows            (Windows = cp1251, DOS = cp1125/cp866; частина банків пише UTF-8)
    ...заголовок: ДатаНачала, ДатаКонца, РасчСчет (може повторюватись)
    СекцияРасчСчет               залишки по рахунку за період (може бути кілька, по днях)
    ...
    КонецРасчСчет
    СекцияДокумент=Платежное поручение
    Номер=, Дата=, Сумма=, ПлательщикСчет=, ПолучательСчет=, ДатаСписано=, ДатаПоступило=,
    НазначениеПлатежа=, ...
    КонецДокумента
    КонецФайла

Ключі російською - так їх пише сама 1С і банки, що її підтримують. Українські конфігурації
пишуть код контрагента як ...ОКПО і код банку як ...МФО, російські - ...ИНН і ...БИК; читаємо
обидва варіанти. Рахунки - IBAN.
"""
import re
from datetime import date, datetime

HEADER = "1CClientBankExchange"
# Код контрагента і банку: перший знайдений ключ виграє.
CODE_KEYS = ("ОКПО", "ЕДРПОУ", "ЄДРПОУ", "Код", "ИНН")
BANK_CODE_KEYS = ("МФО", "БИК")


class Bank1CError(ValueError):
    """Файл схожий на 1CClientBankExchange, але прочитати його не вдалось."""


def is_bank1c(data):
    """Чи це файл обміну з клієнт-банком: перший непорожній рядок - заголовок формату."""
    head = data[:64].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(HEADER.encode("ascii"))


def decode(data):
    """Байти файлу в текст: UTF-8, інакше cp1251 (Windows), інакше DOS.

    Кодування видно з того, в якому з них читаються самі ключі формату. DOS у нас - cp1125:
    це cp866 з українськими літерами (і, ї, є, ґ)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    text = data.decode("cp1251", "replace")
    if re.search(r"^(Кодировка|СекцияДокумент|СекцияРасчСчет)", text, re.M):
        return text
    dos = data.decode("cp1125", "replace")
    if re.search(r"^(Кодировка|СекцияДокумент|СекцияРасчСчет)", dos, re.M):
        return dos
    return text


def iban(value):
    return re.sub(r"\s+", "", value or "").upper()


def amount(value):
    value = re.sub(r"[\s ]", "", value or "").replace(",", ".")
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        raise Bank1CError("Сума «%s» не число" % value)


def day(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise Bank1CError("Дата «%s» не у форматі ДД.ММ.РРРР" % value)


def parse(data):
    """Розбирає файл. Повертає {"header": {}, "accounts": [IBAN], "balances": [{}], "documents": [{}]}.

    Ключі в header, balances і documents - як у файлі. Повторні ключі заголовка (кілька
    РасчСчет) збираються в "accounts"."""
    text = decode(data) if isinstance(data, bytes) else data
    lines = [line.rstrip("\r") for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip().lstrip("﻿") != HEADER:
        raise Bank1CError("Перший рядок файлу не «%s»" % HEADER)
    result = {"header": {}, "accounts": [], "balances": [], "documents": []}
    section = None
    current = None
    for number, line in enumerate(lines[1:], start=2):
        line = line.strip()
        if not line:
            continue
        if line == "КонецФайла":
            break
        if line == "СекцияРасчСчет":
            section, current = "balance", {}
            continue
        if line == "КонецРасчСчет":
            if section == "balance":
                result["balances"].append(current)
            section, current = None, None
            continue
        if line.startswith("СекцияДокумент"):
            kind = line.partition("=")[2].strip()
            section, current = "document", {"_kind": kind, "_line": number}
            continue
        if line == "КонецДокумента":
            if section == "document":
                result["documents"].append(current)
            section, current = None, None
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if section is None:
            if key == "РасчСчет":
                if value:
                    result["accounts"].append(iban(value))
            else:
                result["header"][key] = value
        elif key in current and key.startswith("НазначениеПлатежа"):
            current[key] += " " + value
        else:
            current[key] = value
    if section == "document":
        raise Bank1CError("Документ з рядка %s не закінчується «КонецДокумента»" % current["_line"])
    for balance in result["balances"]:
        account = iban(balance.get("РасчСчет"))
        if account and account not in result["accounts"]:
            result["accounts"].append(account)
    return result


def _first(document, prefix, suffixes):
    for suffix in suffixes:
        value = document.get(prefix + suffix)
        if value:
            return re.sub(r"\D", "", value) or value
    return ""


def side(document, who):
    """Сторона документа: who = "Плательщик" або "Получатель"."""
    name = document.get(who + "1") or document.get(who) or ""
    # Російські клієнт-банки пишуть у «Плательщик» ще й ИНН: «ИНН 7701... ТОВ Ромашка».
    name = re.sub(r"^ИНН\s*\d+\s*", "", name).strip()
    return {
        "account": iban(document.get(who + "Счет") or document.get(who + "РасчСчет")),
        "name": name,
        "code": _first(document, who, CODE_KEYS),
        "bank": document.get(who + "Банк1") or document.get(who + "Банк") or "",
        "bank_code": _first(document, who, BANK_CODE_KEYS),
    }


def purpose(document):
    parts = [document.get("НазначениеПлатежа", "")]
    parts += [document.get("НазначениеПлатежа%d" % index, "") for index in range(1, 7)]
    return " ".join(part for part in parts if part).strip()


def transactions(parsed):
    """Рядки виписки по кожному нашому рахунку: {IBAN: [рядок]}.

    Напрям визначає рахунок: наш рахунок платника - списання, наш рахунок одержувача -
    надходження. Переказ між двома нашими рахунками дає по рядку на кожен."""
    ours = list(parsed["accounts"])
    result = {account: [] for account in ours}
    for document in parsed["documents"]:
        payer, payee = side(document, "Плательщик"), side(document, "Получатель")
        total = amount(document.get("Сумма"))
        hits = []
        if payer["account"] in ours:
            hits.append((payer["account"], -total, payee, document.get("ДатаСписано")))
        if payee["account"] in ours:
            hits.append((payee["account"], total, payer, document.get("ДатаПоступило")))
        if not hits and len(ours) == 1:
            if document.get("ДатаСписано"):
                hits.append((ours[0], -total, payee, document.get("ДатаСписано")))
            elif document.get("ДатаПоступило"):
                hits.append((ours[0], total, payer, document.get("ДатаПоступило")))
        if not hits:
            raise Bank1CError(
                "Документ № %s з рядка %s не стосується жодного рахунку з файлу"
                % (document.get("Номер", "?"), document["_line"]))
        for account, signed, other, moved in hits:
            when = day(moved) or day(document.get("Дата"))
            if not when:
                raise Bank1CError("Документ № %s без дати" % document.get("Номер", "?"))
            result.setdefault(account, []).append({
                "date": when,
                "amount": signed,
                "number": document.get("Номер", ""),
                "document_date": day(document.get("Дата")),
                "kind": document.get("_kind", ""),
                "purpose": purpose(document),
                "partner": other,
            })
    return result


def balances(parsed, account):
    """Залишки рахунку за файл: (початок, кінець, дата початку, дата кінця) або None."""
    rows = [row for row in parsed["balances"] if iban(row.get("РасчСчет")) == account
            or (not row.get("РасчСчет") and len(parsed["accounts"]) == 1)]
    if not rows:
        return None
    rows.sort(key=lambda row: day(row.get("ДатаНачала")) or date.min)
    return (amount(rows[0].get("НачальныйОстаток")), amount(rows[-1].get("КонечныйОстаток")),
            day(rows[0].get("ДатаНачала")), day(rows[-1].get("ДатаКонца")))


# ----------------------------------------------------------------------- запис

def _clean(value):
    value = (value or "").replace("ʼ", "'").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def mfo(account):
    """МФО банку з українського IBAN: шість цифр після контрольних."""
    account = iban(account)
    return account[4:10] if account.startswith("UA") and len(account) == 29 else ""


def render(account, documents, date_from, date_to, sender="odoo-live", now=None):
    """Файл платіжних доручень для завантаження в клієнт-банк, байти cp1251.

    documents - список словників: number, date, amount, purpose і сторони payer/payee
    ({"account", "name", "code", "bank"})."""
    now = now or datetime.now()
    out = [
        HEADER,
        "ВерсияФормата=1.02",
        "Кодировка=Windows",
        "Отправитель=%s" % _clean(sender),
        "Получатель=",
        "ДатаСоздания=%s" % now.strftime("%d.%m.%Y"),
        "ВремяСоздания=%s" % now.strftime("%H:%M:%S"),
        "ДатаНачала=%s" % date_from.strftime("%d.%m.%Y"),
        "ДатаКонца=%s" % date_to.strftime("%d.%m.%Y"),
        "РасчСчет=%s" % iban(account),
        "Документ=Платежное поручение",
    ]
    for document in documents:
        out += [
            "СекцияДокумент=Платежное поручение",
            "Номер=%s" % _clean(str(document["number"])),
            "Дата=%s" % document["date"].strftime("%d.%m.%Y"),
            "Сумма=%.2f" % document["amount"],
        ]
        for who, key in (("Плательщик", "payer"), ("Получатель", "payee")):
            party = document[key]
            out += [
                "%sСчет=%s" % (who, iban(party["account"])),
                "%s=%s" % (who, _clean(party["name"])),
                "%s1=%s" % (who, _clean(party["name"])),
                "%sОКПО=%s" % (who, _clean(party.get("code"))),
                "%sРасчСчет=%s" % (who, iban(party["account"])),
                "%sБанк1=%s" % (who, _clean(party.get("bank"))),
                "%sМФО=%s" % (who, mfo(party["account"])),
            ]
        out += [
            "ВидОплаты=01",
            "НазначениеПлатежа=%s" % _clean(document["purpose"]),
            "КонецДокумента",
        ]
    out.append("КонецФайла")
    return ("\r\n".join(out) + "\r\n").encode("cp1251", "replace")
