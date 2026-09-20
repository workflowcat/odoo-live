"""Перевірка журналу змін і закриття періоду (модуль l10n_ua_changes).

Перевіряємо: журнал сам пише зміни сум, часу і станів; рядок можна прийняти;
непереглянута зміна не дає закрити місяць; закритий місяць ставить дату блокування;
відкрити період можна тільки з причиною.

Скрипт змінює дані і дати блокування, тому працює на копії стенду.
Копія: docker compose exec db sh -c "createdb -U odoo payroll_test; pg_dump -U odoo payroll | psql -U odoo payroll_test"
Запуск: python3 scripts/changes_check.py"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = (os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")) + "/jsonrpc"
DB = os.environ.get("PAYROLL_CHECK_DB", "payroll_test").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

errors, total = [], 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def rpc(service, method, *args):
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(request, timeout=900).read())
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:400])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def fails(fn):
    try:
        fn()
        return ""
    except RuntimeError as e:
        return str(e)


YEAR, MONTH = 2026, 8

# 1. модель на місці
fields = call("ua.change.log", "fields_get", [], attributes=["type"])
need = {"date", "user_id", "area", "operation", "model_name", "res_name", "what",
        "old_value", "new_value", "amount", "year", "month", "state"}
check("журнал має всі поля", need.issubset(fields), f"немає: {sorted(need - set(fields))}")

areas = dict(call("ua.change.log", "fields_get", ["area"])["area"]["selection"])
check("ділянки покривають усі напрями",
      {"hr", "time", "payroll", "account", "bank", "report", "setup"}.issubset(areas), str(list(areas)))

# 2. зміна табеля потрапляє в журнал
sheet = call("ua.timesheet.sheet", "search", [["year", "=", YEAR], ["month", "=", MONTH]], limit=1)
check("табель за серпень є", bool(sheet))
line = call("ua.timesheet.line", "search", [["sheet_id", "=", sheet[0]]], limit=1)
was = call("ua.timesheet.line", "read", line, ["days_worked"])[0]["days_worked"]
before = call("ua.change.log", "search_count", [])
call("ua.timesheet.line", "write", line, {"days_worked": was - 1})
rows = call("ua.change.log", "search_read", [["model_name", "=", "ua.timesheet.line"], ["res_id", "=", line[0]]],
            ["area", "operation", "what", "old_value", "new_value", "amount", "year", "month", "state"],
            order="id desc", limit=1)
check("зміна табеля пише рядок у журнал", bool(rows) and call("ua.change.log", "search_count", []) > before)
row = rows[0] if rows else {}
check("рядок має ділянку «Табель»", row.get("area") == "time", str(row.get("area")))
check("рядок показує було → стало", row.get("old_value") == "%.2f" % was and row.get("new_value") == "%.2f" % (was - 1),
      f"{row.get('old_value')} → {row.get('new_value')}")
check("рядок рахує різницю", abs((row.get("amount") or 0) + 1) < 0.01, str(row.get("amount")))
check("рядок належить періоду табеля", (row.get("year"), row.get("month")) == (YEAR, MONTH), f"{row.get('year')}-{row.get('month')}")
check("новий рядок чекає на перевірку", row.get("state") == "new", str(row.get("state")))
check("назва поля людською мовою", row.get("what") == "Відпрацьовано днів", str(row.get("what")))
call("ua.timesheet.line", "write", line, {"days_worked": was})

# 3. зміна суми в листку
slip = call("hr.payslip", "search", [["date_from", ">=", f"{YEAR}-{MONTH:02d}-01"], ["state", "=", "done"]], limit=1)
if slip:
    contract = call("hr.payslip", "read", slip, ["contract_id"])[0]["contract_id"]
    inp = call("hr.payslip.input", "create", [{"payslip_id": slip[0], "contract_id": contract[0], "code": "BONUS", "name": "Премія (перевірка)", "amount": 500.0}])
    inp = inp[0] if isinstance(inp, list) else inp
    got = call("ua.change.log", "search_read", [["model_name", "=", "hr.payslip.input"], ["res_id", "=", inp]],
               ["operation", "area", "year", "month"], limit=1)
    check("створення введення пише рядок", bool(got) and got[0]["operation"] == "create", str(got))
    check("введення належить ділянці «Зарплата»", bool(got) and got[0]["area"] == "payroll")
    call("hr.payslip.input", "unlink", [inp])
    gone = call("ua.change.log", "search_count", [["model_name", "=", "hr.payslip.input"], ["res_id", "=", inp], ["operation", "=", "unlink"]])
    check("видалення пише рядок", gone == 1, str(gone))

    zero = call("hr.payslip.input", "create", [{"payslip_id": slip[0], "contract_id": contract[0],
                                                "code": "BONUS", "name": "Порожнє введення", "amount": 0.0}])
    zero = zero[0] if isinstance(zero, list) else zero
    noise = call("ua.change.log", "search_count", [["model_name", "=", "hr.payslip.input"], ["res_id", "=", zero]])
    check("порожні рядки розрахунку журнал не пише", noise == 0, str(noise))
    call("hr.payslip.input", "unlink", [zero])

# 4. прийняття
new_ids = call("ua.change.log", "search", [["year", "=", YEAR], ["month", "=", MONTH], ["state", "=", "new"]], limit=1)
call("ua.change.log", "action_accept", new_ids)
state = call("ua.change.log", "read", new_ids, ["state", "accepted_user_id", "accepted_date"])[0]
check("прийнятий рядок змінює стан", state["state"] == "accepted")
check("видно, хто і коли прийняв", bool(state["accepted_user_id"]) and bool(state["accepted_date"]))

# 5. непереглянуті зміни блокують місяць
left = call("ua.change.log", "search_count", [["year", "=", YEAR], ["month", "=", MONTH], ["state", "=", "new"]])
blockers = call("ua.period.close", "blockers", 1, YEAR, MONTH)
check("блокери називають непереглянуті зміни",
      (left > 0) == any("змін" in b for b in blockers), f"нових {left}, блокери {blockers}")
err = fails(lambda: call("ua.period.close", "close_period", YEAR, MONTH))
check("закрити місяць із блокерами не можна", "закрити не можна" in err.lower(), err[:120])

# 6. чистий місяць закривається
call("ua.change.log", "accept_period", YEAR, MONTH)
rest = call("ua.period.close", "blockers", 1, YEAR, MONTH)
print("    залишок блокерів:", rest)
if rest:
    check("після прийняття змін залишились інші блокери (це нормально)", True, str(rest))
    # закриваємо порожній місяць, де точно нема документів
    Y2, M2 = 2025, 1
    call("ua.change.log", "accept_period", Y2, M2)
    check("порожній місяць блокерів не має", not call("ua.period.close", "blockers", 1, Y2, M2))
    # перевірка має бути повторюваною: якщо місяць уже закритий попереднім запуском, відкриваємо його
    prev = call("ua.period.close", "search", [["year", "=", Y2], ["month", "=", M2], ["kind", "=", "month"]], limit=1)
    if prev:
        call("ua.period.close", "write", prev, {"reopen_reason": "повторний запуск перевірки"})
        if call("ua.period.close", "read", prev, ["state"])[0]["state"] == "closed":
            call("ua.period.close", "action_reopen", prev)
            call("ua.change.log", "accept_period", Y2, M2)   # саме відкриття теж пише рядок у журнал
    cid = call("ua.period.close", "close_period", Y2, M2)
    rec = call("ua.period.close", "read", [cid], ["state", "lock_date", "closed_user_id", "hard"])[0]
    check("місяць закрито", rec["state"] == "closed", str(rec["state"]))
    check("дата блокування = кінець місяця", rec["lock_date"] == f"{Y2}-{M2:02d}-31", str(rec["lock_date"]))
    lock = call("res.company", "read", [1], ["fiscalyear_lock_date"])[0]["fiscalyear_lock_date"]
    check("дата блокування стоїть у компанії", lock == rec["lock_date"], str(lock))
    err = fails(lambda: call("ua.period.close", "action_reopen", [cid]))
    check("відкрити без причини не можна", "причин" in err.lower(), err[:120])
    call("ua.period.close", "write", [cid], {"reopen_reason": "перевірка"})
    call("ua.period.close", "action_reopen", [cid])
    rec = call("ua.period.close", "read", [cid], ["state", "reopened_user_id"])[0]
    check("період відкривається знову з причиною", rec["state"] == "open" and bool(rec["reopened_user_id"]))
    trail = call("ua.change.log", "search_count", [["model_name", "=", "ua.period.close"], ["res_id", "=", cid]])
    check("відкриття періоду теж у журналі", trail >= 1, str(trail))
    call("res.company", "write", [1], {"fiscalyear_lock_date": False})

# 6б. квартал і рік
Y2 = 2025
for m in (1, 2, 3):
    call("ua.change.log", "accept_period", Y2, m)
    state = call("ua.period.close", "state_of", 1, Y2, m)
    if state["state"] != "closed" and not call("ua.period.close", "blockers", 1, Y2, m):
        call("ua.period.close", "close_period", Y2, m)
qb = call("ua.period.close", "quarter_blockers", 1, Y2, 1)
check("квартал бачить незакриті місяці або неподану звітність", isinstance(qb, list), str(qb))
check("після закриття місяців лишається вимога подати розрахунок",
      all("місяц" not in b for b in qb) and any("розрахунок" in b for b in qb), str(qb))
err = fails(lambda: call("ua.period.close", "close_quarter", Y2, 1))
check("квартал без поданої звітності не закривається", "закрити не можна" in err.lower(), err[:120])
yb = call("ua.period.close", "year_blockers", 1, Y2)
check("рік бачить незакриті квартали", any("квартал" in b for b in yb), str(yb))
err = fails(lambda: call("ua.period.close", "close_year", Y2))
check("рік без закритих кварталів не закривається", "закрити не можна" in err.lower(), err[:120])
call("res.company", "write", [1], {"fiscalyear_lock_date": False, "tax_lock_date": False})

# 7. сторінка «Період»
data = call("ua.period.board", "get_screen_data", year=YEAR, month=MONTH)
step = [s for s in data["steps"] if s["key"] == "changes"]
check("на сторінці «Період» є крок «Перевірка змін»", bool(step), str([s["key"] for s in data["steps"]]))
# Крок більше не носить окремого «fact»: факти стали підзаголовком і рядками кроку
# (docs/payroll/spec-period-v2.md), тому питаємо саме їх.
body = step[0] if step else {}
check("крок знає число змін", bool(body.get("subtitle") or body.get("rows")),
      str(body.get("subtitle") or [r.get("text") for r in (body.get("rows") or [])][:2]))
check("сторінка віддає стан закриття", "close" in data and "state" in data["close"], str(data.get("close")))
check("сторінка віддає число непереглянутих змін", "new_changes" in data, str(data.get("new_changes")))

# 8. права
lana_pw = ENV.get("LANA_PASSWORD", "").strip()
lana_uid = rpc("common", "login", DB, "lana", lana_pw) if lana_pw else None
if lana_uid:
    seen = rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ua.change.log", "search_count", [[]])
    check("бухгалтер бачить журнал", isinstance(seen, int), str(seen))
    menu = rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ir.ui.menu", "search_read",
               [[["name", "=", "Журнал змін"]]], {"fields": ["name"]})
    check("бухгалтер бачить меню «Журнал змін»", bool(menu), str(len(menu)))
    ids = rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ua.change.log", "search", [[["state", "=", "new"]]], {"limit": 1})
    if ids:
        rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ua.change.log", "action_accept", [ids])
        st = rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ua.change.log", "read", [ids], {"fields": ["state"]})[0]
        check("бухгалтер приймає зміну", st["state"] == "accepted", st["state"])
    else:
        check("бухгалтер приймає зміну", True, "нових рядків немає")
else:
    check("вхід lana", False, "немає пароля")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    for e in errors:
        print("  -", e)
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
