"""Перевірка сторінки «Період» (модуль l10n_ua_period).

Сторінка не має власних даних: вона читає накази, табель, аванс, листки, проводки,
відомості, виписку, журнал змін і звітність. Перевіряємо, що всі дев'ять кроків на місці, стани
відповідають даним стенду, обороти рахунків рахуються, а кнопки відкривають записи.

Оновлено під spec-period-v2.md (смуга кроків замість трьох колонок). Пункти, які перевіряли
блок, якого більше нема, тепер перевіряють те, що прийшло на його місце - не видалені мовчки:
- назва/стан/факт кроку -> name/mark/subtitle (mark: ok/warn/crit/idle, було done/warn/todo);
- "рядок деталей" кроку bank -> рядок у step["rows"] з ціллю-доменом (був details[0] з res_id);
- "числа місяця: estimate" -> "числа місяця: totals" (employer перейменовано на esv);
- "черга винятків" (data.exceptions) -> структурна перевірка step["rows"] на всіх кроках:
  кожен рядок має level/text/target (сама черга розкладена по кроках, п.1 спеки);
- "зміни місяця" (data.changes) -> рядки кроку "changes" (те саме, тепер там же, п.1 спеки);
- "перші кроки: 8 пунктів" + "пункт індексу" - ЗНЯТО, не адаптовано: first_steps переїхав на
  «Домівку» (l10n_ua_home), тут цих даних більше немає в принципі, перевіряти в цьому модулі
  нічого («Перевірка», п.6 спеки: ключ відсутній у відповіді - і перевіряється явно нижче).
Нові пункти: рівно один current, mark зі списку, blockers.count кроку = довжині data.blockers,
рядок «Заважає закрити» веде на перший блокуючий крок, усі чотири прибрані ключі відсутні.

«Перемикання кроку не перезавантажує місяць» - властивість клієнта (period.js), яку RPC-скрипт
не натискає; перевіряємо структурну передумову, яка це і гарантує - усі дев'ять тіл (rows) уже
готові в першій відповіді, а не довантажуються по кліку.

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
expected = {"company", "period", "steps", "done", "total", "turnover", "blockers", "totals"}
check("get_screen_data() повертає всі ключі", expected.issubset(data.keys()),
      f"відсутні: {expected - set(data.keys())}" if not expected.issubset(data.keys()) else data["period"]["label"])
check("first_steps, exceptions, changes відсутні у відповіді (п.1 спеки)",
      {"first_steps", "exceptions", "changes"}.isdisjoint(data.keys()),
      str({"first_steps", "exceptions", "changes"} & set(data.keys())))

keys = [s["key"] for s in data["steps"]]
check("дев'ять кроків у робочому порядку",
      keys == ["orders", "timesheet", "advance", "payslips", "moves", "payment", "bank", "changes", "reporting"], str(keys))
check("кожен крок має назву, позначку і факт",
      all(s["name"] and s["mark"] in ("ok", "warn", "crit", "idle") and s["subtitle"] for s in data["steps"]))
check("кожен крок пронумерований по порядку (n = 1..9)",
      [s["n"] for s in data["steps"]] == list(range(1, 10)), str([s["n"] for s in data["steps"]]))
check("рівно один крок відкритий (current)",
      sum(1 for s in data["steps"] if s["current"]) == 1,
      str([s["key"] for s in data["steps"] if s["current"]]))
check("усі тіла кроків уже в першій відповіді - перемикання кроку не звертається на сервер",
      all("rows" in s and isinstance(s["rows"], list) for s in data["steps"]))
check("періодів для перемикання шість", len(data["period"]["periods"]) == 6, f"{len(data['period']['periods'])}")

by_key = {s["key"]: s for s in data["steps"]}
check("серпень: листки проведено", by_key["payslips"]["mark"] == "ok", by_key["payslips"]["subtitle"])
check("серпень: проводки збалансовані", by_key["moves"]["mark"] == "ok", by_key["moves"]["subtitle"])
check("серпень: відомість на виплату є", by_key["payment"]["mark"] in ("ok", "warn"), by_key["payment"]["subtitle"])
check("серпень: накази проведено", by_key["orders"]["mark"] == "ok", by_key["orders"]["subtitle"])
check("крок звірки знає незвірені рядки як рядок тіла",
      by_key["bank"]["mark"] in ("ok", "warn", "crit") and isinstance(by_key["bank"]["rows"], list),
      by_key["bank"]["subtitle"])
check("крок звітності показує строк подання", "строк" in by_key["reporting"]["subtitle"] or "подано" in by_key["reporting"]["subtitle"],
      by_key["reporting"]["subtitle"])

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
blockers_info = by_key["orders"]["blockers"]
check("blockers.count кроку дорівнює кількості причин, що справді блокують закриття",
      blockers_info["count"] == len(data["blockers"]),
      f"count={blockers_info['count']}, data.blockers={data['blockers']}")
check("рядок «Заважає закрити» однаковий на всіх кроках (одна причина, не дев'ять)",
      all(s["blockers"] == blockers_info for s in data["steps"]))
if blockers_info["count"]:
    check("ціль «Заважає закрити» веде на реальний крок",
          blockers_info["target"].get("step") in keys, str(blockers_info["target"]))
else:
    print("[--] цей місяць нічого не блокує, перевірку цілі «Заважає закрити» пропущено")

action = call("ua.period.board", "open_target", by_key["reporting"]["action"])
check("кнопка кроку відкриває екран", isinstance(action, dict) and action.get("type"), str(action.get("res_model") or action.get("tag")))

bank_domain_row = next((r for r in by_key["bank"]["rows"] if r.get("target", {}).get("domain")), None)
if bank_domain_row:
    found = call("account.bank.statement.line", "search_count", bank_domain_row["target"]["domain"])
    check("рядок кроку веде на реальний перелік записів (ціль-домен резолвиться)",
          found > 0, f"{bank_domain_row['text']} → знайдено {found}")
else:
    print("[--] незвірених рядків немає, перевірку цілі рядка кроку пропущено")

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


# робоче місце місяця: головна дія, числа місяця, рядки кроків
work = {"headline", "totals", "steps"}
check("сторінка віддає дані робочого місця", work.issubset(data.keys()),
      f"немає: {sorted(work - set(data.keys()))}")
head = data.get("headline") or {}
check("головна дія має назву і кнопку", bool(head.get("title")) and "action" in head,
      f"{head.get('title')} → {head.get('label') or 'без кнопки'}")
tot = data.get("totals") or {}
check("числа місяця: нараховано, до виплати, ЄСВ",
      all(tot.get(k) for k in ("gross", "net", "esv")), str(tot))
check("кожен рядок кожного кроку має рівень, текст і ціль (колишня черга винятків розкладена по кроках)",
      all(("level" in r and r.get("text") and "target" in r) for s in data["steps"] for r in s["rows"]),
      f"{sum(len(s['rows']) for s in data['steps'])} рядків усього")
check("крок «Перевірка змін» показує зміни місяця рядками (колишній окремий блок)",
      isinstance(by_key["changes"]["rows"], list))
prepare = call("ua.period.board", "action_prepare_month", 2026, 8)
check("«Підготувати місяць» відповідає повідомленням", bool(prepare.get("message")), str(prepare)[:80])

# ---------------------------------------------------------------- логіка окремо від екрана
# Перешкоди закриття і план закриття живуть в ua.period.close (l10n_ua_changes), сторінка
# лише передає період. Кличемо логіку прямо, без сторінки, і звіряємо результат.
COMPANY_ID = call("res.users", "read", [UID], ["company_id"])[0]["company_id"][0]
NOLOG = {"ua_no_log": True}

logic_blockers = call("ua.period.close", "blocker_rows", COMPANY_ID, 2026, 8)
check("перешкоди закриття мають одне джерело - ua.period.close.blocker_rows()",
      [row["text"] for row in logic_blockers] == data["blockers"],
      f"логіка={[r['text'] for r in logic_blockers]}, сторінка={data['blockers']}")
check("кожна перешкода знає свій крок і свою ціль",
      all(row["key"] in keys and row["short"] and row["plan"] and row["target"] for row in logic_blockers),
      f"{len(logic_blockers)} перешкод")

plan_board = call("ua.period.board", "action_close_month_plan", year=2026, month=8)
plan_logic = call("ua.period.close", "plan", COMPANY_ID, 2026, 8)
check("план закриття складає логіка, сторінка лише передає період",
      plan_board == plan_logic, f"{len(plan_board)} рядків проти {len(plan_logic)}")
check("план закриття - рядки з текстом і рівнем",
      bool(plan_logic) and all(p.get("text") and p.get("level") in ("info", "warn", "crit") for p in plan_logic),
      str([p["level"] for p in plan_logic]))

# Відкриття місяця - процедура hr.payslip.run.ua_prepare_month(), не метод сторінки.
# Доводимо на порожньому місяці: спершу готує сторінка, потім та сама логіка напряму,
# і набір листків збігається. Усе, що скрипт створив, він же й прибирає.
SY, SM = 2027, 3
S_FIRST, S_LAST = f"{SY}-{SM:02d}-01", f"{SY}-{SM:02d}-31"


def scratch_slips():
    rows = call("hr.payslip", "search_read",
                [["company_id", "=", COMPANY_ID], ["date_from", ">=", S_FIRST], ["date_from", "<=", S_LAST]],
                fields=["employee_id"])
    return sorted(r["employee_id"][0] for r in rows)


def scratch_clear():
    slips = call("hr.payslip", "search",
                 [["company_id", "=", COMPANY_ID], ["date_from", ">=", S_FIRST], ["date_from", "<=", S_LAST]])
    if slips:
        # compute_sheet лишає листок у стані «перевірено», а видалити можна лише чернетку
        call("hr.payslip", "action_payslip_draft", slips, context=NOLOG)
        call("hr.payslip", "unlink", slips, context=NOLOG)
    runs = call("hr.payslip.run", "search",
                [["company_id", "=", COMPANY_ID], ["date_start", ">=", S_FIRST], ["date_start", "<=", S_LAST]])
    if runs:
        call("hr.payslip.run", "unlink", runs, context=NOLOG)
    sheets = call("ua.timesheet.sheet", "search",
                  [["company_id", "=", COMPANY_ID], ["year", "=", SY], ["month", "=", SM]])
    if sheets:
        call("ua.timesheet.sheet", "unlink", sheets, context=NOLOG)


try:
    scratch_clear()
    board_prepare = call("ua.period.board", "action_prepare_month", SY, SM, context=NOLOG)
    board_slips = scratch_slips()
    scratch_clear()
    logic_prepare = call("hr.payslip.run", "ua_prepare_month", COMPANY_ID, SY, SM, context=NOLOG)
    logic_slips = scratch_slips()
    check("порожній місяць справді готується (сторінка створила листки)",
          bool(board_slips), f"{len(board_slips)} листків")
    check("логіка дає той самий набір листків, що й сторінка",
          board_slips == logic_slips, f"сторінка {len(board_slips)}, логіка {len(logic_slips)}")
    check("логіка повідомляє про зроблене тими самими словами",
          board_prepare.get("message") == logic_prepare.get("message"),
          f"{board_prepare.get('message')} / {logic_prepare.get('message')}")
finally:
    scratch_clear()
check("стенд прибрано: пробного місяця не лишилося", not scratch_slips(), str(scratch_slips()))

# числа і обороти ведуть у свої записи
tot = data["totals"]
check("числа місяця ведуть у листки", tot.get("model") == "hr.payslip" and bool(tot.get("domain")),
      f"model={tot.get('model')}")
found = call("hr.payslip", "search_count", tot["domain"])
check("домен чисел місяця знаходить листки", found == tot["people"], f"домен={found}, у числі {tot['people']}")
draft = call("hr.payslip", "search_count", tot["draft_domain"])
check("домен чернеток збігається з числом", draft == tot["draft"], f"домен={draft}, у числі {tot['draft']}")
if data["turnover"]:
    row = data["turnover"][0]
    check("рядок оборотів веде у проводки", row.get("model") == "account.move.line" and bool(row.get("domain")),
          f"model={row.get('model')}")
    lines = call("account.move.line", "search_count", row["domain"])
    check("домен рядка оборотів знаходить проводки", lines > 0, f"знайдено {lines}")

# пояснення кожного кроку (режим підказок) - зміст не змінився цією спекою
screen = call("ua.period.board", "get_screen_data", year=2026, month=9)
help_map = screen.get("help", {})
missing_help = [st["key"] for st in screen["steps"] if st["key"] not in help_map]
check("у кожного кроку є пояснення", not missing_help, str(missing_help))
long = [k for k, h in help_map.items() for part in h.values() if len(part.split()) > 25]
check("пояснення не довші за 25 слів у реченні", not long, str(long))

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
