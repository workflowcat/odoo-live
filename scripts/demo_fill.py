#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Показова база: наповнює поля форм, які після demo_show.py лишаються порожніми.

Вхід - demo-out/fill.json (scripts/show_fill.py): поля форми, порожні в усіх записах моделі.
Скрипт дописує значення там, де справжня українська компанія їх мала б, для всіх трьох
компаній бази: «Ясен Меблі», «Ясен Логістика», «АероСіч».

Що робить:
  1. Довідники: області України, умови оплати, мітки контрагентів, товарів і продажів.
  2. Банки і банківські рахунки: SWIFT, адреса, телефон, банк рахунку за МФО з IBAN.
  3. Контрагенти: область, мітки, галузь, умови і способи оплати, кредитний ліміт, контактні
     особи, дані ЄДР (записані напряму, ніби отримані раніше; сам ЄДР не викликається).
  4. Компанії: рахунки бюджету (ПДФО, ВЗ, ЄСВ), керівник, бухгалтер, коди ДПІ.
  5. Основні засоби: групи ОЗ, реквізити наявних об'єктів, нові об'єкти з таблицями амортизації.
  6. Товари, прайси постачальників, специфікації, робочі центри, партії.
  7. Замовлення покупців і постачальникам, нагоди, рахунки.
  8. Решта: підключення банку, KYC, запити на закупівлю, способи платежу, штатний розпис.

Правила:
  - пише тільки в порожні поля: чужі значення не перезаписує, ідентифікатори не змінює;
  - ідемпотентно: кожен новий запис шукається за стійким ключем (код, ref, назва);
  - у закриті періоди нічого не проводить. Старі основні засоби заходять початковим
    залишком першим відкритим днем (Дт 10х / Кт 13х / Кт 441), амортизація до цього дня -
    рядки «початковий залишок» без проводок;
  - кадри і зарплату не чіпає (це зона demo_company.py);
  - лише JSON-RPC: сервер не перезапускає, зовнішніх служб не кличе.

Запуск (після demo_show.py):
    DEMO_DB=show ODOO_URL=http://127.0.0.1:8133 python3 scripts/demo_fill.py
    FILL_STEPS=assets,partners python3 scripts/demo_fill.py      (лише названі кроки)
