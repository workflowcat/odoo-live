"""Перевірка навігації і слів інтерфейсу.

Навігація мусить існувати один раз: сім наших розділів (стільки ж, скільки смуга
ліворуч у l10n_ua_shell веде корінням), жодної однакової назви на корені, жодної дії
у двох пунктах. Стара навігація модуля payroll, «Пульт команд» і пункти-чарівники
мусять бути вимкнені.

Слова: одна дія - одне слово. Перелік нижче - канон. Скрипт шукає в XML кнопки
з забороненими написами.

База читається зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/nav_check.py"""
import collections
import glob
import json
import os
import re
import urllib.request

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
# Порт стенду береться з .env цього ж дерева: інакше скрипт стукав у сусідній стенд на 8110.
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/") + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
LANA_LOGIN = ENV.get("LANA_LOGIN", "lana").strip()
LANA_PW = ENV.get("LANA_PASSWORD", "").strip()

# Сім розділів у тому порядку, у якому їх віддає меню (sequence, потім id).
AREAS = ["Домівка", "Зарплата", "Працівники", "Папери", "Банк", "Звітність", "Налаштування зарплати"]
# Ті самі сім коренів, як їх знає смуга ліворуч: перелік беремо з самого side_rail.js,
# щоб меню і смуга не розійшлися мовчки.
RAIL_JS = open("addons/l10n_ua_shell/static/src/side_rail.js", encoding="utf-8").read()
RAIL_ROOTS = re.findall(r'"(l10n_ua_[a-z_]+\.menu_[a-z_]+root|l10n_ua_bank_online\.menu_ua_bank_board)":\s*"[^"]{2}"', RAIL_JS)
OFF_MENUS = [
    "payroll.payroll_menu_root",
    "l10n_ua_payroll_reports.menu_ua_payroll_report", "l10n_ua_payroll_reports.menu_ua_hire_notice",
    "l10n_ua_hr_docs.menu_ua_staff_list", "l10n_ua_hr_docs.menu_ua_timesheet",
    "l10n_ua_hr_orders.menu_ua_hr_order_register", "l10n_ua_payroll_rules.menu_ua_advance",
    "l10n_ua_hr_orders.menu_ua_hr_order", "l10n_ua_payroll_ui.menu_ua_timesheet_docs",
    "l10n_ua_changes.menu_ua_period_close", "l10n_ua_index.menu_ua_cpi_index",
    "l10n_ua_payroll_rules.menu_ua_payroll_param", "l10n_ua_payroll_account.menu_ua_payroll_account_map",
]
# заборонений напис -> канон
BANNED = {
    "Сформувати XML": "Сформувати", "Розрахувати аванс": "Створити", "Розрахувати звіт": "Перерахувати",
    "Зробити чернеткою": "Повернути в чернетку", "Повернути до заповнення": "Повернути в чернетку",
    "Активувати": "Затвердити", "Підтвердити": "Затвердити", "Створити з ЄДР": "Заповнити з ЄДР",
    "Оновити кроки": "Перерахувати", "Створити з'єднання": "Створити", "Друк П-2": "Друк",
    "Оновити з каталогу": "Заповнити з каталогу",
}

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
        {"Content-Type": "application/json"}), timeout=180)
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:1500])
    return d.get("result")


uid = rpc("common", "login", DB, LOGIN, PW)


def call(model, method, *args, **kw):
    kw.setdefault("context", {})
    kw["context"] = dict({"lang": "uk_UA"}, **kw["context"])
    return rpc("object", "execute_kw", DB, uid, PW, model, method, list(args), kw)


# 1. корені
menus = call("ir.ui.menu", "search_read", [], fields=["name", "parent_id", "sequence", "action"], order="sequence,id")
roots = [m for m in menus if not m["parent_id"]]
ours = [m for m in roots if m["name"] in AREAS]
check("усі сім розділів на місці", len(ours) == len(AREAS), ", ".join(m["name"] for m in ours))
check("смуга ліворуч знає ті самі сім коренів", len(RAIL_ROOTS) == len(AREAS), str(RAIL_ROOTS))
order = [m["name"] for m in sorted(ours, key=lambda x: (x["sequence"], x["id"]))]
check("порядок розділів правильний", order == AREAS, str(order))
names = collections.Counter(m["name"] for m in roots)
dups = [n for n, c in names.items() if c > 1]
check("немає двох коренів з однаковою назвою", not dups, str(dups))

# 2. один пункт на дію в наших розділах
kids = collections.defaultdict(list)
for m in menus:
    kids[m["parent_id"][0] if m["parent_id"] else None].append(m)


def descend(pid, acc):
    for m in kids[pid]:
        acc.append(m)
        descend(m["id"], acc)
    return acc


items = []
for root in ours:
    descend(root["id"], items)
by_action = collections.defaultdict(list)
for m in items:
    if m["action"]:
        by_action[m["action"]].append(m["name"])
