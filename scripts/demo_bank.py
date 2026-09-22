"""Демо-дані банку для стенду: початковий залишок на рахунку і звірка виписки за правилами.

1. Проводка «Початковий залишок на поточному рахунку» на 1 серпня 2026: Дт 311 Кт 441.
   Без неї залишок рахунку від'ємний, бо у виписці є лише виплати зарплати.
2. Дія «Застосувати правила» екрана «Банк»: незвіреним рядкам проставляє рахунок
   за правилами звірки (661, 6411, 6415, 651, 6851).

Скрипт ідемпотентний: проводку шукає за посиланням, повторний запуск нічого не дублює.
База - зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/demo_bank.py"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/") + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

OPENING_REF = "Початковий залишок на поточному рахунку"
OPENING_DATE = "2026-08-01"
# Квартал видатковий (три місяці зарплати на 23 людей проти виторгу), тому початкового
# мільйона не вистачало: тепер, коли платежі відомостей справді йдуть через банк, залишок
# на рахунку видно в контрольній таблиці, і він не має бути від'ємним.
OPENING_AMOUNT = 2700000.00
DEMO_IBAN = "UA213052990000026007233566001"
MONO_JOURNAL = "Monobank (еквайринг)"
MONO_CODE = "MONO"
MONO_IBAN = "UA733220010000026001234567890"


def rpc(service, method, *args):
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(request, timeout=600).read())
    if "error" in data:
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:2000])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти як admin на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def bank_op(method, **params):
    """Одна банківська операція: ua.bank.ops, та сама логіка, що й за чарівником
    «Операції банку»."""
    return call("ua.bank.ops", method, **params)


def account(*codes):
    for code in codes:
        found = call("account.account", "search", [["code", "=like", f"{code}%"]], limit=1)
        if found:
            return found[0]
    raise SystemExit(f"Не знайдено рахунок {codes}")


company = call("res.users", "read", [UID], ["company_id"])[0]["company_id"][0]
journal = call("account.journal", "search", [["type", "=", "bank"], ["company_id", "=", company]], limit=1)
if not journal:
    raise SystemExit("У компанії немає банківського журналу.")

# 0. Вимкнути годинний крон OCA «Pull Online Bank Statements».
# Демо-режим провайдера віддає вигаданий зразок, прив'язаний до місяця вікна: раз на
# годину крон дописував у той самий журнал ще одну «зарплату за вересень», під якою немає
# жодного нарахування, і правило звірки кодувало її на 661. Кнопка «Завантажити за місяць»
# працює як працювала - вимикаємо саме фонове підтягування зразка.
cron = call("ir.model.data", "search_read",
            [["module", "=", "account_statement_import_online"],
             ["name", "=", "ir_cron_account_pull_online_bank_statements"]], fields=["res_id"])
if cron:
    call("ir.cron", "write", [cron[0]["res_id"]], {"active": False})
    print("Фонове підтягування виписок (крон OCA) вимкнено: демо-зразок не вигадує зарплату.")

# 1. Початковий залишок
existing = call("account.move", "search", [["ref", "=", OPENING_REF], ["company_id", "=", company]])
if existing:
    print(f"Початковий залишок уже є (проводка {existing[0]}).")
else:
    misc = call("account.journal", "search", [["type", "=", "general"], ["company_id", "=", company]], limit=1)
    bank_account = call("account.journal", "read", journal, ["default_account_id"])[0]["default_account_id"][0]
    equity = account("441", "44", "40")
    move = call("account.move", "create", {
        "journal_id": misc[0], "date": OPENING_DATE, "ref": OPENING_REF,
        "line_ids": [
            (0, 0, {"account_id": bank_account, "debit": OPENING_AMOUNT, "credit": 0.0, "name": OPENING_REF}),
            (0, 0, {"account_id": equity, "debit": 0.0, "credit": OPENING_AMOUNT, "name": OPENING_REF}),
        ],
    })
    call("account.move", "action_post", [move])
    print(f"Створено і проведено початковий залишок {OPENING_AMOUNT:,.2f} на {OPENING_DATE} (проводка {move}).")

# 1б. Реквізити демо-з'єднання, щоб на екрані було видно рахунок
provider = call("online.bank.statement.provider", "search", [["journal_id", "=", journal[0]]], limit=1)
if not provider:
    action = bank_op("action_create_provider", journal_id=journal[0], service="ua_privat")
    provider = [action["res_id"]]
    print(f"Створено з'єднання {provider[0]} для журналу {journal[0]}.")
call("online.bank.statement.provider", "write", provider,
     {"ua_account": DEMO_IBAN, "ua_demo": True, "service": "ua_privat"})
print(f"Демо-з'єднання {provider[0]}: рахунок {DEMO_IBAN}, ПриватБанк, демо-режим.")

# 1в. Другий банк як зразок: окремий журнал, окреме з'єднання, свої дані
mono = call("account.journal", "search", [["type", "=", "bank"], ["name", "=", MONO_JOURNAL], ["company_id", "=", company]], limit=1)
if not mono:
    mono = [call("account.journal", "create", {"name": MONO_JOURNAL, "type": "bank", "code": MONO_CODE, "company_id": company})]
    print(f"Створено журнал «{MONO_JOURNAL}» ({mono[0]}).")
mono_provider = call("online.bank.statement.provider", "search", [["journal_id", "=", mono[0]]], limit=1)
if not mono_provider:
    action = bank_op("action_create_provider", journal_id=mono[0], service="ua_mono")
    mono_provider = [action["res_id"]]
call("online.bank.statement.provider", "write", mono_provider,
     {"service": "ua_mono", "ua_demo": True, "ua_account": MONO_IBAN, "statement_creation_mode": "monthly"})
today = __import__("datetime").date.today()
pull = bank_op("action_pull_month", journal_id=mono[0], year=today.year, month=today.month)
print(f"Monobank: {pull['message']}")

# 2. Звірка за правилами
before = call("account.bank.statement.line", "search_count", [["is_reconciled", "=", False]])
result = bank_op("action_apply_rules")
after = call("account.bank.statement.line", "search_count", [["is_reconciled", "=", False]])
print(result["message"].replace("\n", " | "))
print(f"Незвірених рядків: було {before}, стало {after}.")

rest = call("account.bank.statement.line", "search_read", [["is_reconciled", "=", False]],
            fields=["date", "payment_ref", "amount"], limit=20)
for line in rest:
    print(f"  лишилось: {line['date']} {line['payment_ref'][:60]} {line['amount']:,.2f}")

balances = call("account.journal", "read", [journal[0], mono[0]], ["name"])
for row in balances:
    lines = call("account.bank.statement.line", "search_count",
                 [["journal_id", "=", row["id"]]])
    print(f"Рядків виписки на рахунку {row['name']}: {lines}")

# 3. Підготовка до підключення: чек-лист на кожен банківський журнал.
# Ключів банку ще немає, тому кроки лишаються невиконаними. Це і є стан справ.
for journal_id, service, holder in ((journal[0], "ua_privat", "Директор"), (mono[0], "ua_mono", "Директор")):
    connect = call("ua.bank.connect", "search", [["journal_id", "=", journal_id]], limit=1)
    if not connect:
        connect = [call("ua.bank.connect", "create",
                        {"journal_id": journal_id, "service": service, "key_holder": holder,
                         "key_place": "worker", "company_id": company})]
    steps = call("ua.bank.connect", "read", connect, ["done_steps", "total_steps", "name"])[0]
    print(f"Підключення {steps['name']}: {steps['done_steps']} з {steps['total_steps']} кроків.")
