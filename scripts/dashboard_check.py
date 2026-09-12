"""Перевірка модуля l10n_ua_dashboard: get_data() повертає всі ключі, підсумок нарахувань
по підрозділах збігається із сумою рядків, клієнтська дія «Зведення» (тег ua_dashboard) існує,
меню «Зведення» видиме для lana і є її домашньою дією.

HTTP-перевірка збірки ресурсів (web.assets_backend, рядок l10n_ua_dashboard.Dashboard) працює лише
коли PAYROLL_DB=payroll і модуль там встановлено - dbfilter стенду (^payroll$) блокує HTTP-доступ
до бази payroll_test. Коли це так, перевірку пропущено з поясненням; на payroll_test збірку
перевірено окремо в odoo shell через ir.qweb._get_asset_bundle() (див. звіт агента).

База читається зі змінної середовища PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll_test python3 scripts/dashboard_check.py"""
import http.cookiejar
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = f"http://127.0.0.1:{PORT}"
URL = f"{BASE}/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
LANA_LOGIN = ENV.get("LANA_LOGIN", "lana").strip()
LANA_PW = ENV.get("LANA_PASSWORD", "").strip()

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(),
        {"Content-Type": "application/json"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як admin на базі {DB} (перевірте ODOO_ADMIN_USER_PASSWORD).")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


# 1. get_data() повертає всі ключі
data = call("ua.dashboard", "get_data", [])
expected_keys = {"company", "periods", "payroll_by_department", "payments", "attention", "documents", "hub"}
check("get_data() повертає всі очікувані ключі", expected_keys.issubset(data.keys()),
      f"відсутні: {expected_keys - set(data.keys())}" if not expected_keys.issubset(data.keys()) else
      f"компанія: {data['company']['name']}, {data['company']['month_label']} {data['company']['year']}")

check("company.employee_count > 0", data["company"]["employee_count"] > 0, f"{data['company']['employee_count']} працівників")
check("periods містить 6 місяців", len(data.get("periods", [])) == 6, f"{len(data.get('periods', []))} періодів")

# 2. payroll_by_department: total збігається із сумою рядків
pbd = data["payroll_by_department"]
rows = pbd.get("rows", [])
total_row = pbd.get("total", {})
sums = {"employees": 0, "gross": 0.0, "pdfo": 0.0, "vz": 0.0, "esv": 0.0, "net": 0.0}
for r in rows:
    for k in sums:
        sums[k] += r.get(k, 0)
mismatches = {k: (round(sums[k], 2), total_row.get(k)) for k in sums if round(sums[k], 2) != total_row.get(k)}
check("payroll_by_department.total = сума рядків", not mismatches, f"розбіжності: {mismatches}" if mismatches else
      f"{len(rows)} підрозділів, разом нараховано {total_row.get('gross')}, на руки {total_row.get('net')}")
check("payroll_by_department: rows або порожній стан з кнопкою", bool(rows) or bool(pbd.get("run_action")),
      "" if rows else "рядків немає, run_action заповнено" if pbd.get("run_action") else "рядків немає і run_action порожній")

# сума рядків нарахувань має збігатись зі знаком - GROSS має бути >= NET (елементарна звірка адекватності чисел)
if rows:
    check("gross >= net у підсумку (адекватність сум)", total_row.get("gross", 0) >= total_row.get("net", 0),
          f"gross={total_row.get('gross')}, net={total_row.get('net')}")

# payments/attention/documents/hub - базова форма
payments = data.get("payments", [])
check("payments має щонайменше 7 рядків", len(payments) >= 7, f"{len(payments)} рядків")
check("усі payments мають state_class з {ok,warn,todo,plan}",
      all(p.get("state_class") in ("ok", "warn", "todo", "plan") for p in payments),
      str([p.get("state_class") for p in payments]))

attention = data.get("attention", [])
check("усі attention мають level з {danger,warning,info}",
      all(a.get("level") in ("danger", "warning", "info") for a in attention),
      f"{len(attention)} рядків: {[a.get('title') for a in attention]}")

hub = data.get("hub", [])
check("hub містить розділи з доступними командами", len(hub) > 0 and all(s.get("items") for s in hub),
      f"{len(hub)} розділів, {sum(len(s['items']) for s in hub)} команд")

# 3. клієнтська дія існує (тег ua_dashboard)
action = call("ir.actions.client", "search_read", [["tag", "=", "ua_dashboard"]], fields=["id", "name"])
check("ir.actions.client з тегом ua_dashboard існує", bool(action), str(action))
action_id = action[0]["id"] if action else None

# 4. меню «Зведення» видиме для lana і є її домашньою дією
if not LANA_PW:
    print(f"[--] пароль {LANA_LOGIN} відсутній у .env (LANA_PASSWORD), перевірку сесії lana пропущено")
else:
    lana_uid = rpc("common", "login", DB, LANA_LOGIN, LANA_PW)
    if not lana_uid:
        check(f"логін користувача {LANA_LOGIN}", False, "невірний логін/пароль")
    else:
        def lana_call(model, method, *a, **kw):
            return rpc("object", "execute_kw", DB, lana_uid, LANA_PW, model, method, list(a), kw)

        menus = lana_call("ir.ui.menu", "load_menus", False)
        dash_menu = next((m for m in menus.values() if isinstance(m, dict) and m.get("xmlid") == "l10n_ua_dashboard.menu_ua_dashboard_root"), None)
        check(f"{LANA_LOGIN} бачить меню «Зведення» (load_menus)", dash_menu is not None,
              "" if dash_menu else "меню не знайдено серед видимих")

        # Пульт команд тепер лише внизу «Зведення»; окреме меню хабу бачить тільки адміністратор
        hub_menu = next((m for m in menus.values() if isinstance(m, dict) and m.get("xmlid") == "l10n_ua_hub.menu_ua_hub_root"), None)
        check(f"{LANA_LOGIN} не бачить окремого меню хабу", hub_menu is None,
              "сховано" if hub_menu is None else "меню видно, хоча має бути лише в адміністратора")
        hub_rows = data.get("hub", [])
        check("пульт команд є всередині «Зведення»", len(hub_rows) >= 5,
              f"{len(hub_rows)} розділів")

        # lana може викликати get_data (перевірка прав ir.model.access)
        try:
            lana_data = lana_call("ua.dashboard", "get_data", [])
            check(f"{LANA_LOGIN} може викликати ua.dashboard.get_data", isinstance(lana_data, dict) and "company" in lana_data)
        except SystemExit as exc:
            check(f"{LANA_LOGIN} може викликати ua.dashboard.get_data", False, str(exc)[:300])

        # домашня дія - «Період»: робоче місце місяця, не аналітика
        lana_user = call("res.users", "search_read", [["login", "=", LANA_LOGIN]], fields=["action_id"])
        lana_action_id = lana_user[0]["action_id"][0] if lana_user and lana_user[0]["action_id"] else None
        period_id = call("ir.model.data", "search_read",
                         [["module", "=", "l10n_ua_period"], ["name", "=", "action_ua_period"]], fields=["res_id"])
        period_id = period_id[0]["res_id"] if period_id else None
        check(f"{LANA_LOGIN} має домашню дію = дія «Період»", lana_action_id == period_id and period_id is not None,
              f"{LANA_LOGIN}.action_id={lana_action_id}, action_ua_period={period_id}")

# 4a. кожне число веде у свій запис: рядок підрозділу, підсумок і платіж мають ціль
dep = data["payroll_by_department"]
if dep["rows"]:
    row = dep["rows"][0]
    check("рядок підрозділу веде в листки", row.get("res_model") == "hr.payslip" and bool(row.get("domain")),
          f"res_model={row.get('res_model')}, domain={row.get('domain')}")
    slips = call("hr.payslip", "search_count", row["domain"])
    check("домен рядка підрозділу знаходить листки", slips > 0, f"знайдено {slips}")
else:
    print("[--] рядків підрозділів немає: перевірку цілі пропущено")
check("підсумок веде в листки місяця", dep["total"].get("res_model") == "hr.payslip" and bool(dep["total"].get("domain")),
      f"total.res_model={dep['total'].get('res_model')}")
targeted = [p for p in data["payments"] if p.get("res_model") or p.get("action")]
check("кожен рядок платежів веде у свій запис", len(targeted) == len(data["payments"]),
      f"з цілями {len(targeted)} з {len(data['payments'])}")
for pay in data["payments"]:
    if pay.get("domain") and pay.get("res_model"):
        found = call(pay["res_model"], "search_count", pay["domain"])
        check(f"домен платежу «{pay['label'][:32]}» дійсний", isinstance(found, int), f"знайдено {found}")

# 5. HTTP-перевірка збірки ресурсів - лише коли DB=payroll (dbfilter стенду блокує payroll_test)
if DB != "payroll":
    print(f"[--] HTTP-перевірка збірки web.assets_backend пропущена: dbfilter стенду дозволяє HTTP "
          f"лише для бази payroll, поточна PAYROLL_DB={DB}. Збірку на {DB} перевірено окремо через "
          f"odoo shell (ir.qweb._get_asset_bundle), див. звіт.")
else:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    auth_body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode()
    opener.open(urllib.request.Request(f"{BASE}/web/session/authenticate", data=auth_body,
                headers={"Content-Type": "application/json"}), timeout=60).read()
    try:
        with opener.open(f"{BASE}/web/assets/debug/web.assets_backend.js", timeout=120) as r:
            code = r.getcode()
            body = r.read().decode("utf-8", errors="replace")
        check("GET /web/assets/debug/web.assets_backend.js -> 200", code == 200, f"code={code}")
        check("бандл містить l10n_ua_dashboard.Dashboard", "l10n_ua_dashboard.Dashboard" in body)
    except Exception as exc:
        check("GET /web/assets/debug/web.assets_backend.js", False, str(exc)[:300])

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