"""
import json
import os
import re
import sys
import urllib.request
from collections import OrderedDict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8133").rstrip("/")
DB = os.environ.get("DEMO_DB", "show").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
ONLY = [s for s in os.environ.get("FILL_STEPS", "").split(",") if s]
BOOKS_START = "2026-07-01"     # перший день обліку в базі, якщо дати блокування немає
POST_UNTIL = "2026-09-30"      # амортизацію проводимо по цей день, як demo_business.py

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

# Компанії шукаємо за кодом ЄДРПОУ, а не за id: на перезібраній базі id можуть бути інші.
CODES = {"mebli": "43812071", "logist": "44772035", "aero": "45128067"}
_rows = rpc("object", "execute_kw", DB, UID, PW, "res.company", "search_read", [[]],
            {"fields": ["name", "company_registry", "partner_id", "fiscalyear_lock_date"]})
CO = {key: next((r for r in _rows if r["company_registry"] == code), None) for key, code in CODES.items()}
if not CO["mebli"]:
    sys.exit("Немає компанії «Ясен Меблі» - спершу scripts/demo_business.py")
ALL = [CO[k]["id"] for k in ("mebli", "logist", "aero") if CO[k]]
MEBLI = CO["mebli"]["id"]
LOGIST = CO["logist"] and CO["logist"]["id"]
AERO = CO["aero"] and CO["aero"]["id"]


def call(model, method, *a, co=0, **kw):
    """co=0 - усі компанії (спільні записи), co=id - від імені однієї компанії."""
    companies = [co] if co else ALL
    kw["context"] = dict({"allowed_company_ids": companies, "lang": "uk_UA"}, **(kw.get("context") or {}))
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def say(msg):
    print(msg, flush=True)


# ---- облік зробленого: модель -> записи, поля, скільки записів змінено цим прогоном ----
STAT = OrderedDict()
REFUSED = []        # (модель, поле, що відповів сервер)
_MODELS = {}
_FIELDS = {}


def has_model(model):
    if model not in _MODELS:
        _MODELS[model] = bool(call("ir.model", "search_count", [["model", "=", model]]))
    return _MODELS[model]


def fields_of(model):
    if model not in _FIELDS:
        _FIELDS[model] = call(model, "fields_get", [], attributes=["type"])
    return _FIELDS[model]


def stat(model):
    return STAT.setdefault(model, {"ids": set(), "fields": set(), "changed": 0, "new": 0})


def is_empty(value):
    if value in (False, None, "", 0, 0.0, []):
        return True
    if isinstance(value, str):
        return not re.sub(r"<[^>]+>|&nbsp;|\s", "", value)
    return False


def safe_write(model, ids, vals, co=0, context=None):
    """Запис; якщо сервер відмовив - по одному полю, відмови збираємо у REFUSED."""
    try:
        call(model, "write", ids, vals, co=co, context=context)
        return True
    except RpcError as first:
        if len(vals) == 1:
            REFUSED.append((model, next(iter(vals)), str(first).splitlines()[0][:160]))
            return False
    done = False
    for key, value in vals.items():
        try:
            call(model, "write", ids, {key: value}, co=co, context=context)
            done = True
        except RpcError as e:
            REFUSED.append((model, key, str(e).splitlines()[0][:160]))
    return done


def fill(model, wanted, co=0, context=None):
    """wanted: {id: {поле: значення}}. Пишемо лише в порожні поля - тому повторний прогін
    нічого не змінює, а значення інших будівників лишаються як є."""
    wanted = {rid: {k: v for k, v in vals.items() if k in fields_of(model) and not is_empty(v)}
              for rid, vals in wanted.items() if rid}
    wanted = {rid: vals for rid, vals in wanted.items() if vals}
    if not wanted:
        return []
    st = stat(model)
    names = sorted({k for vals in wanted.values() for k in vals})
    ctx = dict({"active_test": False}, **(context or {}))
    current = {r["id"]: r for r in call(model, "read", list(wanted), names, co=co, context=ctx)}
    changed = []
    for rid, vals in wanted.items():
        st["ids"].add(rid)
        st["fields"].update(vals)
        todo = {k: v for k, v in vals.items() if is_empty(current[rid].get(k))}
        if todo and safe_write(model, [rid], todo, co=co, context=context):
            changed.append(rid)
    st["changed"] += len(changed)
    return changed


def ensure(model, domain, vals, co=0, context=None):
    """Знайти запис за ключем або створити. Наявний не переписуємо."""
    ctx = dict({"active_test": False}, **(context or {}))
    ids = call(model, "search", domain, co=co, context=ctx, limit=1)
    if ids:
        return ids[0]
    rid = call(model, "create", vals, co=co, context=context)
    rid = rid[0] if isinstance(rid, list) else rid
    st = stat(model)
    st["new"] += 1
    st["ids"].add(rid)
    st["fields"].update(vals)
    return rid


def m2m(ids):
    return [(6, 0, [i for i in ids if i])]


def html(text):
    return "".join("<p>%s</p>" % line for line in text.split("\n"))


# ---- коди з контрольними числами (ті самі правила, що в scripts/demo_business.py) ----
def edrpou(base7):
    d = [int(c) for c in base7]
    n = int(base7) * 10
    w = [7, 1, 2, 3, 4, 5, 6] if 30000000 <= n <= 60000000 else [1, 2, 3, 4, 5, 6, 7]
    c = sum(a * b for a, b in zip(d, w)) % 11
    if c == 10:
        c = sum(a * (b + 2) for a, b in zip(d, w)) % 11
        c = 0 if c == 10 else c
    return base7 + str(c)


def iban_ua(mfo, acc19):
    bban = f"{mfo}{acc19}"
    num = "".join(str(int(ch, 36)) for ch in bban + "UA00")
    return f"UA{98 - int(num) % 97:02d}{bban}"


def ean13(body12):
    digits = [int(c) for c in body12]
    check = (10 - (sum(digits[0::2]) + 3 * sum(digits[1::2])) % 10) % 10
    return body12 + str(check)


def account(code, co):
    """Рахунок за кодом у компанії: код рахунку в Odoo 19 залежить від компанії."""
    ids = call("account.account", "search", [["code", "=", code]], co=co, limit=1)
    return ids[0] if ids else False


def day_after(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def partner_by_ref(ref):
    ids = call("res.partner", "search", [["ref", "=", ref]], context={"active_test": False}, limit=1)
    return ids[0] if ids else False


# =====================================================================================
# 1. Довідники
# =====================================================================================
# Код області - ISO 3166-2:UA. У базі Odoo областей України немає зовсім.
STATES = [("05", "Вінницька область"), ("07", "Волинська область"), ("09", "Луганська область"),
          ("12", "Дніпропетровська область"), ("14", "Донецька область"), ("18", "Житомирська область"),
          ("21", "Закарпатська область"), ("23", "Запорізька область"), ("26", "Івано-Франківська область"),
          ("30", "м. Київ"), ("32", "Київська область"), ("35", "Кіровоградська область"),
          ("40", "м. Севастополь"), ("43", "Автономна Республіка Крим"), ("46", "Львівська область"),
          ("48", "Миколаївська область"), ("51", "Одеська область"), ("53", "Полтавська область"),
          ("56", "Рівненська область"), ("59", "Сумська область"), ("61", "Тернопільська область"),
          ("63", "Харківська область"), ("65", "Херсонська область"), ("68", "Хмельницька область"),
          ("71", "Черкаська область"), ("74", "Чернівецька область"), ("77", "Чернігівська область")]
CITY_STATE = {"Львів": "46", "Сокільники": "46", "Київ": "30", "Одеса": "51", "Харків": "63",
              "Дніпро": "12", "Яремче": "26", "Надвірна": "26", "Тернопіль": "61", "Вінниця": "05",
              "Полтава": "53", "Рівне": "56", "Черкаси": "71", "Бровари": "32", "Стрий": "46"}
# ключ -> (назва, [(відсоток, днів)])
TERMS = {
    "pre100": ("Передоплата 100 %", [(100.0, 0)]),
    "d14": ("Відстрочка 14 днів", [(100.0, 14)]),
    "d30": ("Відстрочка 30 днів", [(100.0, 30)]),
    "p50": ("Передоплата 50 %, решта протягом 14 днів після поставки", [(50.0, 0), (50.0, 14)]),
}
PARTNER_TAGS = ["Покупець", "Постачальник", "Дилер", "Роздріб", "Проєктний замовник", "Експорт", "Імпорт",
                "Перевізник", "Банк", "Орендодавець", "Комунальні послуги", "Підрядник", "Державний орган",
                "Державний замовник", "Благодійний фонд", "Група компаній", "Обладнання і сервіс"]
TAG_PARENTS = {"Покупець": ["Дилер", "Роздріб", "Проєктний замовник", "Експорт", "Державний замовник", "Благодійний фонд"],
               "Постачальник": ["Імпорт", "Перевізник", "Орендодавець", "Комунальні послуги", "Підрядник", "Обладнання і сервіс"]}
SALE_TAGS = ["Дилер", "Роздріб", "Проєкт", "Експорт", "Держзамовлення", "Благодійний фонд", "Тендер", "Повторний покупець"]
SOURCES = ["Сайт компанії", "Рекомендація клієнта", "Виставка «Меблі Експо»", "Холодний дзвінок",
           "Тендерний майданчик", "Повторне звернення"]
REF = {}


def references():
    ua = call("res.country", "search", [["code", "=", "UA"]])[0]
    REF["ua"] = ua
    REF["state"] = {}
    for code, name in STATES:
        REF["state"][code] = ensure("res.country.state", [["country_id", "=", ua], ["code", "=", code]],
                                    {"country_id": ua, "code": code, "name": name})
    REF["term"] = {}
    for key, (name, lines) in TERMS.items():
        REF["term"][key] = ensure("account.payment.term", [["name", "=", name]], {
            "name": name, "note": html(name),
            "line_ids": [(0, 0, {"value": "percent", "value_amount": pct, "delay_type": "days_after",
                                 "nb_days": days}) for pct, days in lines]})
    REF["ptag"] = {n: ensure("res.partner.category", [["name", "=", n]], {"name": n}) for n in PARTNER_TAGS}
    # Дерево міток: уточнення лежать під «Покупець» і «Постачальник».
    fill("res.partner.category", dict(
        [(REF["ptag"][n], {"parent_id": REF["ptag"]["Покупець"]}) for n in TAG_PARENTS["Покупець"]]
        + [(REF["ptag"][n], {"parent_id": REF["ptag"]["Постачальник"]}) for n in TAG_PARENTS["Постачальник"]]))
    REF["stag"] = {n: ensure("crm.tag", [["name", "=", n]], {"name": n}) for n in SALE_TAGS}
    REF["source"] = {n: ensure("utm.source", [["name", "=", n]], {"name": n}) for n in SOURCES}
    REF["industry"] = {r["name"]: r["id"] for r in call("res.partner.industry", "search_read", [], fields=["name"])}
    REF["incoterm"] = {r["code"]: r["id"] for r in call("account.incoterms", "search_read", [], fields=["code"])}
    REF["uah"] = call("res.currency", "search", [["name", "=", "UAH"]])[0]
    REF["admin"] = UID
    buyer = call("res.users", "search", [["login", "=", "zakupivli"]])
    REF["buyer"] = buyer[0] if buyer else UID
    say(f"1. Довідники: областей {len(STATES)}, умов оплати {len(TERMS)}, міток контрагентів {len(PARTNER_TAGS)}, "
        f"міток продажів {len(SALE_TAGS)}, джерел {len(SOURCES)}.")


# =====================================================================================
# 2. Банки і банківські рахунки
# =====================================================================================
# МФО -> (назва, SWIFT, вулиця, місто, індекс, код області, телефон). Адреси і телефони гарячих
# ліній - загальновідомі відкриті дані банків. E-mail не вписуємо: без звірки з джерелом не вгадуємо.
BANKS = {
    "305299": ("АТ КБ «ПриватБанк»", "PBANUA2X", "вул. Набережна Перемоги, 50", "Дніпро", "49094", "12", "3700"),
    "300465": ("АТ «Ощадбанк»", "COSBUAUK", "вул. Госпітальна, 12Г", "Київ", "01001", "30", "0 800 210 800"),
    "322001": ("АТ «Універсал Банк» (monobank)", "UNJSUAUK", "вул. Автозаводська, 54/19", "Київ", "04114", "30", "0 800 205 205"),
    "351005": ("АТ «УкрСиббанк»", "KHABUA2K", "вул. Андріївська, 2/12", "Київ", "04070", "30", "0 800 505 800"),
}


def banks():
    by_mfo = {}
    wanted = {}
    for mfo, (name, bic, street, city, zipc, state, phone) in BANKS.items():
        bid = ensure("res.bank", [["ua_mfo", "=", mfo]], {"name": name, "ua_mfo": mfo, "country": REF["ua"]})
        by_mfo[mfo] = bid
        wanted[bid] = {"bic": bic, "street": street, "city": city, "zip": zipc,
                       "state": REF["state"][state], "country": REF["ua"], "phone": phone}
    fill("res.bank", wanted)
    REF["bank"] = by_mfo
    # Власні рахунки компаній групи, яких у базі ще немає: без них у рахунку-фактурі порожні реквізити.
    for key, mfo, serial in (("logist", "305299", 5044772035), ("aero", "300465", 5045128067)):
        if not CO[key]:
            continue
        pid = CO[key]["partner_id"][0]
        if not call("res.partner.bank", "search_count", [["partner_id", "=", pid]], context={"active_test": False}):
            acc = iban_ua(mfo, f"000002600{serial:010d}")
            bank_acc = ensure("res.partner.bank", [["acc_number", "=", acc]],
                              {"acc_number": acc, "partner_id": pid, "bank_id": by_mfo[mfo],
                               "acc_holder_name": CO[key]["name"], "allow_out_payment": True})
            journal = call("account.journal", "search", [["type", "=", "bank"], ["company_id", "=", CO[key]["id"]],
                                                         ["bank_account_id", "=", False]], limit=1)
            if journal:
                fill("account.journal", {journal[0]: {"bank_account_id": bank_acc}}, co=CO[key]["id"])
    rows = call("res.partner.bank", "search_read", [], fields=["acc_number", "partner_id", "bank_id"],
                context={"active_test": False})
    own = {CO[k]["partner_id"][0] for k in CO if CO[k]}
    wanted = {}
    for r in rows:
        acc = (r["acc_number"] or "").replace(" ", "")
        mfo = acc[4:10] if acc.startswith("UA") and len(acc) == 29 else ""
        note = ("Основний поточний рахунок у гривні" if r["partner_id"][0] in own
                else "Рахунок із договору, підтверджено листом контрагента")
        if "2620" in acc[10:20]:
            note = "Картковий рахунок для виплати заробітної плати"
        wanted[r["id"]] = {"bank_id": by_mfo.get(mfo), "currency_id": REF["uah"], "note": note}
    fill("res.partner.bank", wanted)
    say(f"2. Банки: {len(BANKS)} (SWIFT, адреса, телефон); банківських рахунків {len(rows)}: банк за МФО, валюта, примітка.")


# =====================================================================================
# 3. Контрагенти
# =====================================================================================
# Нові постачальники обладнання, транспорту і послуг: від них куплено основні засоби.
# (ref, назва, основа ЄДРПОУ, місто, індекс, вулиця, що постачає)
NEW_SUPPLIERS = [
    ("DEMO-S11", "ТОВ «Верстат-Імпорт»", "4026731", "Львів", "79035", "вул. Зелена, 238", "деревообробне обладнання і сервіс"),
    ("DEMO-S12", "ТОВ «Автоцентр Захід»", "3697415", "Львів", "79040", "вул. Городоцька, 355", "автомобілі і сервіс"),
    ("DEMO-S13", "ТОВ «Технополіс ІТ»", "4183920", "Львів", "79008", "вул. Личаківська, 55", "комп'ютерна техніка і програми"),
    ("DEMO-S14", "ТОВ «Західбудмонтаж»", "3851276", "Львів", "79024", "вул. Промислова, 50", "будівельно-монтажні роботи"),
    ("DEMO-S15", "ТОВ «Складська техніка Україна»", "3940718", "Київ", "03680", "вул. Кільцева дорога, 12", "навантажувачі і стелажі"),
    ("DEMO-S16", "ТОВ «Патентне бюро «Знак»", "4350682", "Київ", "01030", "вул. Богдана Хмельницького, 32", "реєстрація торговельних марок"),
]

# ref -> картка. kved, reg, cap, head - дані ЄДР (вигадані, але за формою справжні).
# ct / st - умови оплати покупця / постачальника; limit - кредитний ліміт; contact - (ПІБ, посада).
P = {
    "DEMO-C01": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Дилер"], reg="2003-03-18", cap=850000.0,
                     kved="47.59 Роздрібна торгівля меблями, освітлювальним приладдям та іншими товарами для дому в спеціалізованих магазинах",
                     head="Савицький Орест Михайлович", contact=("Гураль Ірина Степанівна", "Менеджерка із закупівель"),
                     ct="d30", limit=500000.0, street2="2 поверх, салон меблів", web="https://demo-c01.example.ua"),
    "DEMO-C02": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Роздріб"], reg="2013-05-22", cap=300000.0,
                     kved="47.59 Роздрібна торгівля меблями, освітлювальним приладдям та іншими товарами для дому в спеціалізованих магазинах",
                     head="Литвиненко Олена Вікторівна", contact=("Мазур Денис Олегович", "Керівник салону"),
                     ct="d14", street2="ТЦ «Ocean Plaza», 3 поверх", web="https://demo-c02.example.ua"),
    "DEMO-C03": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Роздріб"], reg="2017-03-09", cap=120000.0,
                     kved="47.59 Роздрібна торгівля меблями, освітлювальним приладдям та іншими товарами для дому в спеціалізованих магазинах",
                     head="Ткаченко Сергій Анатолійович", contact=("Павленко Аліна Юріївна", "Менеджерка із закупівель"), ct="d14"),
    "DEMO-C04": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Проєктний замовник"], reg="2009-06-11", cap=450000.0,
                     kved="46.65 Оптова торгівля офісними меблями",
                     head="Руденко Олександр Іванович", contact=("Шаповал Катерина Сергіївна", "Провідна фахівчиня з постачання"),
                     ct="d14", limit=250000.0, street2="офіс 407"),
    "DEMO-C05": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Дилер"], reg="2015-08-04", cap=600000.0,
                     kved="46.47 Оптова торгівля меблями, килимами й освітлювальним приладдям",
                     head="Кравець Дмитро Валерійович", contact=("Остапенко Юлія Миколаївна", "Категорійна менеджерка"),
                     ct="d30", limit=400000.0, web="https://demo-c05.example.ua"),
    "DEMO-C06": dict(ind="Харчування/Гостинність", tags=["Покупець", "Проєктний замовник"], reg="2019-01-23", cap=2400000.0,
                     kved="55.10 Діяльність готелів і подібних засобів тимчасового розміщування",
                     head="Палійчук Василь Дмитрович", contact=("Григорчук Марія Іванівна", "Керуюча готелем"), ct="p50"),
    "DEMO-C07": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Державний замовник"], reg="2007-04-12", cap=200000.0,
                     kved="46.49 Оптова торгівля іншими товарами господарського призначення",
                     head="Присяжнюк Галина Петрівна", contact=("Заяць Роман Ігорович", "Менеджер тендерного відділу"),
                     ct="d30", limit=300000.0),
    "DEMO-C08": dict(ind="Виробництво", tags=["Покупець", "Роздріб"], reg="2016-02-11", ct="pre100",
                     kved="31.02 Виробництво кухонних меблів"),
    "DEMO-C09": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Роздріб"], reg="2018-09-03", ct="pre100",
                     kved="47.59 Роздрібна торгівля меблями, освітлювальним приладдям та іншими товарами для дому в спеціалізованих магазинах"),
    "DEMO-C10": dict(ind="Інші послуги", tags=["Покупець", "Роздріб"], reg="2014-06-17", ct="pre100",
                     kved="43.32 Установлення столярних виробів"),
    "DEMO-C11": dict(ind="Інші послуги", tags=["Покупець", "Проєктний замовник"], reg="2020-10-06", ct="pre100",
                     kved="74.10 Спеціалізована діяльність із дизайну", street2="студія 3"),
    "DEMO-C12": dict(ind="Оптова/роздрібна торгівля", tags=["Покупець", "Експорт"], ct="d30", foreign=True,
                     contact=("Katarzyna Wiśniewska", "Specjalista ds. zakupów"), web="https://drewno.example.pl"),
    "DEMO-S01": dict(ind="Виробництво", tags=["Постачальник"], reg="2004-11-02", cap=1200000.0,
                     kved="16.10 Лісопильне та стругальне виробництво",
                     head="Попович Іван Васильович", contact=("Семенюк Надія Михайлівна", "Менеджерка зі збуту"), st="d14"),
    "DEMO-S02": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник"], reg="2010-12-14", cap=900000.0,
                     kved="46.73 Оптова торгівля деревиною, будівельними матеріалами",
                     head="Вовк Андрій Романович", contact=("Кіндрат Оксана Любомирівна", "Менеджерка з продажу"),
                     st="d30", street2="склад 4", web="https://demo-s02.example.ua"),
    "DEMO-S03": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник"], reg="2015-05-27", cap=350000.0,
                     kved="46.74 Оптова торгівля залізними виробами, водопровідним і опалювальним устаткованням і приладдям до нього",
                     head="Бондар Максим Олександрович", contact=("Зінченко Тетяна Григорівна", "Менеджерка по роботі з клієнтами"), st="d14"),
    "DEMO-S04": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник"], reg="2016-06-08", cap=250000.0,
                     kved="46.41 Оптова торгівля текстильними товарами",
                     head="Яковенко Віктор Петрович", contact=("Черненко Людмила Іванівна", "Менеджерка зі збуту"), st="d14",
                     checks="? Зміна керівника: у 2026 році змінено керівника, запис у реєстрі від 2026-03-02"),
    "DEMO-S05": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник"], reg="2008-11-19", cap=500000.0,
                     kved="46.75 Оптова торгівля хімічними продуктами",
                     head="Гончаренко Павло Сергійович", contact=("Мороз Ірина Олексіївна", "Технолог-консультант"), st="pre100"),
    "DEMO-S06": dict(ind="Енергопостачання", tags=["Постачальник", "Комунальні послуги"], reg="1995-08-25", real=True,
                     kved="35.13 Розподілення електроенергії", st="d14",
                     contact=("Відділ обслуговування юридичних споживачів", "")),
    "DEMO-S07": dict(ind="Нерухомість", tags=["Постачальник", "Орендодавець"], reg="2018-01-30", cap=5000000.0,
                     kved="68.20 Надання в оренду й експлуатацію власного чи орендованого нерухомого майна",
                     head="Білецький Юрій Богданович", contact=("Сорока Наталія Ярославівна", "Адміністраторка об'єкта"),
                     st="pre100", street2="адміністративний корпус, каб. 12"),
    "DEMO-S08": dict(ind="Транспорт/Логістика", tags=["Постачальник", "Перевізник"], reg="2013-02-07", cap=400000.0,
                     kved="49.41 Вантажний автомобільний транспорт",
                     head="Петрів Микола Степанович", contact=("Баран Олег Ігорович", "Диспетчер"), st="d14"),
    "DEMO-S09": dict(ind="Інші послуги", tags=["Постачальник", "Підрядник"], reg="2011-04-05", st="d14",
                     kved="33.12 Ремонт і технічне обслуговування машин і устатковання промислового призначення"),
    "DEMO-S10": dict(ind="Фінанси/Страхування", tags=["Банк"], reg="1992-03-19", real=True,
                     kved="64.19 Інші види грошового посередництва", st="d14",
                     contact=("Відділення обслуговування корпоративних клієнтів", "")),
    "DEMO-S11": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник", "Обладнання і сервіс"], reg="2016-02-24", cap=1000000.0,
                     kved="46.62 Оптова торгівля верстатами",
                     head="Кузьмич Володимир Орестович", contact=("Лесів Назар Андрійович", "Сервісний інженер"), st="p50"),
    "DEMO-S12": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник", "Обладнання і сервіс"], reg="2009-10-13", cap=3000000.0,
                     kved="45.11 Торгівля автомобілями та легковими автотранспортними засобами",
                     head="Федишин Ростислав Ігорович", contact=("Матвіїв Христина Романівна", "Менеджерка корпоративних продажів"), st="pre100"),
    "DEMO-S13": dict(ind="IT/Зв'язок", tags=["Постачальник", "Обладнання і сервіс"], reg="2018-03-06", cap=200000.0,
                     kved="46.51 Оптова торгівля комп'ютерами, периферійним устаткованням і програмним забезпеченням",
                     head="Якимів Тарас Олегович", contact=("Демчук Вікторія Сергіївна", "Акаунт-менеджерка"), st="d14",
                     street2="офіс 21"),
    "DEMO-S14": dict(ind="Створення", tags=["Постачальник", "Підрядник"], reg="2013-01-22", cap=750000.0,
                     kved="43.21 Електромонтажні роботи",
                     head="Луців Ігор Мирославович", contact=("Гладкий Петро Васильович", "Виконроб"), st="p50"),
    "DEMO-S15": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник", "Обладнання і сервіс"], reg="2015-03-17", cap=1500000.0,
                     kved="46.69 Оптова торгівля іншими машинами й устаткованням",
                     head="Шевченко Артем Вікторович", contact=("Коломієць Богдан Юрійович", "Менеджер з продажу техніки"), st="p50"),
    "DEMO-S16": dict(ind="Інші послуги", tags=["Постачальник", "Підрядник"], reg="2020-07-14", cap=50000.0,
                     kved="69.10 Діяльність у сфері права",
                     head="Косенко Лариса Анатоліївна", st="pre100", street2="офіс 5"),
    "DEMO-DPS": dict(ind="Публічне адміністрування", tags=["Державний орган"], reg="2020-10-27", real=True,
                     kved="84.11 Державне управління загального характеру",
                     address=("вул. Стрийська, 35", "79003")),
    "AERO-C01": dict(ind="Інші послуги", tags=["Покупець", "Проєктний замовник"], reg="2014-03-20", cap=1000000.0,
                     kved="80.10 Діяльність приватних охоронних служб", co="aero",
                     head="Мельниченко Євген Олександрович",
                     contact=("Тимошенко Анна Валеріївна", "Начальниця відділу технічних засобів охорони"), ct="d14",
                     street2="офіс 310", phone="+380 44 390 21 47", email="aero-c01@example.ua"),
    "AERO-C02": dict(ind="Публічне адміністрування", tags=["Покупець", "Державний замовник"], reg="1998-06-10", real=True,
                     kved="84.22 Діяльність у сфері оборони", co="aero", ct="d30"),
    "AERO-C03": dict(ind="Інші послуги", tags=["Покупець", "Благодійний фонд"], reg="2021-03-30", co="aero",
                     kved="88.99 Надання іншої соціальної допомоги без забезпечення проживання, н.в.і.у.",
                     head="Іванишин Соломія Тарасівна", contact=("Гавриш Остап Миколайович", "Координатор закупівель"),
                     ct="pre100", phone="+380 32 255 40 18", email="aero-c03@example.ua"),
    "AERO-S01": dict(ind="Виробництво", tags=["Постачальник"], reg="2010-04-21", cap=600000.0, co="aero",
                     kved="17.21 Виробництво гофрованого паперу та картону, паперової та картонної тари",
                     head="Дудка Степан Ярославович", contact=("Процик Мар'яна Іванівна", "Менеджерка з продажу"), st="d14",
                     phone="+380 32 244 71 30", email="aero-s01@example.ua"),
    "AERO-S02": dict(ind="Оптова/роздрібна торгівля", tags=["Постачальник"], reg="2004-09-16", cap=800000.0, co="aero",
                     kved="46.52 Оптова торгівля електронним і телекомунікаційним устаткованням, деталями до нього",
                     head="Нестеренко Ігор Леонідович", contact=("Васильченко Олег Петрович", "Інженер з продажу"), st="d14",
                     phone="+380 44 501 62 09", email="aero-s02@example.ua", street2="корпус 7"),
    "AERO-S90": dict(ind="Виробництво", tags=["Постачальник", "Імпорт"], foreign=True, co="aero", st="pre100",
                     contact=("Li Wei", "Sales Manager"), email="sales@skyparts.example.cn", currency="USD",
                     web="https://skyparts.example.cn"),
}
# Самі компанії групи як контрагенти: ключ словника CO -> дані ЄДР.
OWN = {
    "mebli": dict(ind="Виробництво", tags=["Група компаній"], reg="2015-01-20", cap=1500000.0,
                  kved="31.09 Виробництво інших меблів", head="Гаврилюк Богдан Тарасович"),
    "logist": dict(ind="Транспорт/Логістика", tags=["Група компаній", "Перевізник"], reg="2021-09-14", cap=500000.0,
                   kved="49.41 Вантажний автомобільний транспорт", head="Крамар Володимир Зіновійович",
                   phone="+380 32 245 10 27", web="https://yasen-logistyka.example"),
    "aero": dict(ind="Виробництво", tags=["Група компаній"], reg="2023-02-15", cap=2000000.0,
                 kved="30.30 Виробництво повітряних і космічних літальних апаратів, супутнього устатковання",
                 head="Сидорук Марія Василівна", web="https://aerosich.example.ua"),
}
EDR_SYNCED = "2026-09-15 07:12:00"      # UTC; «оновлено з ЄДР» одним днем, як після планового оновлення
FORMS = [("ТОВ ", "ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "), ("ПАТ ", "ПУБЛІЧНЕ АКЦІОНЕРНЕ ТОВАРИСТВО "),
         ("АТ КБ ", "АКЦІОНЕРНЕ ТОВАРИСТВО КОМЕРЦІЙНИЙ БАНК "), ("БФ ", "БЛАГОДІЙНА ОРГАНІЗАЦІЯ «БЛАГОДІЙНИЙ ФОНД "),
         ("ГУ ДПС ", "ГОЛОВНЕ УПРАВЛІННЯ ДПС "), ("ФОП ", "")]


def full_name(name):
    """Повна назва, як її пише ЄДР: форма власності словами, усе великими літерами."""
    for short, long in FORMS:
        if name.startswith(short):
            rest = name[len(short):].upper()
            return (long + rest + ("»" if short == "БФ " else "")).strip()
    return name.upper()


def partners():
    made = 0
    for i, (ref, name, base, city, zipc, street, what) in enumerate(NEW_SUPPLIERS, 11):
        if partner_by_ref(ref):
            continue
        code = edrpou(base)
        pid = ensure("res.partner", [["ref", "=", ref]], {
            "name": name, "ref": ref, "is_company": True, "company_registry": code,
            "street": street, "city": city, "zip": zipc, "country_id": REF["ua"],
            "supplier_rank": 1, "lang": "uk_UA", "comment": what, "ua_vat_payer_status": "payer",
            "vat": (code + "0000")[:12], "phone": f"+380 {32 if city == 'Львів' else 44} {300 + i} {30 + i} {40 + i}",
            "email": f"{ref.lower()}@example.ua"})
        acc = iban_ua("305299", f"00000260081{i:05d}0000"[:19].ljust(19, "0"))
        ensure("res.partner.bank", [["acc_number", "=", acc]],
               {"acc_number": acc, "partner_id": pid, "acc_holder_name": name, "allow_out_payment": True,
                "bank_id": REF["bank"].get("305299"), "currency_id": REF["uah"]})
        made += 1
    cards = {}
    for ref, card in P.items():
        pid = partner_by_ref(ref)
        if pid:
            cards[pid] = card
    for key, card in OWN.items():
        if CO[key]:
            cards[CO[key]["partner_id"][0]] = dict(card, own=key)
    rows = {r["id"]: r for r in call("res.partner", "read", list(cards),
                                     ["name", "ref", "city", "street", "zip", "company_registry", "vat", "is_company",
                                      "ua_vat_payer_status", "phone", "email", "supplier_rank", "customer_rank"])}
    usd = call("res.currency", "search", [["name", "=", "USD"]], context={"active_test": False})
    shared, per_company, contacts, heads = {}, {}, 0, 0
    for pid, card in cards.items():
        r = rows[pid]
        fop = r["name"].startswith("ФОП ")
        vals = {"industry_id": REF["industry"].get(card["ind"]),
                "category_id": m2m([REF["ptag"][t] for t in card["tags"]]),
                "state_id": REF["state"].get(CITY_STATE.get(r["city"] or "", "")),
                "street2": card.get("street2"), "website": card.get("web"),
                "phone": card.get("phone"), "email": card.get("email") or (f"{r['ref'].lower()}@example.ua" if r["ref"] else False)}
        if card.get("address"):
            vals.update(street=card["address"][0], zip=card["address"][1])
        if not card.get("foreign"):
            payer = r["ua_vat_payer_status"] == "payer" and r["vat"]
            vals.update({
                "ua_edr_kind": "fop" if fop else "company",
                "ua_edr_full_name": full_name(r["name"]),
                "ua_edr_status": "зареєстровано",
                "ua_edr_registration_date": card.get("reg"),
                "ua_kved": card.get("kved"),
                "ua_edr_head": card.get("head"),
                "ua_edr_capital": card.get("cap"),
                "ua_vat_status": f"платник ПДВ {r['vat']}" if payer else
                                 ("платник єдиного податку, не платник ПДВ" if fop else "не платник ПДВ"),
                "ua_edr_checks": card.get("checks") or "маркерів немає",
                "ua_edr_synced_at": EDR_SYNCED,
            })
            if not fop and not card.get("real") and r["is_company"]:
                vals.update(ua_signatory_name="Директор", ua_signatory_basis="Статуту")
            if r["supplier_rank"] and not card.get("own"):
                # Картка постачальника у «Вхідних рахунках»: той самий знімок ЄДР і позначка перевірки.
                address = ", ".join(x for x in (r["zip"], r["city"], r["street"]) if x)
                vals.update({
                    "bp_registry_name": vals["ua_edr_full_name"], "bp_registry_status": "зареєстровано",
                    "bp_registry_date": card.get("reg"), "bp_registry_address": address,
                    "bp_registry_head": card.get("head"), "bp_registry_kved": card.get("kved"),
                    "bp_registry_vat": vals["ua_vat_status"],
                    "bp_registry_markers": (card.get("checks") or "немає").lstrip("? "),
                    "bp_registry_checked_at": EDR_SYNCED,
                })
                if ref_of(r) not in ("DEMO-S09", "DEMO-S16"):      # двох лишаємо неперевіреними: так буває
                    vals.update(bp_supplier_status="verified", bp_verified_by=REF["admin"],
                                bp_verified_at="2026-09-16 08:30:00")
                else:
                    vals.update(bp_supplier_status="unverified")
        shared[pid] = vals
        # Поля, що залежать від компанії: пишемо в тій компанії, яка з контрагентом працює.
        cid = CO[card.get("co", "mebli")] and CO[card.get("co", "mebli")]["id"]
        if cid and not card.get("own"):
            dep = {}
            if card.get("ct"):
                dep.update(property_payment_term_id=REF["term"][card["ct"]], user_id=REF["admin"],
                           customer_payment_mode_id=REF.get("mode_in", {}).get(cid))
            if card.get("st"):
                dep.update(property_supplier_payment_term_id=REF["term"][card["st"]],
                           supplier_payment_mode_id=REF.get("mode_out", {}).get(cid))
                if cid == MEBLI:
                    dep["buyer_id"] = REF["buyer"]
            if card.get("limit"):
                dep["credit_limit"] = card["limit"]
            per_company.setdefault(cid, {})[pid] = dep
            if card.get("currency") and usd:
                # Валюта постачальника однакова, хоч би яка компанія групи в нього купувала.
                for each in ALL:
                    per_company.setdefault(each, {}).setdefault(pid, {})["property_purchase_currency_id"] = usd[0]
        # Контактні особи: керівник з ЄДР і людина, з якою працюємо щодня.
        people = []
        if card.get("head") and not card.get("own"):
            people.append((card["head"], "Директор", "director"))
        if card.get("contact"):
            people.append((card["contact"][0], card["contact"][1], "office"))
        slug = (r["ref"] or "").lower()
        for person, function, box in people:
            before = STAT.get("res.partner", {}).get("new", 0)
            ensure("res.partner", [["parent_id", "=", pid], ["name", "=", person]], {
                "name": person, "parent_id": pid, "type": "contact", "function": function or False,
                "email": f"{box}@{slug}.example.ua" if not card.get("foreign") else False,
                "phone": r["phone"] or card.get("phone") or False, "lang": "uk_UA"})
            added = STAT["res.partner"]["new"] - before if "res.partner" in STAT else 0
            contacts += added
            heads += added if box == "director" else 0
    fill("res.partner", shared)
    for cid, wanted in per_company.items():
        fill("res.partner", wanted, co=cid)
    # Адреси доставки компанії (офіс, цех) і решта контактів з містом: лише область.
    rest = call("res.partner", "search_read", [["city", "!=", False], ["state_id", "=", False],
                                               ["country_id", "=", REF["ua"]]], fields=["city"],
                context={"active_test": False})
    fill("res.partner", {r["id"]: {"state_id": REF["state"].get(CITY_STATE.get(r["city"], ""))} for r in rest})
    say(f"3. Контрагенти: карток {len(cards)} (нових постачальників {made}), контактних осіб додано {contacts} "
        f"(з них керівників {heads}); область, мітки, галузь, умови оплати, дані ЄДР.")


def ref_of(row):
    return row.get("ref") or ""


# =====================================================================================
# 4. Способи платежу (OCA account_payment_mode)
# =====================================================================================
def payment_modes():
    REF["mode_in"], REF["mode_out"] = {}, {}
    if not has_model("account.payment.mode"):
        return
    methods = {r["payment_type"]: r["id"] for r in call("account.payment.method", "search_read",
                                                        [["code", "=", "manual"]], fields=["payment_type"])}
    for cid in ALL:
        bank = call("account.journal", "search", [["type", "=", "bank"], ["company_id", "=", cid]], order="id", limit=1)
        if not bank:
            continue
        for kind, name, text in (
                ("outbound", "Банківський переказ постачальникам",
                 "Оплата рахунків постачальників платіжною інструкцією з поточного рахунку."),
                ("inbound", "Оплата від покупців на поточний рахунок",
                 "Покупець платить за рахунком-фактурою на поточний рахунок, реквізити друкуються в рахунку.")):
            if kind not in methods:
                continue
            mid = ensure("account.payment.mode", [["name", "=", name], ["company_id", "=", cid]], {
                "name": name, "company_id": cid, "payment_method_id": methods[kind],
                "bank_account_link": "variable", "variable_journal_ids": m2m(bank), "note": html(text)}, co=cid)
            REF["mode_in" if kind == "inbound" else "mode_out"][cid] = mid
    # Наявні способи «Зарплата» і «Податки»: примітка і журнали, з яких беруть рядки.
    notes = {"Зарплата": "Відомість на перерахування зарплати на картки працівників. Файл для банку - CSV у кодуванні Windows-1251.",
             "Податки": "ПДФО, військовий збір і ЄСВ на рахунки бюджету. Платимо в день виплати зарплати."}
    wanted = {}
    for r in call("account.payment.mode", "search_read", [["name", "in", list(notes)]], fields=["name", "company_id"]):
        cid = r["company_id"][0]
        journals = call("account.journal", "search", [["company_id", "=", cid], ["code", "in", ["ЗП", "MISC"]]])
        wanted[r["id"]] = {"note": html(notes[r["name"]]), "default_journal_ids": m2m(journals)}
    fill("account.payment.mode", wanted)
    say(f"4. Способи платежу: для постачальників і покупців у {len(REF['mode_out'])} компаніях; примітки до наявних.")


# =====================================================================================
# 5. Компанії
# =====================================================================================
# Рахунки бюджету - казначейство (МФО 899998), одні на всю Залізничну ДПІ: вигадані, контрольні числа сходяться.
IBAN_PDFO = iban_ua("899998", "0333169340000013306")
IBAN_VZ = iban_ua("899998", "0333189340000013306")
IBAN_ESV = iban_ua("899998", "0000355669201021306")
STI = {"ua_sti_code": "1306", "ua_reg": "13", "ua_raj": "06", "ua_katottg": "UA46060250010015970",
       "ua_sti_name": "ГУ ДПС у Львівській області, Залізнична ДПІ (Залізничний район м. Львова)"}


def companies():
    dps = partner_by_ref("DEMO-DPS")
    wanted = {}
    for key in CO:
        if not CO[key]:
            continue
        cid = CO[key]["id"]
        vals = {"ua_iban_pdfo": IBAN_PDFO, "ua_iban_vz": IBAN_VZ, "ua_iban_esv": IBAN_ESV}
        if key != "mebli":
            # Керівника і бухгалтера беремо з карток працівників, якщо вони є; кадри не змінюємо.
            people = {e["job_title"]: e for e in call("hr.employee", "search_read", [["company_id", "=", cid]],
                                                      fields=["name", "job_title", "ua_rnokpp"], co=cid)}
            director = people.get("Директор")
            book = people.get("Головний бухгалтер")
            if key == "logist":
                # У «Ясен Логістики» працівників немає: керує комерційний директор групи за сумісництвом,
                # облік веде бухгалтерія «Ясен Меблів».
                group = {e["name"]: e for e in call("hr.employee", "search_read", [["company_id", "=", MEBLI]],
                                                    fields=["name", "ua_rnokpp"], co=MEBLI)}
                director = group.get("Крамар Володимир Зіновійович")
                book = group.get("Стефанишин Оксана Ігорівна")
            vals.update(STI)
            vals.update({"ua_kved": OWN[key]["kved"].split(" ")[0], "ua_dps_partner_id": dps,
                         "ua_purchase_approval_limit": 30000.0 if key == "logist" else 50000.0,
                         "phone": OWN[key].get("phone"), "website": OWN[key].get("web"),
                         "ua_cash_limit": 10000.0})
            if director:
                vals.update(ua_director_name=director["name"], ua_director_rnokpp=director["ua_rnokpp"])
            if book:
                vals.update(ua_accountant_name=book["name"], ua_accountant_rnokpp=book["ua_rnokpp"])
        wanted[cid] = vals
    fill("res.company", wanted)
    say(f"5. Компанії: {len(wanted)}; рахунки бюджету ПДФО {IBAN_PDFO}, ВЗ {IBAN_VZ}, ЄСВ {IBAN_ESV}; "
        f"керівник, бухгалтер і коди ДПІ для «Ясен Логістики» та «АероСічі».")


# =====================================================================================
# 6. Основні засоби
# =====================================================================================
ASSET_ROOTS = [("ОЗ", "Основні засоби (п. 138.3.3 ПКУ)"), ("НМА", "Нематеріальні активи (п. 138.3.4 ПКУ)")]
MEBLI_OFFICE, MEBLI_SHOP, MEBLI_STORE = "Офіс, вул. Городоцька 174", "Цех, Сокільники", "Склад, Сокільники"
AERO_SHOP = "Цех збирання, вул. Наукова 7а, корпус Б"
LOGIST_YARD = "Автомайданчик, вул. Зелена 301"
# Реквізити вже наявних об'єктів (demo_business.py): код -> поля. Постачальника беремо з проводки придбання.
OLD_ASSETS = {
    "ОЗ-001": dict(ua_manufacturer="HOMAG GmbH (Німеччина)", ua_factory_number="0-201-34-7719", ua_year_built="2026",
                   ua_passport_number="Паспорт верстата № HN210-7719", salvage_value=72500.0,
                   note="Обробний центр з ЧПК для свердління, фрезерування і розкрою деталей. Гарантія 24 місяці, "
                        "сервісний договір № 14-С/2026. Планове ТО раз на пів року."),
    "ОЗ-002": dict(ua_manufacturer="Renault Trucks (Франція)", ua_factory_number="VF1MA000X67412985", ua_year_built="2026",
                   ua_passport_number="Свідоцтво про реєстрацію ТЗ СХА № 418265", salvage_value=98000.0,
                   note="Фургон вантажопідйомністю 1,5 т для доставки меблів замовникам. Номерний знак ВС 4172 МТ. "
                         "Поліси ОСЦПВ і КАСКО до 2027-07-14."),
    "ОЗ-003": dict(ua_manufacturer="Lenovo (Китай)", ua_factory_number="PF4K2L8A, PF4K2L8C, PF4K2M1F, PF4K2M3H", ua_year_built="2026",
                   ua_passport_number="Гарантійні талони № 55871-55874",
                   note="Чотири ноутбуки ThinkPad E16 для бухгалтерії і відділу збуту. Вартість одиниці 37 000 грн - "
                        "малоцінні необоротні активи, 100 % амортизації в першому місяці."),
}
# Нові об'єкти: (код, назва, група, правило, вартість, дата введення, строк у місяцях або None,
#               ліквідаційна, місце, відповідальний, виробник, заводський №, паспорт, рік, постачальник, примітка)
NEW_ASSETS = {
    "mebli": [
        ("ОЗ-004", "Поліпшення орендованого цеху: силова електромережа і освітлення", "oz_09", "linear", 620000.0, "2019-09-16", None, 0.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "ТОВ «Західбудмонтаж» (Україна)", "без номера", "Акт КБ-2в № 3 від 2019-09-12", "2019", "DEMO-S14",
         "Капітальні витрати на поліпшення орендованого приміщення за згодою орендодавця (договір оренди № 7 від 2019-06-03)."),
        ("ОЗ-005", "Форматно-розкрійний верстат Altendorf F45", "oz_04", "linear", 890000.0, "2019-11-05", 96, 45000.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "Altendorf GmbH (Німеччина)", "19-08-3345", "Паспорт верстата № F45-3345", "2019", "DEMO-S11",
         "Розкрій плит ДСП і МДФ. Строк корисного використання 8 років за наказом про облікову політику."),
        ("ОЗ-006", "Крайколичкувальний верстат Brandt Ambition 1120 FC", "oz_04", "linear", 1180000.0, "2020-03-12", 96, 59000.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "HOMAG Kantentechnik GmbH (Німеччина)", "0-261-05-1184", "Паспорт верстата № 1120-1184", "2020", "DEMO-S11",
         "Наклеювання кромки ПВХ. У серпні 2026 ремонт вузла подачі (ФОП Дмитрук), витрати віднесено на ремонт."),
        ("ОЗ-007", "Свердлильно-присадний верстат Vitap Alfa 21", "oz_04", "linear", 310000.0, "2020-06-22", 84, 0.0,
         MEBLI_SHOP, "Гнатів Степан Миколайович", "Vitap S.p.A. (Італія)", "VT-21-06617", "Паспорт верстата № 06617", "2020", "DEMO-S11",
         "Присадка отворів під конфірмати і петлі."),
        ("ОЗ-008", "Стелажі палетні складські, 48 секцій", "oz_06", "linear", 365000.0, "2020-08-03", None, 0.0,
         MEBLI_STORE, "Іваничук Марія Степанівна", "ТОВ «Складська техніка Україна»", "СТ-2020-0418", "Паспорт стелажної системи № 418", "2020", "DEMO-S15",
         "Стелажі зон А, Б і В складу. Щорічний огляд несучих конструкцій - у вересні."),
        ("ОЗ-009", "Компресор гвинтовий Atlas Copco GA 11", "oz_04", "linear", 285000.0, "2021-02-10", 84, 0.0,
         MEBLI_SHOP, "Гнатів Степан Миколайович", "Atlas Copco Airpower (Бельгія)", "API482117", "Паспорт посудини під тиском № 482117", "2020", "DEMO-S11",
         "Стиснене повітря для верстатів і фарбувальної камери. ТО кожні 4 000 мотогодин."),
        ("ОЗ-010", "Аспіраційна система цеху з повітроводами", "oz_04", "linear", 420000.0, "2021-04-19", 84, 0.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "Завод «Екофільтр» (Україна)", "ЕФ-7000-0093", "Паспорт установки № 0093", "2021", "DEMO-S11",
         "Видалення стружки і пилу від верстатів, продуктивність 7 000 м. куб. на годину."),
        ("ОЗ-011", "Навантажувач вилковий електричний Toyota 8FBE18T", "oz_04", "linear", 760000.0, "2021-09-07", 84, 76000.0,
         MEBLI_STORE, "Іваничук Марія Степанівна", "Toyota Material Handling (Японія)", "8FBE18T-61420", "Паспорт навантажувача № 61420", "2021", "DEMO-S15",
         "Вантажопідйомність 1,8 т. Технічний огляд і перевірка знань водія - щороку."),
        ("ОЗ-012", "Автомобіль легковий Skoda Octavia A8", "oz_05", "linear", 720000.0, "2022-01-25", None, 72000.0,
         MEBLI_OFFICE, "Крамар Володимир Зіновійович", "Skoda Auto (Чехія)", "TMBJR7NX5NY041736", "Свідоцтво про реєстрацію ТЗ СХН № 207413", "2021", "DEMO-S12",
         "Службовий автомобіль комерційного відділу. Номерний знак ВС 8031 КА."),
        ("ОЗ-013", "Верстаки столярні і набір електроінструменту Festool", "oz_06", "linear", 212000.0, "2022-05-16", None, 0.0,
         MEBLI_SHOP, "Мельничук Андрій Петрович", "Festool GmbH (Німеччина)", "FT-2022-11873", "Гарантійний талон № 11873", "2022", "DEMO-S11",
         "Шість робочих місць дільниці складання."),
        ("ОЗ-014", "Сушильна камера для деревини", "oz_04", "linear", 540000.0, "2022-09-12", 96, 0.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "Завод «Термодрев» (Україна)", "ТД-12-0057", "Паспорт камери № 0057", "2022", "DEMO-S11",
         "Сушіння бруса до вологості 8-10 %, завантаження 12 м. куб."),
        ("ОЗ-015", "Програма проєктування меблів PRO100, 6 ліцензій", "nma_5", "linear", 96000.0, "2023-01-16", None, 0.0,
         MEBLI_OFFICE, "Лозинський Тарас Юрійович", "Ecru Software (Польща)", "PRO100-UA-6-22871", "Ліцензійний договір № 22871", "2023", "DEMO-S13",
         "Безстрокові ліцензії для дизайнерів і технолога. Оновлення за окремим договором."),
        ("ОЗ-016", "Фарбувальна камера з водяною завісою", "oz_04", "linear", 680000.0, "2023-03-27", 96, 34000.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "Завод «Екофільтр» (Україна)", "ЕФ-ФК-0211", "Паспорт камери № 0211", "2023", "DEMO-S11",
         "Нанесення лаків і фарб. Заміна фільтрів щокварталу."),
        ("ОЗ-017", "Сервер Dell PowerEdge T350 і мережеве обладнання", "oz_04", "linear", 248000.0, "2023-06-05", 48, 0.0,
         MEBLI_OFFICE, "Стефанишин Оксана Ігорівна", "Dell Technologies (Китай)", "7QK4TZ3", "Гарантійний талон № 7QK4TZ3", "2023", "DEMO-S13",
         "Файловий сервер і резервні копії облікової системи."),
        ("ОЗ-018", "Торговельна марка «Ясен» (свідоцтво України на знак)", "nma_3", "linear", 38000.0, "2019-11-18", 120, 0.0,
         MEBLI_OFFICE, "Данилюк Олег Ігорович", "Укрпатент", "Свідоцтво № 268417", "Свідоцтво на знак для товарів і послуг № 268417", "2019", "DEMO-S16",
         "Класи МКТП 20 і 35. Строк дії свідоцтва 10 років, до 2029-11-18."),
        ("ОЗ-019", "Прес гарячий для шпонування Italpresse XL/6", "oz_04", "linear", 930000.0, "2024-05-14", 96, 46500.0,
         MEBLI_SHOP, "Прокопів Наталія Богданівна", "Italpresse S.p.A. (Італія)", "XL6-24-0388", "Паспорт преса № 0388", "2024", "DEMO-S11",
         "Облицювання щитів натуральним шпоном."),
        ("ОЗ-020", "Візки платформні складські, 6 шт (МНМА, 50/50)", "oz_11", "mnma_50_50", 39000.0, "2024-06-03", None, 19500.0,
         MEBLI_STORE, "Іваничук Марія Степанівна", "ТОВ «Складська техніка Україна»", "без номерів", "Видаткова накладна № 2114", "2024", "DEMO-S15",
         "Малоцінні необоротні активи за методом 50/50: друга половина піде у витрати при списанні."),
        ("ОЗ-021", "Автомобіль вантажний MAN TGL 8.190, бортовий", "oz_05", "linear", 1350000.0, "2024-10-08", None, 135000.0,
         MEBLI_STORE, "Шевчук Віталій Олегович", "MAN Truck & Bus (Німеччина)", "WMAN04ZZ7KY388614", "Свідоцтво про реєстрацію ТЗ СХТ № 550932", "2019", "DEMO-S12",
         "Придбано вживаним, пробіг на дату введення 214 000 км. Номерний знак ВС 2290 РІ."),
        ("ОЗ-022", "Шуруповерти акумуляторні Makita DDF485, 8 шт (МНМА)", "oz_11", "mnma_100", 46400.0, "2025-03-10", None, 0.0,
         MEBLI_SHOP, "Мельничук Андрій Петрович", "Makita (Японія)", "4418722-4418729", "Гарантійні талони № 4418722-4418729", "2025", "DEMO-S11",
         "Вартість одиниці 5 800 грн. Видані столярам під підпис у відомості МШ-2."),
        ("ОЗ-023", "Шліфувальний калібрувальний верстат Houfek Buldog 5", "oz_04", "linear", 610000.0, "2025-02-18", 96, 0.0,
         MEBLI_SHOP, "Гнатів Степан Миколайович", "Houfek a.s. (Чехія)", "BD5-25-0127", "Паспорт верстата № 0127", "2025", "DEMO-S11",
         "Калібрування і шліфування щитів перед лакуванням."),
        ("ОЗ-024", "Принтер етикеток Zebra ZT231 зі сканерами штрихкодів", "oz_04", "linear", 38400.0, "2026-10-05", 36, 0.0,
         MEBLI_STORE, "Іваничук Марія Степанівна", "Zebra Technologies (США)", "D6J234607211", "Гарантійний талон № 234607211", "2026", "DEMO-S13",
         "Друк етикеток для готової продукції і комірок складу."),
        ("ОЗ-025", "Лазерні нівеліри і вимірювальний інструмент Bosch (МНМА)", "oz_11", "mnma_100", 28500.0, "2026-10-02", None, 0.0,
         MEBLI_SHOP, "Мельничук Андрій Петрович", "Robert Bosch GmbH (Німеччина)", "без номерів", "Видаткова накладна № ВІ-0412", "2026", "DEMO-S11",
         "Для бригади монтажу меблів у замовника."),
    ],
    "logist": [
        ("ЛОГ-001", "Тягач сідловий DAF XF 480 FT", "oz_05", "linear", 2650000.0, "2023-04-11", 84, 265000.0,
         LOGIST_YARD, "Крамар Володимир Зіновійович", "DAF Trucks N.V. (Нідерланди)", "XLRTEH4300G274516", "Свідоцтво про реєстрацію ТЗ СХР № 318804", "2019", "DEMO-S12",
         "Придбано вживаним. Номерний знак ВС 5518 ОН. Тахограф повірено до 2027-04."),
        ("ЛОГ-002", "Напівпричіп тентований Schmitz Cargobull SCS 24/L", "oz_05", "linear", 890000.0, "2023-04-11", 84, 89000.0,
         LOGIST_YARD, "Крамар Володимир Зіновійович", "Schmitz Cargobull AG (Німеччина)", "WSM00000005218843", "Свідоцтво про реєстрацію ТЗ СХР № 318805", "2018", "DEMO-S12",
         "Номерний знак ВС 3107 ХТ. Працює в парі з тягачем ЛОГ-001."),
        ("ЛОГ-003", "Автомобіль вантажний Mercedes-Benz Sprinter 316 CDI, фургон", "oz_05", "linear", 1180000.0, "2024-08-19", None, 118000.0,
         LOGIST_YARD, "Крамар Володимир Зіновійович", "Mercedes-Benz AG (Німеччина)", "W1V9076331P604417", "Свідоцтво про реєстрацію ТЗ СХТ № 771260", "2022", "DEMO-S12",
         "Доставка по Львову і області. Номерний знак ВС 9046 ТА."),
        ("ЛОГ-004", "Ноутбук диспетчера Dell Latitude 5540", "oz_04", "linear", 42000.0, "2025-06-02", 24, 0.0,
         "Офіс, вул. Зелена 301", "Крамар Володимир Зіновійович", "Dell Technologies (Китай)", "9XJ2PY3", "Гарантійний талон № 9XJ2PY3", "2025", "DEMO-S13",
         "Робоче місце диспетчера, програма маршрутів."),
        ("ЛОГ-005", "GPS-трекери Teltonika FMB920, 3 шт (МНМА)", "oz_11", "mnma_100", 9600.0, "2025-01-14", None, 0.0,
         LOGIST_YARD, "Крамар Володимир Зіновійович", "Teltonika (Литва)", "352094088214417-435", "Гарантійні талони № 8214417, 8214426, 8214435", "2024", "DEMO-S13",
         "Встановлено на тягач, фургон і напівпричіп."),
    ],
    "aero": [
        ("АС-ОЗ-001", "3D-принтер Bambu Lab X1 Carbon Combo", "oz_04", "linear", 68000.0, "2024-03-05", 36, 0.0,
         AERO_SHOP, "Кравчук Ірина Андріївна", "Bambu Lab (Китай)", "01S00C352100418", "Гарантійний талон № 352100418", "2024", "DEMO-S13",
         "Друк кріплень камер і корпусів антен із нейлону з вуглеволокном."),
        ("АС-ОЗ-002", "Паяльна станція JBC CD-2BQF з димовитяжкою", "oz_04", "linear", 34500.0, "2024-03-05", 60, 0.0,
         AERO_SHOP, "Дзюба Олег Миколайович", "JBC Soldering S.L. (Іспанія)", "CD2BQF-118734", "Паспорт станції № 118734", "2023", "AERO-S02",
         "Дільниця пайки, робоче місце № 1."),
        ("АС-ОЗ-003", "Осцилограф цифровий Rigol DS1104Z Plus", "oz_04", "linear", 29800.0, "2024-05-20", 60, 0.0,
         AERO_SHOP, "Мельник Тарас Володимирович", "Rigol Technologies (Китай)", "DS1ZC243901775", "Свідоцтво про калібрування № 1775/24", "2024", "AERO-S02",
         "Перевірка регуляторів і відеотракту. Калібрування раз на рік."),
        ("АС-ОЗ-004", "Ноутбуки інженерні Lenovo Legion 5, 3 шт", "oz_04", "linear", 186000.0, "2024-04-08", 24, 0.0,
         AERO_SHOP, "Кравчук Ірина Андріївна", "Lenovo (Китай)", "PF51Q7KD, PF51Q7KH, PF51Q7KM", "Гарантійні талони № 61204-61206", "2024", "DEMO-S13",
         "Конструкторський відділ: проєктування рам і налаштування прошивок."),
        ("АС-ОЗ-005", "Ліцензія SolidWorks Standard, безстрокова", "nma_5", "linear", 215000.0, "2024-06-03", None, 0.0,
         AERO_SHOP, "Кравчук Ірина Андріївна", "Dassault Systemes (Франція)", "9010 0124 5518 7732", "Ліцензійний договір № SW-2024-0612", "2024", "DEMO-S13",
         "Одне робоче місце конструктора."),
        ("АС-ОЗ-006", "Стенд тяги моторів Tyto Robotics Series 1585", "oz_04", "linear", 46000.0, "2024-09-10", 60, 0.0,
         AERO_SHOP, "Гнатів Роман Петрович", "Tyto Robotics (Канада)", "1585-A-20417", "Паспорт стенда № 20417", "2024", "AERO-S02",
         "Вхідний контроль моторів і пропелерів на дільниці ВТК."),
        ("АС-ОЗ-007", "Фрезерний верстат з ЧПК для карбону, портальний", "oz_04", "linear", 385000.0, "2025-02-17", 84, 19250.0,
         AERO_SHOP, "Дзюба Олег Миколайович", "Завод «Портал-ЧПК» (Україна)", "ПЧ-1325-0064", "Паспорт верстата № 0064", "2025", "DEMO-S11",
         "Розкрій карбонових плит на рами 7 і 10 дюймів. Аспірація з НЕРА-фільтром."),
        ("АС-ОЗ-008", "Автомобіль Renault Duster для виїзних льотних випробувань", "oz_05", "linear", 890000.0, "2025-05-12", None, 89000.0,
         "Майданчик, вул. Наукова 7а", "Сидорук Марія Василівна", "Renault (Румунія)", "VF1HJD20X72604183", "Свідоцтво про реєстрацію ТЗ СХХ № 904417", "2025", "DEMO-S12",
         "Номерний знак ВС 6124 ХК."),
        ("АС-ОЗ-009", "Антистатичні робочі місця монтажників, 4 шт (МНМА)", "oz_11", "mnma_100", 58000.0, "2024-03-18", None, 0.0,
         AERO_SHOP, "Дзюба Олег Миколайович", "ТОВ «Електрон Компоненти»", "без номерів", "Видаткова накладна № ЕК-0318", "2024", "AERO-S02",
         "Столи з антистатичним покриттям, браслети і килимки. Вартість одиниці 14 500 грн."),
    ],
}
ASSETS_TOUCHED = set()      # компанії, де цим прогоном щось проведено по ОЗ


def asset_groups(cid):
    """Групи ОЗ: два корені і податкові групи з профілів. Профілі і об'єкти отримують свою групу."""
    roots = {code: ensure("account.asset.group", [["code", "=", code], ["company_id", "=", cid]],
                          {"code": code, "name": name, "company_id": cid}, co=cid) for code, name in ASSET_ROOTS}
    profiles = call("account.asset.profile", "search_read", [["company_id", "=", cid]],
                    fields=["name", "ua_tax_group", "group_ids"], co=cid, context={"active_test": False})
    by_key, wanted = {}, {}
    plus, minus = account("746", cid), account("977", cid)
    for pr in sorted(profiles, key=lambda r: r["ua_tax_group"] or ""):
        key = pr["ua_tax_group"]
        if not key:
            continue
        if key not in by_key:
            kind, number = key.split("_")
            root = "ОЗ" if kind == "oz" else "НМА"
            # «ОЗ, група 4: машини та обладнання» -> «Група 4: машини та обладнання»
            label = re.sub(r"\s*\(.*\)$", "", pr["name"].split(", ", 1)[-1])
            label = label[:1].upper() + label[1:]
            code = f"{root}-{int(number):02d}"
            by_key[key] = ensure("account.asset.group", [["code", "=", code], ["company_id", "=", cid]],
                                 {"code": code, "name": label[:64], "company_id": cid, "parent_id": roots[root]}, co=cid)
        # Рахунки вибуття - для режиму «прибуток або збиток від продажу»: 746 і 977.
        wanted[pr["id"]] = {"group_ids": m2m([by_key[key]]), "account_plus_value_id": plus, "account_min_value_id": minus}
    fill("account.asset.profile", wanted, co=cid)
    return by_key


