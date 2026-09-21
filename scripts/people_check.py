"""Перевірка екрана «Люди» (модуль l10n_ua_people).

Екран своїх даних не тримає: перелік, групування за підрозділами, схема підпорядкування
і штатний розпис рахуються з одного й того самого переліку працівників (hr.employee).
Тому перевіряємо контракт: чотири погляди відповідають без помилок і кожен дає свій
ключ, підсумок збігається з сумою по підрозділах, «Штатний розпис» дає ті самі числа,
що й «За підрозділами», ЦПХ і ФОП у перелік не входять, а чотири старі пункти меню
(«Картки працівників», «Оргструктура», «Підрозділи», «Штатні розписи») зникли.

create_staff_list пише в базу (створює ua.staff.list), тому вмикається окремо і не на
payroll - PEOPLE_CHECK_CREATE=1, той самий прийом, що EXPLAIN_CHECK_FREEZE
в explain_check.py:
PEOPLE_CHECK_CREATE=1 PAYROLL_DB=<копія> python3 scripts/people_check.py

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/people_check.py"""
import json
import os
from datetime import date
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
LANA_LOGIN = ENV.get("LANA_LOGIN", "lana").strip()
LANA_PW = ENV.get("LANA_PASSWORD", "").strip()

VIEWS = ["list", "departments", "chart", "staff"]
VIEW_KEY = {"list": "rows", "departments": "departments", "chart": "chart", "staff": "staff"}
# Чотири старі пункти зникають (active=False); модуль, що визначає xmlid, - той, де
# menuitem уперше заявлений, не обов'язково l10n_ua_navigation (menu_ua_staff_list_docs
# заявлений у l10n_ua_payroll_ui і лише перевизначений у menus_areas.xml).
GONE_MENUS = [
    "l10n_ua_navigation.menu_ua_people_employees",
    "l10n_ua_navigation.menu_ua_people_org_chart",
    "l10n_ua_navigation.menu_ua_people_departments",
    "l10n_ua_payroll_ui.menu_ua_staff_list_docs",
]

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def _post(payload):
    request = urllib.request.Request(
        URL, json.dumps(payload).encode(), {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(request, timeout=900).read())


def rpc(service, method, *args):
    data = _post({"jsonrpc": "2.0", "method": "call",
                  "params": {"service": service, "method": method, "args": args}})
    if "error" in data:
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:600])
    return data.get("result")


def rpc_soft(service, method, *args):
    data = _post({"jsonrpc": "2.0", "method": "call",
                  "params": {"service": service, "method": method, "args": args}})
    if "error" in data:
        return {"__error__": str(data["error"].get("data", {}).get("message") or data["error"])}
    return data.get("result")


