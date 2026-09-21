"""Перевірка модуля l10n_ua_bank_online: екран «Банк» і постачальники виписок.

Що перевіряємо: get_screen_data() повертає всі ключі і принаймні один банківський рахунок;
з'єднання створюється дією екрана; демо-режим завантажує виписку за місяць; повторне
завантаження не дублює рядків (unique_import_id); екран бачить рядки, виписку і незвірені
рядки; розбір відповідей ПриватБанку і Monobank дає правильні суму, знак, дату і призначення
(через odoo shell, бо приватні методи не викликаються по RPC); бандл web.assets_backend
містить компонент; користувач lana бачить меню «Банк».

База читається зі змінної PAYROLL_DB (типово payroll). Демо-виписку тягнемо за поточний
місяць, щоб не чіпати серпневі дані, які звіряють інші перевірки.
Запуск: PAYROLL_DB=payroll python3 scripts/bank_check.py"""
import http.cookiejar
import json
import os
import subprocess
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = f"http://127.0.0.1:{PORT}"
URL = f"{BASE}/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(),
        {"Content-Type": "application/json"}), timeout=600)
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти як admin на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


today = date.today()
YEAR, MONTH = today.year, today.month

# 1. Екран віддає всі ключі
data = call("ua.bank.board", "get_screen_data")
expected = {"company", "period", "accounts", "payments", "unreconciled", "statements", "totals"}
check("get_screen_data() повертає всі ключі", expected.issubset(data.keys()),
      f"відсутні: {expected - set(data.keys())}" if not expected.issubset(data.keys()) else
      f"рахунків: {len(data['accounts'])}, період {data['period']['month']}.{data['period']['year']}")
check("є щонайменше один банківський рахунок", len(data["accounts"]) >= 1)

account = data["accounts"][0]
journal_id = account["journal_id"]
check("у рахунку є назва, валюта і залишок",
      bool(account["name"]) and bool(account["currency"]) and isinstance(account["balance"], (int, float)),
      f"{account['name']}, {account['currency']}, залишок {account['balance']}")

# 2. Дві служби доступні у полі service
services = dict(call("online.bank.statement.provider", "fields_get", ["service"], ["selection"])["service"]["selection"])
check("служба «ПриватБанк (Автоклієнт)» є у списку", services.get("ua_privat") == "ПриватБанк (Автоклієнт)")
check("служба «Monobank» є у списку", services.get("ua_mono") == "Monobank")

# 3. З'єднання: створюємо дією екрана, вмикаємо демо-режим
provider_ids = call("online.bank.statement.provider", "search", [["journal_id", "=", journal_id]])
if not provider_ids:
    action = call("ua.bank.ops", "action_create_provider", journal_id, "ua_privat")
    check("action_create_provider повертає форму з'єднання", action.get("res_model") == "online.bank.statement.provider")
    provider_ids = [action["res_id"]]
else:
    check("action_create_provider не потрібен - з'єднання вже є", True, f"id={provider_ids[0]}")
provider_id = provider_ids[0]
call("online.bank.statement.provider", "write", [provider_id],
     {"service": "ua_privat", "ua_demo": True, "statement_creation_mode": "monthly"})
provider = call("online.bank.statement.provider", "read", [provider_id], ["service", "ua_demo", "journal_id"])[0]
check("з'єднання прив'язане до журналу і в демо-режимі",
      provider["ua_demo"] and provider["journal_id"][0] == journal_id, f"служба {provider['service']}")

# 4. Перевірка зв'язку в демо-режимі не ходить у мережу
result = call("ua.bank.ops", "action_test", journal_id)
check("action_test у демо-режимі відповідає без мережі", bool(result), str(result)[:120])

# 5. Завантаження в порожній місяць (два місяці вперед, щоб не чіпати дані стенду)
TEST_YEAR, TEST_MONTH = (YEAR + 1, MONTH + 2 - 12) if MONTH + 2 > 12 else (YEAR, MONTH + 2)
before = call("account.bank.statement.line", "search_count", [["journal_id", "=", journal_id]])
pull = call("ua.bank.ops", "action_pull_month", journal_id, TEST_YEAR, TEST_MONTH)
check("завантаження створило рядки виписки", pull.get("created", 0) >= 8, pull.get("message", ""))

# 6. Повторне завантаження не дублює (unique_import_id)
again = call("ua.bank.ops", "action_pull_month", journal_id, TEST_YEAR, TEST_MONTH)
check("повторне завантаження не дублює рядків", again.get("created", 0) == 0, f"створено {again.get('created')}")
after = call("account.bank.statement.line", "search_count", [["journal_id", "=", journal_id]])
check("кількість рядків зросла рівно на завантажене", after - before == pull.get("created", 0),
      f"{before} → {after}")

# 7. Суми і знаки в завантажених рядках
test_domain = [["journal_id", "=", journal_id], ["date", ">=", f"{TEST_YEAR}-{TEST_MONTH:02d}-01"]]
lines = call("account.bank.statement.line", "search_read",
             test_domain + [["payment_ref", "ilike", "Заробітна плата"]],
             fields=["amount", "payment_ref", "partner_name", "date"], limit=5)
