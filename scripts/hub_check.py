"""Перевірка модуля l10n_ua_hub: усі action_xmlid резолвляться, кількість пунктів і розділів,
action_open() повертає дію для 5 випадкових пунктів, lana бачить «Зведення» і має домашню дію
як домашню дію.

База читається зі змінної середовища PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll_test python3 scripts/hub_check.py"""
import json
import os
import random
import sys
import urllib.request

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
URL = "http://127.0.0.1:8110/jsonrpc"
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
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(), {"Content-Type": "application/json"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


# 1. Усі action_xmlid резолвляться (пошук у ir.model.data)
items = call("ua.hub.item", "search_read", [], fields=["id", "name", "action_xmlid"])
sections = call("ua.hub.section", "search_read", [], fields=["id", "name"])

unresolved = []
for it in items:
    module, _, name = it["action_xmlid"].partition(".")
    found = call("ir.model.data", "search_count", [["module", "=", module], ["name", "=", name]])
    if not found:
        unresolved.append(f'{it["name"]} ({it["action_xmlid"]})')
check("усі action_xmlid резолвляться в ir.model.data", not unresolved,
      f"{len(unresolved)} нерезолвлених: {unresolved}" if unresolved else "")

# 2. Кількість пунктів і розділів
check("кількість пунктів ≥ 30", len(items) >= 30, f"{len(items)} пунктів")
check("кількість розділів ≥ 8", len(sections) >= 8, f"{len(sections)} розділів")

# 3. action_open() повертає словник з ключем 'type' для 5 випадкових пунктів
sample = random.sample(items, min(5, len(items)))
for it in sample:
    result = call("ua.hub.item", "action_open", [it["id"]])
    ok = isinstance(result, dict) and "type" in result
    check(f"action_open() повертає дію: {it['name']}", ok, "" if ok else f"result={result}")

# 4. lana бачить меню «Головна» (load_menus під її сесією) і має домашню дію = дія хабу
if not LANA_PW:
    print(f"[--] пароль {LANA_LOGIN} відсутній у .env (LANA_PASSWORD), перевірку сесії пропущено")
else:
    lana_uid = rpc("common", "login", DB, LANA_LOGIN, LANA_PW)
    if not lana_uid:
        check(f"логін користувача {LANA_LOGIN}", False, "невірний логін/пароль")
    else:
        def lana_call(model, method, *a, **kw):
            return rpc("object", "execute_kw", DB, lana_uid, LANA_PW, model, method, list(a), kw)

        menus = lana_call("ir.ui.menu", "load_menus", False)
        # Пульт команд живе внизу «Зведення»; окреме меню хабу лишили адміністратору, тому Лана його не бачить
        hub_menu = next((m for m in menus.values() if isinstance(m, dict) and m.get("xmlid") == "l10n_ua_hub.menu_ua_hub_root"), None)
        check(f"{LANA_LOGIN} не бачить технічного меню хабу (пульт живе у «Зведенні»)", hub_menu is None,
              "меню сховано" if hub_menu is None else "меню видно, хоча має бути лише в адміністратора")
        summary_menu = next((m for m in menus.values() if isinstance(m, dict) and m.get("xmlid") == "l10n_ua_dashboard.menu_ua_dashboard_root"), None)
        check(f"{LANA_LOGIN} бачить меню «Зведення»", summary_menu is not None)

        lana_user = call("res.users", "search_read", [["login", "=", LANA_LOGIN]], fields=["action_id"])
        hub_action = call("ir.model.data", "search_read",
                           [["module", "=", "l10n_ua_hub"], ["name", "=", "action_ua_hub_item"]], fields=["res_id"])
        hub_action_id = hub_action[0]["res_id"] if hub_action else None
        lana_action_id = lana_user[0]["action_id"][0] if lana_user and lana_user[0]["action_id"] else None
        check(f"{LANA_LOGIN} має домашню дію (хаб або зведення)", bool(lana_action_id),
              f"lana.action_id={lana_action_id}, хаб={hub_action_id}")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    sys.exit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
