# -*- coding: utf-8 -*-
"""Batch of varied Ukrainian supplier documents for bp_purchase_intake.

Step "pdf" (inside odoo:19): text PDFs for every document -> batch/<id>.pdf
Step "degrade" (inside odoo:19, after qlmanage rendered batch/raster/<id>.pdf.png on the Mac): scans, photo, fax, sideways
Step "eml" (inside odoo:19): one incoming email per document -> batch/<id>.eml, plus batch/expected.json
"""
import json, math, os, random, sys
from decimal import Decimal as D, ROUND_HALF_UP
from email.message import EmailMessage
from email.utils import formatdate

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "batch")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONTB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONTS = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"


def q2(x):
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def money(x):
    return f"{q2(x):,.2f}".replace(",", " ").replace(".", ",")


def num(x):
    s = f"{D(x).normalize():f}"
    return s.replace(".", ",")


def edrpou(first7):
    d = [int(c) for c in first7]; n = int(first7 + "0")
    w = [7, 1, 2, 3, 4, 5, 6] if 30000000 <= n < 60000000 else [1, 2, 3, 4, 5, 6, 7]
    s = sum(a * b for a, b in zip(d, w)) % 11
    if s == 10:
        s = sum(a * (b + 2) for a, b in zip(d, w)) % 11; s = 0 if s == 10 else s
    return first7 + str(s)


def rnokpp(first9):
    d = [int(c) for c in first9]
    return first9 + str((sum(a * b for a, b in zip(d, [-1, 5, 7, 9, 4, 6, 10, 5, 7])) % 11) % 10)


def iban(mfo, acc19):
    bban = mfo + acc19
    n = int("".join(str(int(c, 36)) for c in bban + "UA00"))
    return f"UA{98 - n % 97:02d}{bban}"


BUYER = {"name": "ТОВ «Ясен Меблі»", "code": "43715285", "ipn": "437152813021", "address": "79018, м. Львів, вул. Городоцька, 172"}
OTHER_BUYER = {"name": "ТОВ «Сосна Дім»", "code": edrpou("4402917"), "ipn": "", "address": "01054, м. Київ, вул. Гончара, 31"}
S = {
    "epicentr": {"name": "ТОВ «Епіцентр К»", "code": "32490244", "ipn": "324902426531", "iban": iban("380805", "0000026001234560717"),
                 "bank": "АТ «Райффайзен Банк»", "address": "04128, м. Київ, вул. Берковецька, 6-К", "email": "b2b-invoices@epicentrk-billing.example",
                 "stamp": ["ЕПІЦЕНТР К", "ЄДРПОУ 32490244"]},
    "rozetka": {"name": "ТОВ «Розетка.УА»", "code": "37193071", "ipn": "371930726554", "iban": iban("300335", "0000026002100440218"),
                "bank": "АТ «Райффайзен Банк»", "address": "03150, м. Київ, вул. Єжи Ґедройця, 6", "email": "docs@rozetka-b2b.example",
                "stamp": ["РОЗЕТКА.УА", "ЄДРПОУ 37193071"]},
    "ukrposhta": {"name": "АТ «Укрпошта»", "code": "21560045", "ipn": "215600426655", "iban": iban("300465", "0000026009300125571"),
                  "bank": "АТ «Ощадбанк»", "address": "01001, м. Київ, вул. Хрещатик, 22", "email": "rahunky@ukrposhta-corp.example",
                  "stamp": ["УКРПОШТА", "ЄДРПОУ 21560045"]},
    "oschad": {"name": "АТ «Ощадбанк»", "code": "00032129", "ipn": "000321226656", "iban": iban("300465", "0000029090000321290"),
               "bank": "АТ «Ощадбанк»", "address": "01001, м. Київ, вул. Госпітальна, 12-Г", "email": "business@oschadbank-docs.example",
               "stamp": ["ОЩАДБАНК", "ЄДРПОУ 00032129"]},
    "novaposhta": {"name": "ТОВ «Нова Пошта»", "code": "31316718", "ipn": "313167116014", "iban": iban("305299", "0000026004000123456"),
                   "bank": "АТ КБ «ПриватБанк»", "address": "03045, м. Київ, Столичне шосе, 103, корп. 1", "email": "invoices@novaposhta-billing.example",
                   "stamp": ["НОВА ПОШТА", "ЄДРПОУ 31316718"]},
    "fop": {"name": "ФОП Кравчук Олена Василівна", "code": rnokpp("000014582"), "ipn": "", "iban": iban("322001", "0000026007054123987"),
            "bank": "АТ «Універсал Банк»", "address": "79005, м. Львів, вул. Зелена, 14, кв. 3", "email": "olena.kravchuk.design@example.com",
            "stamp": [], "note": "Платник єдиного податку 3 групи, не є платником ПДВ"},
}