check("зарплатний платіж завантажено зі знаком мінус",
      bool(lines) and all(l["amount"] < 0 for l in lines), lines[0]["payment_ref"] if lines else "рядків немає")
income = call("account.bank.statement.line", "search_read",
              test_domain + [["payment_ref", "ilike", "Оплата за меблі"]],
              fields=["amount", "partner_name"], limit=5)
check("надходження завантажено зі знаком плюс і контрагентом",
      bool(income) and all(l["amount"] > 0 and l["partner_name"] for l in income),
      income[0]["partner_name"] if income else "рядків немає")

# 8. Екран бачить нові дані
data2 = call("ua.bank.board", "get_screen_data", year=TEST_YEAR, month=TEST_MONTH)
account2 = [a for a in data2["accounts"] if a["journal_id"] == journal_id][0]
check("екран показує рядки місяця", account2["lines_month"] >= 8, f"{account2['lines_month']} рядків")
check("екран показує надходження і списання",
      account2["amount_in"] > 0 and account2["amount_out"] < 0,
      f"+{account2['amount_in']} / {account2['amount_out']}")
check("екран показує незвірені рядки", account2["unreconciled"] >= 1, f"{account2['unreconciled']} незвірених")
check("екран показує виписку періоду", len(data2["statements"]) >= 1,
      data2["statements"][0]["name"] if data2["statements"] else "виписок немає")
check("список незвірених рядків непорожній", len(data2["unreconciled"]) >= 1)
check("підсумки екрана рахують з'єднання і незвірене",
      data2["totals"]["connected"] >= 1 and data2["totals"]["unreconciled"] >= 1, str(data2["totals"]))

# 9. Дії відкривають екрани Odoo
reconcile = call("ua.bank.board", "action_open_reconcile", journal_id)
check("дія «Звірити» відкриває рядки виписки",
      reconcile.get("res_model") == "account.bank.statement.line", reconcile.get("name", ""))
statements = call("ua.bank.board", "action_open_statements", journal_id)
check("дія «Виписки» відкриває виписки", statements.get("res_model") == "account.bank.statement")

