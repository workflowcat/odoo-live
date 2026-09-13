# -*- coding: utf-8 -*-
"""Test invoices for bp_purchase_intake: PDF (reportlab, DejaVu Sans) + incoming email (.eml).
Run inside the odoo:19 image:  docker run --rm --user "$(id -u)" -v "$PWD":/w --entrypoint python3 odoo:19 /w/scripts/fixtures/make_invoices.py
"""
import os
from decimal import Decimal as D
from email.message import EmailMessage
from email.utils import formatdate

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))


def edrpou_check(first7):
    d = [int(c) for c in first7]
    n = int(first7 + "0")
    w = [7, 1, 2, 3, 4, 5, 6] if 30000000 <= n < 60000000 else [1, 2, 3, 4, 5, 6, 7]
    s = sum(a * b for a, b in zip(d, w)) % 11
    if s == 10:
        s = sum(a * (b + 2) for a, b in zip(d, w)) % 11
        s = 0 if s == 10 else s
    return first7 + str(s)


def iban_ua(mfo, account19):
    bban = mfo + account19
    num = int("".join(str(int(c, 36)) for c in bban + "UA00"))
    return f"UA{98 - num % 97:02d}{bban}"


def money(x):
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s


BUYER = {"name": "ТОВ «Ясен Меблі»", "code": edrpou_check("4371528"), "address": "79018, м. Львів, вул. Городоцька, 172"}

INVOICES = [
    {
        "file": "01-nova-poshta", "number": "НП-2026-0917", "date": "12 вересня 2026 р.", "due": "22 вересня 2026 р.",
        "supplier": {"name": "ТОВ «Нова Пошта»", "code": "31316718", "ipn": "313167116014",
                     "iban": iban_ua("305299", "0000026004000123456"), "bank": "АТ КБ «ПриватБанк»",
                     "address": "03045, м. Київ, Столичне шосе, 103, корп. 1", "email": "invoices@novaposhta-billing.example"},
        "contract": "Договір № 12-ПД від 03.02.2026",
        "lines": [("Послуги з доставки відправлень за серпень 2026", "1", "послуга", "12500.00"),
                  ("Пакування відправлень", "40", "шт", "35.00"),
                  ("Зберігання вантажу на складі", "1", "міс.", "2100.00")],
        "vat": 20, "total_override": None, "words": "Дев'ятнадцять тисяч двісті гривень 00 копійок",
    },
    {
        "file": "03-bad-code", "number": "ВП-118", "date": "10.09.2026", "due": "",
        "supplier": {"name": "ТОВ «Вигадка Постач»", "code": "12345670", "ipn": "",
                     "iban": "UA213223130000026007233566001", "bank": "АТ «Банк Вигадка»",
                     "address": "01001, м. Київ, вул. Неіснуюча, 1", "email": "office@vygadka.example"},
        "contract": "",
        "lines": [("Папір офісний А4, 80 г/м2", "20", "пач.", "250.00"),
                  ("Картридж для принтера HP 85A", "5", "шт", "1000.00")],
        "vat": 20, "total_override": "12600.00", "words": "Дванадцять тисяч шістсот гривень 00 копійок",
    },
]


