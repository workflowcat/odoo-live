"""Перевірка сторінки «Період» (модуль l10n_ua_period).

Сторінка не має власних даних: вона читає накази, табель, аванс, листки, проводки,
відомості, виписку, журнал змін і звітність. Перевіряємо, що всі дев'ять кроків на місці, стани
відповідають даним стенду, обороти рахунків рахуються, а кнопки відкривають записи.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/period_check.py"""
import http.cookiejar
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
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
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(request, timeout=900).read())
    if "error" in data:
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:600])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


data = call("ua.period.board", "get_screen_data", year=2026, month=8)
expected = {"company", "period", "periods", "steps", "done", "total", "turnover", "blockers"}
check("get_screen_data() повертає всі ключі", expected.issubset(data.keys()),
      f"відсутні: {expected - set(data.keys())}" if not expected.issubset(data.keys()) else data["period"]["label"])

keys = [s["key"] for s in data["steps"]]
check("дев'ять кроків у робочому порядку",
      keys == ["orders", "timesheet", "advance", "payslips", "moves", "payment", "bank", "changes", "reporting"], str(keys))
check("кожен крок має назву, стан і число",
      all(s["title"] and s["state"] in ("done", "warn", "todo") and s["fact"] for s in data["steps"]))
check("періодів для перемикання шість", len(data["periods"]) == 6, f"{len(data['periods'])}")

by_key = {s["key"]: s for s in data["steps"]}
check("серпень: листки проведено", by_key["payslips"]["state"] == "done", by_key["payslips"]["fact"])
check("серпень: проводки збалансовані", by_key["moves"]["state"] == "done", by_key["moves"]["fact"])
check("серпень: відомість на виплату є", by_key["payment"]["state"] in ("done", "warn"), by_key["payment"]["fact"])
check("серпень: накази проведено", by_key["orders"]["state"] == "done", by_key["orders"]["fact"])
check("крок звірки знає незвірені рядки",
      by_key["bank"]["state"] in ("done", "warn") and isinstance(by_key["bank"]["details"], list),
      by_key["bank"]["fact"])
check("крок звітності показує строк подання", "строк" in by_key["reporting"]["fact"] or "подано" in by_key["reporting"]["fact"],
      by_key["reporting"]["fact"])

codes = {row["code"] for row in data["turnover"]}
check("в оборотах є 661, 6411, 651", {"661", "6411", "651"}.issubset(codes), str(sorted(codes)))
payroll_row = next((r for r in data["turnover"] if r["code"] == "661"), None)
check("оборот 661 має і дебет, і кредит",
      payroll_row and payroll_row["debit"] != "0,00" and payroll_row["credit"] != "0,00",
      f"{payroll_row['debit']} / {payroll_row['credit']}" if payroll_row else "рядка немає")
check("числа у форматі 1 194 649,69", payroll_row and "," in payroll_row["credit"], payroll_row["credit"] if payroll_row else "")
check("сальдо показане стороною (Дт або Кт)",
      payroll_row and bool(payroll_row["saldo_credit"]) != bool(payroll_row["saldo_debit"]),
      f"Дт «{payroll_row['saldo_debit']}» Кт «{payroll_row['saldo_credit']}»" if payroll_row else "")

check("перелік того, що заважає закрити, є списком", isinstance(data["blockers"], list), str(data["blockers"]))

action = call("ua.period.board", "action_open", by_key["reporting"]["action"])
check("кнопка кроку відкриває екран", isinstance(action, dict) and action.get("type"), str(action.get("res_model") or action.get("tag")))
if by_key["bank"]["details"]:
    row = by_key["bank"]["details"][0]
    record_action = call("ua.period.board", "action_open_record", row["model"], row["id"])
    check("рядок деталей відкриває сам запис",
          record_action.get("res_model") == row["model"] and record_action.get("res_id") == row["id"],
          f"{record_action.get('res_model')} {record_action.get('res_id')}")
else:
    print("[--] незвірених рядків немає, перевірку відкриття запису пропущено")

lana_pw = ENV.get("LANA_PASSWORD", "").strip()
lana_uid = rpc("common", "login", DB, "lana", lana_pw) if lana_pw else None
if lana_uid:
    menus = rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ir.ui.menu", "search_read",
                [[["name", "=", "Зарплата"], ["parent_id", "=", False]]], {"fields": ["name"]})
    check("lana бачить меню «Зарплата»", bool(menus), f"{len(menus)} пунктів")
    screen = rpc("object", "execute_kw", DB, lana_uid, lana_pw, "ua.period.board", "get_screen_data", [], {})
    check("lana може відкрити сторінку", isinstance(screen, dict) and "steps" in screen)
else:
    check("вхід lana", False, "немає пароля")

if DB == "payroll":
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    auth = json.dumps({"jsonrpc": "2.0", "method": "call",
                       "params": {"db": DB, "login": "admin", "password": PW}}).encode()
    opener.open(urllib.request.Request(BASE + "/web/session/authenticate", data=auth,
                headers={"Content-Type": "application/json"}), timeout=60).read()
    with opener.open(BASE + "/web/assets/debug/web.assets_backend.js", timeout=180) as response:
        body = response.read().decode("utf-8", errors="replace")
    check("бандл містить l10n_ua_period.Period", "l10n_ua_period.Period" in body)


# робоче місце місяця: головна дія, числа, зміни, черга винятків
work = {"headline", "estimate", "changes", "exceptions"}
check("сторінка віддає дані робочого місця", work.issubset(data.keys()),
      f"немає: {sorted(work - set(data.keys()))}")
head = data.get("headline") or {}
check("головна дія має назву і кнопку", bool(head.get("title")) and "action" in head,
      f"{head.get('title')} → {head.get('label') or 'без кнопки'}")
est = data.get("estimate") or {}
check("числа місяця: нараховано, до виплати, ЄСВ",
      all(est.get(k) for k in ("gross", "net", "employer")), str(est))
check("черга винятків має причину і дію",
      all(e.get("title") and e.get("detail") is not None and "action" in e for e in data.get("exceptions", [])),
      f"{len(data.get('exceptions', []))} позицій")
check("зміни місяця показані переліком",
      all(r.get("label") and r.get("count") for r in data.get("changes", [])),
      str([(r["label"], r["count"]) for r in data.get("changes", [])]))
prepare = call("ua.period.board", "action_prepare_month", 2026, 8)
check("«Підготувати місяць» відповідає повідомленням", bool(prepare.get("message")), str(prepare)[:80])

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