double = {a: ns for a, ns in by_action.items() if len(ns) > 1}
check("жодна дія не має двох пунктів меню", not double, str(double))
check("пунктів у наших розділах не більше 45", len(items) <= 45, f"{len(items)}")
by_name = collections.Counter(m["name"] for m in items)
same = [n for n, c in by_name.items() if c > 1]
check("немає двох пунктів з однаковою назвою", not same, str(same))

# 3. стара навігація вимкнена
for xmlid in OFF_MENUS:
    module, _, name = xmlid.partition(".")
    data = call("ir.model.data", "search_read",
                [["module", "=", module], ["name", "=", name], ["model", "=", "ir.ui.menu"]], fields=["res_id"])
    if not data:
        check(f"{xmlid}: запису немає (видалено)", True)
        continue
    rec = call("ir.ui.menu", "search_read", [["id", "=", data[0]["res_id"]]], fields=["name", "active"],
               context={"active_test": False, "lang": "uk_UA"})
    check(f"{xmlid} вимкнено", bool(rec) and not rec[0]["active"], rec[0]["name"] if rec else "")

# 4. дії-чарівники лишаються, хоч і без пунктів меню: їх відкривають кроки «Періоду»
for xmlid in ("l10n_ua_payroll_rules.action_ua_advance_wizard", "l10n_ua_payroll_reports.action_ua_payroll_report_wizard",
              "l10n_ua_hr_docs.action_ua_timesheet_wizard"):
    module, _, name = xmlid.partition(".")
    data = call("ir.model.data", "search_read", [["module", "=", module], ["name", "=", name]],
                fields=["model", "res_id"])
    ok = bool(data) and data[0]["model"].startswith("ir.actions")
    detail = f"{data[0]['model']} #{data[0]['res_id']}" if data else "запису немає"
    check(f"{xmlid} лишилася в системі", ok, detail)

# 5. екран «Звітність» створює документ, якщо його немає
for code in ("timesheet", "staff", "orders"):
    src = open("addons/l10n_ua_reporting/models/ua_report_run.py", encoding="utf-8").read()
    body = src.split(f"def _generate_{code}(self)")[1].split("def ")[0] if f"def _generate_{code}(self)" in src else ""
    check(f"звіт {code} створює документ сам", ".create(" in body, "є create" if ".create(" in body else "немає create")

# 6. слова: заборонених написів немає
bad = []
for path in glob.glob("addons/l10n_ua_*/**/*.xml", recursive=True):
    text = open(path, encoding="utf-8", errors="replace").read()
    for word, canon in BANNED.items():
        for m in re.finditer(r'<button[^>]*>|string="%s"' % re.escape(word), text):
            pass
        if re.search(r'string="%s"' % re.escape(word), text) or f">{word}</button>" in text:
            bad.append(f"{path.split('/')[1]}: «{word}» замість «{canon}»")
check("заборонених написів кнопок немає", not bad, "; ".join(bad[:6]))

# 7. технічні таблиці стоять за групою «лише я»: інтерфейс показує їх тільки в режимі розробника
no_one = call("ir.model.data", "search_read", [["module", "=", "base"], ["name", "=", "group_no_one"]],
              fields=["res_id"])
no_one_id = no_one[0]["res_id"] if no_one else 0
TECH = ["l10n_ua_navigation.menu_ua_setup_questions", "l10n_ua_navigation.menu_ua_setup_profile_table",
        "payroll.hr_payroll_structure_menu", "payroll.menu_hr_salary_rule_category",
        "payroll.menu_action_hr_salary_rule_form", "payroll.hr_contribution_register_menu",
        "payroll.menu_payroll_global_settings"]
for xmlid in TECH:
    module, _, name = xmlid.partition(".")
    data = call("ir.model.data", "search_read",
                [["module", "=", module], ["name", "=", name], ["model", "=", "ir.ui.menu"]], fields=["res_id"])
    rec = call("ir.ui.menu", "search_read", [["id", "=", data[0]["res_id"]]],
               fields=["name", "group_ids"]) if data else []
    ok = bool(rec) and no_one_id in (rec[0]["group_ids"] or [])
    check(f"«{rec[0]['name'] if rec else xmlid}» лише в режимі розробника", ok,
          "групи: %s" % (rec[0]["group_ids"] if rec else "пункту немає"))

if LANA_PW:
    lana_uid = rpc("common", "login", DB, LANA_LOGIN, LANA_PW)
    if lana_uid:
        lana_menus = rpc("object", "execute_kw", DB, lana_uid, LANA_PW, "ir.ui.menu", "search_read",
                         [[["parent_id", "=", False]]], {"fields": ["name"], "context": {"lang": "uk_UA"}})
        seen = {m["name"] for m in lana_menus}
        need = {"Зарплата", "Працівники", "Банк", "Звітність"}
        check(f"{LANA_LOGIN} бачить робочі розділи", need <= seen, str(sorted(need & seen)))

