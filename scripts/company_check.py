"""Перевірка поділу даних між компаніями. Читаємо стенд, нічого не пишемо.

Odoo ділить дані між компаніями двома речами: полем company_id на записі і набором
компаній у користувача (company_ids - кому що дозволено, company_id - яка компанія
відкривається типово). Скрипт дивиться на обидві сторони на живій базі:

  1. по кожній нашій моделі з полем company_id - скільки записів у якій компанії;
  2. записи без компанії: якщо поле обов'язкове - це провал (запис бачать усі, а не
     мав би); якщо поле необов'язкове - це навмисне «порожньо = для всіх компаній»
     (так живуть параметри зарплати, ЄП і податку на прибуток), і воно йде окремим
     рядком як спостереження, а не як провал;
  3. набір компаній у демо-користувачів проти того, який ми задумали (EXPECTED):
     адміністратор бачить усі, lab - «Ясен Меблі» і «АероСіч», завскладі й
     закупівельниця - лише «Ясен Меблі», користувач працівника «АероСіч» - лише її.

Активний набір компаній (той, що показує перемикач угорі) сервер не тримає: це
cookie `cids` у браузері. Сервер задає лише company_id (яка компанія стане активною,
коли cookie немає) і company_ids (що взагалі дозволено). Тому перевіряємо саме їх.

Перевірка тільки читає: search_read, read_group, fields_get. Жодного запису.

База зі змінної DEMO_DB (типово demo), порт - DEMO_PORT (типово 8131).
Запуск: python3 scripts/company_check.py
        DEMO_DB=demo2 DEMO_PORT=8132 python3 scripts/company_check.py"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("DEMO_PORT") or "8131").strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
DB = os.environ.get("DEMO_DB", "demo").strip()
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

MEBLI = "ТОВ «Ясен Меблі»"
LOGISTYKA = "ТОВ «Ясен Логістика»"
AEROSICH = "ТОВ «АероСіч»"

# Кому які компанії дозволені. Ключ - логін, значення - назви компаній.
# Адміністратор веде всі три (він же збирає консолідацію групи), lab показує
# зовнішньому тестовому сайту меблі й дрони, склад і закупівлі сидять в одній компанії.
EXPECTED = {
    "admin": {MEBLI, LOGISTYKA, AEROSICH},
    "lab": {MEBLI, AEROSICH},
    "petrenko": {MEBLI},
    "tkach": {MEBLI},
    "koval": {MEBLI},
    "zakupivli": {MEBLI},
}
# Типова компанія: з неї відкривається сесія, коли в браузері немає cookie cids.
EXPECTED_DEFAULT = {"admin": MEBLI, "lab": MEBLI, "petrenko": MEBLI, "tkach": MEBLI,
                    "koval": MEBLI, "zakupivli": MEBLI}
# Службовий користувач Odoo: компанії йому роздає сам Odoo при створенні кожної нової.
SYSTEM_LOGINS = {"__system__"}

errors = []
notes = []
total = 0
skipped = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def skip(label, why):
    global skipped
    skipped += 1
    print(f"[--] {label} - {why}")


def note(text):
    notes.append(text)
    print(f"[..] {text}")


def rpc(service, method, *args):
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "company-check"})
    data = json.loads(urllib.request.urlopen(request, timeout=600).read())
    if "error" in data:
        message = data["error"].get("data", {}).get("message") or data["error"]
        raise RuntimeError(json.dumps(message, ensure_ascii=False)[:300]
                           if not isinstance(message, str) else message[:300])
    return data.get("result")


try:
    UID = rpc("common", "login", DB, LOGIN, PW)
except Exception as error:
    raise SystemExit(f"Стенд {BASE} не відповідає: {error}")
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як {LOGIN} на базі {DB}.")

COMPANIES = rpc("object", "execute_kw", DB, UID, PW, "res.company", "search_read",
                [[]], {"fields": ["name", "sequence"], "order": "sequence, id"})
ALL_IDS = [c["id"] for c in COMPANIES]
# Читаємо від імені адміністратора з усіма компаніями в контексті: інакше правила
# множинності сховають чужі записи, і перевірка «скільки де» нічого не побачить.
CTX = {"active_test": False, "allowed_company_ids": ALL_IDS}


def call(model, method, *args, **kw):
    kw.setdefault("context", CTX)
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(args), kw)


print(f"База {DB} на {BASE}; компанії: "
      + ", ".join(f'{c["name"]} (id {c["id"]})' for c in COMPANIES))
print()

# 1. наші моделі -----------------------------------------------------------------
# «Наша» модель - та, яку не згадує жоден чужий модуль: у ir.model.modules стоять
# лише l10n_ua_* і bp_*. Розширення чужих моделей (account.move і подібні) сюди не
# потрапляють навмисно: їхній поділ веде саме Odoo, і перевіряти його нам нічого.
models = [m for m in call("ir.model", "search_read", [], fields=["model", "modules", "transient"])
          if m["modules"] and all(part.strip().startswith(("l10n_ua_", "bp_"))
                                  for part in m["modules"].split(","))
          and not m["transient"]]
names = sorted(m["model"] for m in models)
fields = call("ir.model.fields", "search_read",
              [["name", "=", "company_id"], ["model", "in", names]],
              fields=["model", "required"])
WITH_COMPANY = {f["model"]: f for f in fields}

counted = 0
empty = []
for model in sorted(WITH_COMPANY):
    required = bool(WITH_COMPANY[model]["required"])
    try:
        groups = call(model, "read_group", [], ["id"], ["company_id"], lazy=False)
    except RuntimeError as error:
        # Абстрактна основа таблиці не має, і доступу до неї теж: це не провал.
        skip(f"{model}: записи по компаніях", str(error).splitlines()[0][:90])
        continue
    counted += 1
    per = {}
    blank = 0
    for row in groups:
        if row["company_id"]:
            per[row["company_id"][1]] = row["__count"]
        else:
            blank += row["__count"]
    records = sum(per.values()) + blank
    if not records:
        empty.append(model)
        continue
    spread = ", ".join(f"{name}: {qty}" for name, qty in sorted(per.items()))
    if required:
        check(f"{model}: кожен запис має компанію", not blank,
              (f"{blank} записів без компанії; " if blank else "") + (spread or "порожньо"))
    elif blank:
        note(f"{model}: {blank} записів без компанії - спільні для всіх"
             + (f"; {spread}" if spread else ""))
    else:
        note(f"{model}: {spread}")

note(f"наших моделей {len(names)}, із них із company_id {len(WITH_COMPANY)}, "
     f"перелічено {counted}, порожніх {len(empty)}")

# 2. користувачі -------------------------------------------------------------------
users = call("res.users", "search_read", [["share", "=", False]],
             fields=["login", "name", "company_id", "company_ids", "active"])
by_login = {u["login"]: u for u in users}
company_name = {c["id"]: c["name"] for c in COMPANIES}

for login in sorted(EXPECTED):
    user = by_login.get(login)
    if not user:
        skip(f"{login}: набір компаній", "користувача немає в базі")
        continue
    got = {company_name.get(i, str(i)) for i in user["company_ids"]}
    check(f"{login}: компанії за задумом", got == EXPECTED[login],
          "є " + (", ".join(sorted(got)) or "жодної")
          + " · мало бути " + ", ".join(sorted(EXPECTED[login])))
    default = user["company_id"][1] if user["company_id"] else None
    check(f"{login}: типова компанія", default == EXPECTED_DEFAULT[login],
          f"{default} · мало бути {EXPECTED_DEFAULT[login]}")

# Користувачі працівників «АероСіч»: якщо демо їх заведе, вони сидять лише в ній.
employees = call("hr.employee", "search_read", [["user_id", "!=", False]],
                 fields=["name", "user_id", "company_id"])
for employee in employees:
    login = by_login.get(employee["user_id"][1], {}).get("login")
    user = next((u for u in users if u["id"] == employee["user_id"][0]), None)
    if not user or user["login"] in EXPECTED or user["login"] in SYSTEM_LOGINS:
        continue
    want = {employee["company_id"][1]} if employee["company_id"] else set()
    got = {company_name.get(i, str(i)) for i in user["company_ids"]}
    check(f'{user["login"]}: компанії за працівником {employee["name"]}', got == want,
          "є " + ", ".join(sorted(got)) + " · мало бути " + ", ".join(sorted(want)))

strangers = [u for u in users if u["login"] not in EXPECTED and u["login"] not in SYSTEM_LOGINS
             and not any(e["user_id"][0] == u["id"] for e in employees)]
if strangers:
    note("користувачі поза задумом: " + "; ".join(
        f'{u["login"]} ({", ".join(sorted(company_name.get(i, str(i)) for i in u["company_ids"]))})'
        for u in strangers))

# Перемикач компаній відкриється на одній компанії лише тоді, коли в браузері немає
# cookie cids: активний набір тримає клієнт, а не сервер. Нагадуємо це в кінці, щоб
# «у мене все одно три» не виглядало помилкою даних.
note("активний набір компаній - cookie cids у браузері; сервер задає лише типову "
     "компанію і перелік дозволених")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено"
          + (f", пропущено {skipped}" if skipped else ""))
    for label in errors:
        print(f"  - {label}")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total})"
      + (f", пропущено {skipped}" if skipped else "") + ".")