def draw_invoice(inv, path):
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    x0, y = 18 * mm, H - 20 * mm
    s = inv["supplier"]

    def text(t, x, y, size=9, bold=False):
        c.setFont("DVB" if bold else "DV", size)
        c.drawString(x, y, t)

    text("Постачальник:", x0, y, bold=True); text(s["name"], x0 + 32 * mm, y, bold=True); y -= 5 * mm
    text(f"ЄДРПОУ {s['code']}" + (f",  ІПН {s['ipn']}" if s["ipn"] else ""), x0 + 32 * mm, y); y -= 4.5 * mm
    text(f"IBAN {s['iban']} в {s['bank']}", x0 + 32 * mm, y); y -= 4.5 * mm
    text(f"Адреса: {s['address']}", x0 + 32 * mm, y); y -= 4.5 * mm
    text(f"E-mail: {s['email']}", x0 + 32 * mm, y); y -= 8 * mm
    text("Покупець:", x0, y, bold=True); text(BUYER["name"], x0 + 32 * mm, y, bold=True); y -= 5 * mm
    text(f"ЄДРПОУ {BUYER['code']},  {BUYER['address']}", x0 + 32 * mm, y); y -= 5 * mm
    if inv["contract"]:
        text("Договір:", x0, y, bold=True); text(inv["contract"], x0 + 32 * mm, y); y -= 5 * mm
    y -= 6 * mm
    c.setFont("DVB", 14)
    c.drawCentredString(W / 2, y, f"Рахунок на оплату № {inv['number']} від {inv['date']}")
    y -= 10 * mm

    cols = [x0, x0 + 9 * mm, x0 + 100 * mm, x0 + 118 * mm, x0 + 135 * mm, x0 + 157 * mm, x0 + 176 * mm]
    heads = ["№", "Товари (роботи, послуги)", "Кіл-сть", "Од.", "Ціна без ПДВ", "Сума без ПДВ"]
    c.setLineWidth(0.6)
    c.line(x0, y + 4 * mm, cols[-1], y + 4 * mm)
    for i, h in enumerate(heads):
        text(h, cols[i] + 1.2 * mm, y, size=8, bold=True)
    y -= 2.5 * mm
    c.line(x0, y, cols[-1], y)
    untaxed = D("0")
    for n, (name, qty, uom, price) in enumerate(inv["lines"], 1):
        y -= 5 * mm
        amount = D(qty) * D(price)
        untaxed += amount
        for i, v in enumerate([str(n), name, qty, uom, money(D(price)), money(amount)]):
            text(v, cols[i] + 1.2 * mm, y, size=8.5)
        y -= 2.5 * mm
        c.setLineWidth(0.3)
        c.line(x0, y, cols[-1], y)
    tax = (untaxed * inv["vat"] / 100).quantize(D("0.01"))
    total = D(inv["total_override"]) if inv["total_override"] else untaxed + tax
    y -= 7 * mm
    for label, val in [("Разом без ПДВ:", untaxed), (f"ПДВ {inv['vat']}%:", tax), ("Всього з ПДВ:", total)]:
        text(label, cols[4] - 12 * mm, y, size=9, bold=True)
        c.setFont("DVB", 9)
        c.drawRightString(cols[-1] - 1 * mm, y, money(val))
        y -= 5 * mm
    y -= 3 * mm
    text(f"Всього найменувань {len(inv['lines'])}, на суму {money(total)} грн.", x0, y); y -= 5 * mm
    text(inv["words"] + ", у т.ч. ПДВ " + money(tax) + " грн.", x0, y, bold=True); y -= 8 * mm
    if inv["due"]:
        text(f"Оплатити до {inv['due']}. У призначенні платежу вкажіть номер рахунку.", x0, y); y -= 10 * mm
    text("Виписав(ла): ____________________  бухгалтер Коваленко О. В.", x0, y)
    c.showPage()
    c.save()
    return untaxed, tax, total


def make_eml(inv, pdf_path, eml_path, subject_prefix=""):
    s = inv["supplier"]
    msg = EmailMessage()
    msg["From"] = f"Бухгалтерія <{s['email']}>"
    msg["To"] = "rahunky@yasen-mebli.example"
    msg["Subject"] = f"{subject_prefix}Рахунок № {inv['number']} від {inv['date']}"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-Id"] = f"<{inv['file']}-{'repeat' if subject_prefix else 'first'}@test.example>"
    msg.set_content(f"Добрий день!\n\nНадсилаємо рахунок № {inv['number']} від {inv['date']} у вкладенні.\n\n"
                    f"З повагою,\nбухгалтерія {s['name']}\n")
    with open(pdf_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                           filename=f"Rahunok_{inv['number'].replace(' ', '_')}.pdf")
    with open(eml_path, "wb") as f:
        f.write(bytes(msg))


expected = {}
for inv in INVOICES:
    pdf = os.path.join(HERE, inv["file"] + ".pdf")
    untaxed, tax, total = draw_invoice(inv, pdf)
    make_eml(inv, pdf, os.path.join(HERE, inv["file"] + ".eml"))
    expected[inv["file"]] = {"number": inv["number"], "supplier_code": inv["supplier"]["code"],
                             "supplier_ipn": inv["supplier"]["ipn"], "supplier_iban": inv["supplier"]["iban"],
                             "amount_untaxed": str(untaxed), "amount_tax": str(tax), "amount_total": str(total),
                             "lines": len(inv["lines"])}
# the same Nova Poshta invoice sent a second time: must be caught as a duplicate
nova = INVOICES[0]
make_eml(nova, os.path.join(HERE, "01-nova-poshta.pdf"), os.path.join(HERE, "02-nova-poshta-repeat.eml"), "Повторно: ")
expected["02-nova-poshta-repeat"] = dict(expected["01-nova-poshta"])
import json
with open(os.path.join(HERE, "expected.json"), "w", encoding="utf-8") as f:
    json.dump({"buyer": BUYER, "invoices": expected}, f, ensure_ascii=False, indent=1)
print(json.dumps(expected, ensure_ascii=False, indent=1))