# 8. прибирання: зайві модулі видалено, стандартні розділи сховано, оргструктура в «Працівниках»
REMOVED = ["bp_kyc", "l10n_ua_partner_edr", "spreadsheet_dashboard", "spreadsheet", "sms", "snailmail",
           "partner_autocomplete", "iap", "mail_bot", "google_gmail", "microsoft_outlook", "hr_homeworking",
           "web_unsplash", "auth_passkey", "account_edi_ubl_cii", "account_payment", "payment", "hr_skills"]
still = call("ir.module.module", "search_read", [["name", "in", REMOVED], ["state", "=", "installed"]], fields=["name"])
check("зайві модулі видалено", not still, str([m["name"] for m in still]))
KEEP = ["rpc", "auth_totp", "hr_org_chart", "web_hierarchy", "base_import"]
kept = call("ir.module.module", "search_read", [["name", "in", KEEP], ["state", "=", "installed"]], fields=["name"])
check("потрібні модулі лишилися", len(kept) == len(KEEP), str(sorted(m["name"] for m in kept)))
HIDDEN = ["mail.menu_root_discuss", "calendar.mail_menu_calendar", "contacts.menu_contacts", "account.menu_finance",
          "hr.menu_hr_root", "hr_holidays.menu_hr_holidays_root", "base.menu_tests"]
for xmlid in HIDDEN:
    module, _, name = xmlid.partition(".")
    data = call("ir.model.data", "search_read", [["module", "=", module], ["name", "=", name]], fields=["res_id"])
    rec = call("ir.ui.menu", "search_read", [["id", "=", data[0]["res_id"]]], fields=["name", "group_ids"]) if data else []
    check(f"розділ «{rec[0]['name'] if rec else xmlid}» лише в режимі розробника",
          bool(rec) and rec[0]["group_ids"] == [no_one_id], str(rec[0]["group_ids"] if rec else "немає"))
people = [m["name"] for m in items]
# Оргструктура, підрозділи, картки і штатні розписи більше не окремі пункти меню:
# це чотири погляди екрана «Люди» (docs/payroll/spec-people.md). Самі дії лишилися,
# бо на них ведуть цілі з інших екранів, тому перевіряємо саме пункт «Люди».
check("«Люди» в розділі «Працівники»", "Люди" in people, str(people[:6]))
gone = [n for n in ("Оргструктура", "Підрозділи", "Картки працівників", "Штатні розписи") if n in people]
check("старі чотири пункти прибрано з меню", not gone, str(gone))

# 9. жодної порожньої сторінки: кожен видимий пункт наших розділів показує дані, не діалог, має опис
import http.cookiejar as _cj
import urllib.request as _ur
_jar = _cj.CookieJar(); _op = _ur.build_opener(_ur.HTTPCookieProcessor(_jar))
_base = URL.rsplit("/jsonrpc", 1)[0]


def _post(path, params):
    req = _ur.Request(_base + path, json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}).encode(),
                      {"Content-Type": "application/json"})
    return json.loads(_op.open(req, timeout=120).read())


if LANA_PW:
    _post("/web/session/authenticate", {"db": DB, "login": LANA_LOGIN, "password": LANA_PW})
    menus = json.loads(_op.open(_base + "/web/webclient/load_menus", timeout=60).read())
    OUR_ROOTS = set(RAIL_ROOTS)
    leaves = []

    def _walk(mid):
        m = menus[str(mid)]
        if m["children"]:
            for c in m["children"]:
                _walk(c)
        else:
            leaves.append(m)

    for app in menus["root"]["children"]:
        if menus[str(app)]["xmlid"] in OUR_ROOTS:
            _walk(app)
    rail_js = open("addons/l10n_ua_shell/static/src/side_rail.js", encoding="utf-8").read()
    empty, modal, no_help = [], [], []
    for leaf in leaves:
        if leaf["xmlid"] not in rail_js:
            no_help.append(leaf["name"])
        act = _post("/web/action/load", {"action_id": leaf["actionID"]}).get("result") or {}
        if act.get("type") != "ir.actions.act_window":
            continue
        if act.get("target") == "new":
            modal.append(leaf["name"])
            continue
        dom = act.get("domain") or "[]"
        if isinstance(dom, str):
            dom = eval(dom, {}, {"uid": 0, "company_id": 1, "allowed_company_ids": [1]})
        res = _post("/web/dataset/call_kw", {"model": act["res_model"], "method": "search_count", "args": [dom], "kwargs": {}})
        if res.get("result", 0) == 0:
            empty.append(leaf["name"])
    check(f"сторінок у наших розділах для {LANA_LOGIN}: {len(leaves)}", len(leaves) >= 20, "")
    check("жодна сторінка меню не відкриває діалог", not modal, str(modal))
    check("жодна сторінка-перелік не порожня", not empty, str(empty))
    check("кожна сторінка має опис у підказці", not no_help, str(no_help))

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