TOOLS = [("Цемент ПЦ II/Б-Ш-400 25 кг", "40", "мішок", "189.17"), ("Плитка керамічна Golden Tile 300×600", "18.5", "м2", "412.50"),
         ("Клей для плитки Ceresit CM 11 25 кг", "12", "мішок", "298.33"), ("Грунтовка Ceresit CT 17 10 л", "6", "шт", "671.67"),
         ("Профіль для гіпсокартону CD 60 3 м", "64", "шт", "96.25"), ("Гіпсокартон Knauf 12,5 мм 1200×2500", "30", "лист", "259.17"),
         ("Саморізи по металу 3,5×25, 1000 шт", "4", "уп", "154.17"), ("Стрічка армуюча серп'янка 50 мм × 90 м", "5", "рул", "87.50")]
MORE_TOOLS = [(f"{n} (арт. {1000 + i})", q, u, p) for i, (n, q, u, p) in enumerate(TOOLS * 3)] + \
             [("Доставка вантажу по м. Львів", "1", "послуга", "1250.00"), ("Розвантаження вручну", "2", "год", "450.00")]

DOCS = [
    {"id": "04-epicentr-rahunok", "sup": "epicentr", "layout": "rakhunok", "style": "right", "number": "ЕК-00481275",
     "date_text": "05.09.2026", "date": "2026-09-05", "due_text": "", "lines": TOOLS, "vat": 20, "expect": "bill",
     "subject": "Рахунок ЕК-00481275", "variant": "текст PDF, реквізити праворуч"},
    {"id": "05-rozetka-vydatkova", "sup": "rozetka", "layout": "vydatkova", "number": "РЗ-2609-4471", "date_text": "8 вересня 2026 р.",
     "date": "2026-09-08", "lines": [("Кабель мережевий UTP Cat.6", "2.5", "м", "38.00"), ("Роутер TP-Link Archer AX55", "2", "шт", "3749.17"),
                                      ("Патч-корд 1 м", "12", "шт", "62.50"), ("Джерело безперебійного живлення APC BX950MI", "1", "шт", "5832.50"),
                                      ("Стяжки кабельні 200 мм, 100 шт", "3", "уп", "45.83")],
     "vat": 20, "expect": "bill", "subject": "Видаткова накладна РЗ-2609-4471", "variant": "текст PDF, накладна, дробова кількість"},
    {"id": "06-ukrposhta-akt", "sup": "ukrposhta", "layout": "akt", "number": "7/0912", "date_text": "12.09.2026", "date": "2026-09-12",
     "lines": [("Пересилання посилок Укрпошта Стандарт за серпень 2026", "146", "відпр.", "47.50"), ("Послуга «Оплата при отриманні»", "58", "послуга", "12.50")],
     "vat": 20, "expect": "bill", "subject": "Акт наданих послуг за серпень", "variant": "текст PDF, акт"},
    {"id": "07-fop-akt", "sup": "fop", "layout": "akt", "number": "14", "date_text": "11 вересня 2026 р.", "date": "2026-09-11",
     "lines": [("Розробка дизайну каталогу меблів, 48 сторінок", "1", "послуга", "18000.00")], "vat": 0, "expect": "review",
     "subject": "акт і рахунок за дизайн каталогу", "variant": "текст PDF, ФОП без ПДВ, немає в ЄДР"},
    {"id": "08-rozetka-z-pdv", "sup": "rozetka", "layout": "rakhunok", "style": "left", "incl": True, "number": "РЗ-2609-4480",
     "date_text": "09.09.2026", "date": "2026-09-09", "due_text": "12.09.2026",
     "lines": [("Ноутбук Lenovo IdeaPad Slim 5 16\"", "2", "шт", "38999.00"), ("Монітор Dell P2425H 23.8\"", "3", "шт", "7299.00"), ("Миша Logitech M185", "5", "шт", "399.00")],
     "vat": 20, "expect": "bill", "subject": "Рахунок на оплату РЗ-2609-4480", "variant": "текст PDF, ціни з ПДВ"},
    {"id": "09-oschad-bez-pdv", "sup": "oschad", "layout": "rakhunok", "style": "left", "number": "Б-2026/09-118", "date_text": "01.09.2026",
     "date": "2026-09-01", "due_text": "10.09.2026",
     "lines": [("Розрахунково-касове обслуговування, пакет «Бізнес Оптимальний», вересень 2026", "1", "міс.", "420.00"),
               ("Обслуговування зарплатного проєкту, комісія за зарахування", "1", "послуга", "1380.00")],
     "vat": 0, "vat_note": "Без ПДВ (операції звільнені від оподаткування, пп. 196.1.5 ПКУ)", "expect": "bill",
     "subject": "Рахунок за банківські послуги", "variant": "текст PDF, звільнено від ПДВ"},
    {"id": "10-epicentr-2-storinky", "sup": "epicentr", "layout": "rakhunok", "style": "right", "number": "ЕК-00481290",
     "date_text": "10.09.2026", "date": "2026-09-10", "due_text": "17.09.2026", "lines": MORE_TOOLS, "vat": 20, "expect": "bill",
     "subject": "Рахунок ЕК-00481290 (2 сторінки)", "variant": "текст PDF, 26 рядків, 2 сторінки"},
    {"id": "11-ukrposhta-insha-kompaniia", "sup": "ukrposhta", "layout": "rakhunok", "style": "left", "buyer": "other", "number": "7/0914",
     "date_text": "12.09.2026", "date": "2026-09-12", "due_text": "",
     "lines": [("Пакувальні коробки Укрпошта розмір M", "200", "шт", "18.75")], "vat": 20, "expect": "review",
     "subject": "Рахунок 7/0914", "variant": "текст PDF, покупець інша компанія"},
    {"id": "12-ukrposhta-podatkova", "sup": "ukrposhta", "layout": "tax", "number": "1245", "date_text": "12.09.2026", "date": "2026-09-12",
     "lines": [("Пересилання посилок Укрпошта Стандарт за серпень 2026", "146", "послуга", "47.50"), ("Послуга «Оплата при отриманні»", "58", "послуга", "12.50")],
     "vat": 20, "expect": "review", "subject": "Податкова накладна 1245", "variant": "текст PDF, податкова накладна"},
    {"id": "13-epicentr-skan", "sup": "epicentr", "layout": "rakhunok", "style": "right", "number": "ЕК-00481302", "date_text": "11.09.2026",
     "date": "2026-09-11", "due_text": "", "lines": TOOLS[:5], "vat": 20, "expect": "bill", "scan": "scan",
     "subject": "Скан рахунку з печаткою", "variant": "скан PDF без тексту, печатка, підпис, нахил"},
    {"id": "14-novaposhta-foto", "sup": "novaposhta", "layout": "akt", "number": "НП-А-2026-0911", "date_text": "11.09.2026", "date": "2026-09-11",
     "lines": [("Послуги з доставки відправлень за період 01.08.2026-31.08.2026", "1", "послуга", "9870.00"), ("Послуги зберігання", "1", "міс.", "2100.00")],
     "vat": 20, "expect": "bill", "scan": "photo", "subject": "фото акту", "variant": "фото на телефон, JPG, перспектива і тінь"},
    {"id": "15-ukrposhta-faks", "sup": "ukrposhta", "layout": "rakhunok", "style": "left", "number": "7/0915", "date_text": "13.09.2026",
     "date": "2026-09-13", "due_text": "20.09.2026",
     "lines": [("Франкування листів, серпень 2026", "420", "лист", "22.00"), ("Рекомендовані листи з повідомленням", "35", "лист", "58.00")],
     "vat": 20, "expect": "bill", "scan": "fax", "subject": "рахунок 7/0915", "variant": "чорно-білий скан низької якості"},
    {"id": "16-rozetka-bokom", "sup": "rozetka", "layout": "rakhunok", "style": "left", "number": "РЗ-2609-4502", "date_text": "13.09.2026",
     "date": "2026-09-13", "due_text": "", "lines": [("Картридж HP 85A CE285A", "4", "шт", "1832.50"), ("Папір офісний A4 Double A 80 г/м2", "10", "пач.", "245.83")],
     "vat": 20, "expect": "bill", "scan": "sideways", "subject": "Рахунок (скан)", "variant": "скан PDF повернутий на 90°"},
]