def _profile(cid, group, rule):
    ids = call("account.asset.profile", "search", [["ua_tax_group", "=", group], ["ua_rule", "=", rule],
                                                   ["company_id", "=", cid]], co=cid, limit=1)
    if not ids:
        return None
    return call("account.asset.profile", "read", ids,
                ["account_asset_id", "account_depreciation_id", "journal_id", "method", "method_number",
                 "method_period", "method_time", "prorata"], co=cid)[0]


def _opening_entry(cid, aid, code, name, value, open_day, profile):
    """Початковий залишок старого об'єкта першим відкритим днем: Дт 10х / Кт 13х / Кт 441.
    Так само demo_bank.py ввів залишок на поточному рахунку. У закритий період нічого не йде."""
    key = f"Початковий залишок ОЗ: {code} {name}"
    if call("account.move", "search_count", [["ref", "=", key], ["company_id", "=", cid]], co=cid):
        return 0.0
    lines = call("account.asset.line", "search_read",
                 [["asset_id", "=", aid], ["type", "=", "depreciate"], ["init_entry", "=", True]],
                 fields=["amount"], co=cid)
    worn = round(sum(l["amount"] for l in lines), 2)
    a441 = account("441", cid)
    rows = [(0, 0, {"account_id": profile["account_asset_id"][0], "name": name, "asset_id": aid,
                    "debit": value, "credit": 0.0})]
    if worn:
        rows.append((0, 0, {"account_id": profile["account_depreciation_id"][0], "name": f"Знос на {open_day}: {name}",
                            "debit": 0.0, "credit": worn}))
    if round(value - worn, 2):
        rows.append((0, 0, {"account_id": a441, "name": f"Залишкова вартість на {open_day}: {name}",
                            "debit": 0.0, "credit": round(value - worn, 2)}))
    mid = call("account.move", "create", {"journal_id": profile["journal_id"][0], "company_id": cid, "date": open_day,
                                          "ref": key, "line_ids": rows}, co=cid, context={"allow_asset": True})
    call("account.move", "action_post", [mid], co=cid, context={"allow_asset": True})
    return value