UID = rpc("common", "login", DB, LOGIN, PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як {LOGIN} на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def call_soft(model, method, *a, **kw):
    return rpc_soft("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def screen(view=None, search=None, department=None, kwargs=None):
    kw = dict(kwargs or {})
    if view is not None:
        kw["view"] = view
    if search is not None:
        kw["search"] = search
    if department is not None:
        kw["department"] = department
    return call_soft("ua.people", "get_screen_data", **kw)


def targets_in(node, out=None):
    """Усі цілі відповіді, знайдені за формою словника, а не за іменем ключа - як
    у papers_check.py, щоб нові поля не вимагали правки цього файла."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("xmlid") or (node.get("model") and "group" not in node):
            out.append(node)
        for v in node.values():
            targets_in(v, out)
    elif isinstance(node, list):
        for v in node:
            targets_in(v, out)
    return out


# 1. дія і пункт «Люди» видимі звичайному користувачу
actions = call("ir.actions.client", "search_read", [["tag", "=", "ua_people"]], fields=["name"])
check("клієнтська дія з тегом ua_people існує", len(actions) == 1, str(actions))

if LANA_PW:
    lana_uid = rpc("common", "login", DB, LANA_LOGIN, LANA_PW)
    if lana_uid:
        menus = rpc("object", "execute_kw", DB, lana_uid, LANA_PW, "ir.ui.menu", "search_read",
                    [[["name", "=", "Люди"]]], {"fields": ["name", "parent_id"]})
        check(f"пункт «Люди» видимий звичайному користувачу ({LANA_LOGIN})", bool(menus), f"{len(menus)} пунктів")
    else:
        check(f"вхід {LANA_LOGIN}", False, "не вдалося увійти")
else:
    check(f"вхід {LANA_LOGIN}", False, "немає пароля в .env (LANA_PASSWORD)")

# 2. чотири погляди відповідають без помилок, кожен дає свій ключ
by_view = {}
bad_view = []
for view in VIEWS:
    res = screen(view=view)
    key = VIEW_KEY[view]
    if "__error__" in (res or {}) or not isinstance(res, dict) or res.get(key) is None:
        bad_view.append((view, str(res)[:100]))
        continue
    by_view[view] = res
check("чотири погляди відповідають без помилок, кожен дає свій ключ", not bad_view, str(bad_view))

# кожна відповідь несе спільний підсумок і саму назву погляду
bad_shape = [v for v, res in by_view.items()
             if res.get("view") != v or not isinstance(res.get("summary"), dict)]
check("кожна відповідь називає свій погляд і несе підсумок", not bad_shape, str(bad_shape))

# 3. у «Переліку» немає ЦПХ і ФОП
company_id = call("res.users", "read", [UID], ["company_id"])[0]["company_id"][0]
excluded = call("hr.employee", "search_read",
                [("company_id", "=", company_id), ("ua_contract_kind", "in", ["gph", "fop"])],
                fields=["name"])
list_rows = (by_view.get("list") or {}).get("rows") or []
list_ids = {r["id"] for r in list_rows}
leaked = [e["name"] for e in excluded if e["id"] in list_ids]
check("у «Переліку» немає ЦПХ і ФОП", not leaked, str(leaked[:5]) if leaked else f"{len(excluded)} ЦПХ/ФОП виключено")

bad_kind = [r for r in list_rows if r.get("kind") in ("gph", "fop")]
check("кожен рядок переліку несе вид відносин, і серед них немає ЦПХ/ФОП", not bad_kind, str(bad_kind[:3]))

# 4. підсумок збігається з сумою по підрозділах (особи, одиниці, фонд)
summary = (by_view.get("list") or {}).get("summary") or {}
depts = (by_view.get("departments") or {}).get("departments") or []
check("«За підрозділами» не порожній", bool(depts), f"{len(depts)} підрозділів")

dept_people = sum(d.get("people", 0) for d in depts)
dept_units = sum(d.get("units", 0) for d in depts)
dept_fund = sum(d.get("fund", 0) for d in depts)
check("підсумок людей збігається з сумою по підрозділах",
      summary.get("people") == dept_people, f"{summary.get('people')} проти {dept_people}")
check("підсумок штатних одиниць збігається з сумою по підрозділах",
      abs((summary.get("units") or 0) - dept_units) < 0.01, f"{summary.get('units')} проти {dept_units}")
check("підсумок фонду збігається з сумою по підрозділах",
      abs((summary.get("fund") or 0) - dept_fund) < 0.01, f"{summary.get('fund')} проти {dept_fund}")

# кожен рядок «За підрозділами» - та сама форма, що й рядок «Переліку» (одна форма рядка,
# спека «Чотири погляди - це один набір даних»)
dept_row_ids = {r["id"] for d in depts for r in (d.get("rows") or [])}
check("рядки в підрозділах - ті самі люди, що і в «Переліку»", dept_row_ids == list_ids,
      f"{len(dept_row_ids ^ list_ids)} розбіжностей" if dept_row_ids != list_ids else "збігається")

# 5. «Штатний розпис» дає ті самі одиниці й фонд, що й «За підрозділами»
staff = (by_view.get("staff") or {}).get("staff") or {}
totals = staff.get("totals") or {}
check("штатний розпис має рядки і підсумок", bool(staff.get("lines")) and "units" in totals and "fund" in totals,
      str(totals))
check("«Штатний розпис» дає ту саму кількість штатних одиниць, що й «За підрозділами»",
      abs((totals.get("units") or 0) - dept_units) < 0.01, f"{totals.get('units')} проти {dept_units}")
check("«Штатний розпис» дає той самий фонд, що й «За підрозділами»",
      abs((totals.get("fund") or 0) - dept_fund) < 0.01, f"{totals.get('fund')} проти {dept_fund}")

if staff.get("current"):
    cur = staff["current"]
    check("«чинний розпис» несе назву, ціль і різницю",
          bool(cur.get("name")) and cur.get("target") and "diff_units" in cur and cur.get("diff_text"),
          str(cur))
else:
    check("«чинний розпис» - або дані про нього, або None", "current" in staff, str(staff.get("current")))

# 6. пошук звужує перелік і не падає на порожньому результаті
full_n = len(list_rows)
narrowed = None
if list_rows:
    needle = (list_rows[0]["name"] or "")[:4].strip()
    if needle:
        res = screen(view="list", search=needle)
        narrowed = res.get("rows") if isinstance(res, dict) else None
check("пошук звужує перелік", isinstance(narrowed, list) and 0 < len(narrowed) <= full_n,
      f"{len(narrowed) if isinstance(narrowed, list) else narrowed} з {full_n}")

empty_res = screen(view="list", search="жодна людина не збігається зі щзщзщ12390")
check("пошук без збігів повертає порожній перелік, не помилку",
      isinstance(empty_res, dict) and empty_res.get("rows") == [], str(empty_res)[:150])

# порожній пошук на кожному погляді не падає: «Штатний розпис» лишається словником
# (as_of, totals тощо завжди на місці), тільки lines стає порожнім - решта поглядів
# просто повертають порожній список.
bad_empty = []
for view in VIEWS:
    res = screen(view=view, search="жодна людина не збігається зі щзщзщ12390")
    key = VIEW_KEY[view]
    val = res.get(key) if isinstance(res, dict) else None
    if view == "staff":
        ok = isinstance(val, dict) and val.get("lines") == []
    else:
        ok = val == []
    if not (isinstance(res, dict) and ok):
        bad_empty.append((view, str(res)[:100]))
check("порожній результат пошуку не падає на жодному погляді", not bad_empty, str(bad_empty))

# 7. кожна ціль відкривається через open_target
targets = []
for res in by_view.values():
    targets.extend(targets_in(res))
seen, uniq = set(), []
for t in targets:
    k = json.dumps(t, sort_keys=True, ensure_ascii=False)
    if k not in seen:
        seen.add(k)
        uniq.append(t)
broken = []
for t in uniq:
    res = call_soft("ua.people", "open_target", t)
    if not isinstance(res, dict) or "__error__" in res or not res.get("type"):
        broken.append((json.dumps(t, ensure_ascii=False)[:70], str(res)[:60]))
check(f"кожна ціль відкривається ({len(uniq)} цілей)", not broken, str(broken[:4]))

# перегляд нічого не пише в базу
before = call("hr.employee", "search_count", [])
screen(view="staff")
after = call("hr.employee", "search_count", [])
check("перегляд не змінює кількість працівників", before == after, f"{before} -> {after}")

# 8. create_staff_list створює документ і відкриває його - лише на копії бази
if os.environ.get("PEOPLE_CHECK_CREATE") == "1":
    if DB == "payroll":
        raise SystemExit("PEOPLE_CHECK_CREATE пише в базу (створює ua.staff.list). Запускайте на копії, не на payroll.")
    before_n = call("ua.staff.list", "search_count", [])
    res = call_soft("ua.people", "run_action", "create_staff_list")
    after_n = call("ua.staff.list", "search_count", [])
    check("create_staff_list створює документ", after_n == before_n + 1, f"{before_n} -> {after_n}")
    ok_action = (isinstance(res, dict) and "__error__" not in res and res.get("res_model") == "ua.staff.list"
                and isinstance(res.get("res_id"), int))
    check("create_staff_list відкриває створений документ", ok_action, str(res)[:150])
    if ok_action:
        doc = call("ua.staff.list", "read", [res["res_id"]], ["state", "line_ids"])
        check("новий штатний розпис - чернетка з рядками",
              bool(doc) and doc[0]["state"] == "draft" and bool(doc[0]["line_ids"]),
              str(doc[0]) if doc else "запису немає")
else:
    print(f"[--] create_staff_list пропущено: встановіть PEOPLE_CHECK_CREATE=1 на копії бази (DB={DB})")

# 9. чотирьох старих пунктів меню більше немає
for xmlid in GONE_MENUS:
    module, _, name = xmlid.partition(".")
    data = call("ir.model.data", "search_read",
                [["module", "=", module], ["name", "=", name], ["model", "=", "ir.ui.menu"]], fields=["res_id"])
    if not data:
        check(f"{xmlid}: запису немає (видалено)", True)
        continue
    rec = call("ir.ui.menu", "search_read", [["id", "=", data[0]["res_id"]]], fields=["name", "active"],
               context={"active_test": False})
    check(f"«{rec[0]['name'] if rec else xmlid}» більше немає в меню",
          bool(rec) and not rec[0]["active"], rec[0]["name"] if rec else "")

# «Люди» стоїть на місці цих чотирьох - і активний
new_menu = call("ir.model.data", "search_read",
                [["module", "=", "l10n_ua_navigation"], ["name", "=", "menu_ua_people_screen"],
                 ["model", "=", "ir.ui.menu"]], fields=["res_id"])
new_rec = call("ir.ui.menu", "search_read", [["id", "=", new_menu[0]["res_id"]]],
              fields=["name", "active", "action"]) if new_menu else []
check("пункт «Люди» на місці і активний",
      bool(new_rec) and new_rec[0]["active"] and new_rec[0]["name"] == "Люди" and bool(new_rec[0]["action"]),
      str(new_rec[0]) if new_rec else "запису немає")

# Архів не має ховати тих, хто працює. Наказ про звільнення - не остаточне слово:
# людину можуть прийняти знову тією самою карткою. Ткачука так і не було видно в
# «Людях», у штатному розписі й у повідомленні до ТЦК - картка лишилась архівною
# після звільнення 31.05.2026, хоча з 17.08.2026 він знову на роботі.
today = date.today().isoformat()
archived = call("hr.employee", "search_read", [["active", "=", False]],
                fields=["name", "version_id"], context={"active_test": False})
wrongly = []
for e in archived:
    if not e.get("version_id"):
        continue
    ver = call("hr.version", "read", [e["version_id"][0]], ["contract_date_start", "contract_date_end"])[0]
    if not ver.get("contract_date_start"):
        continue   # службові картки (Administrator) без контракту - не люди компанії
    end = ver.get("contract_date_end")
    if not end or str(end) >= today:
        wrongly.append(e["name"])
check("в архіві немає нікого з чинною версією контракту", not wrongly, ", ".join(wrongly[:5]))

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