def totals(doc):
    rate = D(doc["vat"])
    amounts = [q2(D(q) * D(p)) for _, q, _, p in doc["lines"]]
    if doc.get("incl"):
        total = sum(amounts); tax = q2(total * rate / (100 + rate)); untaxed = total - tax
    else:
        untaxed = sum(amounts); tax = q2(untaxed * rate / 100); total = untaxed + tax
    return amounts, untaxed, tax, total


# ---------------------------------------------------------------- PDF
def make_pdfs():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(TTFont("DV", FONT)); pdfmetrics.registerFont(TTFont("DVB", FONTB)); pdfmetrics.registerFont(TTFont("DVS", FONTS))
    W, H = A4

    for doc in DOCS:
        sup = S[doc["sup"]]
        buyer = OTHER_BUYER if doc.get("buyer") == "other" else BUYER
        amounts, untaxed, tax, total = totals(doc)
        c = canvas.Canvas(os.path.join(OUT, doc["id"] + ".pdf"), pagesize=A4)
        x0, x1 = 16 * mm, W - 16 * mm
        body = "DVS" if doc["layout"] == "akt" else "DV"

        def t(s, x, y, size=9, bold=False, font=None, right=False, center=False):
            c.setFont(font or ("DVB" if bold else body), size)
            (c.drawRightString if right else c.drawCentredString if center else c.drawString)(x, y, s)

        y = H - 18 * mm
        title = {"rakhunok": f"Рахунок на оплату № {doc['number']} від {doc['date_text']}",
                 "vydatkova": f"Видаткова накладна № {doc['number']} від {doc['date_text']}",
                 "akt": f"Акт наданих послуг № {doc['number']} від {doc['date_text']}",
                 "tax": f"ПОДАТКОВА НАКЛАДНА № {doc['number']} від {doc['date_text']}"}[doc["layout"]]

        if doc["layout"] == "tax":
            t("Додаток 1 до Порядку заповнення податкової накладної", x1, y, 7, right=True); y -= 10 * mm
            t(title, W / 2, y, 13, bold=True, center=True); y -= 10 * mm
            for label, party in (("Продавець", sup), ("Покупець", buyer)):
                t(f"{label}:", x0, y, 9, bold=True); t(party["name"], x0 + 30 * mm, y, 9); y -= 5 * mm
                t("Індивідуальний податковий номер:", x0 + 30 * mm, y, 8); t(" ".join(party.get("ipn") or "—"), x0 + 90 * mm, y, 9, bold=True); y -= 5 * mm
                t(f"Код ЄДРПОУ: {party['code']}", x0 + 30 * mm, y, 8); y -= 8 * mm
            t("Розділ Б", x0, y, 9, bold=True); y -= 6 * mm
            cols = [x0, x0 + 8 * mm, x0 + 88 * mm, x0 + 108 * mm, x0 + 122 * mm, x0 + 140 * mm, x0 + 160 * mm, x1]
            heads = ["№", "Опис товарів (послуг)", "Код ДКПП", "Од.", "Кількість", "Ціна без ПДВ", "Обсяг без ПДВ"]
        elif doc.get("style") == "right" or doc["layout"] in ("vydatkova",):
            t(sup["name"], x1, y, 11, bold=True, right=True); y -= 5 * mm
            for line in [sup["address"], f"ЄДРПОУ {sup['code']}   ІПН {sup['ipn']}", f"р/р {sup['iban']}", sup["bank"], sup["email"]]:
                t(line, x1, y, 8, right=True); y -= 4.2 * mm
            y -= 6 * mm
            t(title, W / 2, y, 13, bold=True, center=True); y -= 9 * mm
            t("Постачальник:", x0, y, 9, bold=True); t(f"{sup['name']}, ЄДРПОУ {sup['code']}", x0 + 30 * mm, y); y -= 5 * mm
            t("Одержувач:", x0, y, 9, bold=True); t(f"{buyer['name']}, ЄДРПОУ {buyer['code']}, {buyer['address']}", x0 + 30 * mm, y); y -= 5 * mm
            if doc["layout"] == "vydatkova":
                t("Місце складання: м. Київ.  Підстава: рахунок-фактура РЗ-2609-4462 від 01.09.2026", x0, y, 8); y -= 5 * mm
            y -= 3 * mm
        elif doc["layout"] == "akt":
            t(title, W / 2, y, 13, bold=True, center=True); y -= 7 * mm
            t(f"м. {'Львів' if doc['sup'] == 'fop' else 'Київ'}", x0, y, 9); t(doc["date_text"], x1, y, 9, right=True); y -= 9 * mm
            para = [f"Виконавець: {sup['name']}, код {sup['code']}" + (f", ІПН {sup['ipn']}" if sup["ipn"] else "") + ",",
                    f"адреса: {sup['address']}, IBAN {sup['iban']} в {sup['bank']}" + (f". {sup['note']}." if sup.get("note") else "."),
                    f"Замовник: {buyer['name']}, код ЄДРПОУ {buyer['code']}, адреса: {buyer['address']}.",
                    "Ми, що нижче підписалися, представники Виконавця і Замовника, склали цей акт про те, що Виконавець",
                    "надав, а Замовник прийняв такі послуги:"]
            for p in para:
                t(p, x0, y, 9); y -= 5 * mm
            y -= 4 * mm
        else:
            for label, lines in (("Постачальник:", [sup["name"], f"ЄДРПОУ {sup['code']}" + (f", ІПН {sup['ipn']}" if sup["ipn"] else ""),
                                                     f"IBAN {sup['iban']}, {sup['bank']}", sup["address"], sup["email"]]),
                                 ("Покупець:", [buyer["name"], f"ЄДРПОУ {buyer['code']}", buyer["address"]])):
                t(label, x0, y, 9, bold=True)
                for i, line in enumerate(lines):
                    t(line, x0 + 30 * mm, y, 9, bold=(i == 0)); y -= 4.6 * mm
                y -= 3 * mm
            y -= 3 * mm
            t(title, W / 2, y, 14, bold=True, center=True); y -= 10 * mm

        if doc["layout"] != "tax":
            incl = doc.get("incl")
            cols = [x0, x0 + 8 * mm, x0 + 98 * mm, x0 + 116 * mm, x0 + 132 * mm, x0 + 154 * mm, x1]
            heads = ["№", "Найменування товару (послуги)", "Кількість", "Од.", "Ціна з ПДВ" if incl else "Ціна без ПДВ", "Сума з ПДВ" if incl else "Сума без ПДВ"]

        def header(y):
            c.setLineWidth(0.7); c.line(x0, y + 4 * mm, x1, y + 4 * mm)
            for i, h in enumerate(heads):
                t(h, cols[i] + 1 * mm, y, 7.5, bold=True, font="DVB")
            y -= 2.5 * mm; c.line(x0, y, x1, y)
            return y

        y = header(y)
        page = 1
        for n, ((name, qty, uom, price), amount) in enumerate(zip(doc["lines"], amounts), 1):
            if y < 45 * mm:
                t(f"Сторінка {page}. Продовження на наступній сторінці.", x1, 12 * mm, 7, right=True)
                c.showPage(); page += 1; y = H - 20 * mm
                t(f"Продовження: {title}. Сторінка {page}", x0, y, 8); y -= 10 * mm
                y = header(y)
            y -= 5 * mm
            vals = [str(n), name, num(qty), uom, money(price), money(amount)] if doc["layout"] != "tax" else \
                   [str(n), name, "53.10.1", uom, num(qty), money(price), money(amount)]
            for i, v in enumerate(vals):
                if i >= (2 if doc["layout"] != "tax" else 3) and i != 3 and not (doc["layout"] == "tax" and i == 3):
                    t(v, cols[i + 1] - 1.5 * mm, y, 8.2, right=True, font="DV")
                else:
                    t(v[:62], cols[i] + 1 * mm, y, 8.2, font="DV")
            y -= 2.2 * mm; c.setLineWidth(0.25); c.line(x0, y, x1, y)
        y -= 7 * mm
        rows = [("Разом з ПДВ:", total), (f"у т.ч. ПДВ {doc['vat']}%:", tax)] if doc.get("incl") else \
               [("Разом без ПДВ:", untaxed), (doc.get("vat_note") or f"ПДВ {doc['vat']}%:", tax), ("Всього з ПДВ:", total)] if doc["vat"] else \
               [("Разом:", untaxed), ("Без ПДВ", None), ("Всього до сплати:", total)]
        for label, val in rows:
            t(label, cols[-3] - (28 * mm if len(label) < 30 else 95 * mm), y, 9, bold=True, font="DVB")
            if val is not None:
                t(money(val), x1 - 1.5 * mm, y, 9, bold=True, right=True, font="DVB")
            y -= 5 * mm
        y -= 3 * mm
        if doc["layout"] == "akt":
            t(f"Загальна вартість послуг: {money(total)} грн" + (f", у т.ч. ПДВ {money(tax)} грн." if doc["vat"] else ", без ПДВ."), x0, y, 9); y -= 5 * mm
            t("Послуги надано в повному обсязі, сторони претензій одна до одної не мають.", x0, y, 9); y -= 14 * mm
            t("Від Виконавця ____________________", x0, y, 9); t("Від Замовника ____________________", x0 + 95 * mm, y, 9)
        elif doc["layout"] == "vydatkova":
            t(f"Всього на суму: {money(total)} грн, у т.ч. ПДВ {money(tax)} грн.", x0, y, 9, bold=True); y -= 14 * mm
            t("Від постачальника: ____________________", x0, y, 9); t("Отримав(ла): ____________________", x0 + 95 * mm, y, 9); y -= 5 * mm
            t("за довіреністю № ______ від ____________", x0 + 95 * mm, y, 7.5)
        elif doc["layout"] == "tax":
            t("Податкову накладну складено в електронній формі та зареєстровано в ЄРПН.", x0, y, 8); y -= 10 * mm
            t("Уповноважена особа продавця ____________________", x0, y, 9)
        else:
            t(f"Всього найменувань {len(doc['lines'])}, на суму {money(total)} грн.", x0, y, 9); y -= 6 * mm
            if doc.get("due_text"):
                t(f"Рахунок дійсний до сплати до {doc['due_text']}.", x0, y, 9); y -= 6 * mm
            y -= 8 * mm
            t("Виписав(ла): ____________________  Головний бухгалтер", x0, y, 9)
        c.save()
        doc["_totals"] = {"amount_untaxed": str(untaxed), "amount_tax": str(tax), "amount_total": str(total)}