def _purchase_entry(cid, aid, name, value, day, profile, partner):
    """Придбання у відкритому періоді - та сама проводка, що в demo_business.py:
    Дт 1521 і Дт 6441 / Кт 631, далі введення в експлуатацію Дт 10х / Кт 1521."""
    key = f"Придбання і введення в експлуатацію: {name}"
    if call("account.move", "search_count", [["ref", "=", key], ["company_id", "=", cid]], co=cid):
        return 0.0
    a152 = account("1521", cid) or account("152", cid)
    a6441, a631 = account("6441", cid), account("631", cid)
    vat = round(value * 0.2, 2)
    mid = call("account.move", "create", {
        "journal_id": profile["journal_id"][0], "company_id": cid, "date": day, "ref": key,
        "line_ids": [
            (0, 0, {"account_id": a152, "partner_id": partner, "name": name, "debit": value, "credit": 0.0}),
            (0, 0, {"account_id": a6441, "partner_id": partner, "name": "ПДВ", "debit": vat, "credit": 0.0}),
            (0, 0, {"account_id": a631, "partner_id": partner, "name": name, "debit": 0.0, "credit": value + vat}),
            (0, 0, {"account_id": profile["account_asset_id"][0], "name": "Введення в експлуатацію: " + name,
                    "asset_id": aid, "debit": value, "credit": 0.0}),
            (0, 0, {"account_id": a152, "name": "Введення в експлуатацію", "debit": 0.0, "credit": value})]},
        co=cid, context={"allow_asset": True})
    call("account.move", "action_post", [mid], co=cid, context={"allow_asset": True})
    return value


