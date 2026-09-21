#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Демо-життя ТОВ «Ясен Меблі» за липень-вересень 2026 на базі demo.

Спершу проганяє наявні будівники зарплати і кадрів (demo_company, demo_hire,
demo_military, demo_bank, demo_card) на цій самій базі, потім додає бізнес:
контрагентів, номенклатуру зі специфікаціями, закупівлі, виробництво, продажі
з ПДВ, банк, касу, основні засоби, курси НБУ і CRM.

Ідемпотентно: кожен запис шукається за стійким ключем (ref контрагента,
default_code товару, partner_ref замовлення, code активу, ref проводки).

Запуск: python3 scripts/demo_business.py
Змінні: ODOO_URL (типово http://127.0.0.1:8131), DEMO_DB (типово demo),
        SKIP_PAYROLL=1 - не переганяти будівники зарплати.
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8131").rstrip("/")
DB = os.environ.get("DEMO_DB", "demo").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
COMPANY = 1

_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36")]
urllib.request.install_opener(_opener)


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


class RpcError(Exception):
    pass


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    sys.exit("Не вдалося увійти в базу %s на %s" % (DB, URL))


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def say(msg):
    print(msg, flush=True)


def upsert(model, domain, vals):
    ids = call(model, "search", domain)
    if ids:
        call(model, "write", [ids[0]], vals)
        return ids[0]
    return call(model, "create", vals)


# ---- коди з контрольними числами (ті самі функції, що в scripts/demo_company.py) ----
def rnokpp(birthday, sex, serial):
    days = (birthday - date(1899, 12, 31)).days
    body = f"{days:05d}{serial:03d}" + str((serial * 7 + (1 if sex == "male" else 0)) % 10 // 2 * 2 + (1 if sex == "male" else 0))
    w = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    return body + str(sum(int(c) * k for c, k in zip(body, w)) % 11 % 10)


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


# =====================================================================================
# 1. План рахунків і країна (запобіжник; звичайно це вже зробив demo_server.sh)
# =====================================================================================
def ensure_chart():
    co = call("res.company", "read", [COMPANY], ["country_id", "chart_template"])[0]
    ua = call("res.country", "search", [["code", "=", "UA"]])[0]
    if not co["country_id"] or co["country_id"][0] != ua:
        call("res.company", "write", [COMPANY], {"country_id": ua})
    if co["chart_template"] != "ua_psbo":
        say("План рахунків ua_psbo ще не завантажено - завантажуємо через try_loading.")
        call("account.chart.template", "try_loading", "ua_psbo", COMPANY, False)
        short_codes()
    say("План рахунків: ua_psbo, країна: Україна.")


def short_codes():
    """Код рахунку = код із шаблону (те саме, що робить hooks._short_codes)."""
    changed = 0
    data = call("ir.model.data", "search_read",
                [["model", "=", "account.account"], ["name", "like", "ua_psbp_"]],
                fields=["name", "res_id"])
    for d in data:
        m = re.search(r"ua_psbp_(\d+)$", d["name"])
        if not m:
            continue
        target = m.group(1)
        acc = call("account.account", "read", [d["res_id"]], ["code"])
        if not acc or acc[0]["code"] == target:
            continue
        if call("account.account", "search_count", [["code", "=", target]]):
            continue
        try:
            call("account.account", "write", [d["res_id"]], {"code": target})
            changed += 1
        except RpcError:
            pass
    say(f"Скорочено кодів рахунків: {changed}.")


# =====================================================================================
# 2. Будівники зарплати і кадрів (не дублюємо - проганяємо як є)
# =====================================================================================
# demo_company.py і demo_card.py зашивають DB = "payroll", demo_hire.py заходить
# у довгоживучий контейнер через `docker compose exec`. Ці скрипти нам не належать,
# тому правимо не їх, а тимчасову копію: три підстановки в тексті.
PAYROLL_PATCHES = {
    "demo_company.py": [('DB = "payroll";', 'DB = os.environ.get("PAYROLL_DB", "payroll");', 1)],
    "demo_card.py": [('DB = "payroll"', 'DB = os.environ.get("PAYROLL_DB", "payroll")', 1)],
    "demo_hire.py": [('["docker", "compose", "exec", "-T", "odoo",',
                      '["docker", "compose", "run", "--rm", "--no-deps", "-T", "odoo",', 1)],
    # Банківські дії переїхали з екрана ua.bank.board у ua.bank.ops (l10n_ua_bank_online);
    # екран лишив по собі лише run_action(key). demo_bank.py кличе старі імена напряму.
    "demo_bank.py": [('call("ua.bank.board", "action_', 'call("ua.bank.ops", "action_', 0)],
}


def repair_versions():
    """Обхід помилки l10n_ua_hr_card/models/hr_employee.py:115.

    `_compute_ua_first_hire_date` робить min() над списком, у якому може бути
    False: версія контракту без contract_date_start. На чистій базі така версія
    завжди є - Odoo заводить її разом із карткою працівника, - і щойно
    demo_company.py додає працівникові другу версію (повторне прийняття),
    обчислення падає з TypeError. Тут проставляємо дату початку тим версіям,
    де її немає; після цього min() отримує самі дати.
    """
    vers = call("hr.version", "search_read", [["contract_date_start", "=", False]],
                fields=["employee_id", "date_version"])
    if not vers:
        return 0
    emps = call("hr.employee", "read",
                sorted({v["employee_id"][0] for v in vers if v["employee_id"]}),
                ["ua_hire_date"])
    hire = {e["id"]: e.get("ua_hire_date") for e in emps}
    by_date = {}
    for v in vers:
        eid = v["employee_id"][0] if v["employee_id"] else False
        day = hire.get(eid) or v["date_version"]
        if day:
            by_date.setdefault(day, []).append(v["id"])
    for day, ids in by_date.items():
        call("hr.version", "write", ids, {"contract_date_start": day})
    say(f"   обхід l10n_ua_hr_card:115 - дату початку проставлено {len(vers)} версіям")
    return len(vers)


CERT_STUB = "тимчасовий запис демо (довідку видамо після листків)"


def repair_income_certificate():
    """Обхід порядку в scripts/demo_company.py.

    Майстер довідки про доходи (ua.income.certificate.wizard.action_print) там
    викликається за 60 рядків до того, як з'являються пакети розрахункових
    листків. На базі, де листки вже є від попереднього прогону, це непомітно;
    на чистій базі майстер щоразу падає з «За цей період немає проведених
    розрахункових листків», і скрипт не доходить до самих листків. Кладемо
    в реєстр запис-заглушку, щоб demo_company.py пропустив майстер, а
    справжню довідку видамо після того, як листки будуть на місці.
    """
    emp = call("hr.employee", "search", [["name", "like", "Гаврилюк"]], limit=1)
    if not emp:
        return 0
    if call("ua.income.certificate.register", "search_count",
            [["employee_id", "=", emp[0]], ["date_from", "=", "2026-02-01"]]):
        return 0
    call("ua.income.certificate.register", "create", {
        "name": "тимчасово", "date": "2026-09-15", "company_id": COMPANY,
        "employee_id": emp[0], "date_from": "2026-02-01", "date_to": "2026-07-31",
        "purpose": CERT_STUB})
    say("   обхід порядку в demo_company.py - заглушка в реєстрі довідок про доходи")
    return 1


def issue_income_certificate():
    """Замінити заглушку справжньою довідкою - листки вже проведені."""
    stub = call("ua.income.certificate.register", "search", [["purpose", "=", CERT_STUB]])
    if not stub:
        return
    rec = call("ua.income.certificate.register", "read", stub, ["employee_id"])[0]
    try:
        wid = call("ua.income.certificate.wizard", "create", {
            "employee_id": rec["employee_id"][0], "date_from": "2026-03-01",
            "date_to": "2026-08-31", "purpose": "для подання до банку"})
        call("ua.income.certificate.wizard", "action_print", [wid])
        # заглушку не видаляємо (у реєстрі немає права на видалення) - дописуємо їй
        # звичайні реквізити, і вона читається як ще одна раніше видана довідка
        call("ua.income.certificate.register", "write", stub, {
            "name": "1", "date": "2026-08-03", "purpose": "для подання до банку"})
        say("Довідка про доходи видана майстром; заглушку дописано як раніше видану довідку.")
    except RpcError as e:
        say(f"Довідка про доходи: {str(e)[:150]}")


def repair(stdout):
    """Полагодити те, що заважає будівникам зарплати стати на чисту базу."""
    n = repair_versions()
    if "розрахункових листків" in (stdout or ""):
        n += repair_income_certificate()
    return n


def run_payroll_builders():
    if os.environ.get("SKIP_PAYROLL") == "1":
        say("Будівники зарплати пропущено (SKIP_PAYROLL=1).")
        return
    env = dict(os.environ, PAYROLL_DB=DB, ODOO_URL=URL)
    # Копії кладемо в demo-out/ (тека в .gitignore), а не в /tmp: усі ці скрипти
    # рахують корінь дерева як dirname(dirname(__file__)) і в /tmp не знайшли б
    # ні .env, ні docker-compose.yml.
    tmp = os.path.join(ROOT, "demo-out")
    os.makedirs(tmp, exist_ok=True)
    for name in ["demo_company.py", "demo_hire.py", "demo_military.py",
                 "demo_bank.py", "demo_card.py"]:
        src = open(os.path.join(ROOT, "scripts", name), encoding="utf-8").read()
        for old, new, count in PAYROLL_PATCHES.get(name, []):
            if old not in src:
                sys.exit(f"{name}: не знайдено рядок для підстановки: {old}")
            src = src.replace(old, new) if count == 0 else src.replace(old, new, count)
        path = os.path.join(tmp, name)
        open(path, "w", encoding="utf-8").write(src)
        say(f"-> {name}")
        for attempt in (1, 2, 3, 4, 5, 6):
            p = subprocess.run([sys.executable, path], cwd=ROOT, env=env,
                               capture_output=True, text=True)
            if p.returncode == 0:
                break
            # demo_company.py повідомляє про збій через SystemExit, тобто в stderr
            out = (p.stdout or "") + "\n" + (p.stderr or "")
            say(f"   спроба {attempt} впала: " + (out.strip().splitlines() or [""])[-1][:250])
            if repair(out) == 0:
                say(p.stdout[-2500:])
                say(p.stderr[-1500:])
                sys.exit(f"{name} впав (код {p.returncode}), лагодити нічого")
        else:
            say(p.stdout[-2500:])
            sys.exit(f"{name} впав остаточно")
        say(f"   {name}: {len(p.stdout.splitlines())} рядків виводу, ок")
        os.remove(path)
    issue_income_certificate()


# =====================================================================================
# 3. Блокування періодів (липень закриває demo_company.py; для липневої первинки знімаємо)
# =====================================================================================
LOCKS = ["fiscalyear_lock_date", "tax_lock_date", "hard_lock_date",
         "sale_lock_date", "purchase_lock_date"]


def read_locks():
    fields_present = call("res.company", "fields_get", [], {"attributes": ["type"]})
    keys = [k for k in LOCKS if k in fields_present]
    return keys, call("res.company", "read", [COMPANY], keys)[0]


def unlock_periods():
    keys, saved = read_locks()
    vals = {k: False for k in keys if saved.get(k)}
    if vals:
        call("res.company", "write", [COMPANY], vals)
        say("Дати блокування тимчасово знято: " + ", ".join(vals))
    return {k: saved.get(k) for k in keys}


def relock_periods(saved):
    vals = {k: v for k, v in saved.items() if v}
    if vals:
        call("res.company", "write", [COMPANY], vals)
        say("Дати блокування повернуто: " + ", ".join(f"{k}={v}" for k, v in vals.items()))


# =====================================================================================
# 4. Реквізити компанії для первинки і ПДВ
# =====================================================================================
def company_details():
    co = call("res.company", "read", [COMPANY], ["partner_id", "company_registry"])[0]
    call("res.company", "write", [COMPANY], {
        "vat": "438120726558",
        "ua_acts_on_basis": "Статуту",
        "ua_cash_limit": 20000.0,
        "ua_dps_reg": "13", "ua_dps_raj": "06", "ua_dps_sti": "1306",
    })
    call("res.partner", "write", [co["partner_id"][0]], {
        "vat": "438120726558",
        "ua_vat_payer_status": "payer",
        "ua_actual_address": "81130, Сокільники, вул. Промислова, 8",
    })
    say("Реквізити компанії: ІПН, ліміт каси 20 000 грн, коди ДПІ Львівщини.")


def pricelists():
    """Прайс-листи в гривні плюс один експортний у євро.

    Типовий прайс-лист Odoo створюється в доларі (валюта даних модуля base), і
    поки його не виправити, кожне замовлення на продаж виходить у USD, хоча
    компанія веде облік у гривні. Валюта замовлення - related до прайс-листа,
    тому писати currency_id прямо в замовлення марно.
    """
    uah = call("res.company", "read", [COMPANY], ["currency_id"])[0]["currency_id"][0]
    eur = call("res.currency", "search", [["name", "=", "EUR"]], context={"active_test": False})
    call("res.currency", "write", eur, {"active": True})
    wrong = call("product.pricelist", "search", [["currency_id", "!=", uah]])
    export = upsert("product.pricelist", [["name", "=", "Експорт (EUR)"]],
                    {"name": "Експорт (EUR)", "currency_id": eur[0], "company_id": COMPANY})
    wrong = [p for p in wrong if p != export]
    if wrong:
        call("product.pricelist", "write", wrong, {"currency_id": uah})
    say(f"Прайс-листи: {len(wrong)} переведено в гривню, окремий «Експорт (EUR)» готовий.")
    return export


def trust_banks():
    """Odoo 19 не дає провести рахунок із «ненадійним» банківським рахунком:
    у житті це підтверджує людина кнопкою, у демо - цей крок."""
    banks = call("res.partner.bank", "search", [["allow_out_payment", "=", False]])
    if banks:
        call("res.partner.bank", "write", banks, {"allow_out_payment": True})
    return len(banks)


# =====================================================================================
# 5. Контрагенти
# =====================================================================================
BANK_MFO = {"privat": "305299", "mono": "322001", "oschad": "300465", "ukrsib": "351005"}

CUSTOMERS = [
    # (ref, назва, ЄДРПОУ/РНОКПП-основа, статус ПДВ, місто, індекс, вулиця, банк)
    ("DEMO-C01", "ТОВ «Меблевий дім Галичина»", "3223313", "payer", "Львів", "79005", "вул. Дорошенка, 41", "privat"),
    ("DEMO-C02", "ТОВ «Інтер'єр Плюс»", "3876412", "payer", "Київ", "03150", "вул. Антоновича, 176", "oschad"),
    ("DEMO-C03", "ТОВ «Затишна оселя»", "4120556", "payer", "Одеса", "65012", "вул. Канатна, 83", "privat"),
    ("DEMO-C04", "ТОВ «Офіс-Стандарт»", "3654781", "payer", "Харків", "61002", "вул. Сумська, 118", "ukrsib"),
    ("DEMO-C05", "ТОВ «Дніпро Меблі»", "3991204", "payer", "Дніпро", "49000", "просп. Яворницького, 60", "privat"),
    ("DEMO-C06", "ТОВ «Карпатський готель»", "4277130", "payer", "Яремче", "78500", "вул. Свободи, 274", "oschad"),
    ("DEMO-C07", "ТОВ «Школярик»", "3502998", "payer", "Тернопіль", "46001", "вул. Руська, 22", "mono"),
    ("DEMO-C08", "ФОП Бондаренко Ігор Петрович", None, "single_tax", "Вінниця", "21000", "вул. Соборна, 51", "mono"),
    ("DEMO-C09", "ФОП Левченко Оксана Миколаївна", None, "single_tax", "Полтава", "36000", "вул. Європейська, 14", "privat"),
    ("DEMO-C10", "ФОП Гриценко Андрій Сергійович", None, "single_tax", "Рівне", "33000", "вул. Соборна, 195", "oschad"),
    ("DEMO-C11", "ФОП Марченко Тетяна Василівна", None, "payer", "Львів", "79017", "вул. Кульпарківська, 93", "privat"),
]
FOREIGN = ("DEMO-C12", "Drewno Sp. z o.o.", "PL5272834109", "Warszawa", "00-844", "ul. Grzybowska 62")

SUPPLIERS = [
    ("DEMO-S01", "ТОВ «Карпатський ліс»", "3310447", "payer", "Надвірна", "78400", "вул. Соборна, 12", "деревина"),
    ("DEMO-S02", "ТОВ «Плита-Захід»", "3745219", "payer", "Львів", "79066", "вул. Хуторівка, 4", "ДСП і МДФ"),
    ("DEMO-S03", "ТОВ «Фурнітура Сервіс»", "3981065", "payer", "Київ", "02093", "вул. Бориспільська, 9", "фурнітура"),
    ("DEMO-S04", "ТОВ «Текстиль Груп»", "4055872", "payer", "Черкаси", "18000", "вул. Смілянська, 120", "тканина і поролон"),
    ("DEMO-S05", "ТОВ «Лаки і фарби Україна»", "3623910", "payer", "Бровари", "07400", "вул. Фабрична, 6", "лак і фарба"),
    ("DEMO-S06", "ПАТ «Львівобленерго»", "0013122", "payer", "Львів", "79026", "вул. Козельницька, 3", "електроенергія"),
    ("DEMO-S07", "ТОВ «Промнерухомість Львів»", "4188304", "payer", "Львів", "79022", "вул. Городоцька, 174", "оренда"),
    ("DEMO-S08", "ТОВ «Транс Лоджистик»", "3859127", "payer", "Львів", "79040", "вул. Зелена, 301", "логістика"),
    ("DEMO-S09", "ФОП Дмитрук Василь Іванович", None, "single_tax", "Сокільники", "81130", "вул. Івасюка, 7", "ремонт верстатів"),
    ("DEMO-S10", "АТ КБ «ПриватБанк»", "4141101", "payer", "Дніпро", "49094", "вул. Набережна Перемоги, 50", "банк"),
]


def ipn_from_edrpou(code8):
    """ІПН платника ПДВ: 12 цифр. Для демо - код ЄДРПОУ з доповненням."""
    return (code8 + "0000")[:12]


def partners():
    ua = call("res.country", "search", [["code", "=", "UA"]])[0]
    pl = call("res.country", "search", [["code", "=", "PL"]])[0]
    ids = {}
    for i, (ref, name, base, status, city, zipc, street, bank) in enumerate(CUSTOMERS, 1):
        code = edrpou(base) if base else rnokpp(date(1980, 3, 1 + i), "male" if i % 2 else "female", 200 + i)
        vals = {"name": name, "ref": ref, "is_company": bool(base), "company_registry": code,
                "street": street, "city": city, "zip": zipc, "country_id": ua,
                "customer_rank": 1, "lang": "uk_UA",
                "ua_vat_payer_status": status,
                "vat": ipn_from_edrpou(code) if status == "payer" else False,
                "ua_signatory_name": "Директор", "ua_signatory_basis": "Статуту",
                "phone": f"+380 {32 + i} {200 + i} {10 + i} {20 + i}",
                "email": f"{ref.lower()}@example.ua"}
        ids[ref] = upsert("res.partner", [["ref", "=", ref]], vals)
        acc = iban_ua(BANK_MFO[bank], f"00000260071{i:05d}0000"[:19].ljust(19, "0"))
        upsert("res.partner.bank", [["partner_id", "=", ids[ref]]],
               {"acc_number": acc, "partner_id": ids[ref], "acc_holder_name": name})
    ref, name, vatpl, city, zipc, street = FOREIGN
    ids[ref] = upsert("res.partner", [["ref", "=", ref]], {
        "name": name, "ref": ref, "is_company": True, "vat": vatpl,
        "street": street, "city": city, "zip": zipc, "country_id": pl,
        "customer_rank": 1, "ua_vat_payer_status": "non_payer",
        "email": "biuro@drewno.example.pl"})
    for i, (ref, name, base, status, city, zipc, street, what) in enumerate(SUPPLIERS, 1):
        code = edrpou(base) if base else rnokpp(date(1975, 6, 1 + i), "male", 300 + i)
        vals = {"name": name, "ref": ref, "is_company": bool(base), "company_registry": code,
                "street": street, "city": city, "zip": zipc, "country_id": ua,
                "supplier_rank": 1, "lang": "uk_UA", "comment": what,
                "ua_vat_payer_status": status,
                "vat": ipn_from_edrpou(code) if status == "payer" else False,
                "phone": f"+380 {44 + i} {300 + i} {30 + i} {40 + i}"}
        ids[ref] = upsert("res.partner", [["ref", "=", ref]], vals)
        acc = iban_ua(BANK_MFO["privat"], f"00000260081{i:05d}0000"[:19].ljust(19, "0"))
        upsert("res.partner.bank", [["partner_id", "=", ids[ref]]],
               {"acc_number": acc, "partner_id": ids[ref], "acc_holder_name": name})
    # ДПС - одержувач податків
    ids["DPS"] = upsert("res.partner", [["ref", "=", "DEMO-DPS"]], {
        "name": "ГУ ДПС у Львівській області", "ref": "DEMO-DPS", "is_company": True,
        "company_registry": "43968090", "country_id": ua, "city": "Львів",
        "ua_vat_payer_status": "non_payer", "supplier_rank": 1})
    say(f"Контрагенти: {len(CUSTOMERS) + 1} покупців (з них 3 єдинники без ПДВ, 1 з ЄС), "
        f"{len(SUPPLIERS)} постачальників.")
    return ids


# =====================================================================================
# 6. Номенклатура і специфікації
# =====================================================================================
COMPONENTS = [
    # (код, назва, ціна закупівлі, УКТ ЗЕД)
    ("M01", "ДСП ламінована 18 мм, дуб сонома (лист)", 780.0, "4411131000"),
    ("M02", "МДФ 16 мм, біла (лист)", 950.0, "4411121000"),
    ("M03", "Фанера березова 12 мм (лист)", 1120.0, "4412330000"),
    ("M04", "Шпон дубовий натуральний (м. кв.)", 340.0, "4408909800"),
    ("M05", "Брус сосновий 40x60 мм (м. пог.)", 95.0, "4407110000"),
    ("M06", "Кромка ПВХ 2 мм (м. пог.)", 12.5, "3920430000"),
    ("M07", "Клей ПВА меблевий (кг)", 180.0, "3506100000"),
    ("M08", "Лак поліуретановий (л)", 420.0, "3209100000"),
    ("M09", "Фарба акрилова біла (л)", 310.0, "3209100000"),
    ("M10", "Морилка на водній основі (л)", 260.0, "3208201000"),
    ("M11", "Петля меблева накладна (шт)", 28.0, "8302420000"),
    ("M12", "Напрямні кулькові 450 мм (компл.)", 165.0, "8302420000"),
    ("M13", "Ручка меблева алюмінієва (шт)", 74.0, "8302420000"),
    ("M14", "Ніжка меблева регульована (шт)", 22.0, "8302420000"),
    ("M15", "Конфірмат 7x50 мм (100 шт)", 96.0, "7318159000"),
    ("M16", "Шуруп 4x30 мм (100 шт)", 48.0, "7318120000"),
    ("M17", "Тканина оббивна рогожка (м. пог.)", 395.0, "5801270000"),
    ("M18", "Поролон меблевий 40 мм (м. кв.)", 210.0, "3921139000"),
    ("M19", "Скло загартоване 6 мм (м. кв.)", 690.0, "7007191000"),
    ("M20", "Дзеркало 4 мм (м. кв.)", 520.0, "7009910000"),
]

# (код, назва, ціна продажу, УКТ ЗЕД, [(код компонента, кількість)])
GOODS = [
    ("F01", "Стіл обідній «Ясен» 160x90", 12400.0, "9403300000",
     [("M01", 3), ("M05", 8), ("M06", 12), ("M08", 1.5), ("M14", 4), ("M15", 1)]),
    ("F02", "Стіл письмовий «Академія» 120x60", 8600.0, "9403300000",
     [("M01", 2), ("M06", 8), ("M12", 2), ("M13", 2), ("M15", 1), ("M08", 1)]),
    ("F03", "Стілець «Буковина»", 2450.0, "9401610000",
     [("M05", 4), ("M03", 0.5), ("M17", 1), ("M18", 0.6), ("M16", 1), ("M08", 0.3)]),
    ("F04", "Крісло м'яке «Затишок»", 6900.0, "9401610000",
     [("M05", 6), ("M03", 1), ("M17", 3), ("M18", 2), ("M16", 2), ("M08", 0.4)]),
    ("F05", "Шафа-купе «Модерн» 220x240", 28500.0, "9403500000",
     [("M01", 8), ("M06", 30), ("M12", 4), ("M13", 4), ("M20", 3), ("M15", 3)]),
    ("F06", "Шафа книжкова «Бібліотека»", 15200.0, "9403500000",
     [("M01", 5), ("M06", 20), ("M19", 1.5), ("M11", 4), ("M13", 2), ("M15", 2)]),
    ("F07", "Комод «Львів» 4 шухляди", 11300.0, "9403500000",
     [("M02", 3), ("M06", 14), ("M12", 4), ("M13", 4), ("M09", 1.2), ("M15", 2)]),
    ("F08", "Тумба приліжкова «Соната»", 4700.0, "9403500000",
     [("M02", 1), ("M06", 6), ("M12", 1), ("M13", 1), ("M09", 0.4), ("M16", 1)]),
]
SERVICES = [
    ("SV1", "Доставка меблів по Україні", 1800.0),
    ("SV2", "Збирання меблів у замовника", 2600.0),
]


def _account_by_code(code):
    ids = call("account.account", "search", [["code", "=like", f"{code}%"]], order="code", limit=1)
    return ids[0] if ids else False


def taxes():
    def one(use, amount, zero_kind=None):
        dom = [["type_tax_use", "=", use], ["amount", "=", amount],
               ["company_id", "=", COMPANY], ["amount_type", "=", "percent"]]
        if zero_kind:
            dom.append(["tax_group_id.ua_vat_zero_kind", "=", zero_kind])
        ids = call("account.tax", "search", dom, limit=1)
        return ids[0] if ids else False
    t = {"sale20": one("sale", 20.0), "purchase20": one("purchase", 20.0),
         "export0": one("sale", 0.0, "export"), "exempt0": one("sale", 0.0, "exempt")}
    missing = [k for k, v in t.items() if not v]
    if missing:
        say("УВАГА: не знайдено податки " + ", ".join(missing))
    return t


def products(tx):
    """Категорії з українськими рахунками, матеріали, готова продукція, послуги."""
    cat_mat = upsert("product.category", [["name", "=", "Сировина і матеріали"]], {
        "name": "Сировина і матеріали",
        "property_account_expense_categ_id": _account_by_code("201"),
        "property_account_income_categ_id": _account_by_code("701")})
    cat_fin = upsert("product.category", [["name", "=", "Готова продукція"]], {
        "name": "Готова продукція",
        "property_account_expense_categ_id": _account_by_code("901"),
        "property_account_income_categ_id": _account_by_code("701")})
    cat_srv = upsert("product.category", [["name", "=", "Послуги"]], {
        "name": "Послуги",
        "property_account_expense_categ_id": _account_by_code("949"),
        "property_account_income_categ_id": _account_by_code("703")})
    P = {}
    for code, name, price, uktzed in COMPONENTS:
        tid = upsert("product.template", [["default_code", "=", code]], {
            "name": name, "default_code": code, "type": "consu", "is_storable": True,
            "categ_id": cat_mat, "standard_price": price, "list_price": price * 1.4,
            "ua_uktzed": uktzed, "purchase_ok": True, "sale_ok": False,
            "supplier_taxes_id": [(6, 0, [tx["purchase20"]])] if tx["purchase20"] else False,
            "taxes_id": [(6, 0, [tx["sale20"]])] if tx["sale20"] else False})
        P[code] = call("product.product", "search", [["product_tmpl_id", "=", tid]])[0]
    comp_price = dict((c[0], c[2]) for c in COMPONENTS)
    for code, name, price, uktzed, bom in GOODS:
        cost = round(sum(comp_price[m] * q for m, q in bom), 2)
        tid = upsert("product.template", [["default_code", "=", code]], {
            "name": name, "default_code": code, "type": "consu", "is_storable": True,
            "categ_id": cat_fin, "standard_price": cost, "list_price": price,
            "ua_uktzed": uktzed, "purchase_ok": False, "sale_ok": True,
            "taxes_id": [(6, 0, [tx["sale20"]])] if tx["sale20"] else False})
        P[code] = call("product.product", "search", [["product_tmpl_id", "=", tid]])[0]
    for code, name, price in SERVICES:
        tid = upsert("product.template", [["default_code", "=", code]], {
            "name": name, "default_code": code, "type": "service",
            "categ_id": cat_srv, "list_price": price, "standard_price": price * 0.6,
            "sale_ok": True, "purchase_ok": False, "invoice_policy": "order",
            "taxes_id": [(6, 0, [tx["sale20"]])] if tx["sale20"] else False})
        P[code] = call("product.product", "search", [["product_tmpl_id", "=", tid]])[0]
    say(f"Номенклатура: {len(COMPONENTS)} матеріалів, {len(GOODS)} готових виробів, "
        f"{len(SERVICES)} послуги; УКТ ЗЕД проставлено.")
    return P


def boms(P):
    n = 0
    for code, name, price, uktzed, bom in GOODS:
        tmpl = call("product.product", "read", [P[code]], ["product_tmpl_id"])[0]["product_tmpl_id"][0]
        if call("mrp.bom", "search_count", [["product_tmpl_id", "=", tmpl]]):
            continue
        call("mrp.bom", "create", {
            "product_tmpl_id": tmpl, "product_qty": 1, "type": "normal",
            "company_id": COMPANY,
            "bom_line_ids": [(0, 0, {"product_id": P[m], "product_qty": q}) for m, q in bom]})
        n += 1
    say(f"Специфікації (BOM): {n} створено, усього {call('mrp.bom', 'search_count', [])}.")


# =====================================================================================
# 7. Курси НБУ
# =====================================================================================
def nbu_rates():
    prov = call("res.currency.rate.provider", "search", [["service", "=", "NBU"]])
    eur = call("res.currency", "search", [["name", "=", "EUR"]], context={"active_test": False})
    usd = call("res.currency", "search", [["name", "=", "USD"]], context={"active_test": False})
    call("res.currency", "write", eur + usd, {"active": True})
    if not prov:
        prov = [call("res.currency.rate.provider", "create", {
            "service": "NBU", "company_id": COMPANY, "currency_ids": [(6, 0, eur + usd)],
            "interval_type": "days", "interval_number": 1})]
    else:
        call("res.currency.rate.provider", "write", prov, {"currency_ids": [(6, 0, eur + usd)]})
    ok = False
    try:
        wiz = call("res.currency.rate.update.wizard", "create", {
            "date_from": "2026-07-01", "date_to": "2026-09-30",
            "provider_ids": [(6, 0, prov)]})
        call("res.currency.rate.update.wizard", "action_update", [wiz])
        ok = call("res.currency.rate", "search_count",
                  [["name", ">=", "2026-07-01"], ["name", "<=", "2026-09-30"]]) > 0
    except RpcError as e:
        say(f"Провайдер НБУ не відповів ({str(e)[:120]}) - ставимо курси вручну.")
    if not ok:
        manual = [("2026-07-01", 45.80, 41.75), ("2026-07-15", 46.10, 41.90),
                  ("2026-08-03", 46.45, 41.60), ("2026-08-18", 47.02, 41.45),
                  ("2026-09-01", 47.30, 41.35), ("2026-09-15", 47.55, 41.20)]
        for d, e_rate, u_rate in manual:
            for cur, uah in ((eur[0], e_rate), (usd[0], u_rate)):
                upsert("res.currency.rate",
                       [["name", "=", d], ["currency_id", "=", cur], ["company_id", "=", COMPANY]],
                       {"name": d, "currency_id": cur, "company_id": COMPANY,
                        "inverse_company_rate": uah})
        say("Курси НБУ: вставлено вручну 12 записів (EUR і USD, липень-вересень) - "
            "зовнішній API недоступний або не дав даних.")
    else:
        n = call("res.currency.rate", "search_count",
                 [["name", ">=", "2026-07-01"], ["name", "<=", "2026-09-30"]])
        say(f"Курси НБУ: завантажено з bank.gov.ua, {n} записів за квартал.")


# =====================================================================================
# 8. Закупівлі: замовлення -> надходження -> рахунок постачальника
# =====================================================================================
PURCHASES = [
    # (ключ, постачальник, дата, [(код, кількість)])
    ("ЗП-2026-01", "DEMO-S02", "2026-07-02", [("M01", 220), ("M02", 120)]),
    ("ЗП-2026-02", "DEMO-S01", "2026-07-03", [("M03", 60), ("M04", 90), ("M05", 900)]),
    ("ЗП-2026-03", "DEMO-S03", "2026-07-06", [("M11", 300), ("M12", 260), ("M13", 240),
                                              ("M14", 200), ("M15", 120), ("M16", 150)]),
    ("ЗП-2026-04", "DEMO-S04", "2026-07-07", [("M17", 180), ("M18", 120)]),
    ("ЗП-2026-05", "DEMO-S05", "2026-07-08", [("M08", 90), ("M09", 70), ("M10", 40), ("M07", 60)]),
    ("ЗП-2026-06", "DEMO-S02", "2026-08-04", [("M01", 160), ("M06", 1400)]),
    ("ЗП-2026-07", "DEMO-S03", "2026-08-11", [("M19", 30), ("M20", 40)]),
    ("ЗП-2026-08", "DEMO-S01", "2026-09-02", [("M05", 600), ("M03", 40)]),
    ("ЗП-2026-09", "DEMO-S04", "2026-09-09", [("M17", 90), ("M18", 60)]),
]
# Витрати без запасів: оренда, комуналка, логістика, ремонт
EXPENSES = [
    ("DEMO-S07", "2026-07-31", "Оренда виробничих приміщень за липень 2026", 60000.0, "91"),
    ("DEMO-S06", "2026-07-31", "Електроенергія за липень 2026", 38500.0, "91"),
    ("DEMO-S08", "2026-07-31", "Транспортні послуги за липень 2026", 24000.0, "93"),
    ("DEMO-S07", "2026-08-31", "Оренда виробничих приміщень за серпень 2026", 60000.0, "91"),
    ("DEMO-S06", "2026-08-31", "Електроенергія за серпень 2026", 41200.0, "91"),
    ("DEMO-S08", "2026-08-31", "Транспортні послуги за серпень 2026", 27500.0, "93"),
    ("DEMO-S09", "2026-08-20", "Ремонт кромкооблицювального верстата", 18000.0, "91"),
    ("DEMO-S07", "2026-09-30", "Оренда виробничих приміщень за вересень 2026", 60000.0, "91"),
    ("DEMO-S06", "2026-09-30", "Електроенергія за вересень 2026", 39800.0, "91"),
    ("DEMO-S08", "2026-09-30", "Транспортні послуги за вересень 2026", 25900.0, "93"),
]


def _validate_picking(pid, when):
    pick = call("stock.picking", "read", [pid], ["state", "move_ids"])[0]
    if pick["state"] in ("done", "cancel"):
        return
    moves = call("stock.move", "read", pick["move_ids"], ["product_uom_qty", "quantity", "state"])
    for mv in moves:
        call("stock.move", "write", [mv["id"]],
             {"quantity": mv["product_uom_qty"], "picked": True})
    ctx0 = {"skip_sms": True, "skip_backorder": True, "skip_immediate": True}
    res = call("stock.picking", "button_validate", [pid], context=ctx0)
    if isinstance(res, dict) and res.get("res_model"):
        # майстер (нестача, часткова доставка, SMS) - підтверджуємо його
        ctx = dict(res.get("context") or {}, **ctx0)
        wiz = call(res["res_model"], "create", {}, context=ctx)
        for method in ("process", "action_confirm", "dont_send_sms", "apply"):
            try:
                call(res["res_model"], method, [wiz], context=ctx)
                break
            except RpcError as e:
                if "does not exist" not in str(e):
                    say(f"   майстер {res['res_model']}.{method}: {str(e)[:150]}")
                    break
    call("stock.picking", "write", [pid], {"date_done": when + " 10:00:00"})


def purchases(PR, P, tx):
    made = 0
    for ref, sup, day, lines in PURCHASES:
        ids = call("purchase.order", "search", [["partner_ref", "=", ref]])
        if ids:
            po = ids[0]
        else:
            po = call("purchase.order", "create", {
                "partner_id": PR[sup], "partner_ref": ref, "company_id": COMPANY,
                "date_order": day + " 09:00:00",
                "order_line": [(0, 0, {
                    "product_id": P[code], "product_qty": qty,
                    "price_unit": dict((c[0], c[2]) for c in COMPONENTS)[code],
                    "date_planned": day + " 09:00:00",
                    "tax_ids": [(6, 0, [tx["purchase20"]])] if tx["purchase20"] else False,
                }) for code, qty in lines]})
            made += 1
        state = call("purchase.order", "read", [po], ["state", "picking_ids", "invoice_ids"])[0]
        if state["state"] in ("draft", "sent"):
            call("purchase.order", "button_confirm", [po])
            state = call("purchase.order", "read", [po], ["state", "picking_ids", "invoice_ids"])[0]
        for pid in state["picking_ids"]:
            _validate_picking(pid, day)
        if not state["invoice_ids"]:
            call("purchase.order", "action_create_invoice", [po])
            bills = call("purchase.order", "read", [po], ["invoice_ids"])[0]["invoice_ids"]
            for b in bills:
                call("account.move", "write", [b], {
                    "invoice_date": day, "date": day, "ref": "Видаткова накладна " + ref,
                    "ua_in_pn_registered": True})
                call("account.move", "action_post", [b])
    # витрати без запасів - рахунки постачальників одним рядком
    for sup, day, text, amount, acc_code in EXPENSES:
        key = f"{text}"
        if call("account.move", "search_count", [["ref", "=", key], ["move_type", "=", "in_invoice"]]):
            continue
        mid = call("account.move", "create", {
            "move_type": "in_invoice", "partner_id": PR[sup], "company_id": COMPANY,
            "invoice_date": day, "date": day, "ref": key,
            "ua_in_pn_registered": True,
            "invoice_line_ids": [(0, 0, {
                "name": text, "quantity": 1, "price_unit": amount,
                "account_id": _account_by_code(acc_code),
                "tax_ids": [(6, 0, [tx["purchase20"]])] if tx["purchase20"] else False})]})
        call("account.move", "action_post", [mid])
    say(f"Закупівлі: {len(PURCHASES)} замовлень (нових {made}) з надходженнями і рахунками, "
        f"{len(EXPENSES)} рахунків на оренду, енергію, логістику і ремонт.")


# =====================================================================================
# 9. Виробництво
# =====================================================================================
ORDERS_MRP = [
    ("ВЗ-2026-01", "F01", 12, "2026-07-13"),
    ("ВЗ-2026-02", "F03", 60, "2026-07-14"),
    ("ВЗ-2026-03", "F05", 6, "2026-07-20"),
    ("ВЗ-2026-04", "F02", 20, "2026-08-05"),
    ("ВЗ-2026-05", "F07", 15, "2026-08-12"),
    ("ВЗ-2026-06", "F04", 24, "2026-08-19"),
    ("ВЗ-2026-07", "F08", 30, "2026-09-03"),
    ("ВЗ-2026-08", "F06", 10, "2026-09-10"),
    ("ВЗ-2026-09", "F01", 8, "2026-09-16"),
]


def manufacturing(P):
    done = 0
    costs = {}
    for ref, code, qty, day in ORDERS_MRP:
        ids = call("mrp.production", "search", [["origin", "=", ref]])
        if ids:
            mo = ids[0]
        else:
            bom = call("mrp.bom", "search", [["product_tmpl_id", "=",
                       call("product.product", "read", [P[code]], ["product_tmpl_id"])[0]["product_tmpl_id"][0]]])[0]
            mo = call("mrp.production", "create", {
                "product_id": P[code], "product_qty": qty, "bom_id": bom,
                "origin": ref, "company_id": COMPANY,
                "date_start": day + " 08:00:00"})
        st = call("mrp.production", "read", [mo], ["state", "move_raw_ids"])[0]
        if st["state"] == "draft":
            call("mrp.production", "action_confirm", [mo])
            st = call("mrp.production", "read", [mo], ["state", "move_raw_ids"])[0]
        if st["state"] != "done":
            call("mrp.production", "write", [mo], {"qty_producing": qty})
            raws = call("stock.move", "read",
                        call("mrp.production", "read", [mo], ["move_raw_ids"])[0]["move_raw_ids"],
                        ["should_consume_qty", "product_uom_qty", "quantity"])
            for mv in raws:
                call("stock.move", "write", [mv["id"]],
                     {"quantity": mv.get("should_consume_qty") or mv["product_uom_qty"],
                      "picked": True})
            try:
                res = call("mrp.production", "button_mark_done", [mo],
                           context={"skip_consumption": True, "skip_immediate": True})
                if isinstance(res, dict) and res.get("res_model"):
                    say(f"   {ref}: майстер {res['res_model']} - пропущено")
            except RpcError as e:
                say(f"   {ref}: {str(e)[:200]}")
                continue
            done += 1
        cost = call("product.product", "read", [P[code]], ["standard_price"])[0]["standard_price"]
        costs[ref] = (code, qty, round(cost * qty, 2), day)
    say(f"Виробництво: {len(ORDERS_MRP)} замовлень, завершено цього прогону {done}.")
    return costs


def production_cost_entries(costs):
    """Собівартість періодичним методом: Дт 23 / Кт 201, далі Дт 26 / Кт 23."""
    a23, a201, a26 = _account_by_code("23"), _account_by_code("201"), _account_by_code("26")
    jr = call("account.journal", "search", [["type", "=", "general"], ["company_id", "=", COMPANY]])[0]
    n = 0
    for ref, (code, qty, amount, day) in costs.items():
        key = f"Собівартість випуску {ref}"
        if call("account.move", "search_count", [["ref", "=", key]]):
            continue
        mid = call("account.move", "create", {
            "journal_id": jr, "company_id": COMPANY, "date": day, "ref": key,
            "line_ids": [
                (0, 0, {"account_id": a23, "name": f"Матеріали у виробництво {ref}",
                        "debit": amount, "credit": 0.0}),
                (0, 0, {"account_id": a201, "name": f"Матеріали у виробництво {ref}",
                        "debit": 0.0, "credit": amount}),
                (0, 0, {"account_id": a26, "name": f"Випуск готової продукції {ref}",
                        "debit": amount, "credit": 0.0}),
                (0, 0, {"account_id": a23, "name": f"Випуск готової продукції {ref}",
                        "debit": 0.0, "credit": amount})]})
        call("account.move", "action_post", [mid])
        n += 1
    say(f"Собівартість: {n} проводок Дт 23 / Кт 201 і Дт 26 / Кт 23.")


# =====================================================================================
# 10. Продажі
# =====================================================================================
# (ключ, покупець, дата замовлення, [(код, кількість)], спосіб, дата відвантаження, дата оплати)
#   спосіб: advance - спершу аванс, потім відвантаження і рахунок
#           shipment - спершу відвантаження і рахунок, оплата пізніше
#           open - відвантажено, рахунок є, оплати немає
SALES = [
    ("ЗМ-2026-01", "DEMO-C01", "2026-07-06", [("F01", 4), ("SV1", 1)], "advance", "2026-07-21", "2026-07-10"),
    ("ЗМ-2026-02", "DEMO-C02", "2026-07-08", [("F03", 24)], "shipment", "2026-07-22", "2026-08-05"),
    ("ЗМ-2026-03", "DEMO-C08", "2026-07-15", [("F03", 8), ("F01", 1)], "shipment", "2026-07-24", "2026-07-30"),
    ("ЗМ-2026-04", "DEMO-C03", "2026-07-20", [("F05", 3), ("SV2", 1)], "advance", "2026-08-06", "2026-07-23"),
    ("ЗМ-2026-05", "DEMO-C04", "2026-08-03", [("F02", 12), ("SV1", 1)], "advance", "2026-08-18", "2026-08-06"),
    ("ЗМ-2026-06", "DEMO-C05", "2026-08-10", [("F07", 8)], "shipment", "2026-08-20", "2026-09-04"),
    ("ЗМ-2026-07", "DEMO-C06", "2026-08-12", [("F04", 12), ("SV2", 1)], "shipment", "2026-08-25", "2026-09-08"),
    ("ЗМ-2026-08", "DEMO-C09", "2026-08-17", [("F08", 10)], "shipment", "2026-08-27", "2026-09-02"),
    ("ЗМ-2026-09", "DEMO-C07", "2026-09-01", [("F02", 6), ("F08", 6)], "advance", "2026-09-14", "2026-09-03"),
    ("ЗМ-2026-10", "DEMO-C10", "2026-09-04", [("F03", 12)], "shipment", "2026-09-11", "2026-09-17"),
    ("ЗМ-2026-11", "DEMO-C11", "2026-09-07", [("F01", 2), ("F04", 4)], "open", "2026-09-15", None),
    ("ЗМ-2026-12", "DEMO-C01", "2026-09-09", [("F06", 5), ("SV1", 1)], "shipment", "2026-09-18", None),
    ("ЗМ-2026-13", "DEMO-C02", "2026-09-14", [("F05", 2)], "open", "2026-09-21", None),
]
EXPORT = ("ЗМ-2026-14", "DEMO-C12", "2026-09-08", [("F01", 6), ("F06", 3)], "2026-09-18")
RETURN_ORDER = "ЗМ-2026-06"   # з нього оформимо повернення і РК


def _bank_journal():
    return call("account.journal", "search", [["type", "=", "bank"], ["company_id", "=", COMPANY]])[0]


def _cash_journal():
    """Журнал каси. План ua_psbo його не створює - заводимо з рахунком 301."""
    ids = call("account.journal", "search", [["type", "=", "cash"], ["company_id", "=", COMPANY]])
    if ids:
        return ids[0]
    return call("account.journal", "create", {
        "name": "Каса", "code": "CASH", "type": "cash", "company_id": COMPANY,
        "default_account_id": _account_by_code("301")})


def _pay(partner, amount, day, kind, memo, journal=None, dest=None, ptype=None):
    """Платіж: ідемпотентний за memo."""
    ids = call("account.payment", "search", [["memo", "=", memo]])
    if ids:
        return ids[0]
    vals = {"payment_type": kind, "partner_type": ptype or ("customer" if kind == "inbound" else "supplier"),
            "partner_id": partner, "amount": round(amount, 2), "date": day,
            "journal_id": journal or _bank_journal(), "company_id": COMPANY, "memo": memo}
    if dest:
        vals["destination_account_id"] = dest
    pid = call("account.payment", "create", vals)
    call("account.payment", "action_post", [pid])
    return pid


def _reconcile_payment_with_invoice(payment_id, invoice_id):
    pm = call("account.payment", "read", [payment_id], ["move_id"])[0]["move_id"][0]
    dom_acc = [["account_id.account_type", "in", ["asset_receivable", "liability_payable"]],
               ["reconciled", "=", False], ["parent_state", "=", "posted"]]
    a = call("account.move.line", "search", [["move_id", "=", pm]] + dom_acc)
    b = call("account.move.line", "search", [["move_id", "=", invoice_id]] + dom_acc)
    if a and b:
        try:
            call("account.move.line", "reconcile", a + b)
        except RpcError as e:
            say(f"   звірка {payment_id}/{invoice_id}: {str(e)[:150]}")


def _invoice_from_so(so, day):
    inv = call("sale.order", "read", [so], ["invoice_ids"])[0]["invoice_ids"]
    if not inv:
        wiz = call("sale.advance.payment.inv", "create", {"advance_payment_method": "delivered"},
                   context={"active_model": "sale.order", "active_ids": [so], "active_id": so})
        call("sale.advance.payment.inv", "create_invoices", [wiz],
             context={"active_model": "sale.order", "active_ids": [so], "active_id": so})
        inv = call("sale.order", "read", [so], ["invoice_ids"])[0]["invoice_ids"]
    for i in inv:
        st = call("account.move", "read", [i], ["state"])[0]["state"]
        if st == "draft":
            call("account.move", "write", [i], {"invoice_date": day, "date": day})
            call("account.move", "action_post", [i])
    return inv


def sales(PR, P, tx):
    prices = dict((g[0], g[2]) for g in GOODS)
    prices.update(dict((s[0], s[2]) for s in SERVICES))
    invoices = {}
    for ref, cust, day, lines, mode, ship_day, pay_day in SALES:
        ids = call("sale.order", "search", [["client_order_ref", "=", ref]])
        if ids:
            so = ids[0]
        else:
            so = call("sale.order", "create", {
                "partner_id": PR[cust], "client_order_ref": ref, "company_id": COMPANY,
                "date_order": day + " 10:00:00",
                "order_line": [(0, 0, {"product_id": P[c], "product_uom_qty": q,
                                       "price_unit": prices[c],
                                       "tax_ids": [(6, 0, [tx["sale20"]])] if tx["sale20"] else False})
                               for c, q in lines]})
        st = call("sale.order", "read", [so], ["state", "picking_ids", "amount_total"])[0]
        if st["state"] in ("draft", "sent"):
            call("sale.order", "action_confirm", [so])
            st = call("sale.order", "read", [so], ["state", "picking_ids", "amount_total"])[0]
        # аванс до відвантаження - перша подія за оплатою
        if mode == "advance" and pay_day:
            adv = round(st["amount_total"] * 0.5, 2)
            _pay(PR[cust], adv, pay_day, "inbound",
                 f"Аванс за замовленням {ref}")
        for pid in st["picking_ids"]:
            _validate_picking(pid, ship_day)
        inv = _invoice_from_so(so, ship_day)
        invoices[ref] = inv
        if mode == "shipment" and pay_day and inv:
            total = call("account.move", "read", inv, ["amount_total"])[0]["amount_total"]
            p = _pay(PR[cust], total, pay_day, "inbound", f"Оплата за рахунком {ref}")
            _reconcile_payment_with_invoice(p, inv[0])
        if mode == "advance" and inv:
            adv_ids = call("account.payment", "search", [["memo", "=", f"Аванс за замовленням {ref}"]])
            if adv_ids:
                _reconcile_payment_with_invoice(adv_ids[0], inv[0])
    say(f"Продажі: {len(SALES)} замовлень на ПДВ 20 % - "
        f"{sum(1 for s in SALES if s[4] == 'advance')} з авансом до відвантаження, "
        f"{sum(1 for s in SALES if s[4] == 'shipment')} з оплатою після, "
        f"{sum(1 for s in SALES if s[4] == 'open')} без оплати.")
    return invoices


def export_sale(PR, P, tx, export_pricelist):
    ref, cust, day, lines, ship_day = EXPORT
    ids = call("sale.order", "search", [["client_order_ref", "=", ref]])
    if ids:
        so = ids[0]
    else:
        so = call("sale.order", "create", {
            "partner_id": PR[cust], "client_order_ref": ref, "company_id": COMPANY,
            "date_order": day + " 10:00:00", "pricelist_id": export_pricelist,
            "order_line": [(0, 0, {"product_id": P[c], "product_uom_qty": q,
                                   "price_unit": round(dict((g[0], g[2]) for g in GOODS)[c] / 47.0, 2),
                                   "tax_ids": [(6, 0, [tx["export0"]])] if tx["export0"] else False})
                           for c, q in lines]})
    st = call("sale.order", "read", [so], ["state", "picking_ids"])[0]
    if st["state"] in ("draft", "sent"):
        call("sale.order", "action_confirm", [so])
        st = call("sale.order", "read", [so], ["state", "picking_ids"])[0]
    for pid in st["picking_ids"]:
        _validate_picking(pid, ship_day)
    inv = _invoice_from_so(so, ship_day)
    say(f"Експорт: замовлення {ref} у EUR за ставкою 0 %, рахунок {inv}.")
    return inv


def sale_return(PR, invoices, tx):
    """Повернення частини партії: сторно рахунку -> РК складається автоматично."""
    inv = invoices.get(RETURN_ORDER) or []
    # сторнуємо саме вихідний рахунок: у invoice_ids замовлення після першого
    # прогону лежить і сторно, і якщо взяти його, сторнується сторно
    heads = [m["id"] for m in call("account.move", "read", inv, ["move_type"])
             if m["move_type"] == "out_invoice"]
    if not heads:
        say("Повернення: первинного рахунку немає, пропущено.")
        return None
    origin = min(heads)
    # ПН первинного рахунку має бути до сторно: без неї l10n_ua_vat не бачить,
    # що коригувати, і РК не складається (_ua_auto_adjustment).
    call("account.move", "action_ua_create_tax_invoice", [origin])
    exist = call("account.move", "search", [["reversed_entry_id", "=", origin]])
    if exist:
        ref_id = exist[0]
    else:
        jr = call("account.move", "read", [origin], ["journal_id"])[0]["journal_id"][0]
        wiz = call("account.move.reversal", "create", {
            "move_ids": [(6, 0, [origin])], "date": "2026-09-07", "journal_id": jr,
            "reason": "Повернення 2 комодів «Львів» за актом від 07.09.2026"},
            context={"active_model": "account.move", "active_ids": [origin]})
        call("account.move.reversal", "reverse_moves", [wiz],
             context={"active_model": "account.move", "active_ids": [origin]})
        ref_id = call("account.move", "search", [["reversed_entry_id", "=", origin]])[0]
    st = call("account.move", "read", [ref_id], ["state", "invoice_line_ids"])[0]
    if st["state"] == "draft":
        # повертаємо не всю партію, а дві одиниці
        for line in call("account.move.line", "read", st["invoice_line_ids"], ["quantity", "display_type"]):
            if line["display_type"] in (False, "product") and line["quantity"] > 2:
                call("account.move.line", "write", [line["id"]], {"quantity": 2})
        call("account.move", "write", [ref_id], {"invoice_date": "2026-09-07", "date": "2026-09-07"})
        call("account.move", "action_post", [ref_id])
    rk = call("ua.vat.document", "search", [["move_id", "=", ref_id], ["doc_kind", "=", "adjustment"]])
    if not rk:
        # РК складається гаком у _post; якщо сторно провели раніше за ПН - перепроводимо
        call("account.move", "button_draft", [ref_id])
        call("account.move", "action_post", [ref_id])
        rk = call("ua.vat.document", "search",
                  [["move_id", "=", ref_id], ["doc_kind", "=", "adjustment"]])
    say(f"Повернення: сторно-рахунок {ref_id}, розрахунок коригування {rk or 'не складено'}.")
    return ref_id


def cogs_entries():
    """Собівартість реалізації: Дт 901 / Кт 26 на кожну відвантажену доставку.

    Рахуємо за фактом складу, а не за рахунком: так залишок рахунку 26 завжди
    дорівнює вартості готової продукції на складі.
    """
    a901, a26 = _account_by_code("901"), _account_by_code("26")
    jr = call("account.journal", "search", [["type", "=", "general"], ["company_id", "=", COMPANY]])[0]
    picks = call("stock.picking", "search_read",
                 [["state", "=", "done"], ["picking_type_code", "=", "outgoing"],
                  ["company_id", "=", COMPANY]],
                 fields=["name", "date_done", "move_ids"])
    n, total = 0, 0.0
    for pk in picks:
        key = f"Собівартість реалізації {pk['name']}"
        if call("account.move", "search_count", [["ref", "=", key]]):
            continue
        amount = 0.0
        for mv in call("stock.move", "read", pk["move_ids"], ["product_id", "quantity", "state"]):
            if mv["state"] != "done":
                continue
            cost = call("product.product", "read", [mv["product_id"][0]],
                        ["standard_price", "is_storable"])[0]
            if not cost["is_storable"]:
                continue
            amount += mv["quantity"] * cost["standard_price"]
        amount = round(amount, 2)
        if amount <= 0:
            continue
        day = (pk["date_done"] or "")[:10] or "2026-09-30"
        mid = call("account.move", "create", {
            "journal_id": jr, "company_id": COMPANY, "date": day, "ref": key,
            "line_ids": [(0, 0, {"account_id": a901, "name": key, "debit": amount, "credit": 0.0}),
                         (0, 0, {"account_id": a26, "name": key, "debit": 0.0, "credit": amount})]})
        call("account.move", "action_post", [mid])
        n += 1
        total += amount
    say(f"Собівартість реалізації: {n} проводок Дт 901 / Кт 26 на {total:,.2f} грн.")


def tax_invoices():
    """Податкові накладні на всі вихідні рахунки платникам ПДВ; частину реєструємо."""
    moves = call("account.move", "search_read",
                 [["move_type", "=", "out_invoice"], ["state", "=", "posted"],
                  ["company_id", "=", COMPANY], ["reversed_entry_id", "=", False],
                  ["partner_id.ua_vat_payer_status", "=", "payer"]],
                 fields=["invoice_date", "name"])
    made = 0
    for m in moves:
        if call("ua.vat.document", "search_count",
                [["move_id", "=", m["id"]], ["doc_kind", "=", "tax_invoice"]]):
            continue
        call("account.move", "action_ua_create_tax_invoice", [m["id"]])
        made += 1
    docs = call("ua.vat.document", "search_read",
                [["ua_pn_registered_date", "=", False]], fields=["date", "doc_kind"])
    reg = 0
    for d in docs:
        if not d["date"] or d["date"] >= "2026-09-10":
            continue   # свіжі лишаємо незареєстрованими - буде що показати в роботі
        day = date.fromisoformat(d["date"])
        due = date(day.year + (1 if day.month == 12 else 0),
                   1 if day.month == 12 else day.month + 1, 5 if day.day <= 15 else 18)
        call("ua.vat.document", "write", [d["id"]], {"ua_pn_registered_date": str(due - timedelta(days=2))})
        reg += 1
    total = call("ua.vat.document", "search_count", [])
    say(f"Податкові документи: складено {made} нових, усього {total}, зареєстровано в ЄРПН {reg}.")


# =====================================================================================
# 11. Банк: оплати постачальникам і податки
# =====================================================================================
def bank_money(PR):
    bills = call("account.move", "search_read",
                 [["move_type", "=", "in_invoice"], ["state", "=", "posted"],
                  ["company_id", "=", COMPANY], ["invoice_date", "<=", "2026-09-15"]],
                 fields=["partner_id", "amount_total", "invoice_date", "name", "payment_state"])
    paid = 0
    for b in bills:
        if b["payment_state"] in ("paid", "in_payment", "reversed"):
            continue
        day = (date.fromisoformat(b["invoice_date"]) + timedelta(days=9)).isoformat()
        if day > "2026-09-21":
            continue
        p = _pay(b["partner_id"][0], b["amount_total"], day, "outbound",
                 f"Оплата постачальнику за {b['name']}")
        _reconcile_payment_with_invoice(p, b["id"])
        paid += 1
    # сплата ПДВ за липень і серпень: Дт 6412 / Кт 311
    jr = call("account.journal", "search", [["type", "=", "general"], ["company_id", "=", COMPANY]])[0]
    a6412, a311 = _account_by_code("6412"), _account_by_code("311")
    n = 0
    for day, amount, label in [("2026-08-28", 72000.0, "ПДВ за липень 2026"),
                               ("2026-09-29", 84000.0, "ПДВ за серпень 2026")]:
        key = f"Сплата {label}"
        if call("account.move", "search_count", [["ref", "=", key]]):
            continue
        mid = call("account.move", "create", {
            "journal_id": jr, "company_id": COMPANY, "date": day, "ref": key,
            "line_ids": [(0, 0, {"account_id": a6412, "partner_id": PR["DPS"], "name": key,
                                 "debit": amount, "credit": 0.0}),
                         (0, 0, {"account_id": a311, "partner_id": PR["DPS"], "name": key,
                                 "debit": 0.0, "credit": amount})]})
        call("account.move", "action_post", [mid])
        n += 1
    say(f"Банк: {paid} оплат постачальникам зі звіркою, {n} платежі ПДВ до бюджету.")


# =====================================================================================
# 12. Каса: ПКО, ВКО, підзвіт і авансовий звіт
# =====================================================================================
def cash_orders(PR):
    cash = _cash_journal()
    a3721 = _account_by_code("3721") or _account_by_code("372")
    made = []
    # ПКО: дрібні продажі за готівку від єдинників
    for cust, day, amount, text in [
            ("DEMO-C08", "2026-07-17", 14800.0, "Оплата за стільці готівкою, замовлення ЗМ-2026-03"),
            ("DEMO-C10", "2026-09-12", 9600.0, "Часткова оплата за замовленням ЗМ-2026-10"),
            ("DEMO-C09", "2026-08-28", 12300.0, "Оплата за тумби, замовлення ЗМ-2026-08")]:
        made.append(_pay(PR[cust], amount, day, "inbound", text, journal=cash))
    # ВКО: аванс працівникові на господарські потреби
    emp = call("hr.employee", "search_read", [["name", "like", "Шевчук"]],
               fields=["work_contact_id", "name"])
    if not emp or not emp[0]["work_contact_id"]:
        say("Каса: працівника для підзвіту не знайдено - авансовий звіт пропущено.")
        return
    person, pname = emp[0]["work_contact_id"][0], emp[0]["name"]
    adv = _pay(person, 9000.0, "2026-09-07", "outbound",
               "Аванс на господарські потреби (відрядження і ПММ)",
               journal=cash, dest=a3721)
    call("account.payment", "write", [adv], {"ua_person": pname,
                                             "ua_document": "Паспорт громадянина України, ID-картка"})
    made.append(adv)
    # ВКО: здача понадлімітної готівки в банк
    made.append(_pay(PR["DEMO-S10"], 15000.0, "2026-09-14", "outbound",
                     "Здача готівки в банк на поточний рахунок", journal=cash,
                     dest=_account_by_code("333") or _account_by_code("311")))
    # авансовий звіт
    rep = call("ua.advance.report", "search", [["payment_id", "=", adv]])
    if not rep:
        rid = call("ua.advance.report", "create", {
            "partner_id": person, "date": "2026-09-15", "payment_id": adv,
            "company_id": COMPANY,
            "line_ids": [
                (0, 0, {"name": "Пально-мастильні матеріали, чек № 0451",
                        "amount": 3800.0, "expense_account_id": _account_by_code("93")}),
                (0, 0, {"name": "Проживання у відрядженні, рахунок № 118",
                        "amount": 2600.0, "expense_account_id": _account_by_code("92")}),
                (0, 0, {"name": "Дрібний інструмент для цеху, чек № 7712",
                        "amount": 1450.0, "expense_account_id": _account_by_code("91")})]})
        call("ua.advance.report", "action_confirm", [rid])
        try:
            call("ua.advance.report", "action_settle_balance", [rid])
        except RpcError as e:
            say(f"   залишок підзвіту: {str(e)[:120]}")
    # ліміт каси і касова книга за вересень
    book = call("ua.cash.book", "search", [["date_from", "=", "2026-09-01"]])
    if not book:
        book = [call("ua.cash.book", "create", {
            "company_id": COMPANY, "journal_id": cash,
            "date_from": "2026-09-01", "date_to": "2026-09-30"})]
    call("ua.cash.book", "action_compute", book)
    b = call("ua.cash.book", "read", book, ["opening_balance", "total_in", "total_out",
                                            "closing_balance", "over_limit_days"])[0]
    say(f"Каса: {len(made)} ордерів (ПКО і ВКО), авансовий звіт затверджено; "
        f"касова книга за вересень: надходження {b['total_in']:.2f}, видаток {b['total_out']:.2f}, "
        f"залишок {b['closing_balance']:.2f}, днів понад ліміт {b['over_limit_days']}.")


# =====================================================================================
# 13. Основні засоби
# =====================================================================================
ASSETS = [
    # (код, назва, група, вартість без ПДВ, дата введення, місце, відповідальний)
    ("ОЗ-001", "Верстат ЧПК Homag Centateq N-210", "oz_04", 1450000.0, "2026-07-09",
     "Цех, Сокільники", "Прокопів Наталія Богданівна"),
    ("ОЗ-002", "Автомобіль вантажний Renault Master", "oz_05", 980000.0, "2026-07-15",
     "Склад, Сокільники", "Шевчук Віталій Олегович"),
    ("ОЗ-003", "Ноутбуки Lenovo ThinkPad, 4 шт (МНМА)", "oz_11", 148000.0, "2026-07-22",
     "Офіс, вул. Городоцька 174", "Стефанишин Оксана Ігорівна"),
]


def assets(PR, tx):
    jr = call("account.journal", "search", [["type", "=", "general"], ["company_id", "=", COMPANY]])[0]
    a152, a6441, a631 = _account_by_code("152"), _account_by_code("6441"), _account_by_code("631")
    created = []
    for code, name, group, value, day, place, who in ASSETS:
        prof = call("account.asset.profile", "search",
                    [["ua_tax_group", "=", group], ["company_id", "=", COMPANY]], limit=1)
        if not prof:
            say(f"   профіль {group} не знайдено - {code} пропущено")
            continue
        pr = call("account.asset.profile", "read", prof,
                  ["account_asset_id", "account_depreciation_id",
                   "account_expense_depreciation_id", "journal_id", "method", "method_number",
                   "method_period", "method_time", "prorata", "salvage_type", "salvage_value",
                   "ua_start_next_month"])[0]
        # придбання: Дт 152 / Кт 631 + ПДВ, введення в експлуатацію: Дт 104 (112) / Кт 152
        key = f"Придбання і введення в експлуатацію: {name}"
        if not call("account.move", "search_count", [["ref", "=", key]]):
            vat = round(value * 0.2, 2)
            mid = call("account.move", "create", {
                "journal_id": jr, "company_id": COMPANY, "date": day, "ref": key,
                "line_ids": [
                    (0, 0, {"account_id": a152, "partner_id": PR["DEMO-S03"], "name": name,
                            "debit": value, "credit": 0.0}),
                    (0, 0, {"account_id": a6441, "partner_id": PR["DEMO-S03"], "name": "ПДВ",
                            "debit": vat, "credit": 0.0}),
                    (0, 0, {"account_id": a631, "partner_id": PR["DEMO-S03"], "name": name,
                            "debit": 0.0, "credit": value + vat},),
                    (0, 0, {"account_id": pr["account_asset_id"][0], "name": "Введення в експлуатацію",
                            "debit": value, "credit": 0.0}),
                    (0, 0, {"account_id": a152, "name": "Введення в експлуатацію",
                            "debit": 0.0, "credit": value})]})
            call("account.move", "action_post", [mid])
        ids = call("account.asset", "search", [["code", "=", code]])
        # Рахунки і журнал актив бере з профілю; у самого активу таких полів немає,
        # а строк і метод по RPC не підтягуються onchange - переносимо явно.
        vals = {"name": name, "code": code, "profile_id": prof[0], "purchase_value": value,
                "date_start": day, "company_id": COMPANY, "method": pr["method"],
                "method_number": pr["method_number"], "method_period": pr["method_period"],
                "method_time": pr["method_time"], "prorata": pr["prorata"],
                "ua_location": place, "ua_responsible": who,
                "ua_commission": "Акт приймання-передачі (введення в експлуатацію) ОЗ-1 від " + day}
        if pr.get("salvage_value"):
            vals["salvage_value"] = pr["salvage_value"]
        if ids:
            aid = ids[0]
            if call("account.asset", "read", [aid], ["state"])[0]["state"] == "draft":
                call("account.asset", "write", [aid], vals)
        else:
            aid = call("account.asset", "create", vals)
        created.append(aid)
        if call("account.asset", "read", [aid], ["state"])[0]["state"] == "draft":
            call("account.asset", "validate", [aid])
        call("account.asset", "compute_depreciation_board", [aid])
    # проводки амортизації за серпень і вересень
    posted = 0
    lines = call("account.asset.line", "search_read",
                 [["asset_id", "in", created], ["type", "=", "depreciate"],
                  ["move_check", "=", False], ["line_date", "<=", "2026-09-30"]],
                 fields=["line_date", "amount", "asset_id"], order="line_date")
    for ln in lines:
        try:
            call("account.asset.line", "create_move", [ln["id"]])
            posted += 1
        except RpcError as e:
            say(f"   амортизація {ln['line_date']}: {str(e)[:200]}")
            break
    # відомість амортизації за вересень
    sheet = call("ua.depreciation.sheet", "create",
                 {"company_id": COMPANY, "date_from": "2026-09-01", "date_to": "2026-09-30"})
    try:
        call("ua.depreciation.sheet", "action_compute", [sheet])
    except RpcError:
        pass
    say(f"Основні засоби: {len(created)} об'єкти (верстат, автомобіль, МНМА), "
        f"проведено {posted} рядків амортизації за серпень-вересень.")


# =====================================================================================
# 14. CRM
# =====================================================================================
LEADS = [
    ("Мережа кав'ярень «Кава Львів»: 40 столів і 120 стільців", "DEMO-C01", 620000, 70, 0),
    ("Готель «Дністер»: меблі для 30 номерів", "DEMO-C06", 1250000, 50, 1),
    ("Коворкінг «Хаб 14»: 60 робочих місць", "DEMO-C04", 480000, 40, 1),
    ("ТОВ «Школярик»: парти для трьох шкіл", "DEMO-C07", 890000, 60, 2),
    ("Салон «Інтер'єр Плюс»: шафи-купе на замовлення", "DEMO-C02", 340000, 30, 0),
    ("ФОП Бондаренко: кухонні фасади", "DEMO-C08", 96000, 25, 0),
    ("ТОВ «Дніпро Меблі»: дилерська угода на 2027", "DEMO-C05", 2100000, 35, 1),
    ("Drewno Sp. z o.o.: експорт столів до Польщі, друга партія", "DEMO-C12", 760000, 55, 2),
    ("ТОВ «Затишна оселя»: гардеробні системи", "DEMO-C03", 410000, 45, 2),
    ("ФОП Марченко: меблі для студії", "DEMO-C11", 128000, 20, 3),
]


def crm(PR):
    # останній етап - «Виграно»: нагода в ньому не може мати ймовірність нижче 100,
    # тому демо-нагоди розкладаємо лише по робочих етапах
    stages = call("crm.stage", "search_read", [["is_won", "=", False]],
                  fields=["name"], order="sequence") \
        or call("crm.stage", "search_read", [], fields=["name"], order="sequence")[:-1]
    made = 0
    for name, cust, value, prob, stage_idx in LEADS:
        if call("crm.lead", "search_count", [["name", "=", name]]):
            continue
        call("crm.lead", "create", {
            "name": name, "partner_id": PR[cust], "type": "opportunity",
            "expected_revenue": value, "probability": prob, "company_id": COMPANY,
            "stage_id": stages[min(stage_idx, len(stages) - 1)]["id"] if stages else False})
        made += 1
    say(f"CRM: {made} нових нагод, усього {call('crm.lead', 'search_count', [])}; "
        f"етапи: {', '.join(s['name'] for s in stages)}.")


# =====================================================================================
# 15. Звітність і контрольна таблиця
# =====================================================================================
def vat_by_month():
    out = []
    for m, last in [(7, 31), (8, 31), (9, 30)]:
        wiz = call("ua.vat.cabinet", "create", {"date_from": f"2026-{m:02d}-01",
                                                "date_to": f"2026-{m:02d}-{last}",
                                                "company_id": COMPANY})
        call("ua.vat.cabinet", "action_compute", [wiz])
        r = call("ua.vat.cabinet", "read", [wiz],
                 ["pz_total", "pk_total", "due_total", "ua_fe_vat", "ua_r_export_base",
                  "ua_r19", "problems"])[0]
        out.append((m, r))
    return out


def osv():
    rid = call("ua.osv.report", "create", {"company_id": COMPANY,
                                           "date_from": "2026-07-01", "date_to": "2026-09-30"})
    call("ua.osv.report", "action_compute", [rid])
    return call("ua.osv.report", "read", [rid],
                ["total_open_debit", "total_open_credit", "total_debit", "total_credit",
                 "total_close_debit", "total_close_credit", "control_ok"])[0], rid


def finrep_balance():
    out = {}
    for xmlid, label in [("l10n_ua_finrep.instance_f1", "Ф1"), ("l10n_ua_finrep.instance_f2", "Ф2")]:
        mod, name = xmlid.split(".")
        d = call("ir.model.data", "search_read", [["module", "=", mod], ["name", "=", name]],
                 fields=["res_id"])
        if not d:
            continue
        inst = d[0]["res_id"]
        try:
            res = call("mis.report.instance", "compute", [inst])
        except RpcError as e:
            out[label] = {"error": str(e)[:200]}
            continue
        # рядок форми впізнаємо за чотиризначним кодом на початку підпису
        # («1300 Баланс (актив)»): compute() віддає саме label, без імені KPI
        vals = {}
        for line in res.get("body", []):
            m = re.match(r"^(\d{4})\b", line.get("label") or "")
            cells = line.get("cells") or []
            val = cells[0].get("val") if cells and isinstance(cells[0], dict) else None
            if m:
                vals["r" + m.group(1)] = val
        out[label] = vals
    return out


def account_balance(code, date_to="2026-09-30"):
    accs = call("account.account", "search", [["code", "=like", f"{code}%"]])
    if not accs:
        return 0.0
    res = call("account.move.line", "read_group",
               [["account_id", "in", accs], ["parent_state", "=", "posted"],
                ["date", "<=", date_to], ["company_id", "=", COMPANY]],
               ["balance:sum"], [])
    return round(res[0]["balance"] if res and res[0].get("balance") else 0.0, 2)


def stock_value():
    prods = call("product.product", "search_read",
                 [["is_storable", "=", True]], fields=["default_code", "qty_available",
                                                       "standard_price", "categ_id"])
    mat = sum(p["qty_available"] * p["standard_price"] for p in prods
              if (p["default_code"] or "").startswith("M"))
    fin = sum(p["qty_available"] * p["standard_price"] for p in prods
              if (p["default_code"] or "").startswith("F"))
    return round(mat, 2), round(fin, 2)


def control_table():
    say("")
    say("=" * 96)
    say("КОНТРОЛЬНА ТАБЛИЦЯ ДЕМО-БАЗИ «ЯСЕН МЕБЛІ» (липень-вересень 2026)")
    say("=" * 96)
    models = [
        ("res.partner", [["ref", "like", "DEMO-"]], "контрагенти демо"),
        ("product.template", [["default_code", "!=", False]], "номенклатура"),
        ("mrp.bom", [], "специфікації"),
        ("purchase.order", [], "замовлення на закупівлю"),
        ("sale.order", [], "замовлення на продаж"),
        ("stock.picking", [["state", "=", "done"]], "проведені переміщення"),
        ("mrp.production", [["state", "=", "done"]], "виконані виробничі замовлення"),
        ("account.move", [["move_type", "=", "out_invoice"], ["state", "=", "posted"]], "рахунки клієнтам"),
        ("account.move", [["move_type", "=", "out_refund"], ["state", "=", "posted"]], "повернення (сторно)"),
        ("account.move", [["move_type", "=", "in_invoice"], ["state", "=", "posted"]], "рахунки постачальників"),
        ("account.move", [["state", "=", "posted"]], "проведені проводки, усього"),
        ("account.payment", [["state", "in", ["posted", "paid", "in_process"]]], "платежі"),
        ("account.payment", [["ua_order_kind", "!=", False]], "касові ордери ПКО/ВКО"),
        ("ua.advance.report", [], "авансові звіти"),
        ("ua.vat.document", [["doc_kind", "=", "tax_invoice"]], "податкові накладні"),
        ("ua.vat.document", [["doc_kind", "=", "adjustment"]], "розрахунки коригування"),
        ("ua.vat.document", [["state", "=", "registered"]], "зареєстровано в ЄРПН"),
        ("account.asset", [["state", "!=", "draft"]], "основні засоби"),
        ("account.asset.line", [["move_check", "=", True]], "проведені рядки амортизації"),
        ("res.currency.rate", [["name", ">=", "2026-07-01"]], "курси НБУ за квартал"),
        ("crm.lead", [], "нагоди CRM"),
        ("hr.employee", [["active", "=", True]], "працівники"),
        ("hr.payslip", [["state", "=", "done"]], "проведені розрахункові листки"),
    ]
    for model, dom, label in models:
        try:
            n = call(model, "search_count", dom)
        except RpcError as e:
            n = f"помилка: {str(e)[:60]}"
        say(f"  {label:<42} {n}")
    say("-" * 96)
    res = call("account.move.line", "read_group",
               [["parent_state", "=", "posted"], ["company_id", "=", COMPANY]],
               ["debit:sum", "credit:sum"], [])
    dt = round(res[0]["debit"], 2) if res else 0.0
    kt = round(res[0]["credit"], 2) if res else 0.0
    say(f"  Проведені проводки: Дт {dt:,.2f} = Кт {kt:,.2f}  ->  "
        f"{'сходиться' if abs(dt - kt) < 0.01 else 'РОЗБІЖНІСТЬ ' + format(dt - kt, ',.2f')}")
    o, _rid = osv()
    say(f"  ОСВ за квартал: оборот Дт {o['total_debit']:,.2f}, Кт {o['total_credit']:,.2f}, "
        f"контроль {'ok' if o['control_ok'] else 'НІ'}")
    mat, fin = stock_value()
    b201, b26, b23 = account_balance("201"), account_balance("26"), account_balance("23")
    say(f"  Склад матеріалів {mat:,.2f} vs рахунок 201 {b201:,.2f}  "
        f"(різниця {mat - b201:,.2f})")
    say(f"  Готова продукція {fin:,.2f} vs рахунок 26 {b26:,.2f}  "
        f"(різниця {fin - b26:,.2f}); незавершене 23 = {b23:,.2f}")
    say("-" * 96)
    for m, r in vat_by_month():
        say(f"  ПДВ {m:02d}.2026: ПЗ {r['pz_total']:,.2f}, ПК {r['pk_total']:,.2f}, "
            f"до сплати {r['due_total']:,.2f} (аванси {r['ua_fe_vat']:,.2f}, "
            f"експорт {r['ua_r_export_base']:,.2f}, від'ємне {r['ua_r19']:,.2f})")
    say("-" * 96)
    fr = finrep_balance()
    f1 = fr.get("Ф1", {})
    act, pas = f1.get("r1300"), f1.get("r1900")
    if act is None or pas is None:
        say(f"  Ф1: не вдалося прочитати рядки 1300/1900 ({list(f1)[:6]})")
    else:
        say(f"  Ф1 Баланс: Актив (1300) {act:,.2f} = Пасив (1900) {pas:,.2f}  ->  "
            f"{'сходиться' if abs(act - pas) < 1 else 'РОЗБІЖНІСТЬ ' + format(act - pas, ',.2f')}")
    f2 = fr.get("Ф2", {})
    if f2.get("r2000") is not None:
        say(f"  Ф2: чистий дохід (2000) {f2.get('r2000') or 0:,.2f}, "
            f"собівартість (2050) {f2.get('r2050') or 0:,.2f}, "
            f"фінрезультат (2290/2295) {f2.get('r2290') or f2.get('r2295') or 0:,.2f}")
    say("=" * 96)


# =====================================================================================
def main():
    say("== база %s на %s ==" % (DB, URL))
    ensure_chart()
    run_payroll_builders()
    saved = unlock_periods()
    try:
        company_details()
        PR = partners()
        say(f"Банківських рахунків позначено надійними: {trust_banks()}.")
        tx = taxes()
        P = products(tx)
        boms(P)
        nbu_rates()
        export_pricelist = pricelists()
        purchases(PR, P, tx)
        costs = manufacturing(P)
        production_cost_entries(costs)
        invoices = sales(PR, P, tx)
        export_sale(PR, P, tx, export_pricelist)
        cogs_entries()
        sale_return(PR, invoices, tx)
        tax_invoices()
        bank_money(PR)
        cash_orders(PR)
        assets(PR, tx)
        crm(PR)
    finally:
        relock_periods(saved)
    control_table()


if __name__ == "__main__":
    main()