# ---------------------------------------------------------------- scans
def stamp_layer(size, texts, color=(38, 66, 168), seed=1):
    from PIL import Image, ImageDraw, ImageFont
    rnd = random.Random(seed)
    s = 300
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    a = 170
    dr.ellipse((8, 8, s - 8, s - 8), outline=color + (a,), width=7)
    dr.ellipse((40, 40, s - 40, s - 40), outline=color + (a,), width=3)
    f = ImageFont.truetype(FONTB, 26); f2 = ImageFont.truetype(FONT, 20)
    for i, txt in enumerate(texts[:2]):
        font = f if i == 0 else f2
        w = dr.textlength(txt, font=font)
        dr.text(((s - w) / 2, s / 2 - 34 + i * 40), txt, font=font, fill=color + (a,))
    return layer.rotate(rnd.uniform(-18, 18), resample=Image.BICUBIC, expand=False)


def signature(dr, x, y, seed):
    rnd = random.Random(seed)
    pts = []
    for i in range(46):
        pts.append((x + i * 5 + rnd.uniform(-2, 2), y + 18 * math.sin(i / 3.1) + rnd.uniform(-5, 5) - i * 0.6))
    dr.line(pts, fill=(20, 30, 90), width=3)
    dr.line([(x + 30, y + 10), (x + 210, y - 22)], fill=(20, 30, 90), width=2)