def assets():
    out = []
    for key in ("mebli", "logist", "aero"):
        if not CO[key]:
            continue
        cid = CO[key]["id"]
        groups = asset_groups(cid)
        lock = call("res.company", "read", [cid], ["fiscalyear_lock_date"])[0]["fiscalyear_lock_date"]
        open_day = max(day_after(lock), BOOKS_START) if lock else BOOKS_START
        made, opening, bought, posted = 0, 0.0, 0.0, 0
        for (code, name, group, rule, value, day, months, salvage, place, who, maker, factory, passport, year,
             supplier, note) in NEW_ASSETS[key]:
            try:
                profile = _profile(cid, group, rule)
                if not profile:
                    out.append(f"профіль {group}/{rule} не знайдено - {code} пропущено")
                    continue
                partner = partner_by_ref(supplier)
                ids = call("account.asset", "search", [["code", "=", code], ["company_id", "=", cid]], co=cid,
                           context={"active_test": False})
                if not ids:
                    vals = {"name": name, "code": code, "profile_id": profile["id"], "purchase_value": value,
                            "date_start": day, "company_id": cid, "method": profile["method"],
                            "method_number": months or profile["method_number"], "method_period": profile["method_period"],
                            "method_time": profile["method_time"], "prorata": profile["prorata"],
                            "salvage_value": salvage, "partner_id": partner, "note": note,
                            "ua_location": place, "ua_responsible": who, "ua_manufacturer": maker,
                            "ua_factory_number": factory, "ua_passport_number": passport, "ua_year_built": year,
                            "ua_commission": "Акт приймання-передачі (введення в експлуатацію) ОЗ-1 від " + day,
                            "group_ids": m2m([groups.get(group)])}
                    ids = [call("account.asset", "create", vals, co=cid)]
                    made += 1
                    st = stat("account.asset")
                    st["new"] += 1
                    st["fields"].update(vals)
                aid = ids[0]
                # Об'єкт уже був: дописуємо лише порожні реквізити (наприклад, постачальника, якого завели пізніше).
                fill("account.asset", {aid: {"partner_id": partner, "note": note, "ua_location": place,
                                             "ua_responsible": who, "ua_manufacturer": maker, "ua_factory_number": factory,
                                             "ua_passport_number": passport, "ua_year_built": year,
                                             "group_ids": m2m([groups.get(group)])}}, co=cid)
                state = call("account.asset", "read", [aid], ["state"], co=cid)[0]["state"]
                old = day < open_day
                if state == "draft":
                    # validate сам будує таблицю амортизації. Вдруге її не кличемо: для об'єкта з одним
                    # рядком (МНМА 50/50) повторний розрахунок OCA падає на вже зарахованому рядку.
                    call("account.asset", "validate", [aid], co=cid)
                    if old:
                        # Амортизація до першого відкритого дня - початковий залишок, без проводок.
                        past = call("account.asset.line", "search",
                                    [["asset_id", "=", aid], ["type", "=", "depreciate"], ["line_date", "<", open_day],
                                     ["init_entry", "=", False], ["move_id", "=", False]], co=cid)
                        if past:
                            call("account.asset.line", "write", past, {"init_entry": True}, co=cid)
                        call("account.asset", "validate", [aid], co=cid)       # повністю замортизований - «Закрито»
                if old:
                    got = _opening_entry(cid, aid, code, name, value, open_day, profile)
                    opening += got
                else:
                    got = _purchase_entry(cid, aid, name, value, day, profile, partner)
                    bought += got
                if got:
                    ASSETS_TOUCHED.add(cid)
            except RpcError as e:
                # Відома вада: об'єкт, введений у грудні, з амортизацією з наступного місяця валить
                # таблицю OCA (перший фінансовий рік без рядків). Такі дати в таблиці не вживаємо.
                out.append(f"{code}: {str(e).splitlines()[0][:140]}")
        # Амортизація відкритих місяців по POST_UNTIL - звичайними проводками, по черзі за датою.
        mine = call("account.asset", "search", [["code", "in", [a[0] for a in NEW_ASSETS[key]]], ["company_id", "=", cid]], co=cid)
        due = call("account.asset.line", "search_read",
                   [["asset_id", "in", mine], ["type", "=", "depreciate"], ["move_check", "=", False],
                    ["init_entry", "=", False], ["line_date", ">=", open_day], ["line_date", "<=", POST_UNTIL]],
                   fields=["line_date"], order="line_date, id", co=cid)
        for ln in due:
            try:
                call("account.asset.line", "create_move", [ln["id"]], co=cid)
                posted += 1
                ASSETS_TOUCHED.add(cid)
            except RpcError as e:
                out.append(f"амортизація {ln['line_date']} не проведена: {str(e).splitlines()[0][:140]}")
                break
        # Наявні об'єкти demo_business.py: реквізити, група, постачальник із проводки придбання.
        if key == "mebli":
            wanted = {}
            for r in call("account.asset", "search_read", [["code", "in", list(OLD_ASSETS)], ["company_id", "=", cid]],
                          fields=["code", "name", "profile_id", "salvage_value", "state"], co=cid):
                vals = dict(OLD_ASSETS[r["code"]])
                move = call("account.move.line", "search_read",
                            [["move_id.ref", "=", f"Придбання і введення в експлуатацію: {r['name']}"],
                             ["partner_id", "!=", False], ["company_id", "=", cid]], fields=["partner_id"], limit=1, co=cid)
                vals["partner_id"] = move[0]["partner_id"][0] if move else False
                pr = call("account.asset.profile", "read", [r["profile_id"][0]], ["ua_tax_group"], co=cid)[0]
                vals["group_ids"] = m2m([groups.get(pr["ua_tax_group"])])
                wanted[r["id"]] = vals
                if vals.get("salvage_value") and not r["salvage_value"] and r["state"] == "open":
                    wanted[r["id"]]["_board"] = True
            boards = [rid for rid, v in wanted.items() if v.pop("_board", False)]
            changed = fill("account.asset", wanted, co=cid)
            for rid in boards:
                if rid in changed:
                    # Ліквідаційна вартість змінила базу: перераховуємо лише ще не проведені рядки.
                    try:
                        call("account.asset", "compute_depreciation_board", [rid], co=cid)
                    except RpcError as e:
                        REFUSED.append(("account.asset", "salvage_value", str(e).splitlines()[0][:160]))
        total = call("account.asset", "search_count", [["company_id", "=", cid], ["state", "!=", "draft"]], co=cid)
        out.append(f"{CO[key]['name']}: об'єктів у реєстрі {total} (нових {made}); перший відкритий день {open_day}; "
                   f"цим прогоном початкових залишків {opening:,.2f}, придбань {bought:,.2f}, рядків амортизації проведено {posted}")
        if cid in ASSETS_TOUCHED:
            _refresh_after_assets(cid, out)
    say("6. Основні засоби: " + "; ".join(out) + ".")


def _refresh_after_assets(cid, out):
    """Відомості амортизації і декларація з прибутку тримають збережені підсумки: перераховуємо."""
    for month in ("8", "9"):
        sheet = ensure("ua.depreciation.sheet", [["company_id", "=", cid], ["year", "=", 2026], ["month", "=", month]],
                       {"company_id": cid, "year": 2026, "month": month}, co=cid)
        try:
            call("ua.depreciation.sheet", "action_compute", [sheet], co=cid)
        except RpcError:
            pass
    if not has_model("ua.profit.declaration"):
        return
    ids = call("ua.profit.declaration", "search", [["company_id", "=", cid], ["year", "=", 2026]], co=cid)
    if not ids:
        return
    try:
        if call("ua.profit.declaration", "read", ids, ["state"], co=cid)[0]["state"] != "draft":
            call("ua.profit.declaration", "action_draft", ids, co=cid)
        call("ua.profit.declaration", "action_compute", ids, co=cid)
        call("ua.profit.declaration", "action_confirm", ids, co=cid)
        d = call("ua.profit.declaration", "read", ids, ["finres", "diff_amortisation"], co=cid)[0]
        out.append(f"декларацію з прибутку перераховано: фінрезультат {d['finres']:,.2f}, "
                   f"амортизаційна різниця {d['diff_amortisation']:,.2f}")
    except RpcError as e:
        out.append("декларація з прибутку не перерахувалась: " + str(e).splitlines()[0][:140])


