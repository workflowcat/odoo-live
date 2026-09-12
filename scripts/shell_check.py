"""Перевірка каркаса: смуга навігації і перегляд документів з друком браузером.

- модуль l10n_ua_shell встановлено, ресурси смуги потрапили в збірку;
- «Період» віддає документи кроків і смугу строків;
- /ua/print рендерить документ і пакет, альбомні форми позначає альбомними,
  чернетки - знаком, у режимі вбудовування не показує рядок кнопок;
- чужі або порожні запити не ламають маршрут.

Запуск: PAYROLL_DB=payroll python3 scripts/shell_check.py"""
import http.cookiejar
import json
import os
import urllib.parse
import urllib.request

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
BASE = os.environ.get("ODOO_URL", "http://127.0.0.1:8110").rstrip("/")
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def post(path, payload):
    req = urllib.request.Request(BASE + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    return json.loads(opener.open(req, timeout=180).read())


def call(model, method, *args, **kw):
    res = post("/web/dataset/call_kw", {"jsonrpc": "2.0", "method": "call",
                                        "params": {"model": model, "method": method, "args": list(args), "kwargs": kw}})
    if "error" in res:
        raise SystemExit(json.dumps(res["error"], ensure_ascii=False)[:800])
    return res["result"]


def get(path):
    with opener.open(BASE + path, timeout=180) as r:
        return r.getcode(), r.read().decode("utf-8", "replace")


auth = post("/web/session/authenticate", {"jsonrpc": "2.0", "method": "call",
                                          "params": {"db": DB, "login": LOGIN, "password": PW}})
check("вхід", bool(auth.get("result")), "")

mod = call("ir.module.module", "search_read", [["name", "=", "l10n_ua_shell"]], fields=["state"])
check("l10n_ua_shell встановлено", bool(mod) and mod[0]["state"] == "installed", str(mod))

code, bundle_js = get("/web/assets/debug/web.assets_backend.js")
check("смуга навігації в збірці ресурсів", "l10n_ua_shell.SideRail" in bundle_js, f"code={code}")

# «Період»: документи кроків і строки
data = call("ua.period.board", "get_screen_data", year=2026, month=9)
docs = data.get("documents", {})
flat = [d for items in docs.values() for d in items]
check("«Період» віддає документи кроків", len(flat) >= 3, f"{len(flat)} документів у {len(docs)} кроках")
step_keys = {s["key"] for s in data["steps"]}
check("документи прив'язані до наявних кроків", set(docs) <= step_keys, str(sorted(set(docs) - step_keys)))
check("кожен документ має вид print, filing або file", all(d["kind"] in ("print", "filing", "file") for d in flat))
check("документ для друку має шаблон і записи", all(d["report"] and d["ids"] for d in flat if d["kind"] == "print"))
filings = [d for d in flat if d["kind"] == "filing"]
check("подання мають строк", all(d["deadline"] for d in filings), f"{len(filings)} подань")
dl = data.get("deadlines", [])
check("смуга строків не порожня", len(dl) >= 2, f"{len(dl)} позначок")
keys = [(d["date"][6:], d["date"][3:5], d["date"][:2]) for d in dl]
check("строки йдуть за датою", keys == sorted(keys), str([d["date"] for d in dl]))
check("квартальний дубль прибрано зі смуги", not any("квартал" in d["label"] for d in dl))

# /ua/print: один документ
timesheet = next((d for d in docs.get("timesheet", []) if d["kind"] == "print"), None)
payslips = next((d for d in docs.get("payslips", []) if d["kind"] == "print"), None)
if timesheet:
    q = urllib.parse.urlencode({"items": json.dumps([{"r": timesheet["report"], "ids": timesheet["ids"]}])})
    code, html = get("/ua/print?" + q)
    check("табель рендериться в HTML", code == 200 and "ua-sec" in html, f"code={code}")
    check("табель позначено альбомною сторінкою", "ua-sec ua-land" in html)
    check("сторінка має правило альбомного друку", "size: A4 landscape" in html)
    check("рядок кнопок з друком браузера є", 'onclick="window.print()"' in html)
    code, emb = get("/ua/print?" + q + "&embed=1")
    check("у режимі вбудовування рядка кнопок немає", 'class="ua-toolbar"' not in emb)
    check("заголовок сторінки - назва документа", "<title>Odoo Report</title>" not in html)
if timesheet and payslips:
    q = urllib.parse.urlencode({"items": json.dumps([{"r": timesheet["report"], "ids": timesheet["ids"], "t": "Табель"},
                                                     {"r": payslips["report"], "ids": payslips["ids"][:2], "t": "Листки"}]),
                                "title": "Пакет"})
    code, html = get("/ua/print?" + q)
    secs = html.count('<section class="ua-sec')
    check("пакет з двох документів", secs == 2, f"секцій {secs}")
    check("чернетки листків позначено знаком", "ua-draft" in html)

# стійкість маршруту
code, html = get("/ua/print?items=" + urllib.parse.quote("[]"))
check("порожній пакет не ламає маршрут", code == 200 and "Немає документів" in html, f"code={code}")
code, html = get("/ua/print?items=" + urllib.parse.quote(json.dumps([{"r": "no.such_report", "ids": [1]}])))
check("невідомий шаблон пропускається", code == 200, f"code={code}")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
