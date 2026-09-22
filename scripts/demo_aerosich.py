#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Друга демо-компанія ТОВ «АероСіч» (Львів): збирання FPV-дронів.

Стає в ту саму базу, що й «Ясен Меблі»: demo_business.py лишається без змін, а цей
скрипт додає поруч окрему компанію - свій план рахунків, склад із полицями, маршрути
виробництва з робочими центрами, серійні номери на дронах, партії на акумуляторах,
імпорт комплектуючих із митним ПДВ, продажі комерційному клієнту і військовій частині
та протокол ВТК на кожен виріб. Адміністратор бачить обидві компанії.

Ідемпотентно: кожен запис шукається за стійким ключем (ref контрагента, default_code
товару, partner_ref замовлення, origin виробничого замовлення, серійний номер).

Запуск (після demo_business.py):
    ODOO_URL=http://127.0.0.1:8131 DEMO_DB=demo python3 scripts/demo_aerosich.py
Змінні: ODOO_URL (типово http://127.0.0.1:8131), DEMO_DB (типово demo).
"""
import base64
import json
import os
import re
import sys
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8131").rstrip("/")
DB = os.environ.get("DEMO_DB", "demo").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

# Назва компанії в одному місці: перейменування - один рядок.
COMPANY = {
    "name": "ТОВ «АероСіч»",
    "short": "АероСіч",
    "street": "вул. Наукова, 7а",
    "city": "Львів",
    "zip": "79060",
    "edrpou7": "4512806",
    "email": "office@aerosich.example.ua",
    "phone": "+380 32 297 44 10",
    "actual": "79060, Львів, вул. Наукова, 7а, корпус Б",
}
DRAWING = os.path.join(ROOT, "scripts", "demo_assets", "shershen.svg")

_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36")]
urllib.request.install_opener(_opener)


class RpcError(Exception):
    pass


def rpc(service, method, *args):
    req = urllib.request.Request(
        URL + "/jsonrpc",
        json.dumps({"jsonrpc": "2.0", "method": "call",
                    "params": {"service": service, "method": method, "args": args},
                    "id": 1}).encode(),
        {"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=600).read())
    if "error" in d:
        msg = d["error"].get("data", {}).get("message") or d["error"].get("message")
        raise RpcError(str(msg)[:3000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    sys.exit("Не вдалося увійти в базу %s на %s" % (DB, URL))

# Контекст компанії: усе, що пише цей скрипт, іде від імені «АероСічі».
# Поля, залежні від компанії (рахунки категорій, податки, курси), беруть компанію
# саме з allowed_company_ids, тому підмішуємо його в кожен виклик.
CTX = {"lang": "uk_UA"}
CO = None


def call(model, method, *a, **kw):
    ctx = dict(CTX, **(kw.pop("context", None) or {}))
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a),
               dict(kw, context=ctx))


def call0(model, method, *a, **kw):
    """Виклик без компанійного контексту: створення самої компанії і довідники."""
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def say(msg):
    print(msg, flush=True)


def upsert(model, domain, vals):
    ids = call(model, "search", domain)
    if ids:
        call(model, "write", [ids[0]], vals)
        return ids[0]
    return call(model, "create", vals)


def has_field(model, name):
    return name in call(model, "fields_get", [name], ["type"])


def edrpou(base7):
    d = [int(c) for c in base7]
    n = int(base7) * 10
    w = [7, 1, 2, 3, 4, 5, 6] if 30000000 <= n <= 60000000 else [1, 2, 3, 4, 5, 6, 7]
    c = sum(a * b for a, b in zip(d, w)) % 11
    if c == 10:
        c = sum(a * (b + 2) for a, b in zip(d, w)) % 11
        c = 0 if c == 10 else c
    return base7 + str(c)


def ipn_from_edrpou(code8):
    return code8 + str((int(code8) * 3) % 10) + str((int(code8) * 7) % 10) + \
        str((int(code8) * 9) % 10) + str((int(code8) * 11) % 10)


def rnokpp(birthday, sex, serial):
    days = (birthday - date(1899, 12, 31)).days
    body = f"{days:05d}{serial:03d}" + str((serial * 7 + (1 if sex == "male" else 0)) % 10 // 2 * 2 + (1 if sex == "male" else 0))
    w = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    return body + str(sum(int(c) * k for c, k in zip(body, w)) % 11 % 10)


# =====================================================================================
# 1. Компанія, план рахунків, реквізити
# =====================================================================================
def ensure_company():
    global CO
    ua = call0("res.country", "search", [["code", "=", "UA"]])[0]
    uah = call0("res.currency", "search", [["name", "=", "UAH"]],
                context={"active_test": False})[0]
    code = edrpou(COMPANY["edrpou7"])
    ids = call0("res.company", "search", [["name", "=", COMPANY["name"]]])
    vals = {"name": COMPANY["name"], "currency_id": uah, "country_id": ua,
            "street": COMPANY["street"], "city": COMPANY["city"], "zip": COMPANY["zip"],
            "company_registry": code, "email": COMPANY["email"], "phone": COMPANY["phone"]}
    co = ids[0] if ids else call0("res.company", "create", vals)
    if ids:
        call0("res.company", "write", [co], vals)
    call0("res.users", "write", [UID], {"company_ids": [(4, co)]})
    CO = co
    CTX["allowed_company_ids"] = [co]
    info = call("res.company", "read", [co], ["chart_template", "partner_id"])[0]
    if info["chart_template"] != "ua_psbo":
        call("account.chart.template", "try_loading", "ua_psbo", co, False)
    call("res.company", "write", [co], {
        "vat": ipn_from_edrpou(code),
        "ua_acts_on_basis": "Статуту",
        "ua_cash_limit": 20000.0,
        "ua_dps_reg": "13", "ua_dps_raj": "06", "ua_dps_sti": "1306"})
    call("res.partner", "write", [info["partner_id"][0]], {
        "vat": ipn_from_edrpou(code), "ua_vat_payer_status": "payer",
        "ua_actual_address": COMPANY["actual"], "lang": "uk_UA",
        "supplier_rank": 1, "customer_rank": 1})
    plan = call("res.company", "read", [co], ["chart_template"])[0]["chart_template"]
    say(f"Компанія: {COMPANY['name']} (id {co}), ЄДРПОУ {code}, план {plan}, "
        f"{COMPANY['city']}.")
    return co


def acc(code):
    ids = call("account.account", "search",
               [["code", "=like", f"{code}%"], ["company_ids", "in", CO]],
               order="code", limit=1)
    return ids[0] if ids else False


def taxes():
    def one(use, amount, zero_kind=None):
        dom = [["type_tax_use", "=", use], ["amount", "=", amount],
               ["company_id", "=", CO], ["amount_type", "=", "percent"]]
        if zero_kind:
            dom.append(["tax_group_id.ua_vat_zero_kind", "=", zero_kind])
        ids = call("account.tax", "search", dom, limit=1)
        return ids[0] if ids else False
    t = {"sale20": one("sale", 20.0), "purchase20": one("purchase", 20.0),
         "exempt0": one("sale", 0.0, "exempt")}
    missing = [k for k, v in t.items() if not v]
    if missing:
        say("УВАГА: не знайдено податки " + ", ".join(missing))
    say(f"Податки: ПДВ 20 % на продаж і закупівлю, пільгова 0 % для постачання ЗСУ "
        f"({'є' if t['exempt0'] else 'НЕМАЄ'}).")
    return t


# Курси НБУ для другої компанії: імпортні рахунки без них перерахувалися б один до
# одного. Ті самі числа, що вставляє demo_business.py, але на цю компанію.
RATES = [("2026-07-01", 45.80, 41.75), ("2026-07-15", 46.10, 41.90),
         ("2026-08-03", 46.45, 41.60), ("2026-08-18", 47.02, 41.45),
         ("2026-09-01", 47.30, 41.35), ("2026-09-15", 47.55, 41.20)]


def currency_rates():
    eur = call0("res.currency", "search", [["name", "=", "EUR"]], context={"active_test": False})
    usd = call0("res.currency", "search", [["name", "=", "USD"]], context={"active_test": False})
    call0("res.currency", "write", eur + usd, {"active": True})
    n = 0
    for day, e_rate, u_rate in RATES:
        for cur, uah in ((eur[0], e_rate), (usd[0], u_rate)):
            upsert("res.currency.rate",
                   [["name", "=", day], ["currency_id", "=", cur], ["company_id", "=", CO]],
                   {"name": day, "currency_id": cur, "company_id": CO,
                    "inverse_company_rate": uah})
            n += 1
    say(f"Курси НБУ на компанію: {n} записів (EUR і USD, липень-вересень).")
    return usd[0], eur[0]


# =====================================================================================
# 2. Контрагенти
# =====================================================================================
CUSTOMERS = [
    ("AERO-C01", "ТОВ «Скайлайн Секʼюриті»", "3914702", "payer", "Київ", "03150",
     "вул. Антоновича, 176"),
    ("AERO-C02", "Військова частина А4512", "2277501", "non_payer", "Львів", "79000",
     "вул. Стрийська, 10"),
    ("AERO-C03", "БФ «Крила Допомоги»", "4408913", "non_payer", "Львів", "79005",
     "вул. Дорошенка, 41"),
]
SUPPLIERS = [
    ("AERO-S01", "ТОВ «Пакувальні рішення»", "3702815", "payer", "Львів", "79035",
     "вул. Зелена, 147"),
    ("AERO-S02", "ТОВ «Електрон Компоненти»", "3305914", "payer", "Київ", "04073",
     "пр. Степана Бандери, 21"),
]
# Іноземний постачальник: рахунок у валюті, ПДВ сплачується на митниці.
FOREIGN = ("AERO-S90", "Shenzhen SkyParts Co., Ltd", "CN", "Shenzhen", "518000",
           "Bao'an District, Xixiang Street 118")


def partners(usd):
    PR = {}
    ua = call0("res.country", "search", [["code", "=", "UA"]])[0]
    cn = call0("res.country", "search", [["code", "=", "CN"]])[0]
    for ref, name, base7, status, city, zip_, street in CUSTOMERS + SUPPLIERS:
        code = edrpou(base7)
        PR[ref] = upsert("res.partner", [["ref", "=", ref]], {
            "name": name, "ref": ref, "is_company": True, "company_registry": code,
            "vat": ipn_from_edrpou(code) if status == "payer" else False,
            "ua_vat_payer_status": status, "country_id": ua, "city": city, "zip": zip_,
            "street": street, "lang": "uk_UA", "company_id": False,
            "customer_rank": 1 if ref.startswith("AERO-C") else 0,
            "supplier_rank": 1 if ref.startswith("AERO-S") else 0})
    ref, name, _cc, city, zip_, street = FOREIGN
    PR[ref] = upsert("res.partner", [["ref", "=", ref]], {
        "name": name, "ref": ref, "is_company": True, "country_id": cn,
        "city": city, "zip": zip_, "street": street, "company_id": False,
        "ua_vat_payer_status": "non_payer", "supplier_rank": 1,
        "property_purchase_currency_id": usd})
    say(f"Контрагенти: {len(CUSTOMERS)} покупці (комерційний, військова частина, фонд), "
        f"{len(SUPPLIERS)} українські постачальники, 1 іноземний ({name}).")
    return PR


# =====================================================================================
# 3. Номенклатура і специфікації
# =====================================================================================
# (код, назва, ціна UAH, УКТ ЗЕД, габарит, відстеження, імпортний)
COMPONENTS = [
    ("D01", "Рама карбонова 7\" «Шершень» (компл.)", 1850.0, "3921903000", "m", "none", True),
    ("D02", "Мотор безколекторний 2207 1950KV", 980.0, "8501109300", "s", "none", True),
    ("D03", "Регулятор ESC 4-в-1 45 А", 2450.0, "8504403090", "s", "none", True),
    ("D04", "Політний контролер F722", 1980.0, "8537109100", "s", "none", True),
    ("D05", "Приймач ELRS 2.4 ГГц", 520.0, "8517620000", "s", "none", True),
    ("D06", "Камера FPV Nano 1200TVL", 1150.0, "8525893000", "s", "none", True),
    ("D07", "Відеопередавач VTX 1.6 Вт", 1320.0, "8525600000", "s", "none", True),
    ("D08", "Антена відео 5.8 ГГц RHCP", 340.0, "8529107000", "s", "none", True),
    ("D09", "Пропелер 7\" трилопатевий", 95.0, "8803300000", "s", "none", True),
    ("D10", "Акумулятор Li-ion 6S 3500 мАг", 3400.0, "8507600000", "m", "lot", True),
    ("D11", "Комплект пакування: ремінець, коробка, поролон", 240.0, "4819100000", "m", "none", False),
    ("D12", "Рама карбонова 10\" «Оса» (компл.)", 2400.0, "3921903000", "m", "none", True),
    ("D13", "Мотор безколекторний 2810 900KV", 1320.0, "8501109300", "s", "none", True),
    ("D14", "Пропелер 10\" дволопатевий", 140.0, "8803300000", "s", "none", True),
    ("D15", "Акумулятор Li-ion 6S 6000 мАг", 5200.0, "8507600000", "m", "lot", True),
]
# Специфікації: порядок рядків = номери позицій на кресленні (pos-1 .. pos-11).
DRONES = [
    ("FPV7", "FPV-дрон «Шершень» 7\"", 29800.0, "8806210000", "l",
     [("D01", 1), ("D02", 4), ("D03", 1), ("D04", 1), ("D05", 1), ("D06", 1),
      ("D07", 1), ("D08", 1), ("D09", 4), ("D10", 1), ("D11", 1)]),
    ("FPV10", "FPV-дрон «Оса» 10\"", 41500.0, "8806210000", "l",
     [("D12", 1), ("D13", 4), ("D03", 1), ("D04", 1), ("D05", 1), ("D06", 1),
      ("D07", 1), ("D08", 1), ("D14", 4), ("D15", 1), ("D11", 1)]),
]
# Маршрут: робочий центр, назва операції, норма часу (хв), кроки, перевірка ВТК,
# і які позиції специфікації (від одиниці) належать цій операції.
ROUTING = [
    ("РОЗКР", "Дільниця розкрою", "Розкрій і збирання рами", 25.0,
     "Перевірити комплектність рами за пакувальним листом\n"
     "Зняти захисну плівку з карбону\n"
     "Зібрати деку і промені, момент затягування 0,6 Нм",
     "Діагоналі рами рівні, розбіг не більше 0,5 мм\nГвинти затягнуті, різьба ціла",
     [1]),
    ("ПАЙКА", "Пайка", "Пайка силової частини", 40.0,
     "Залудити майданчики ESC\n"
     "Припаяти три фази кожного мотора за схемою\n"
     "Припаяти силовий джгут XT60, перевірити полярність",
     "Опір між фазами однаковий\nКоротких замикань на корпус немає\nПайка блискуча, без каніфолі",
     [2, 3]),
    ("ПРОШ", "Прошивка і налаштування", "Монтаж і прошивка", 35.0,
     "Встановити політний контролер на стек, м'які демпфери\n"
     "Прошити прошивку, залити конфігурацію\n"
     "Прив'язати приймач, перевірити канали",
     "Версія прошивки збігається з паспортом виробу\nУсі канали відгукуються\n"
     "Аварійне вимкнення (failsafe) спрацьовує",
     [4, 5]),
    ("ЗБИР", "Складальна дільниця", "Збирання", 45.0,
     "Встановити камеру, виставити кут нахилу\n"
     "Встановити відеопередавач і антену\n"
     "Накрутити пропелери за напрямком обертання",
     "Картинка чиста на всіх каналах\nАнтена не торкається пропелерів\n"
     "Пропелери стоять за стрілками",
     [6, 7, 8, 9]),
    ("ВТК", "ВТК і льотний тест", "ВТК і льотний тест", 30.0,
     "Встановити акумулятор, зафіксувати ремінцем\n"
     "Зависання 2 хвилини, перевірка стабілізації\n"
     "Перевірити дальність відеоканалу",
     "Струм споживання в межах норми\nВібрації в межах норми\n"
     "Дальність відео не менша за паспортну",
     [10]),
    ("ПАК", "Пакування", "Пакування", 15.0,
     "Розрядити акумулятор до транспортного рівня\n"
     "Укласти виріб і комплектацію в коробку\n"
     "Наклеїти етикетку з серійним номером",
     "Серійний номер на коробці збігається з виробом\nКомплектність за пакувальним листом",
     [11]),
]


def products(tx):
    cat_c = upsert("product.category", [["name", "=", "Комплектуючі дронів"]], {
        "name": "Комплектуючі дронів",
        "property_account_expense_categ_id": acc("201"),
        "property_account_income_categ_id": acc("701")})
    cat_d = upsert("product.category", [["name", "=", "Дрони"]], {
        "name": "Дрони",
        "property_account_expense_categ_id": acc("901"),
        "property_account_income_categ_id": acc("701")})
    size = has_field("product.template", "ua_size")
    P, T = {}, {}
    for code, name, price, uktzed, dim, track, _imp in COMPONENTS:
        vals = {"name": name, "default_code": code, "type": "consu", "is_storable": True,
                "categ_id": cat_c, "standard_price": price, "list_price": price * 1.4,
                "ua_uktzed": uktzed, "purchase_ok": True, "sale_ok": False,
                "tracking": track,
                "supplier_taxes_id": [(6, 0, [tx["purchase20"]])] if tx["purchase20"] else False,
                "taxes_id": [(6, 0, [tx["sale20"]])] if tx["sale20"] else False}
        if size:
            vals["ua_size"] = dim
        tid = upsert("product.template", [["default_code", "=", code]], vals)
        T[code] = tid
        P[code] = call("product.product", "search", [["product_tmpl_id", "=", tid]])[0]
    price_of = dict((c[0], c[2]) for c in COMPONENTS)
    for code, name, price, uktzed, dim, bom in DRONES:
        cost = round(sum(price_of[m] * q for m, q in bom), 2)
        vals = {"name": name, "default_code": code, "type": "consu", "is_storable": True,
                "categ_id": cat_d, "standard_price": cost, "list_price": price,
                "ua_uktzed": uktzed, "purchase_ok": False, "sale_ok": True,
                "tracking": "serial",
                "taxes_id": [(6, 0, [tx["sale20"]])] if tx["sale20"] else False}
        if size:
            vals["ua_size"] = dim
        tid = upsert("product.template", [["default_code", "=", code]], vals)
        T[code] = tid
        P[code] = call("product.product", "search", [["product_tmpl_id", "=", tid]])[0]
    lots = [c[0] for c in COMPONENTS if c[5] == "lot"]
    say(f"Номенклатура: {len(COMPONENTS)} комплектуючих, {len(DRONES)} вироби; "
        f"серійні номери на дронах, партії на акумуляторах ({', '.join(lots)}); "
        f"габарит S/M/L {'проставлено' if size else 'пропущено - поля ua_size ще немає'}.")
    return P, T


def workcenters():
    WC = {}
    for code, name, _op, _t, _s, _c, _pos in ROUTING:
        WC[code] = upsert("mrp.workcenter", [["code", "=", code], ["company_id", "=", CO]], {
            "name": name, "code": code, "company_id": CO, "time_efficiency": 100.0,
            "costs_hour": {"РОЗКР": 180.0, "ПАЙКА": 260.0, "ПРОШ": 320.0,
                           "ЗБИР": 240.0, "ВТК": 300.0, "ПАК": 150.0}[code]})
    say(f"Робочі центри: {len(WC)} ("
        + ", ".join(r[1] for r in ROUTING) + ").")
    return WC


def boms(P, T, WC):
    steps = has_field("mrp.routing.workcenter", "ua_steps")
    made = 0
    for code, name, price, uktzed, dim, lines in DRONES:
        tmpl = T[code]
        ids = call("mrp.bom", "search", [["product_tmpl_id", "=", tmpl],
                                         ["company_id", "=", CO]])
        if not ids:
            ids = [call("mrp.bom", "create", {
                "product_tmpl_id": tmpl, "product_qty": 1, "type": "normal",
                "company_id": CO})]
            made += 1
        bom = ids[0]
        # Операції маршруту: спершу вони, бо рядки специфікації на них посилаються.
        ops = []
        for seq, (wc, _wcname, op_name, minutes, s_text, c_text, _pos) in enumerate(ROUTING, start=1):
            vals = {"name": op_name, "workcenter_id": WC[wc], "bom_id": bom,
                    "sequence": seq * 10, "time_mode": "manual",
                    "time_cycle_manual": minutes, "company_id": CO}
            if steps:
                vals["ua_steps"] = s_text
                vals["ua_checks"] = c_text
            ops.append(upsert("mrp.routing.workcenter",
                              [["bom_id", "=", bom], ["name", "=", op_name]], vals))
        pos_of_op = {}
        for i, (_wc, _wcname, _n, _m, _s, _c, positions) in enumerate(ROUTING):
            for pos in positions:
                pos_of_op[pos] = ops[i]
        old = call("mrp.bom.line", "search", [["bom_id", "=", bom]])
        if old:
            call("mrp.bom.line", "unlink", old)
        for pos, (comp, qty) in enumerate(lines, start=1):
            call("mrp.bom.line", "create", {
                "bom_id": bom, "product_id": P[comp], "product_qty": qty,
                "sequence": pos * 10, "operation_id": pos_of_op.get(pos, False),
                "company_id": CO})
    n_ops = call("mrp.routing.workcenter", "search_count", [["company_id", "=", CO]])
    say(f"Специфікації: {len(DRONES)} (нових {made}), по {len(DRONES[0][5])} позицій; "
        f"операцій маршруту {n_ops}, норми часу "
        + ", ".join(f"{r[2]} {r[3]:.0f} хв" for r in ROUTING) + "; "
        + ("кроки і перевірка ВТК записані"
           if steps else "кроків не записали - полів ua_steps/ua_checks ще немає") + ".")
    return steps


# =====================================================================================
# 4. Склад: зона комплектуючих, шафа акумуляторів, готові вироби
# =====================================================================================
SHELVES = ["К-1", "К-2", "К-3", "К-4"]
BATTERY_LOC = "Шафа акумуляторів"
FINISHED_LOC = "Готові дрони"
# Місткість полиць ставимо не наосліп, а після того, як залишки лягли на місця:
# двом полицям навмисно даємо менше місць, ніж на них лежить, - шафі акумуляторів і
# карбоновій полиці з рамами. Решта лишається з запасом. Так карта складу показує
# рівно два переповнення, а не випадкове число.
OVERFULL = [BATTERY_LOC, "К-1"]
SHELF_OF = {"D01": "К-1", "D12": "К-1", "D02": "К-2", "D13": "К-2", "D09": "К-2",
            "D14": "К-2", "D03": "К-3", "D04": "К-3", "D05": "К-3", "D06": "К-3",
            "D07": "К-3", "D08": "К-3", "D11": "К-4"}


def warehouse(P):
    fields_ = ["name", "code", "lot_stock_id", "int_type_id", "in_type_id",
               "out_type_id"]
    wh = call("stock.warehouse", "search_read", [["company_id", "=", CO]],
              fields=fields_, context={"active_test": False})
    if not wh:
        # Компанія, створена через RPC, приходить без складу: Odoo заводить його
        # лише на встановленні модуля stock. Заводимо самі.
        wid = call("stock.warehouse", "create",
                   {"name": COMPANY["short"], "code": "AER", "company_id": CO})
        wh = call("stock.warehouse", "search_read", [["id", "=", wid]],
                  fields=fields_, context={"active_test": False})
    wh = wh[0]
    call("stock.warehouse", "write", [wh["id"]], {"name": COMPANY["short"]})
    stock = wh["lot_stock_id"][0]
    cap = has_field("stock.location", "ua_capacity")

    def loc(name, parent):
        ids = call("stock.location", "search",
                   [["name", "=", name], ["location_id", "=", parent]],
                   context={"active_test": False})
        vals = {"name": name, "location_id": parent, "usage": "internal",
                "company_id": CO, "active": True}
        if ids:
            call("stock.location", "write", [ids[0]], vals)
            return ids[0]
        return call("stock.location", "create", vals)

    L = {"stock": stock, "wh": wh["id"], "int_type": wh["int_type_id"][0]}
    L["zone"] = loc("Комплектуючі", stock)
    for s in SHELVES:
        L[s] = loc(s, L["zone"])
    L[BATTERY_LOC] = loc(BATTERY_LOC, L["zone"])
    L[FINISHED_LOC] = loc(FINISHED_LOC, stock)
    types = call("stock.picking.type", "search",
                 [["warehouse_id", "=", wh["id"]], ["code", "=", "internal"]],
                 context={"active_test": False})
    call("stock.picking.type", "write", types, {"active": True})
    # Правила розкладання: категорія в зону, акумулятори в шафу, решта - на полиці
    cat_c = call("product.category", "search", [["name", "=", "Комплектуючі дронів"]])
    cat_d = call("product.category", "search", [["name", "=", "Дрони"]])
    n = 0

    def rule(loc_in, loc_out, product=None, category=None):
        dom = [["location_in_id", "=", loc_in], ["company_id", "=", CO]]
        dom.append(["product_id", "=", product] if product else ["category_id", "=", category])
        vals = {"location_in_id": loc_in, "location_out_id": loc_out, "company_id": CO}
        if product:
            vals["product_id"] = product
        else:
            vals["category_id"] = category
        upsert("stock.putaway.rule", dom, vals)

    if cat_c:
        rule(stock, L["zone"], category=cat_c[0])
        n += 1
    if cat_d:
        rule(stock, L[FINISHED_LOC], category=cat_d[0])
        n += 1
    # Правило розкладання спрацьовує на один крок, тому товарні правила пишемо і від
    # складу, і від зони: інакше ящик доїжджає лише до «Комплектуючих» і лягає там.
    for code, shelf in SHELF_OF.items():
        rule(stock, L[shelf], product=P[code])
        rule(L["zone"], L[shelf], product=P[code])
        n += 2
    for code in ("D10", "D15"):
        rule(stock, L[BATTERY_LOC], product=P[code])
        rule(L["zone"], L[BATTERY_LOC], product=P[code])
        n += 2
    say(f"Склад «{COMPANY['short']}»: зона комплектуючих із {len(SHELVES)} полицями, "
        f"{BATTERY_LOC.lower()} і «{FINISHED_LOC}»; правил розкладання {n}; "
        f"місткість {'проставимо після завантаження' if cap else 'пропущено - поля ua_capacity ще немає'}.")
    return L


def capacities(L):
    """Місць на кожній полиці; дві полиці навмисно переповнені.

    Місткість рахуємо від того, що реально лежить (`ua_capacity_used` - це
    кількість × габарит товару), тому переповнення не залежить від того, скільки
    саме комплектуючих привезли цього прогону.
    """
    if not has_field("stock.location", "ua_capacity"):
        say("Місткість полиць: поля ua_capacity немає - пропущено.")
        return 0, 0
    names = SHELVES + [BATTERY_LOC, FINISHED_LOC]
    rows = []
    for name in names:
        used = call("stock.location", "read", [L[name]], ["ua_capacity_used"])[0]["ua_capacity_used"]
        if name in OVERFULL:
            cap = max(1, int(used * 0.7))       # менше, ніж лежить: полиця переповнена
        else:
            cap = max(20, int(used * 1.5) + 10)  # з запасом
        call("stock.location", "write", [L[name]], {"ua_capacity": cap})
        rows.append((name, cap, used))
    # Зона і склад цілком: сума дітей, щоб карта читалася на будь-якому рівні
    call("stock.location", "write", [L["zone"]],
         {"ua_capacity": sum(c for n, c, _u in rows if n != FINISHED_LOC)})
    call("stock.location", "write", [L["stock"]],
         {"ua_capacity": sum(c for _n, c, _u in rows)})
    over = [(n, c, u) for n, c, u in rows if u > c]
    say(f"Місткість полиць: {len(rows)} локацій; переповнені {len(over)} ("
        + ", ".join(f"{n}: зайнято {u} з {c}" for n, c, u in over) + ").")
    return len(rows), len(over)


# =====================================================================================
# 5. Закупівлі: українська і імпортна з митним ПДВ
# =====================================================================================
LOCAL_PO = ("АС-ЗП-2026-01", "AERO-S01", "2026-07-04", [("D11", 60)])
IMPORT_PO = ("АС-ЗП-2026-02", "AERO-S90", "2026-07-07", [
    ("D01", 20), ("D02", 90), ("D03", 24), ("D04", 24), ("D05", 24), ("D06", 24),
    ("D07", 24), ("D08", 24), ("D09", 100), ("D10", 24),
    ("D12", 10), ("D13", 45), ("D14", 50), ("D15", 12)])
CUSTOMS_DECL = "UA209140/2026/018374"
LOT_PREFIX = {"D10": "АКБ-3500-2607", "D15": "АКБ-6000-2607"}


def _lot(product_id, name):
    ids = call("stock.lot", "search", [["name", "=", name], ["product_id", "=", product_id]])
    if ids:
        return ids[0]
    return call("stock.lot", "create", {"name": name, "product_id": product_id,
                                        "company_id": CO})


def _fill_lots(move_ids, lot_name):
    """Проставити партію на рядках переміщення для товарів з відстеженням."""
    moves = call("stock.move", "read", move_ids, ["product_id", "move_line_ids"])
    tracked = call("product.product", "read", [m["product_id"][0] for m in moves],
                   ["tracking", "default_code"])
    track_of = {t["id"]: (t["tracking"], t["default_code"]) for t in tracked}
    for m in moves:
        tracking, code = track_of.get(m["product_id"][0], ("none", ""))
        if tracking == "none":
            continue
        for line in call("stock.move.line", "read", m["move_line_ids"], ["lot_id", "quantity"]):
            if line["lot_id"]:
                continue
            name = lot_name(code)
            call("stock.move.line", "write", [line["id"]],
                 {"lot_id": _lot(m["product_id"][0], name)})


def _assign(pid):
    """Зарезервувати переміщення, якщо його ще є сенс резервувати."""
    if call("stock.picking", "read", [pid], ["state"])[0]["state"] in ("done", "cancel"):
        return
    call("stock.picking", "action_assign", [pid])


def _validate_picking(pid, when, lot_name=None):
    pick = call("stock.picking", "read", [pid], ["state", "move_ids"])[0]
    if pick["state"] in ("done", "cancel"):
        return
    moves = call("stock.move", "read", pick["move_ids"], ["product_uom_qty", "quantity"])
    for mv in moves:
        call("stock.move", "write", [mv["id"]],
             {"quantity": mv["product_uom_qty"], "picked": True})
    if lot_name:
        _fill_lots(pick["move_ids"], lot_name)
    ctx = {"skip_sms": True, "skip_backorder": True, "skip_immediate": True,
           "force_period_date": when}
    res = call("stock.picking", "button_validate", [pid], context=ctx)
    if isinstance(res, dict) and res.get("res_model"):
        c = dict(res.get("context") or {}, **ctx)
        wiz = call(res["res_model"], "create", {}, context=c)
        for method in ("process", "action_confirm", "dont_send_sms", "apply"):
            try:
                call(res["res_model"], method, [wiz], context=c)
                break
            except RpcError as e:
                if "does not exist" not in str(e):
                    say(f"   майстер {res['res_model']}.{method}: {str(e)[:150]}")
                    break
    call("stock.picking", "write", [pid], {"date_done": when + " 10:00:00"})


def _validate_reserved(pid, when):
    """Провести переміщення так, як його зарезервував Odoo: кількості й партії на
    рядках уже стоять, лишається позначити рядки взятими."""
    pick = call("stock.picking", "read", [pid], ["state", "move_ids"])[0]
    if pick["state"] in ("done", "cancel"):
        return
    call("stock.move", "write", pick["move_ids"], {"picked": True})
    ctx = {"skip_sms": True, "skip_backorder": True, "skip_immediate": True,
           "force_period_date": when}
    res = call("stock.picking", "button_validate", [pid], context=ctx)
    if isinstance(res, dict) and res.get("res_model"):
        c = dict(res.get("context") or {}, **ctx)
        wiz = call(res["res_model"], "create", {}, context=c)
        for method in ("process", "action_confirm", "apply"):
            try:
                call(res["res_model"], method, [wiz], context=c)
                break
            except RpcError:
                continue
    call("stock.picking", "write", [pid], {"date_done": when + " 10:00:00"})


SPREAD_ORIGIN = "Розкладання по полицях"


def spread_to_shelves(P, L, day="2026-09-20", tag="1"):
    """Залишки з зони і з самого складу - на полиці, одним внутрішнім переміщенням.

    Проходів два: перший одразу після надходження (щоб виробництво резервувало вже
    з полиць), другий наприкінці - для готових виробів і решти.
    """
    origin = f"{SPREAD_ORIGIN} {tag}"
    ids = call("stock.picking", "search",
               [["origin", "=", origin], ["company_id", "=", CO]])
    if ids and call("stock.picking", "read", ids, ["state"])[0]["state"] == "done":
        say(f"Розкладання по полицях ({tag}): уже зроблено.")
        return ids[0]
    by_id = {pid: code for code, pid in P.items()}
    parents = [L["stock"], L["zone"]]
    quants = call("stock.quant", "search_read",
                  [["location_id", "in", parents], ["quantity", ">", 0],
                   ["company_id", "=", CO]],
                  fields=["product_id", "quantity", "location_id"])
    moves = []
    for q in quants:
        code = by_id.get(q["product_id"][0]) or ""
        if code in ("D10", "D15"):
            dest = L[BATTERY_LOC]
        elif code in ("FPV7", "FPV10"):
            dest = L[FINISHED_LOC]
        else:
            dest = L.get(SHELF_OF.get(code, "К-4"), L["К-4"])
        if dest == q["location_id"][0]:
            continue
        moves.append((0, 0, {"product_id": q["product_id"][0],
                             "product_uom_qty": q["quantity"], "company_id": CO,
                             "location_id": q["location_id"][0],
                             "location_dest_id": dest}))
    if not moves:
        say(f"Розкладання по полицях ({tag}): усе вже лежить на місцях.")
        return None
    pid = ids[0] if ids else call("stock.picking", "create", {
        "picking_type_id": L["int_type"], "company_id": CO, "origin": origin,
        "location_id": L["zone"], "location_dest_id": L["zone"],
        "scheduled_date": day + " 08:00:00", "move_ids": moves})
    call("stock.picking", "action_confirm", [pid])
    call("stock.picking", "action_assign", [pid])
    _validate_reserved(pid, day)
    left = call("stock.quant", "search_count",
                [["location_id", "in", parents], ["quantity", ">", 0],
                 ["company_id", "=", CO]])
    say(f"Розкладання по полицях ({tag}): {len(moves)} позицій рознесено; у зоні і на "
        f"складі лишилось {left} залишків.")
    return pid


def _purchase(key, partner, day, lines, P, tx, currency=None, rate=1.0, with_tax=True):
    ids = call("purchase.order", "search", [["partner_ref", "=", key]])
    price_of = dict((c[0], c[2]) for c in COMPONENTS)
    if not ids:
        vals = {"partner_id": partner, "partner_ref": key, "company_id": CO,
                "date_order": day + " 09:00:00",
                "order_line": [(0, 0, {
                    "product_id": P[c], "product_qty": q,
                    "price_unit": round(price_of[c] / rate, 2),
                    "date_planned": day + " 09:00:00",
                    "tax_ids": [(6, 0, [tx["purchase20"]])] if (with_tax and tx["purchase20"]) else [(5, 0, 0)],
                }) for c, q in lines]}
        if currency:
            vals["currency_id"] = currency
        ids = [call("purchase.order", "create", vals)]
    po = ids[0]
    if call("purchase.order", "read", [po], ["state"])[0]["state"] in ("draft", "sent"):
        call("purchase.order", "button_confirm", [po])
    st = call("purchase.order", "read", [po], ["picking_ids", "invoice_ids", "name"])[0]
    for pid in st["picking_ids"]:
        _assign(pid)
        _validate_picking(pid, day, lot_name=lambda code: f"{LOT_PREFIX.get(code, code)}-01")
    if not st["invoice_ids"]:
        call("purchase.order", "action_create_invoice", [po])
        st = call("purchase.order", "read", [po], ["invoice_ids", "name"])[0]
        for b in st["invoice_ids"]:
            call("account.move", "write", [b], {
                "invoice_date": day, "date": day,
                "ref": "Рахунок постачальника " + key,
                "ua_in_pn_registered": bool(with_tax)})
            call("account.move", "action_post", [b])
    return po, call("purchase.order", "read", [po], ["invoice_ids"])[0]["invoice_ids"]


def purchases(PR, P, tx, usd):
    key, sup, day, lines = LOCAL_PO
    _purchase(key, PR[sup], day, lines, P, tx)
    say(f"Закупівля в Україні: {key}, {len(lines)} позиція, ПДВ 20 %, надходження і "
        f"рахунок проведені.")

    key, sup, day, lines = IMPORT_PO
    rate = dict((d, u) for d, _e, u in RATES)["2026-07-01"]
    po, bills = _purchase(key, PR[sup], day, lines, P, tx, currency=usd,
                          rate=rate, with_tax=False)
    if not bills:
        say("УВАГА: імпортний рахунок не створився.")
        return None
    bill = bills[0]
    b = call("account.move", "read", [bill],
             ["name", "amount_total", "amount_total_signed", "currency_id",
              "ua_is_import", "ua_customs_move_id"])[0]
    vat = round(abs(b["amount_total_signed"]) * 0.2, 2)
    if not b["ua_customs_move_id"]:
        call("account.move", "write", [bill], {
            "ua_customs_decl_number": CUSTOMS_DECL, "ua_customs_vat": vat})
        call("account.move", "action_ua_post_customs_vat", [bill])
    b = call("account.move", "read", [bill],
             ["name", "amount_total", "amount_total_signed", "ua_is_import",
              "ua_customs_vat", "ua_customs_move_id"])[0]
    entry = b["ua_customs_move_id"]
    say(f"Імпорт: {key} на {b['amount_total']:,.2f} USD "
        f"({abs(b['amount_total_signed']):,.2f} грн), імпортний рахунок "
        f"{'так' if b['ua_is_import'] else 'НІ'}; МД {CUSTOMS_DECL}, митний ПДВ "
        f"{b['ua_customs_vat']:,.2f} грн у кредиті проводкою "
        f"{entry[1] if entry else 'НЕ СТВОРЕНО'}.")
    return bill


# =====================================================================================
# 6. Виробництво: серійні номери, наряди, готові і незакриті замовлення
# =====================================================================================
# (origin, код виробу, серійний номер, дата, закрити)
MOS = [
    ("АС-ВЗ-2026-01", "FPV7", "ШРШ-2026-0001", "2026-08-05", True),
    ("АС-ВЗ-2026-02", "FPV7", "ШРШ-2026-0002", "2026-08-12", True),
    ("АС-ВЗ-2026-03", "FPV7", "ШРШ-2026-0003", "2026-08-26", True),
    ("АС-ВЗ-2026-04", "FPV10", "ОСА-2026-0001", "2026-09-03", True),
    ("АС-ВЗ-2026-05", "FPV10", "ОСА-2026-0002", "2026-09-11", True),
    ("АС-ВЗ-2026-06", "FPV7", "ШРШ-2026-0004", "2026-09-24", False),
]


def manufacturing(P, T):
    done, open_ = 0, 0
    serials = {}
    for origin, code, serial, day, close in MOS:
        ids = call("mrp.production", "search", [["origin", "=", origin]])
        if not ids:
            bom = call("mrp.bom", "search", [["product_tmpl_id", "=", T[code]],
                                             ["company_id", "=", CO]])[0]
            ids = [call("mrp.production", "create", {
                "product_id": P[code], "product_qty": 1, "bom_id": bom,
                "origin": origin, "company_id": CO,
                "date_start": day + " 08:00:00"})]
        mo = ids[0]
        st = call("mrp.production", "read", [mo], ["state", "name"])[0]
        if st["state"] == "draft":
            call("mrp.production", "action_confirm", [mo])
        call("mrp.production", "action_assign", [mo])
        lot = _lot(P[code], serial)
        # В Odoo 19 серійний номер випуску - many2many lot_producing_ids
        call("mrp.production", "write", [mo], {"lot_producing_ids": [(6, 0, [lot])],
                                               "qty_producing": 1})
        serials[origin] = (serial, lot)
        st = call("mrp.production", "read", [mo], ["state", "name", "workorder_ids"])[0]
        if not close:
            open_ += 1
            raws = call("stock.move", "read",
                        call("mrp.production", "read", [mo], ["move_raw_ids"])[0]["move_raw_ids"],
                        ["state"])
            ok = sum(1 for r in raws if r["state"] in ("assigned", "partially_available"))
            say(f"   {origin}: {st['name']} у роботі ({st['state']}), "
                f"зарезервовано {ok} з {len(raws)} рядків, нарядів {len(st['workorder_ids'])}.")
            continue
        if st["state"] == "done":
            continue
        for wo in st["workorder_ids"]:
            for method in ("button_start", "button_finish"):
                try:
                    call("mrp.workorder", method, [wo])
                except RpcError as e:
                    say(f"   наряд {wo}.{method}: {str(e)[:120]}")
        try:
            res = call("mrp.production", "button_mark_done", [mo],
                       context={"skip_consumption": True, "skip_immediate": True,
                                "force_period_date": day})
            if isinstance(res, dict) and res.get("res_model"):
                c = dict(res.get("context") or {}, skip_consumption=True)
                wiz = call(res["res_model"], "create", {}, context=c)
                for method in ("process", "action_confirm", "action_done"):
                    try:
                        call(res["res_model"], method, [wiz], context=c)
                        break
                    except RpcError:
                        continue
        except RpcError as e:
            say(f"   {origin}: {str(e)[:220]}")
            continue
        call("mrp.production", "write", [mo], {"date_finished": day + " 16:00:00"})
        done += 1
    total_done = call("mrp.production", "search_count",
                      [["company_id", "=", CO], ["state", "=", "done"]])
    say(f"Виробництво: {len(MOS)} замовлень, закрито цього прогону {done}, "
        f"усього закритих {total_done}, у роботі {open_}; "
        f"серійні номери {', '.join(s for s, _ in serials.values())}.")
    return serials


# =====================================================================================
# 7. Продажі і відвантаження
# =====================================================================================
SALES = [
    ("АС-ЗМ-2026-01", "AERO-C01", "2026-09-08", [("FPV7", 2)], "vat", "2026-09-12"),
    ("АС-ЗМ-2026-02", "AERO-C02", "2026-09-15", [("FPV10", 1)], "exempt", "2026-09-18"),
]


def sales(PR, P, tx):
    price_of = dict((d[0], d[2]) for d in DRONES)
    out = []
    for ref, cust, day, lines, mode, ship in SALES:
        ids = call("sale.order", "search", [["client_order_ref", "=", ref]])
        tax = tx["exempt0"] if mode == "exempt" else tx["sale20"]
        if not ids:
            ids = [call("sale.order", "create", {
                "partner_id": PR[cust], "client_order_ref": ref, "company_id": CO,
                "date_order": day + " 10:00:00",
                "order_line": [(0, 0, {
                    "product_id": P[c], "product_uom_qty": q,
                    "price_unit": price_of[c],
                    "tax_ids": [(6, 0, [tax])] if tax else [(5, 0, 0)]})
                    for c, q in lines]})]
        so = ids[0]
        if call("sale.order", "read", [so], ["state"])[0]["state"] in ("draft", "sent"):
            call("sale.order", "action_confirm", [so])
        st = call("sale.order", "read", [so], ["picking_ids", "name", "amount_total",
                                               "invoice_ids"])[0]
        for pid in st["picking_ids"]:
            _assign(pid)
            _validate_picking(pid, ship)
        if not st["invoice_ids"]:
            try:
                inv = call("sale.advance.payment.inv", "create",
                           {"advance_payment_method": "delivered"},
                           context={"active_model": "sale.order", "active_ids": [so],
                                    "active_id": so})
                call("sale.advance.payment.inv", "create_invoices", [inv],
                     context={"active_model": "sale.order", "active_ids": [so],
                              "active_id": so})
            except RpcError as e:
                say(f"   {ref}: рахунок не створився ({str(e)[:140]})")
        st = call("sale.order", "read", [so], ["invoice_ids", "name", "amount_total"])[0]
        for inv in st["invoice_ids"]:
            m = call("account.move", "read", [inv], ["state"])[0]
            if m["state"] == "draft":
                call("account.move", "write", [inv],
                     {"invoice_date": ship, "date": ship,
                      "ref": "Видаткова накладна " + ref})
                call("account.move", "action_post", [inv])
        out.append((ref, st["name"], st["amount_total"], mode))
    say("Продажі: " + "; ".join(
        f"{r} {n} на {a:,.2f} грн ({'ПДВ 20 %' if m == 'vat' else 'пільга 0 % (ЗСУ)'})"
        for r, n, a, m in out) + " - відвантажено і виставлено рахунки.")
    return out


# =====================================================================================
# 8. Протоколи ВТК на кожен виріб
# =====================================================================================
def quality(P, serials):
    made = 0
    for origin, code, serial, day, close in MOS:
        if not close:
            continue
        got = serials.get(origin)
        if not got:
            continue
        note = f"Виріб {serial} за {origin}"
        ids = call("ua.quality.protocol", "search", [["note", "=", note]])
        if not ids:
            ids = [call("ua.quality.protocol", "create", {
                "company_id": CO, "date": day, "product_id": P[code],
                "lot_id": got[1], "quantity": 1.0,
                "inspector": "Інженер ВТК Гнатів Роман Петрович", "note": note})]
            call("ua.quality.protocol", "action_fill_checklist", ids)
            call("ua.quality.protocol", "action_pass", ids)
            made += 1
    total = call("ua.quality.protocol", "search_count", [["company_id", "=", CO]])
    say(f"Протоколи ВТК: {made} нових, усього {total} - по одному на кожен готовий виріб, "
        f"із серійним номером.")
    return total


# =====================================================================================
# 9. Складальне креслення
# =====================================================================================
def drawing(T):
    if not os.path.exists(DRAWING):
        say(f"УВАГА: креслення {DRAWING} немає.")
        return None
    raw = open(DRAWING, "rb").read()
    data = base64.b64encode(raw).decode()
    ids = sorted(set(re.findall(r'id="(pos-\d+|bom-\d+)"', raw.decode("utf-8"))))
    tmpl = T["FPV7"]
    if has_field("product.template", "ua_drawing_svg"):
        vals = {"ua_drawing_svg": data}
        if has_field("product.template", "ua_drawing_name"):
            vals["ua_drawing_name"] = "drawing.svg"
        call("product.template", "write", [tmpl], vals)
        where = "поле ua_drawing_svg на product.template"
    else:
        upsert("ir.attachment",
               [["res_model", "=", "product.template"], ["res_id", "=", tmpl],
                ["name", "=", "drawing.svg"]],
               {"name": "drawing.svg", "res_model": "product.template", "res_id": tmpl,
                "mimetype": "image/svg+xml", "type": "binary", "datas": data,
                "company_id": CO})
        where = "вкладення drawing.svg (поля ua_drawing_svg ще немає)"
    say(f"Креслення «Шершень» 7\": {len(raw):,} байтів, {len([i for i in ids if i.startswith('pos-')])} позицій "
        f"(id pos-1..pos-11 і bom-1..bom-11) -> {where}.")
    return where


# =====================================================================================
# 10. Працівники
# =====================================================================================
# demo_company.py прив'язаний до першої компанії (COMPANY = 1) і переписує їй назву,
# тому кадри «АероСічі» тут свої і менші: працівники без договорів і зарплати -
# рівно стільки, щоб виробничі підрозділи мали людей.
STAFF = [
    ("Гнатів Роман Петрович", "Інженер ВТК", "Виробництво", "male", date(1988, 3, 14)),
    ("Сидорук Марія Василівна", "Директор", "Адміністрація", "female", date(1981, 7, 2)),
    ("Луцик Богдан Ігорович", "Головний бухгалтер", "Адміністрація", "male", date(1985, 11, 9)),
    ("Дзюба Олег Миколайович", "Начальник виробництва", "Виробництво", "male", date(1979, 5, 21)),
    ("Кравчук Ірина Андріївна", "Інженер-конструктор", "Конструкторський відділ", "female", date(1992, 1, 30)),
    ("Мельник Тарас Володимирович", "Інженер-електронник", "Конструкторський відділ", "male", date(1990, 9, 17)),
    ("Бойко Наталія Степанівна", "Монтажниця РЕА", "Виробництво", "female", date(1994, 4, 8)),
    ("Гаврилюк Петро Іванович", "Монтажник РЕА", "Виробництво", "male", date(1996, 12, 3)),
    ("Романів Софія Олегівна", "Складальниця", "Виробництво", "female", date(1997, 6, 25)),
    ("Ткачук Віктор Ярославович", "Складальник", "Виробництво", "male", date(1993, 2, 11)),
    ("Павлів Юрій Романович", "Комірник", "Склад", "male", date(1987, 8, 19)),
    ("Захарчук Оксана Тарасівна", "Менеджер із продажів", "Продажі", "female", date(1991, 10, 5)),
]


def staff():
    depts = {}
    for _n, _j, dept, _s, _b in STAFF:
        if dept not in depts:
            depts[dept] = upsert("hr.department",
                                 [["name", "=", dept], ["company_id", "=", CO]],
                                 {"name": dept, "company_id": CO})
    jobs = {}
    n = 0
    for i, (name, job, dept, sex, born) in enumerate(STAFF, start=1):
        if job not in jobs:
            jobs[job] = upsert("hr.job", [["name", "=", job], ["company_id", "=", CO]],
                               {"name": job, "department_id": depts[dept],
                                "company_id": CO})
        code = rnokpp(born, sex, 500 + i)
        upsert("hr.employee", [["ua_rnokpp", "=", code]], {
            "name": name, "ua_rnokpp": code, "company_id": CO, "sex": sex,
            "birthday": born.isoformat(), "job_id": jobs[job], "job_title": job,
            "department_id": depts[dept], "country_id":
                call0("res.country", "search", [["code", "=", "UA"]])[0]})
        n += 1
    say(f"Працівники: {n} у {len(depts)} підрозділах ("
        + ", ".join(sorted(depts)) + ") - без договорів і зарплати: "
        f"кадровий будівник demo_company.py прив'язаний до першої компанії.")
    return n


# =====================================================================================
# 11. Контрольна таблиця
# =====================================================================================
def _f1():
    d = call0("ir.model.data", "search_read",
              [["module", "=", "l10n_ua_finrep"], ["name", "=", "instance_f1"]],
              fields=["res_id"])
    if not d:
        return {"error": "звіт Ф1 не знайдено"}
    base = d[0]["res_id"]
    label = f"Ф1. Баланс - {COMPANY['name']}"
    # Правило множинності на mis.report.instance читає allowed_company_ids: з однією
    # компанією адміністратор не побачить власної ж копії звіту.
    both = {"allowed_company_ids": sorted({1, CO})}
    ids = call("mis.report.instance", "search", [["name", "=", label]], context=both)
    if not ids:
        try:
            # copy() в Odoo 19 віддає список id, а не один id
            made = call("mis.report.instance", "copy", [base],
                        {"name": label, "company_id": CO}, context=both)
            ids = made if isinstance(made, list) else [made]
        except RpcError as e:
            return {"error": str(e)[:160]}
    try:
        res = call("mis.report.instance", "compute", [ids[0]], context=both)
    except RpcError as e:
        return {"error": str(e)[:160]}
    vals = {}
    for line in res.get("body", []):
        m = re.match(r"^(\d{4})\b", line.get("label") or "")
        cells = line.get("cells") or []
        val = cells[0].get("val") if cells and isinstance(cells[0], dict) else None
        if m:
            vals["r" + m.group(1)] = val
    return vals


def control_table(extra):
    say("")
    say("=" * 96)
    say("КОНТРОЛЬНА ТАБЛИЦЯ: %s" % COMPANY["name"].upper())
    say("=" * 96)
    models = [
        ("res.partner", [["ref", "like", "AERO-"]], "контрагенти"),
        ("product.template", [["default_code", "like", "D"]], "комплектуючі"),
        ("product.template", [["default_code", "like", "FPV"]], "вироби"),
        ("mrp.bom", [["company_id", "=", CO]], "специфікації"),
        ("mrp.bom.line", [["company_id", "=", CO]], "позиції специфікацій"),
        ("mrp.workcenter", [["company_id", "=", CO]], "робочі центри"),
        ("mrp.routing.workcenter", [["company_id", "=", CO]], "операції маршруту"),
        ("mrp.production", [["company_id", "=", CO], ["state", "=", "done"]], "закриті ВЗ"),
        ("mrp.production", [["company_id", "=", CO], ["state", "not in", ["done", "cancel"]]], "незакриті ВЗ"),
        ("mrp.workorder", [["company_id", "=", CO]], "наряди"),
        ("stock.lot", [["company_id", "=", CO]], "партії і серійні номери"),
        ("stock.location", [["company_id", "=", CO], ["usage", "=", "internal"]], "внутрішні локації"),
        ("stock.putaway.rule", [["company_id", "=", CO]], "правила розкладання"),
        ("stock.picking", [["company_id", "=", CO], ["state", "=", "done"]], "проведені переміщення"),
        ("stock.picking", [["company_id", "=", CO], ["state", "in", ["draft", "waiting", "confirmed", "assigned"]]], "відкриті переміщення"),
        ("purchase.order", [["company_id", "=", CO]], "замовлення на закупівлю"),
        ("sale.order", [["company_id", "=", CO]], "замовлення на продаж"),
        ("account.move", [["company_id", "=", CO], ["move_type", "=", "in_invoice"], ["state", "=", "posted"]], "рахунки постачальників"),
        ("account.move", [["company_id", "=", CO], ["move_type", "=", "out_invoice"], ["state", "=", "posted"]], "рахунки клієнтам"),
        ("account.move", [["company_id", "=", CO], ["ua_customs_entry", "=", True]], "проводки митного ПДВ"),
        ("account.move", [["company_id", "=", CO], ["state", "=", "posted"]], "проведені проводки"),
        ("ua.quality.protocol", [["company_id", "=", CO]], "протоколи ВТК"),
        ("hr.employee", [["company_id", "=", CO]], "працівники"),
    ]
    for model, dom, label in models:
        try:
            n = call(model, "search_count", dom)
        except RpcError as e:
            n = f"помилка: {str(e)[:60]}"
        say(f"  {label:<42} {n}")
    say("-" * 96)
    res = call("account.move.line", "read_group",
               [["parent_state", "=", "posted"], ["company_id", "=", CO]],
               ["debit:sum", "credit:sum"], [])
    dt = round(res[0]["debit"], 2) if res and res[0].get("debit") else 0.0
    kt = round(res[0]["credit"], 2) if res and res[0].get("credit") else 0.0
    say(f"  {COMPANY['name']}: Дт {dt:,.2f} = Кт {kt:,.2f} -> "
        f"{'сходиться' if abs(dt - kt) < 0.01 else 'РОЗБІЖНІСТЬ ' + format(dt - kt, ',.2f')}")
    f1 = _f1()
    if f1.get("error"):
        say(f"  Ф1: не порахувалась ({f1['error']})")
    else:
        a, p = f1.get("r1300"), f1.get("r1900")
        if a is None or p is None:
            say(f"  Ф1: немає рядків 1300/1900 ({list(f1)[:6]})")
        else:
            say(f"  Ф1: Актив (1300) {a:,.2f} = Пасив (1900) {p:,.2f} -> "
                f"{'сходиться' if abs(a - p) < 1 else 'РОЗБІЖНІСТЬ ' + format(a - p, ',.2f')}")
    rows = call("stock.warehouse.orderpoint", "search_read", [["company_id", "=", CO]],
                fields=["product_id", "qty_on_hand", "product_min_qty", "qty_to_order"])
    below = [r for r in rows if (r["qty_to_order"] or 0) > 0]
    say(f"  Мінімальні залишки: {len(rows)} правил, нижче мінімуму {len(below)}")
    open_pick = call("stock.picking", "search_read",
                     [["company_id", "=", CO],
                      ["state", "in", ["draft", "waiting", "confirmed", "assigned"]]],
                     fields=["name", "state"])
    open_mo = call("mrp.production", "search_read",
                   [["company_id", "=", CO], ["state", "not in", ["done", "cancel"]]],
                   fields=["name", "state"])
    say(f"  Відкриті операції: переміщень {len(open_pick)} ("
        + ", ".join(f"{p['name']} {p['state']}" for p in open_pick[:6])
        + f"), виробничих замовлень {len(open_mo)} ("
        + ", ".join(f"{m['name']} {m['state']}" for m in open_mo) + ")")
    if extra.get("customs_bill"):
        b = call("account.move", "read", [extra["customs_bill"]],
                 ["name", "ua_customs_vat", "ua_customs_decl_number",
                  "ua_customs_move_id"])[0]
        say(f"  Митний ПДВ: {b['name']}, МД {b['ua_customs_decl_number']}, "
            f"{b['ua_customs_vat']:,.2f} грн, проводка "
            f"{b['ua_customs_move_id'][1] if b['ua_customs_move_id'] else 'НЕМАЄ'}")
    caps, over = extra.get("capacity", (0, 0))
    if caps:
        rows = call("stock.location", "search_read",
                    [["company_id", "=", CO], ["usage", "=", "internal"],
                     ["ua_capacity", ">", 0], ["child_ids", "=", False]],
                    fields=["complete_name", "ua_capacity", "ua_capacity_used"])
        full = [r for r in rows if r["ua_capacity_used"] > r["ua_capacity"]]
        say(f"  Місткість: полиць із заданими місцями {len(rows)}, переповнених "
            f"{len(full)} ("
            + ", ".join(f"{r['complete_name'].split('/')[-1]} {r['ua_capacity_used']}/"
                        f"{r['ua_capacity']}" for r in full) + ")")
    if extra.get("drawing"):
        say(f"  Креслення: {extra['drawing']}")
    say("=" * 96)


# =====================================================================================
# Доступ до другої компанії
# =====================================================================================
# Власних користувачів цей скрипт не заводить: кадри «АероСічі» йдуть без логінів.
# Компанію Odoo сам додає лише тому, хто її створив (адміністраторові) і службовому
# OdooBot - res_company.create лінкує company_ids тільки їм. Тому доступ для решти
# ставимо тут руками, і рівно для того, кому він потрібен.
MEBLI_CO = 1        # перша компанія бази - «Ясен Меблі» (demo_business.py, CO_ID)
LAB_LOGIN = "lab"   # зовнішній тестовий сайт: склад і виробництво в обох компаніях


def lab_access():
    """Користувач lab бачить «Ясен Меблі» і «АероСіч», відкривається в «Меблях».

    Ідемпотентно: перелік задаємо повністю, тож повторний прогін нічого не додає.
    Активний набір компаній у перемикачі сервер не задає - це cookie `cids` у
    браузері; з сервера керуємо лише переліком дозволених і типовою компанією.
    """
    ids = call0("res.users", "search", [["login", "=", LAB_LOGIN]],
                context={"active_test": False})
    if not ids:
        say(f"Користувача {LAB_LOGIN} у базі немає - доступ до «АероСічі» не роздаємо.")
        return
    call0("res.users", "write", ids, {"company_ids": [(6, 0, [MEBLI_CO, CO])],
                                      "company_id": MEBLI_CO})
    say(f"Користувач {LAB_LOGIN}: дозволені «Ясен Меблі» і {COMPANY['name']}, "
        f"типова - «Ясен Меблі».")


# =====================================================================================
def main():
    say("== база %s на %s ==" % (DB, URL))
    ensure_company()
    usd, _eur = currency_rates()
    tx = taxes()
    PR = partners(usd)
    P, T = products(tx)
    WC = workcenters()
    boms(P, T, WC)
    L = warehouse(P)
    staff()
    extra = {"customs_bill": purchases(PR, P, tx, usd)}
    if L:
        spread_to_shelves(P, L, "2026-07-10", "1")
    serials = manufacturing(P, T)
    sales(PR, P, tx)
    quality(P, serials)
    extra["drawing"] = drawing(T)
    if L:
        spread_to_shelves(P, L, "2026-09-20", "2")
    # Місткість - після всіх рухів: вона рахується від того, що лежить на полицях
    extra["capacity"] = capacities(L) if L else (0, 0)
    lab_access()
    control_table(extra)


if __name__ == "__main__":
    main()