# =====================================================================================
# 7. Товари, прайси постачальників, специфікації
# =====================================================================================
# код -> (вага кг, об'єм м. куб., мітки, опис). Опис іде в продаж для виробів і в закупівлю для матеріалів.
PRODUCTS = {
    "M01": (38.5, 0.104, ["Плитні матеріали"], "ДСП ламінована 18 мм, декор «дуб сонома», лист 2800x2070 мм, клас емісії E1."),
    "M02": (36.0, 0.093, ["Плитні матеріали"], "МДФ 16 мм, біла ламінована з двох боків, лист 2800x2070 мм."),
    "M03": (15.5, 0.028, ["Плитні матеріали", "Деревина"], "Фанера березова ФК 12 мм, сорт 2/2, лист 1525x1525 мм, шліфована."),
    "M04": (0.4, 0.0006, ["Деревина"], "Шпон дубовий натуральний 0,6 мм, радіальний розпил, у пачках по 24 листи."),
    "M05": (1.3, 0.0024, ["Деревина"], "Брус сосновий сухий стругований 40x60 мм, вологість 8-10 %, довжина 3 м."),
    "M06": (0.07, 0.0001, ["Плитні матеріали"], "Кромка ПВХ 22x2 мм, декор «дуб сонома» і білий, бухта 100 м."),
    "M07": (1.0, 0.001, ["Лаки, фарби, клеї"], "Клей ПВА меблевий D3, відро 10 кг. Зберігати при температурі від +5 °C."),
    "M08": (1.05, 0.001, ["Лаки, фарби, клеї"], "Лак поліуретановий двокомпонентний матовий, каністра 20 л, із затверджувачем."),
    "M09": (1.3, 0.001, ["Лаки, фарби, клеї"], "Фарба акрилова біла на водній основі для МДФ, відро 10 л."),
    "M10": (1.0, 0.001, ["Лаки, фарби, клеї"], "Морилка на водній основі, тон «горіх», каністра 5 л."),
    "M11": (0.09, 0.0001, ["Фурнітура"], "Петля меблева накладна з доводчиком, чашка 35 мм, з монтажною планкою."),
    "M12": (0.85, 0.0008, ["Фурнітура"], "Напрямні кулькові повного висування 450 мм, навантаження 35 кг, комплект на шухляду."),
    "M13": (0.06, 0.0001, ["Фурнітура"], "Ручка-скоба алюмінієва 128 мм, матовий хром."),
    "M14": (0.05, 0.0001, ["Фурнітура"], "Ніжка меблева регульована 100 мм, пластик, навантаження 150 кг."),
    "M15": (0.75, 0.0005, ["Кріплення"], "Конфірмат 7x50 мм, оцинкований, упаковка 100 шт."),
    "M16": (0.25, 0.0002, ["Кріплення"], "Шуруп універсальний 4x30 мм, жовтий цинк, упаковка 100 шт."),
    "M17": (0.45, 0.002, ["Тканини і наповнювачі"], "Тканина оббивна «рогожка», ширина 140 см, 320 г/м. кв., сірий меланж."),
    "M18": (1.0, 0.04, ["Тканини і наповнювачі"], "Поролон меблевий ST 2536, товщина 40 мм, лист 1x2 м."),
    "M19": (15.0, 0.006, ["Скло і дзеркала"], "Скло загартоване прозоре 6 мм, обробка кромки - полірування, порізка за розмірами."),
    "M20": (10.0, 0.004, ["Скло і дзеркала"], "Дзеркало срібне 4 мм з полірованою кромкою, порізка за розмірами."),
    "F01": (48.0, 0.21, ["Столи і стільці"], "Стіл обідній «Ясен» 160x90x75 см: стільниця з ламінованої ДСП дуб сонома, ніжки з масиву сосни під лаком. Постачається розібраним, фурнітура в комплекті. Гарантія 24 місяці."),
    "F02": (34.0, 0.14, ["Столи і стільці", "Офісні меблі"], "Стіл письмовий «Академія» 120x60x75 см з двома шухлядами на кулькових напрямних. Декор дуб сонома. Гарантія 24 місяці."),
    "F03": (6.5, 0.09, ["Столи і стільці", "М'які меблі"], "Стілець «Буковина» з м'яким сидінням, каркас із масиву сосни, оббивка «рогожка». Навантаження до 120 кг."),
    "F04": (19.0, 0.42, ["М'які меблі"], "Крісло м'яке «Затишок»: каркас із бруса і фанери, наповнювач - поролон 40 мм, оббивка «рогожка». Гарантія 18 місяців."),
    "F05": (182.0, 0.62, ["Корпусні меблі"], "Шафа-купе «Модерн» 220x240x60 см, двоє дверей із дзеркалом, чотири шухляди. Доставка і складання - окремими послугами."),
    "F06": (96.0, 0.38, ["Корпусні меблі", "Офісні меблі"], "Шафа книжкова «Бібліотека» 90x200x35 см зі скляними дверцятами, п'ять полиць."),
    "F07": (58.0, 0.24, ["Корпусні меблі"], "Комод «Львів» 100x85x45 см, чотири шухляди на кулькових напрямних, МДФ під білою фарбою."),
    "F08": (17.0, 0.08, ["Корпусні меблі"], "Тумба приліжкова «Соната» 45x50x40 см з однією шухлядою, МДФ під білою фарбою."),
    "SV1": (0.0, 0.0, ["Послуги"], "Доставка меблів по Україні власним транспортом або перевізником. Ціна за одну адресу до 300 км від Львова."),
    "SV2": (0.0, 0.0, ["Послуги"], "Збирання меблів у замовника бригадою з двох монтажників. Ціна за один виїзд."),
    "D01": (0.19, 0.0012, ["Рами і гвинти"], "Рама карбонова 7 дюймів «Шершень»: плити 5 мм, промені змінні, кріплення в комплекті."),
    "D02": (0.036, 0.0001, ["Мотори і регулятори"], "Мотор безколекторний 2207 1950KV, вал 5 мм, дроти 20AWG 150 мм."),
    "D03": (0.016, 0.0001, ["Мотори і регулятори", "Електроніка"], "Регулятор ESC 4-в-1 45 А, 3-6S, прошивка BLHeli_32."),
    "D04": (0.009, 0.0001, ["Електроніка"], "Політний контролер F722 з барометром і чорною скринькою 16 МБ, кріплення 30,5x30,5 мм."),
    "D05": (0.002, 0.0001, ["Електроніка", "Зв'язок і відео"], "Приймач ELRS 2,4 ГГц з керамічною антеною."),
    "D06": (0.006, 0.0001, ["Зв'язок і відео"], "Камера FPV Nano 1200TVL, об'єктив 2,1 мм, 5-36 В."),
    "D07": (0.021, 0.0001, ["Зв'язок і відео"], "Відеопередавач VTX 5,8 ГГц 1,6 Вт з радіатором, роз'єм MMCX."),
    "D08": (0.008, 0.0001, ["Зв'язок і відео"], "Антена відео 5,8 ГГц RHCP, роз'єм MMCX, довжина 90 мм."),
    "D09": (0.007, 0.0002, ["Рами і гвинти"], "Пропелер 7 дюймів трилопатевий, полікарбонат, посадка 5 мм."),
    "D10": (0.46, 0.0004, ["Акумулятори"], "Акумулятор Li-ion 6S2P 3500 мА·год, роз'єм XT60, з балансиром."),
    "D11": (0.35, 0.006, ["Пакування"], "Комплект пакування: ремінець акумулятора, коробка з гофрокартону, поролоновий ложемент."),
    "D12": (0.31, 0.002, ["Рами і гвинти"], "Рама карбонова 10 дюймів «Оса»: плити 6 мм, посилений центр."),
    "D13": (0.072, 0.0002, ["Мотори і регулятори"], "Мотор безколекторний 2810 900KV, вал 5 мм."),
    "D14": (0.012, 0.0004, ["Рами і гвинти"], "Пропелер 10 дюймів дволопатевий, нейлон зі скловолокном."),
    "D15": (0.82, 0.0007, ["Акумулятори"], "Акумулятор Li-ion 6S3P 6000 мА·год, роз'єм XT90."),
    "FPV7": (0.78, 0.008, ["Дрони"], "FPV-дрон «Шершень» 7 дюймів: корисне навантаження до 1,5 кг, дальність до 10 км, аналогове відео 5,8 ГГц, ELRS 2,4 ГГц. Акумулятор у комплекті. Гарантія 6 місяців."),
    "FPV10": (1.45, 0.014, ["Дрони"], "FPV-дрон «Оса» 10 дюймів: корисне навантаження до 3 кг, дальність до 15 км. Акумулятор 6000 мА·год у комплекті. Гарантія 6 місяців."),
}
# Примітки для складу: приймання (in), відвантаження (out), внутрішнє переміщення (int).
PICKING_NOTES = {
    "M01": ("in", "Розвантажувати навантажувачем. Зберігати горизонтально на рівних прокладках, не вище 30 листів у стосі."),
    "M02": ("in", "Розвантажувати навантажувачем. Берегти ламінат від подряпин: між пачками - картон."),
    "M19": ("in", "Крихке. Перевозити і зберігати вертикально на пірамідах із прокладками. Приймати з оглядом кожного листа."),
    "M20": ("in", "Крихке. Зберігати вертикально, дзеркальний шар не торкатися руками."),
    "M08": ("in", "Легкозаймисте. Зберігати в шафі для ЛФМ при +5…+30 °C, каністри закриті."),
    "D10": ("in", "Літій-іонні акумулятори, клас 9. Приймати з перевіркою напруги, зберігати у вогнетривкій шафі із зарядом 40-60 %."),
    "D15": ("in", "Літій-іонні акумулятори, клас 9. Приймати з перевіркою напруги, зберігати у вогнетривкій шафі із зарядом 40-60 %."),
}
# постачальник (ref) -> (префікс коду, днів поставки, діє з, діє до, знижка %)
SUPPLIER_TERMS = {
    "DEMO-S01": ("КЛ", 7, "2026-01-01", "2026-12-31", 0.0),
    "DEMO-S02": ("ПЗ", 3, "2026-01-01", "2026-12-31", 3.0),
    "DEMO-S03": ("ФС", 5, "2026-01-01", "2026-12-31", 2.0),
    "DEMO-S04": ("ТГ", 7, "2026-01-01", "2026-12-31", 0.0),
    "DEMO-S05": ("ЛФ", 4, "2026-01-01", "2026-12-31", 0.0),
    "AERO-S01": ("ПР", 5, "2026-06-01", "2026-12-31", 0.0),
    "AERO-S90": ("SP", 35, "2026-06-01", "2026-12-31", 0.0),
}
# виріб -> (днів виробництва, днів підготовки, днів до відвантаження покупцю)
LEAD_TIMES = {"F01": (2, 1, 7), "F02": (2, 1, 7), "F03": (1, 1, 5), "F04": (2, 1, 7), "F05": (5, 2, 14),
              "F06": (3, 1, 10), "F07": (3, 1, 10), "F08": (1, 1, 5), "FPV7": (2, 1, 5), "FPV10": (2, 1, 5),
              "SV1": (0, 0, 2), "SV2": (0, 0, 3)}


def products():
    tags = {}
    for _w, _v, names, _d in PRODUCTS.values():
        for n in names:
            if n not in tags:
                tags[n] = ensure("product.tag", [["name", "=", n]], {"name": n})
    rows = call("product.template", "search_read", [["default_code", "in", list(PRODUCTS)]],
                fields=["default_code", "sale_ok", "purchase_ok", "type", "product_variant_ids", "seller_ids"],
                context={"active_test": False}, order="id")
    by_code = {r["default_code"]: r for r in rows}
    services = [by_code[c]["id"] for c in ("SV1", "SV2") if c in by_code]
    sellers = {}
    for s in call("product.supplierinfo", "search_read", [], fields=["partner_id", "product_tmpl_id"]):
        sellers.setdefault(s["product_tmpl_id"][0], s["partner_id"][1])
    tmpl, variant = {}, {}
    for n, r in enumerate(rows, 1):
        code = r["default_code"]
        weight, volume, names, text = PRODUCTS[code]
        aero = code.startswith(("D", "FPV"))
        made = code.startswith("F")
        # Вага і об'єм зберігаються з двома знаками: дрібна фурнітура і електроніка дають нуль, їх не пишемо.
        vals = {"weight": round(weight, 2), "volume": round(volume, 2), "product_tag_ids": m2m([tags[x] for x in names]),
                "description_sale": text if r["sale_ok"] else False,
                "description_purchase": text if r["purchase_ok"] else False}
        if r["sale_ok"] and code in LEAD_TIMES:
            vals["sale_delay"] = LEAD_TIMES[code][2]
        if made and not aero:
            vals["optional_product_ids"] = m2m(services)
            vals["description_pickingout"] = ("Пакувати в гофрокартон із захистом кутів. На кожному місці - етикетка "
                                              "з номером замовлення і кількістю місць.")
            vals["description"] = html("Виготовляємо під замовлення і на склад. Специфікація і технологічна карта - "
                                       "у розділі «Виробництво».")
        elif made:
            vals["description_pickingout"] = ("Відвантажувати в заводській коробці з ложементом. Серійний номер "
                                              "вписати у видаткову накладну і гарантійний талон.")
            vals["description"] = html("Серійний облік. Кожен виріб проходить ВТК і льотний тест, протокол - у «Якості».")
        elif r["type"] == "service":
            vals["description"] = html("Послуга для покупців меблів, у рахунку йде окремим рядком.")
        else:
            vals["description"] = html("Основний постачальник: %s. Мінімальний залишок тримає правило поповнення складу."
                                       % sellers.get(r["id"], "визначається запитом цін"))
        if code in PICKING_NOTES:
            kind, note = PICKING_NOTES[code]
            vals["description_pickingin"] = note
            vals["description_picking"] = note
        tmpl[r["id"]] = vals
        if r["type"] != "service" and r["product_variant_ids"]:
            # EAN-13 з українським префіксом 482: окремий діапазон на компанію, номер - порядок товару.
            body = ("4820456" if aero else "4820123") + f"{n:05d}"
            variant[r["product_variant_ids"][0]] = {"barcode": ean13(body)}
    fill("product.template", tmpl)
    fill("product.product", variant)
    # Прайси постачальників: код і назва товару в постачальника, строк поставки, строк дії ціни.
    wanted = {}
    partners_ref = {partner_by_ref(ref): ref for ref in SUPPLIER_TERMS}
    names = {r["id"]: r for r in call("product.template", "search_read", [], fields=["name", "default_code"],
                                      context={"active_test": False})}
    for s in call("product.supplierinfo", "search_read", [], fields=["partner_id", "product_tmpl_id"]):
        ref = partners_ref.get(s["partner_id"][0])
        if not ref:
            continue
        prefix, delay, start, end, discount = SUPPLIER_TERMS[ref]
        t = names[s["product_tmpl_id"][0]]
        short = re.sub(r"\s*\([^)]*\)\s*$", "", t["name"])
        wanted[s["id"]] = {"product_code": f"{prefix}-{t['default_code']}-{s['id']:03d}", "product_name": short,
                           "delay": delay, "date_start": start, "date_end": end, "discount": discount}
    fill("product.supplierinfo", wanted)
    # Специфікації: код, тип операції «Виробництво» своєї компанії, строки.
    boms = {}
    for b in call("mrp.bom", "search_read", [], fields=["product_tmpl_id", "company_id"]):
        code = names[b["product_tmpl_id"][0]]["default_code"]
        cid = b["company_id"][0]
        op = call("stock.picking.type", "search", [["code", "=", "mrp_operation"], ["company_id", "=", cid]], limit=1)
        produce, prepare, _sale = LEAD_TIMES.get(code, (2, 1, 7))
        boms[b["id"]] = {"code": f"СП-{code}/2026", "picking_type_id": op and op[0],
                         "produce_delay": produce, "days_to_prepare_mo": prepare}
    fill("mrp.bom", boms)
    say(f"7. Товари: {len(tmpl)} (вага, об'єм, мітки, описи, строки), штрихкодів EAN-13 {len(variant)}; "
        f"прайсів постачальників {len(wanted)}; специфікацій {len(boms)}.")