# 10. Розбір відповідей банків (odoo shell: приватні методи недоступні по RPC)
shell = r'''
env = env(user=1)
p = env["online.bank.statement.provider"].search([], limit=1)
privat = p._ua_privat_line({
    "AUT_CNTR_NAM": "ГУ ДПС у м. Києві", "AUT_CNTR_ACC": "UA9089999803130800000000101",
    "CCY": "UAH", "OSND": "ПДФО за серпень 2026", "SUM": "37581.00", "TRANTYPE": "D",
    "DATE_TIME_DAT_OD_TIM_P": "06.09.2026 10:15:00", "ID": "PRV-1", "NUM_DOC": "42",
})
mono = p._ua_mono_line({
    "id": "MONO-1", "time": 1788679800, "description": "ТОВ «Дім і сад»",
    "comment": "Оплата за меблі", "amount": 18000000, "counterName": "ТОВ «Дім і сад»",
    "counterIban": "UA213052990000026007233566001",
})
skip = p._ua_privat_line({"CCY": "USD", "OSND": "валютний", "SUM": "10", "TRANTYPE": "C", "DAT_OD": "06.09.2026"})
print("SHELL_RESULT", repr([
    privat["amount"], privat["payment_ref"], privat["partner_name"], str(privat["date"])[:16], privat["unique_import_id"],
    mono["amount"], mono["payment_ref"], mono["unique_import_id"], skip is None,
]))
'''
proc = subprocess.run(
    ["docker", "compose", "run", "--rm", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http", "--log-level=warn"],
    input=shell, capture_output=True, text=True, cwd=ROOT, timeout=900)
out = [l for l in proc.stdout.splitlines() if l.startswith("SHELL_RESULT")]
if not out:
    check("розбір відповідей банків (odoo shell)", False, (proc.stderr or proc.stdout)[-300:])
else:
    values = eval(out[0][len("SHELL_RESULT"):].strip())  # noqa: S307 - власний вивід
    amount, ref, partner, moment, uid_privat, mono_amount, mono_ref, mono_uid, skipped = values
    check("ПриватБанк: списання стає мінусом", amount == -37581.0, str(amount))
    check("ПриватБанк: призначення і контрагент на місці",
          ref == "ПДФО за серпень 2026" and partner == "ГУ ДПС у м. Києві", f"{ref} / {partner}")
    check("ПриватБанк: дата з часом банку", moment.startswith("2026-09-06"), moment)
    check("ПриватБанк: ідентифікатор для захисту від дублів", uid_privat == "PRV-1", uid_privat)
    check("ПриватБанк: рядок в іншій валюті пропущено", skipped is True)
    check("Monobank: копійки стають гривнями", mono_amount == 180000.0, str(mono_amount))
    check("Monobank: призначення склеєне з опису і коментаря",
          mono_ref == "ТОВ «Дім і сад»: Оплата за меблі", mono_ref)
    check("Monobank: ідентифікатор для захисту від дублів", mono_uid == "MONO-1", mono_uid)

# 10б. Прибираємо тестовий місяць: стенд лишається з даними серпня і вересня
test_statements = call("account.bank.statement", "search",
                       [["journal_id", "=", journal_id], ["date", ">=", f"{TEST_YEAR}-{TEST_MONTH:02d}-01"]])
if test_statements:
    call("account.bank.statement", "unlink", test_statements)
test_lines = call("account.bank.statement.line", "search", test_domain)
if test_lines:
    call("account.bank.statement.line", "unlink", test_lines)
left = call("account.bank.statement.line", "search_count", test_domain)
check("тестовий місяць прибрано зі стенду", left == 0, f"лишилось рядків: {left}")

# 11. Меню «Банк» бачить бухгалтер
lana_uid = rpc("common", "login", DB, "lana", ENV.get("LANA_PASSWORD", "").strip())
if lana_uid:
    menus = rpc("object", "execute_kw", DB, lana_uid, ENV["LANA_PASSWORD"].strip(),
                "ir.ui.menu", "search_read", [[["name", "=", "Банк"]]], {"fields": ["name", "action"]})
    check("lana бачить меню «Банк»", bool(menus), f"{len(menus)} пунктів")
else:
    check("вхід lana для перевірки меню", False, "не вдалося увійти")

# 11б. Підготовка до підключення: чек-лист, розмітки файлів, кнопка «Виписка файлом»
conn_fields = call("ua.bank.connect", "fields_get", [], attributes=["type"])
check("модель підключення банку має потрібні поля",
      {"journal_id", "service", "state", "key_holder", "key_place", "step_ids", "done_steps"}.issubset(conn_fields),
      str(sorted({"journal_id", "service", "state", "key_holder", "key_place", "step_ids", "done_steps"} - set(conn_fields))))

journals = call("account.journal", "search", [["type", "=", "bank"]])
conn = call("ua.bank.connect", "search", [["journal_id", "=", journals[0]]], limit=1)
if not conn:
    conn = [call("ua.bank.connect", "create", {"journal_id": journals[0], "service": "ua_privat"})]
    conn = [conn[0] if isinstance(conn[0], list) else conn[0]]
rec = call("ua.bank.connect", "read", conn, ["done_steps", "total_steps", "service", "state"])[0]
check("чек-лист підключення наповнений кроками", rec["total_steps"] >= 6, f"{rec['done_steps']} з {rec['total_steps']}")
steps = call("ua.bank.connect.step", "search_read", [["connect_id", "=", conn[0]]], ["name", "who", "hint"])
check("у кожного кроку є виконавець і підказка",
      all(st["who"] and st["hint"] for st in steps), str(len(steps)))
check("кроки називають ключ і сховище",
      any("ключ" in st["name"].lower() for st in steps) and any("сховищ" in st["name"].lower() for st in steps))

maps = call("account.statement.import.sheet.mapping", "search_read", [], ["name"])
names = " | ".join(m["name"] for m in maps)
check("є розмітка файлової виписки ПриватБанку", "ПриватБанк" in names, names[:160])
check("є розмітка файлової виписки Monobank", "Monobank" in names, names[:160])

action = call("ua.bank.board", "action_import_file", journals[0])
check("кнопка «Виписка файлом» відкриває майстер імпорту",
      action.get("res_model") == "account.statement.import", str(action.get("res_model")))
action = call("ua.bank.board", "action_open_connect", journals[0])
check("кнопка «Підготовка до підключення» відкриває чек-лист",
      action.get("res_model") == "ua.bank.connect" and action.get("res_id"), str(action.get("res_model")))
data = call("ua.bank.board", "get_screen_data")
check("екран «Банк» показує стан підключення кожного рахунку",
      all("connect" in a and a["connect"].get("label") for a in data["accounts"]),
      str([a["connect"]["label"] for a in data["accounts"]]))

# 12. Компонент у бандлі
if DB == "payroll":
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    auth = json.dumps({"jsonrpc": "2.0", "method": "call",
                       "params": {"db": DB, "login": "admin", "password": PW}}).encode()
    opener.open(urllib.request.Request(f"{BASE}/web/session/authenticate", data=auth,
                headers={"Content-Type": "application/json"}), timeout=60).read()
    try:
        with opener.open(f"{BASE}/web/assets/debug/web.assets_backend.js", timeout=180) as r:
            code, body = r.getcode(), r.read().decode("utf-8", errors="replace")
        check("GET /web/assets/debug/web.assets_backend.js -> 200", code == 200, f"code={code}")
        check("бандл містить l10n_ua_bank_ui.BankBoard", "l10n_ua_bank_ui.BankBoard" in body)
    except Exception as exc:  # noqa: BLE001
        check("GET /web/assets/debug/web.assets_backend.js", False, str(exc)[:300])
else:
    print(f"[--] перевірку бандла пропущено: dbfilter стенду дозволяє HTTP лише для payroll (зараз {DB}).")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
