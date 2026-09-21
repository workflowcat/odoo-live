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
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
# без ODOO_URL перевіряємо той стенд, у якому лежить цей скрипт (ODOO_PORT із .env),
# а не сусідній стенд на 8110
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
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

# стилі: помилка SCSS не ламає сторінку, а тихо лишає старі стилі - шукаємо її явно
import re as _re
code, home = get("/odoo")
css_links = _re.findall(r'href="(/web/assets/[^"]+web\.assets_web[^"]*\.css)"', home)
if css_links:
    code, css = get(css_links[0])
    err = _re.search(r"This error occurred while compiling the bundle[^\n]{0,160}", css)
    check("стилі зібрано без помилок SCSS", not err and "o_ua_pd_row" in css, (err.group(0) if err else "")[:160])
else:
    check("стилі зібрано без помилок SCSS", False, "посилання на CSS не знайдено")

# методи екранів - так, як їх викликає інтерфейс: без позиційних аргументів
for model, method, kwargs in (("ua.period.board", "get_screen_data", {}), ("ua.dashboard", "get_screen_data", {}),
                              ("ua.bank.board", "get_screen_data", {}), ("ua.report.run", "get_screen_data", {}),
                              ("ua.setup.profile", "screen", {})):
    res = post("/web/dataset/call_kw", {"jsonrpc": "2.0", "method": "call",
                                        "params": {"model": model, "method": method, "args": [], "kwargs": kwargs}})
    err = res.get("error", {}).get("data", {}).get("message", "") if "error" in res else ""
    check(f"екран {model}.{method} відкривається з інтерфейсу", "error" not in res, err[:120])

# «Період»: тіло кроку і строки. Екран більше не віддає документи всіх кроків одним
# словником: видно один крок за раз (docs/payroll/spec-period-v2.md), тому питаємо
# кожен крок окремо і збираємо його рядки.
data = call("ua.period.board", "get_screen_data", year=2026, month=9)
step_keys = [s["key"] for s in data["steps"]]
check("«Період» віддає дев'ять кроків", len(step_keys) == 9, f"{len(step_keys)} кроків")
check("рівно один крок відкритий", sum(1 for s in data["steps"] if s.get("current")) == 1,
      str([s["key"] for s in data["steps"] if s.get("current")]))

# Крок перемикається на клієнті, тому всі дев'ять приходять разом зі своїми рядками.
rows = [r for step in data["steps"] for r in (step.get("rows") or [])]
with_rows = [s["key"] for s in data["steps"] if s.get("rows")]
check("кроки разом дають рядки", len(rows) >= 3,
      f"{len(rows)} рядків у {len(with_rows)} кроках з {len(step_keys)}")
check("кожен рядок кроку має рівень і текст",
      all(r.get("level") and r.get("text") for r in rows),
      str([r for r in rows if not (r.get("level") and r.get("text"))][:2]))
dl = data.get("deadlines", [])
check("смуга строків не порожня", len(dl) >= 2, f"{len(dl)} позначок")
keys = [(d["date"][6:], d["date"][3:5], d["date"][:2]) for d in dl]
check("строки йдуть за датою", keys == sorted(keys), str([d["date"] for d in dl]))
check("квартальний дубль прибрано зі смуги", not any("квартал" in d["label"] for d in dl))

# /ua/print: один документ. Раніше звіт і записи бралися з документів кроку «Періоду»;
# екран місяця їх більше не віддає, тому беремо прямо з моделей - перевіряємо сам
# контролер друку, а не те, звідки його викликали. Параметр r - це report_name
# (шаблон QWeb), а не xmlid дії звіту: _get_report_from_name шукає саме його.
sheet_ids = call("ua.timesheet.sheet", "search", [["year", "=", 2026], ["month", "=", 9]])
slip_ids = call("hr.payslip", "search", [["date_from", ">=", "2026-09-01"], ["date_to", "<=", "2026-09-30"]])
timesheet = ({"report": "l10n_ua_hr_docs.report_ua_timesheet", "ids": sheet_ids, "kind": "print"}
             if sheet_ids else None)
payslips = ({"report": "l10n_ua_payroll_reports.report_ua_payslip", "ids": slip_ids, "kind": "print"}
            if slip_ids else None)
check("є табель і листки вересня для друку", bool(timesheet) and bool(payslips),
      f"табелів {len(sheet_ids)}, листків {len(slip_ids)}")
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