# =====================================================================================
# 8. Виробництво і склад: робочі центри, замовлення, партії
# =====================================================================================
# код центру -> (мітки, хв. на налагодження, хв. на прибирання, опис)
WORKCENTERS = {
    "ЯМ-РОЗКР": (["Механічна обробка"], 10, 5, "Форматно-розкрійний верстат Altendorf F45 (ОЗ-005) і обробний центр Homag (ОЗ-001). Два верстатники в зміну."),
    "ЯМ-КРАЙК": (["Механічна обробка"], 15, 5, "Крайколичкувальний верстат Brandt (ОЗ-006). Перед зміною декору - прогрів клейового вузла 15 хвилин."),
    "ЯМ-СКЛАД": (["Складання"], 5, 10, "Шість верстаків (ОЗ-013), присадка на Vitap Alfa 21 (ОЗ-007). Бригада столярів."),
    "ЯМ-ПАК": (["Пакування"], 5, 5, "Пакувальний стіл, гофрокартон і захисні кути. Етикетки друкує принтер Zebra (ОЗ-024)."),
    "РОЗКР": (["Механічна обробка"], 10, 10, "Портальний фрезерний верстат з ЧПК для карбону (АС-ОЗ-007). Після кожної плити - прибирання пилу."),
    "ПАЙКА": (["Електромонтаж"], 5, 5, "Паяльна станція JBC (АС-ОЗ-002) на антистатичних робочих місцях (АС-ОЗ-009)."),
    "ПРОШ": (["Електромонтаж", "Налаштування"], 5, 0, "Прошивка політного контролера і регуляторів, налаштування каналів зв'язку."),
    "ЗБИР": (["Складання"], 5, 5, "Складання рами, встановлення моторів, камери і відеопередавача."),
    "ВТК": (["Контроль якості"], 10, 5, "Стенд тяги моторів (АС-ОЗ-006), осцилограф (АС-ОЗ-003), льотний тест на майданчику."),
    "ПАК": (["Пакування"], 5, 5, "Комплектування коробки: дрон, акумулятор, ремінець, паспорт виробу."),
}


def production():
    tags = {}
    wanted = {}
    for r in call("mrp.workcenter", "search_read", [["code", "in", list(WORKCENTERS)]], fields=["code"],
                  context={"active_test": False}):
        names, start, stop, text = WORKCENTERS[r["code"]]
        for n in names:
            if n not in tags:
                tags[n] = ensure("mrp.workcenter.tag", [["name", "=", n]], {"name": n})
        wanted[r["id"]] = {"tag_ids": m2m([tags[n] for n in names]), "time_start": start, "time_stop": stop,
                           "note": html(text)}
    fill("mrp.workcenter", wanted)
    # Замовлення на виробництво: кінцевий термін - день планового завершення.
    orders = {}
    for r in call("mrp.production", "search_read", [], fields=["date_start", "date_finished", "state"]):
        end = r["date_finished"] or r["date_start"]
        if end and r["date_start"] and end < r["date_start"]:
            end = r["date_start"]          # у частини замовлень «АероСічі» початок - день збірки демо
        orders[r["id"]] = {"date_deadline": end and (end[:10] + " 15:00:00")}
    fill("mrp.production", orders)
    # Партії і серійні номери: посилання на документ постачальника або паспорт виробу, примітка.
    lots = {}
    for r in call("stock.lot", "search_read", [], fields=["name", "product_id"]):
        product = r["product_id"][1]
        if "Акумулятор" in product:
            lots[r["id"]] = {"ref": "SKY-" + r["name"][-7:],
                             "note": html("Партія Shenzhen SkyParts, митна декларація UA209140/2026/018374. "
                                          "Напруга при прийманні 3,7-3,8 В на елемент. Строк зберігання 24 місяці.")}
        else:
            lots[r["id"]] = {"ref": "Паспорт виробу № " + r["name"],
                             "note": html("Серійний номер нанесено на раму і коробку. Прошивка Betaflight 4.5, "
                                          "протокол ВТК і льотного тесту додано до паспорта.")}
    fill("stock.lot", lots)
    say(f"8. Виробництво: робочих центрів {len(wanted)}, замовлень {len(orders)}, партій і серійних номерів {len(lots)}.")


# =====================================================================================
# 9. Продажі, закупівлі, CRM, рахунки
# =====================================================================================
SALE_NOTE = ("Товар відвантажується зі складу в с. Сокільники після оплати згідно з умовами договору. "
             "Гарантія на меблі 24 місяці. Претензії щодо кількості і якості приймаємо протягом 14 днів від дати поставки.")
AERO_SALE_NOTE = ("Постачання зі складу у Львові. Кожен виріб проходить ВТК і льотний тест, серійні номери - "
                  "у видатковій накладній. Гарантія 6 місяців, крім бойових і механічних пошкоджень.")
PURCHASE_NOTE = ("Поставка на склад покупця: Львівська обл., с. Сокільники, вул. Промислова, 8, у робочі дні з 8:00 до 16:00. "
                 "З товаром - видаткова накладна, ТТН і сертифікати якості. Податкову накладну реєструйте в ЄРПН у строк.")
AERO_PURCHASE_NOTE = "Поставка на склад: м. Львів, вул. Наукова, 7а, корпус Б. З товаром - видаткова накладна і сертифікати."
# ref покупця -> (номер договору, дата, мітки замовлень)
CONTRACTS = {
    "DEMO-C01": ("Д-12/2024", "2024-02-12", ["Дилер", "Повторний покупець"]),
    "DEMO-C02": ("П-07/2025", "2025-04-03", ["Роздріб", "Повторний покупець"]),
    "DEMO-C03": ("П-21/2026", "2026-07-20", ["Роздріб"]),
    "DEMO-C04": ("П-18/2026", "2026-06-25", ["Проєкт"]),
    "DEMO-C05": ("Д-03/2025", "2025-01-15", ["Дилер"]),
    "DEMO-C06": ("П-24/2026", "2026-08-03", ["Проєкт"]),
    "DEMO-C07": ("П-26/2026", "2026-08-21", ["Тендер", "Держзамовлення"]),
    "DEMO-C08": ("П-15/2026", "2026-06-08", ["Роздріб"]),
    "DEMO-C09": ("П-22/2026", "2026-07-30", ["Роздріб"]),
    "DEMO-C10": ("П-27/2026", "2026-08-28", ["Роздріб"]),
    "DEMO-C11": ("П-28/2026", "2026-09-01", ["Проєкт"]),
    "DEMO-C12": ("EXP-02/2026", "2026-08-17", ["Експорт"]),
    "AERO-C01": ("АС-05/2026", "2026-08-10", ["Проєкт"]),
    "AERO-C02": ("АС-07/2026", "2026-08-24", ["Держзамовлення"]),
    "AERO-C03": ("АС-08/2026", "2026-09-01", ["Благодійний фонд"]),
}
# Нагоди: назва (початок) -> (контакт, посада, очікуване закриття, мітки, джерело, від кого, сайт, опис)
LEADS = {
    "Мережа кав'ярень": ("Гураль Ірина Степанівна", "Менеджерка із закупівель", "2026-10-30", ["Проєкт", "Дилер"], "Рекомендація клієнта",
                         "Меблевий дім Галичина", "https://kava-lviv.example.ua",
                         "Сім кав'ярень, відкриття двох нових у листопаді. Потрібні 40 столів 70x70 і 120 стільців «Буковина» "
                         "в оббивці з каталогу замовника. Просять зразок стільця до 2026-10-15 і розстрочку на 60 днів."),
    "Готель «Дністер»": ("Григорчук Марія Іванівна", "Керуюча готелем", "2026-11-20", ["Проєкт"], "Виставка «Меблі Експо»", "", "https://dnister-hotel.example.ua",
                         "Реновація 30 номерів: ліжка, тумби «Соната», письмові столи, шафи. Є дизайн-проєкт, чекають "
                         "кошторис за трьома варіантами оздоблення. Рішення приймає власник після презентації."),
    "Коворкінг «Хаб 14»": ("Шаповал Катерина Сергіївна", "Провідна фахівчиня з постачання", "2026-11-05", ["Проєкт"], "Сайт компанії", "", "https://hub14.example.ua",
                           "60 робочих місць: столи «Академія» 120x60 з кабель-каналом і тумби. Відкриття нового поверху 1 грудня. "
                           "Конкурент дає ціну на 6 % нижче, але строк 8 тижнів проти наших 4."),
    "ТОВ «Школярик»": ("Заяць Роман Ігорович", "Менеджер тендерного відділу", "2026-10-25", ["Тендер", "Держзамовлення"], "Тендерний майданчик", "", "",
                       "Парти і стільці для трьох шкіл Тернопільської громади, закупівля через майданчик. Потрібні сертифікати "
                       "відповідності і висновок СЕС. Подання пропозицій до 2026-10-20."),
    "Салон «Інтер'єр Плюс»": ("Мазур Денис Олегович", "Керівник салону", "2026-11-15", ["Роздріб", "Повторний покупець"], "Повторне звернення", "", "",
                              "Шафи-купе «Модерн» під розміри замовників салону, орієнтовно 10-12 шаф на місяць. "
                              "Домовляємося про строки виготовлення і виставковий зразок у салоні."),
    "ФОП Бондаренко": ("Бондаренко Ігор Петрович", "Власник", "2026-09-30", ["Роздріб"], "Холодний дзвінок", "", "",
                       "Фасади з МДФ під фарбою для власного виробництва кухонь, 40-50 м. кв. на місяць. "
                       "Після розрахунку ціни замовник обрав місцевого виробника фасадів."),
    "ТОВ «Дніпро Меблі»": ("Остапенко Юлія Миколаївна", "Категорійна менеджерка", "2026-12-15", ["Дилер"], "Повторне звернення", "", "",
                           "Дилерська угода на 2027 рік: план закупівель 2,1 млн грн, знижка від обсягу, ексклюзив на Дніпро. "
                           "Зустріч на фабриці призначена на листопад."),
    "Drewno Sp. z o.o.": ("Katarzyna Wiśniewska", "Specjalista ds. zakupów", "2026-11-28", ["Експорт"], "Виставка «Меблі Експо»", "", "https://drewno.example.pl",
                          "Друга партія обідніх столів «Ясен», 60 штук, умови FCA Львів. Потрібні фітосанітарний сертифікат "
                          "і маркування польською мовою."),
    "ТОВ «Затишна оселя»": ("Павленко Аліна Юріївна", "Менеджерка із закупівель", "2026-11-10", ["Роздріб"], "Сайт компанії", "", "",
                            "Гардеробні системи на основі шаф «Модерн» для салону в Одесі, пробна партія 8 комплектів."),
    "ФОП Марченко": ("Марченко Тетяна Василівна", "Дизайнерка, власниця студії", "2026-10-20", ["Проєкт"], "Рекомендація клієнта", "ФОП Левченко Оксана Миколаївна", "",
                     "Меблі для дизайн-студії: два столи, книжкова шафа і комод у білому кольорі. Просить фото готових робіт."),
}
LOST_LEAD = "ФОП Бондаренко"


def _terms(cid):
    """Умови оплати контрагентів у компанії: {контрагент: (покупця, постачальника)}."""
    rows = call("res.partner", "search_read", [["ref", "!=", False]],
                fields=["ref", "property_payment_term_id", "property_supplier_payment_term_id"], co=cid,
                context={"active_test": False})
    return {r["id"]: (r["property_payment_term_id"] and r["property_payment_term_id"][0],
                      r["property_supplier_payment_term_id"] and r["property_supplier_payment_term_id"][0], r["ref"])
            for r in rows}


def documents():
    counts = {}
    for cid in ALL:
        terms = _terms(cid)
        aero = cid == AERO
        # --- замовлення покупців
        leads = {l["partner_id"][0]: l["id"] for l in call(
            "crm.lead", "search_read", [["company_id", "=", cid], ["partner_id", "!=", False]],
            fields=["partner_id"], co=cid, order="id desc")} if has_model("crm.lead") else {}
        wanted = {}
        for so in call("sale.order", "search_read", [["company_id", "=", cid]],
                       fields=["partner_id", "effective_date", "date_order", "client_order_ref", "invoice_status"], co=cid):
            pid = so["partner_id"][0]
            term, _s, ref = terms.get(pid, (False, False, ""))
            number, day, tags = CONTRACTS.get(ref, (False, False, []))
            export = ref == "DEMO-C12"
            vals = {"payment_term_id": term, "ua_contract_number": number, "ua_contract_date": day,
                    "note": html(AERO_SALE_NOTE if aero else SALE_NOTE),
                    "tag_ids": m2m([REF["stag"][t] for t in tags]),
                    "commitment_date": so["effective_date"] or "2026-10-20 10:00:00",
                    "origin": f"Заявка покупця {so['client_order_ref'] or ''} (e-mail)".replace("  ", " ")}
            if export:
                vals.update(incoterm=REF["incoterm"].get("FCA"), incoterm_location="Львів, Україна")
            if not so["effective_date"] and pid in leads:
                vals["opportunity_id"] = leads[pid]       # ще не відвантажене замовлення виросло з нагоди
            wanted[so["id"]] = vals
        fill("sale.order", wanted, co=cid)
        counts["sale.order"] = counts.get("sale.order", 0) + len(wanted)
        # --- замовлення постачальникам
        wanted = {}
        for po in call("purchase.order", "search_read", [["company_id", "=", cid]], fields=["partner_id"], co=cid):
            _c, term, ref = terms.get(po["partner_id"][0], (False, False, ""))
            vals = {"payment_term_id": term, "note": html(AERO_PURCHASE_NOTE if aero else PURCHASE_NOTE)}
            if ref == "AERO-S90":
                vals.update(incoterm_id=REF["incoterm"].get("DAP"), incoterm_location="Львів, Україна",
                            note=html("Delivery DAP Lviv, Ukraine. Customs clearance by the buyer. "
                                      "Packing list and commercial invoice with each shipment."))
            wanted[po["id"]] = vals
        fill("purchase.order", wanted, co=cid)
        counts["purchase.order"] = counts.get("purchase.order", 0) + len(wanted)
        # --- рахунки покупцям і від постачальників. Проведений рахунок Odoo дає змінити не скрізь:
        #     що не дозволено (умови оплати проведеного рахунку), потрапляє у список відмов.
        wanted = {}
        for mv in call("account.move", "search_read",
                       [["company_id", "=", cid], ["move_type", "in", ["out_invoice", "in_invoice", "out_refund"]]],
                       fields=["partner_id", "move_type", "state", "invoice_date", "ref", "name", "invoice_origin"], co=cid):
            pid = mv["partner_id"][0]
            cterm, sterm, ref = terms.get(pid, (False, False, ""))
            sale = mv["move_type"] in ("out_invoice", "out_refund")
            number, day, _tags = CONTRACTS.get(ref, (False, False, []))
            vals = {"payment_mode_id": (REF["mode_in"] if sale else REF["mode_out"]).get(cid)}
            if mv["state"] == "draft":
                vals["invoice_payment_term_id"] = cterm if sale else sterm
            if sale:
                basis = f"Договір № {number} від {day}. " if number else ""
                vals["narration"] = html(basis + ("Оплата на поточний рахунок за реквізитами продавця. "
                                                  "У призначенні платежу вкажіть номер рахунка."))
                vals["taxable_supply_date"] = mv["invoice_date"]
            else:
                vals["narration"] = html(f"Первинний документ постачальника: {mv['ref'] or 'рахунок'}. "
                                         "Оригінал у папці «Закупівлі» за місяць документа.")
                vals["payment_reference"] = f"Оплата згідно з документом: {mv['ref'] or 'рахунок'} від {mv['invoice_date']}"
                vals["delivery_date"] = mv["invoice_date"]
            if ref == "DEMO-C12":
                vals.update(invoice_incoterm_id=REF["incoterm"].get("FCA"), incoterm_location="Львів, Україна")
            if ref == "AERO-S90":
                vals.update(invoice_incoterm_id=REF["incoterm"].get("DAP"), incoterm_location="Львів, Україна")
            wanted[mv["id"]] = vals
        fill("account.move", wanted, co=cid)
        counts["account.move"] = counts.get("account.move", 0) + len(wanted)
    crm_leads()
    say(f"9. Документи: замовлень покупців {counts.get('sale.order', 0)}, замовлень постачальникам "
        f"{counts.get('purchase.order', 0)}, рахунків {counts.get('account.move', 0)}, нагод {len(LEADS)}.")