def degrade():
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    for doc in DOCS:
        mode = doc.get("scan")
        if not mode:
            continue
        src = os.path.join(OUT, "raster", doc["id"] + ".pdf.png")
        img = Image.open(src).convert("RGB")
        W0, H0 = img.size
        rnd = random.Random(doc["id"])
        sup = S[doc["sup"]]
        # stamp and signature near the bottom of the text block
        dr = ImageDraw.Draw(img)
        sy = int(H0 * 0.62) if len(doc["lines"]) < 8 else int(H0 * 0.78)
        if sup.get("stamp"):
            st = stamp_layer(None, sup["stamp"], seed=len(doc["id"]))
            img.paste(st, (int(W0 * 0.52), sy - 120), st)
        signature(ImageDraw.Draw(img), int(W0 * 0.22), sy + 40, seed=len(doc["number"]))
        if mode == "scan":
            paper = Image.new("RGB", img.size, (236, 233, 224))
            img = Image.blend(img, paper, 0.18)
            img = img.rotate(rnd.uniform(0.6, 1.1), resample=Image.BICUBIC, expand=True, fillcolor=(236, 233, 224))
            noise = Image.effect_noise(img.size, 28).convert("RGB")
            img = Image.blend(img, noise, 0.07).filter(ImageFilter.GaussianBlur(0.7))
            out = os.path.join(OUT, doc["id"] + ".pdf")
            img.save(out, "PDF", resolution=170, quality=55)
        elif mode == "photo":
            bg = Image.new("RGB", (int(W0 * 1.25), int(H0 * 1.18)), (121, 94, 70))
            bgn = Image.effect_noise(bg.size, 40).convert("RGB")
            bg = Image.blend(bg, bgn, 0.12)
            ox, oy = int(W0 * 0.12), int(H0 * 0.08)
            bg.paste(img, (ox, oy))
            # perspective: the far edge (top) narrower, a little rotation
            Wb, Hb = bg.size
            quad = (int(Wb * 0.02), int(Hb * 0.06), int(Wb * 0.10), int(Hb * 0.97), int(Wb * 0.93), int(Hb * 0.99), int(Wb * 0.99), int(Hb * 0.02))
            img = bg.transform((int(Wb * 0.9), int(Hb * 0.9)), Image.QUAD, quad, resample=Image.BICUBIC)
            grad = Image.linear_gradient("L").resize(img.size).rotate(35, expand=False)
            shadow = Image.new("RGB", img.size, (30, 26, 22))
            img = Image.composite(img, shadow, ImageOps.autocontrast(grad).point(lambda v: 150 + v // 2.6))
            img = img.filter(ImageFilter.GaussianBlur(1.1))
            img.save(os.path.join(OUT, doc["id"] + ".jpg"), "JPEG", quality=68)
        elif mode == "fax":
            g = ImageOps.grayscale(img).resize((int(W0 * 0.62), int(H0 * 0.62)), Image.BILINEAR)
            g = g.rotate(rnd.uniform(-0.8, -0.4), resample=Image.BILINEAR, expand=True, fillcolor=255)
            g = g.point(lambda v: 0 if v < 165 else 255)
            px = g.load()
            for _ in range(int(g.size[0] * g.size[1] * 0.0015)):
                px[rnd.randrange(g.size[0]), rnd.randrange(g.size[1])] = 0
            g.save(os.path.join(OUT, doc["id"] + ".pdf"), "PDF", resolution=110, quality=60)
        elif mode == "sideways":
            img = img.rotate(90, expand=True).filter(ImageFilter.GaussianBlur(0.5))
            img.save(os.path.join(OUT, doc["id"] + ".pdf"), "PDF", resolution=170, quality=65)


# ---------------------------------------------------------------- emails
def make_emls():
    expected = {}
    for doc in DOCS:
        sup = S[doc["sup"]]
        _, untaxed, tax, total = totals(doc)
        msg = EmailMessage()
        msg["From"] = f"{'Олена Кравчук' if doc['sup'] == 'fop' else 'Бухгалтерія'} <{sup['email']}>"
        msg["To"] = "rahunky@yasen-mebli.example"
        msg["Subject"] = doc["subject"]
        msg["Date"] = formatdate(localtime=True)
        msg["Message-Id"] = f"<{doc['id'].encode('ascii', 'ignore').decode()}@test.example>"
        msg.set_content("Добрий день!\n\nДокумент у вкладенні.\n\nЗ повагою\n")
        path = os.path.join(OUT, doc["id"] + (".jpg" if doc.get("scan") == "photo" else ".pdf"))
        with open(path, "rb") as f:
            data = f.read()
        if path.endswith(".jpg"):
            msg.add_attachment(data, maintype="image", subtype="jpeg", filename="IMG_20260911_1432.jpg")
        else:
            msg.add_attachment(data, maintype="application", subtype="pdf", filename=f"{doc['layout']}_{doc['number'].replace('/', '-')}.pdf")
        with open(os.path.join(OUT, doc["id"] + ".eml"), "wb") as f:
            f.write(bytes(msg))
        expected[doc["id"]] = {"variant": doc["variant"], "file": os.path.basename(path), "supplier": sup["name"], "number": doc["number"],
                               "date": doc["date"], "supplier_code": sup["code"], "amount_untaxed": str(untaxed), "amount_tax": str(tax),
                               "amount_total": str(total), "lines": len(doc["lines"]), "expect": doc["expect"], "subject": doc["subject"]}
    with open(os.path.join(OUT, "expected.json"), "w", encoding="utf-8") as f:
        json.dump(expected, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: (v["expect"], v["amount_total"], v["file"]) for k, v in expected.items()}, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    step = sys.argv[1]
    {"pdf": make_pdfs, "degrade": degrade, "eml": make_emls}[step]()
    print("done", step)
