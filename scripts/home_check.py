"""Перевірка сторінки «Домівка» (модуль l10n_ua_home).

Сторінка не має власних даних: карта п'яти розділів (люди, зарплата, банк, звітність,
налаштування) з потоком між ними, особиста панель праворуч (що зробити зараз, нещодавнє,
чернетки користувача) і перемикач місяця. Дані читаються з тих самих моделей, що й
«Період» (l10n_ua_period): накази, документи, справи прийняття, військовий облік, табель,
аванс, листки, виписка банку, звітність, анкета компанії, журнал змін.

Цілі (`target`) з будь-якого блоку відповіді (дія розділу, бейдж, рядок «зробити»,
нещодавнє, чернетка) шукаються по всій відповіді загально - за формою словника
(є "xmlid", або є "model"), а не за іменем ключа, - і кожна мусить відкриватись через
`ua.home.open_target`. Так нові блоки покриваються автоматично, без правок цього файлу.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/home_check.py"""
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
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
LANA_LOGIN = ENV.get("LANA_LOGIN", "lana").strip()
LANA_PW = ENV.get("LANA_PASSWORD", "").strip()

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


UID = rpc("common", "login", DB, LOGIN, PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як {LOGIN} на базі {DB} (перевірте ODOO_ADMIN_USER_PASSWORD).")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


# 1. клієнтська дія з тегом ua_home існує
actions = call("ir.actions.client", "search_read", [["tag", "=", "ua_home"]], fields=["name"])
check("клієнтська дія з тегом ua_home існує", len(actions) == 1, str(actions))

# 2. корінь «Домівка» видимий не лише admin, а й звичайному користувачу зарплати (lana)
root_admin = call("ir.ui.menu", "search_read", [["name", "=", "Домівка"], ["parent_id", "=", False]], fields=["name"])
check("корінь «Домівка» видимий admin", bool(root_admin), f"{len(root_admin)} пунктів")

if LANA_PW:
    lana_uid = rpc("common", "login", DB, LANA_LOGIN, LANA_PW)
    if lana_uid:
        menus = rpc("object", "execute_kw", DB, lana_uid, LANA_PW, "ir.ui.menu", "search_read",
                    [[["name", "=", "Домівка"], ["parent_id", "=", False]]], {"fields": ["name"]})
        check(f"корінь «Домівка» видимий звичайному користувачу ({LANA_LOGIN})", bool(menus), f"{len(menus)} пунктів")
    else:
        check(f"вхід {LANA_LOGIN}", False, "не вдалося увійти")
else:
    check(f"вхід {LANA_LOGIN}", False, "немає пароля в .env (LANA_PASSWORD)")

# 3. get_screen_data(): усі ключі, п'ять розділів у фіксованому порядку, кожен з count/mark/name
data = call("ua.home", "get_screen_data")
expected_keys = {"period", "company", "regions", "flows", "todo", "recent", "drafts", "unseen_changes"}
check("get_screen_data() повертає всі ключі", expected_keys.issubset(data.keys()),
      f"відсутні: {expected_keys - set(data.keys())}" if not expected_keys.issubset(data.keys()) else data["period"]["label"])

regions = data["regions"]
region_keys = [r["key"] for r in regions]
check("п'ять розділів у фіксованому порядку (люди, зарплата, банк, звітність, налаштування)",
      region_keys == ["people", "payroll", "bank", "reporting", "setup"], str(region_keys))
check("кожен розділ має непорожній count, mark з двох символів і назву",
      all(r.get("count") and len(r.get("mark", "")) == 2 and r.get("name") for r in regions),
      str([(r["key"], r.get("count"), r.get("mark"), r.get("name")) for r in regions]))

# 4. flows - чотири очікувані пари, у заданому порядку
expected_flows = [["people", "payroll"], ["payroll", "bank"], ["payroll", "reporting"], ["setup", "payroll"]]
check("flows містить чотири очікувані пари", data.get("flows") == expected_flows, str(data.get("flows")))

# 5. period.periods - шість пунктів, рівно один поточний
periods = data["period"]["periods"]
check("періодів для перемикання шість", len(periods) == 6, f"{len(periods)}")
current_flags = [p for p in periods if p.get("current")]
check("рівно один період позначений як поточний", len(current_flags) == 1,
      str([p["label"] for p in current_flags]))

# 6. попередній місяць: інша мітка і інший набір бейджів/рядків «зробити» - аргумент місяця
# дійсно змінює відповідь, а не просто повторює поточний місяць
year, month = data["period"]["year"], data["period"]["month"]
prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
prev_data = call("ua.home", "get_screen_data", year=prev_year, month=prev_month)
check("попередній місяць має іншу мітку", prev_data["period"]["label"] != data["period"]["label"],
      f"{prev_data['period']['label']} vs {data['period']['label']}")


def badge_signature(d):
    return sorted((b["level"], b["text"]) for r in d["regions"] for b in r.get("badges", []))


def todo_signature(d):
    return sorted((t["level"], t["text"]) for t in d.get("todo", []))


badges_differ = badge_signature(prev_data) != badge_signature(data)
todo_differs = todo_signature(prev_data) != todo_signature(data)
check("попередній місяць дає інший набір бейджів чи рядків «зробити»", badges_differ or todo_differs,
      "однаковий набір і бейджів, і todo" if not (badges_differ or todo_differs)
      else f"бейджі {'відрізняються' if badges_differ else 'однакові'}, todo {'відрізняється' if todo_differs else 'однакове'}")


# 7. кожна ціль (`target`), знайдена будь-де у відповіді, відкривається через open_target і
# повертає словник з ключем "type". Ціль розпізнається за формою, а не за ім'ям ключа
# ("target", "action" тощо), щоб нові блоки покривались автоматично.
def is_target(node):
    return isinstance(node, dict) and ("xmlid" in node or "model" in node)


def collect_targets(node, out):
    if isinstance(node, dict):
        if is_target(node):
            out.append(node)
            return
        for value in node.values():
            collect_targets(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_targets(item, out)


targets = []
collect_targets(data, targets)
check("у відповіді знайдено цілі для перевірки", len(targets) > 0, f"{len(targets)} цілей")

bad = []
for target in targets:
    try:
        opened = call("ua.home", "open_target", target)
    except SystemExit as exc:
        bad.append((target, str(exc)[:150]))
        continue
    if not (isinstance(opened, dict) and opened.get("type")):
        bad.append((target, str(opened)[:150]))
check("кожна ціль відкривається через open_target і має ключ type", not bad,
      str(bad[:5]) if bad else f"{len(targets)} цілей перевірено")

# 8. recent: у кожного рядка непорожній who
recent = data.get("recent", [])
if recent:
    check("кожен рядок «нещодавнього» має who", all(r.get("who") for r in recent), f"{len(recent)} рядків")
else:
    print("[--] «нещодавнього» за цей місяць немає, перевірку who пропущено")

# 9. бандл ресурсів реєструє три статичні файли l10n_ua_home - спершу маніфест, тоді сам бандл
manifest_path = os.path.join(ROOT, "addons", "l10n_ua_home", "__manifest__.py")
manifest_src = open(manifest_path, encoding="utf-8").read()
expected_assets = ["l10n_ua_home/static/src/home.scss", "l10n_ua_home/static/src/home.js",
                    "l10n_ua_home/static/src/home.xml"]
check("маніфест l10n_ua_home оголошує всі три файли в web.assets_backend",
      all(a in manifest_src for a in expected_assets), manifest_path)

if DB == "payroll":
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    auth = json.dumps({"jsonrpc": "2.0", "method": "call",
                       "params": {"db": DB, "login": LOGIN, "password": PW}}).encode()
    opener.open(urllib.request.Request(BASE + "/web/session/authenticate", data=auth,
                headers={"Content-Type": "application/json"}), timeout=60).read()
    try:
        with opener.open(BASE + "/web/assets/debug/web.assets_backend.js", timeout=180) as response:
            js_body = response.read().decode("utf-8", errors="replace")
        check("бандл JS реєструє l10n_ua_home/static/src/home.js", "l10n_ua_home/static/src/home.js" in js_body)
        check("бандл JS реєструє l10n_ua_home/static/src/home.xml (шаблони owl)",
              "l10n_ua_home/static/src/home.xml" in js_body)
    except Exception as exc:
        check("GET /web/assets/debug/web.assets_backend.js", False, str(exc)[:300])
    try:
        with opener.open(BASE + "/web/assets/debug/web.assets_backend.css", timeout=180) as response:
            css_body = response.read().decode("utf-8", errors="replace")
        check("бандл CSS реєструє l10n_ua_home/static/src/home.scss", "l10n_ua_home/static/src/home.scss" in css_body)
    except Exception as exc:
        check("GET /web/assets/debug/web.assets_backend.css", False, str(exc)[:300])
else:
    print(f"[--] HTTP-перевірка збірки ресурсів пропущена: PAYROLL_DB={DB}, не payroll")


print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