def crm_leads():
    if not has_model("crm.lead"):
        return
    rows = call("crm.lead", "search_read", [], fields=["name", "partner_id", "active", "probability"],
                context={"active_test": False})
    partners_state = {r["id"]: (r["state_id"] and r["state_id"][0], r["street2"]) for r in call(
        "res.partner", "read", list({r["partner_id"][0] for r in rows if r["partner_id"]}), ["state_id", "street2"])}
    wanted, lost = {}, None
    for r in rows:
        key = next((k for k in LEADS if r["name"].startswith(k)), None)
        if not key:
            continue
        person, function, deadline, tags, source, referred, site, text = LEADS[key]
        wanted[r["id"]] = {"contact_name": person, "function": function, "date_deadline": deadline,
                           "tag_ids": m2m([REF["stag"][t] for t in tags]), "source_id": REF["source"][source],
                           "referred": referred, "website": site, "description": html(text),
                           "state_id": r["partner_id"] and partners_state.get(r["partner_id"][0], (False, False))[0],
                           "street2": r["partner_id"] and partners_state.get(r["partner_id"][0], (False, False))[1]}
        if key == LOST_LEAD:
            lost = r
    fill("crm.lead", wanted)
    if lost and lost["active"]:
        # Одна програна нагода: штатна дія «Позначити як втрачену» з причиною з довідника.
        reason = call("crm.lost.reason", "search", [["name", "ilike", "дорого"]], limit=1) \
            or call("crm.lost.reason", "search", [], limit=1)
        try:
            call("crm.lead", "action_set_lost", [lost["id"]], lost_reason_id=reason and reason[0])
            stat("crm.lead")["fields"].add("lost_reason_id")
            stat("crm.lead")["changed"] += 1
        except RpcError as e:
            REFUSED.append(("crm.lead", "lost_reason_id", str(e).splitlines()[0][:160]))
    elif lost:
        stat("crm.lead")["fields"].add("lost_reason_id")


# =====================================================================================
# 10. Решта власних і підключених модулів
# =====================================================================================
def bank_connect():
    """Підключення банків: ПриватБанк уже працює (з'єднання є), Monobank - ключ замовлено."""
    if not has_model("ua.bank.connect"):
        return 0
    rows = call("ua.bank.connect", "search_read", [], fields=["journal_id", "service", "state", "provider_id", "step_ids"])
    done = 0
    for r in rows:
        provider = call("online.bank.statement.provider", "search_read", [["journal_id", "=", r["journal_id"][0]]],
                        fields=["ua_account"], limit=1, context={"active_test": False})
        acc = provider and provider[0]["ua_account"]
        privat = r["service"] == "ua_privat"
        vals = {"account": acc, "requested_date": "2026-09-14" if privat else "2026-10-01",
                "note": ("Автоклієнт увімкнув директор у Приват24 для бізнесу. Ключ передано через сховище паролів, "
                         "заміна ключа - у вересні 2027." if privat else
                         "Токен mono Бізнес замовлено, чекаємо відповіді банку. До того виписку еквайрингу вантажимо файлом.")}
        if privat:
            vals.update(received_date="2026-09-18", provider_id=provider and provider[0]["id"])
        changed = fill("ua.bank.connect", {r["id"]: vals})
        target = "connected" if privat and provider else "requested"
        if r["state"] == "draft":
            call("ua.bank.connect", "write", [r["id"]], {"state": target})
            steps = call("ua.bank.connect.step", "search_read", [["connect_id", "=", r["id"]]],
                         fields=["done"], order="sequence, id")
            ready = steps if privat else steps[:2]
            day = "2026-09-18" if privat else "2026-10-01"
            ids = [s["id"] for s in ready if not s["done"]]
            if ids:
                call("ua.bank.connect.step", "write", ids, {"done": True, "done_date": day})
            changed = changed or [r["id"]]
        done += 1
    return done


def kyc():
    """Знімок ЄДР у справах KYC - ті самі дані, що в картці контрагента. Рішень не ставимо: вони йдуть через міст."""
    if not has_model("kyc.case"):
        return 0
    wanted = {}
    for c in call("kyc.case", "search_read", [], fields=["partner_id", "stage"], context={"active_test": False}):
        p = call("res.partner", "read", [c["partner_id"][0]],
                 ["ref", "ua_edr_registration_date", "ua_vat_status", "ua_edr_head", "ua_edr_capital"])[0]
        card = P.get(p["ref"] or "", {})
        vals = {"docs_requested_at": "2026-09-18 08:00:00"}
        if c["stage"] in ("screen", "assess", "done"):
            head = p["ua_edr_head"]
            capital = f"{p['ua_edr_capital']:,.2f}".replace(",", " ")
            owners = (f"{head} - засновник і кінцевий бенефіціарний власник, частка 100 %, внесок {capital} грн"
                      if head and not card.get("checks") else
                      f"Засновник - фізична особа, громадянин України, частка 100 %. Керівник з 2026-03-02: {head}.")
            vals.update({
                "registry_date": p["ua_edr_registration_date"], "registry_vat": p["ua_vat_status"],
                "registry_head": head, "registry_capital": p["ua_edr_capital"], "screened_at": "2026-09-22 09:40:00",
                "registry_beneficiaries": owners,
            })
        wanted[c["id"]] = vals
    fill("kyc.case", wanted)
    return len(wanted)


def purchase_requests():
    if not has_model("purchase.request"):
        return 0
    wanted = {r["id"]: {"assigned_to": REF["buyer"]} for r in call("purchase.request", "search_read", [], fields=["state"])}
    fill("purchase.request", wanted, co=MEBLI)
    lines = {}
    for l in call("purchase.request.line", "search_read", [], fields=["product_id", "product_qty"]):
        code = re.match(r"\[(\w+)\]", l["product_id"][1] if l["product_id"] else "")
        text = PRODUCTS.get(code.group(1), (0, 0, [], ""))[3] if code else ""
        lines[l["id"]] = {"specifications": (text + " Заміна на аналог - лише за погодженням з технологом.").strip()}
    fill("purchase.request.line", lines, co=MEBLI)
    return len(wanted)


def report_run():
    """Наявний звітний прогін доводимо кнопками до «Подано», якщо перевірки модуля це дозволяють."""
    if not has_model("ua.report.run"):
        return "немає моделі"
    runs = call("ua.report.run", "search_read", [], fields=["name", "state", "month", "year"], order="id", limit=1)
    if not runs:
        return "прогонів немає"
    run = runs[0]
    stat("ua.report.run")["ids"].add(run["id"])
    stat("ua.report.run")["fields"].update(["submitted_date", "submitted_by", "note"])
    # Помилки перевірок прогону - кадрові і зарплатні (чернетки листків, РНОКПП): їх виправляє
    # demo_company.py. Поки вони є, action_generate відмовить, тож кнопок не тиснемо зовсім.
    errors = call("ua.report.check", "search_read", [["run_id", "=", run["id"]], ["level", "=", "error"]],
                  fields=["title", "detail"])
    if run["state"] in ("draft", "checked") and errors:
        REFUSED.append(("ua.report.run", "submitted_date", "перевірки прогону з помилками: "
                        + "; ".join(f"{c['title']} ({c['detail']})" for c in errors)[:200]))
    else:
        try:
            for state, method in (("draft", "action_refresh"), ("checked", "action_generate"),
                                  ("generated", "action_mark_submitted")):
                if call("ua.report.run", "read", [run["id"]], ["state"])[0]["state"] == state:
                    call("ua.report.run", method, [run["id"]])
                    stat("ua.report.run")["changed"] += 1
        except RpcError as e:
            REFUSED.append(("ua.report.run", "submitted_date", str(e).splitlines()[0][:160]))
    now = call("ua.report.run", "read", [run["id"]], ["state", "submitted_date"])[0]
    if now["state"] == "submitted":
        # Дія ставить «сьогодні»; повідомлення за вересень подавали наприкінці вересня.
        day = "%04d-%02d-28" % (run["year"], run["month"] or 9)
        if now["submitted_date"] != day:
            call("ua.report.run", "write", [run["id"]], {"submitted_date": day})
        fill("ua.report.run", {run["id"]: {"note": "Подано через Електронний кабінет, квитанцію № 2 отримано того ж дня."}})
    return f"{run['name']}: {now['state']}"


def other():
    done = bank_connect()
    cases = kyc()
    requests = purchase_requests()
    run = report_run()
    extra = []
    if has_model("ua.staff.list"):
        rows = call("ua.staff.list", "search_read", [], fields=["order_number", "order_date"])
        fill("ua.staff.list", {r["id"]: {"order_ref": f"Наказ № {r['order_number']} від {r['order_date']}",
                                         "note": "Затверджено наказом директора, введено в дію з дати розпису. "
                                                 "Зміни вносяться окремим наказом."}
                               for r in rows if r["order_number"] and r["order_date"]})
        extra.append(f"штатних розписів {len(rows)}")
    if has_model("ua.setup.profile"):
        rows = call("ua.setup.profile", "search", [])
        fill("ua.setup.profile", {i: {"note": "Анкету заповнила головний бухгалтер 2026-09-29, затвердив директор. "
                                              "Питання про ІТ-послуги і Дія.City лишено без відповіді: до виробництва меблів не стосуються."}
                                  for i in rows})
        extra.append(f"анкет {len(rows)}")
    say(f"10. Решта: підключень банку {done}, справ KYC {cases}, запитів на закупівлю {requests}, "
        f"звітний прогін - {run}; " + ", ".join(extra) + ".")


# =====================================================================================
# Контроль
# =====================================================================================
def balances():
    """Дт = Кт проведених проводок і баланс Ф1 (актив = пасив) по кожній компанії."""
    out, ok = [], True
    base = call("ir.model.data", "search_read", [["module", "=", "l10n_ua_finrep"], ["name", "=", "instance_f1"]],
                fields=["res_id"])
    for key in ("mebli", "logist", "aero"):
        if not CO[key]:
            continue
        cid, name = CO[key]["id"], CO[key]["name"]
        tot = call("account.move.line", "read_group", [["company_id", "=", cid], ["parent_state", "=", "posted"]],
                   ["debit:sum", "credit:sum"], [], co=cid)[0]
        dt, kt = round(tot["debit"] or 0.0, 2), round(tot["credit"] or 0.0, 2)
        line = f"  {name}: Дт {dt:,.2f}  Кт {kt:,.2f}  різниця {dt - kt:,.2f}"
        ok = ok and abs(dt - kt) < 0.005
        # Ф1 рахує рідний звіт l10n_ua_finrep: для головної компанії - сам, для решти - копія,
        # яку зробив demo_business.py. Нових копій тут не створюємо.
        ctx = {"allowed_company_ids": sorted({MEBLI, cid})}
        inst = base and base[0]["res_id"]
        if inst and cid != MEBLI:
            found = rpc("object", "execute_kw", DB, UID, PW, "mis.report.instance", "search",
                        [[["name", "=", f"Ф1. Баланс - {name}"]]], {"context": ctx})
            inst = found and found[0]
        if inst:
            try:
                res = rpc("object", "execute_kw", DB, UID, PW, "mis.report.instance", "compute", [[inst]], {"context": ctx})
                rows = {}
                for body in res.get("body", []):
                    m = re.match(r"^(\d{4})\b", body.get("label") or "")
                    cells = body.get("cells") or []
                    if m and cells and isinstance(cells[0], dict):
                        rows[m.group(1)] = cells[0].get("val") or 0.0
                a, p = rows.get("1300"), rows.get("1900")
                if a is None or p is None:
                    line += "; Ф1: немає рядків 1300/1900"
                else:
                    same = abs(a - p) < 1
                    ok = ok and same
                    line += f"; Ф1: актив {a:,.2f} = пасив {p:,.2f} -> " + ("сходиться" if same else f"РОЗБІЖНІСТЬ {a - p:,.2f}")
            except RpcError as e:
                line += "; Ф1 не порахувалась: " + str(e).splitlines()[0][:100]
        else:
            line += "; Ф1: звіту для компанії немає"
        out.append(line)
    return out, ok


STEPS = [("references", references), ("banks", banks), ("payment_modes", payment_modes), ("partners", partners),
         ("companies", companies), ("assets", assets), ("products", products), ("production", production),
         ("documents", documents), ("other", other)]
ALWAYS = ("references", "banks", "payment_modes")     # довідники потрібні решті кроків


def main():
    say("== наповнення полів: база %s на %s ==" % (DB, URL))
    before, _ok = balances()
    say("Баланс до прогону:\n" + "\n".join(before))
    errors = []
    for name, step in STEPS:
        if ONLY and name not in ONLY and name not in ALWAYS:
            continue
        try:
            step()
        except RpcError as e:
            errors.append(f"{name}: {str(e)[:500]}")
            say(f"ПОМИЛКА {name}: {str(e)[:500]}")
    say("\nПідсумок по моделях (записів охоплено; поля):")
    for model, st in STAT.items():
        say(f"  {model}: {len(st['ids'])}; " + ", ".join(sorted(st["fields"])))
    if REFUSED:
        say("\nСервер відмовив (поле лишилось як було):")
        seen = OrderedDict()
        for model, field, msg in REFUSED:
            seen.setdefault((model, field, msg), 0)
            seen[(model, field, msg)] += 1
        for (model, field, msg), n in seen.items():
            say(f"  {model}.{field} x{n}: {msg}")
    after, ok = balances()
    say("\nБаланс після прогону:\n" + "\n".join(after))
    say("\nЦим прогоном: нових записів %s, змінено наявних %s." % (
        sum(st["new"] for st in STAT.values()), sum(st["changed"] for st in STAT.values())))
    if not ok:
        errors.append("баланс не сходиться")
    if errors:
        say("\nНе все пройшло: " + " | ".join(errors))
        sys.exit(1)
    say("Готово: поля форм наповнено.")


if __name__ == "__main__":
    main()
