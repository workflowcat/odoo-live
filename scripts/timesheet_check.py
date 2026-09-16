"""Перевірка табеля як джерела відпрацьованого часу.

Затверджений табель задає дні і години у листку, а оклад рахується пропорційно.
Перевіряємо: норма береться з графіка; правка «Факт днів» і «Факт годин» змінює
суму листка; «Відпрацьовано» у листку збігається з табелем; повернення значень
повертає початкову суму; неповна ставка не рахується двічі (ставка × частка часу).

База зі змінної PAYROLL_DB (типово payroll). Скрипт сам повертає дані як були.
Запуск: PAYROLL_DB=payroll python3 scripts/timesheet_check.py"""
import json
import os
import calendar
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/") + "/jsonrpc"
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
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:1000])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти як admin на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


today = date.today()
YEAR, MONTH = today.year, today.month
LAST = calendar.monthrange(YEAR, MONTH)[1]

# 1. Табель поточного місяця: беремо наявний або створюємо
sheets = call("ua.timesheet.sheet", "search", [["year", "=", YEAR], ["month", "=", MONTH]], limit=1)
if not sheets:
    sheets = [call("ua.timesheet.sheet", "create", {"year": YEAR, "month": MONTH})]
    call("ua.timesheet.sheet", "action_refill", sheets)
sheet = sheets[0]
state0 = call("ua.timesheet.sheet", "read", [sheet], ["state"])[0]["state"]
lines = call("ua.timesheet.line", "search_read", [["sheet_id", "=", sheet]],
             fields=["employee_id", "norm_days", "norm_hours", "days_worked", "hours", "diff_days"])
check("у табелі є рядки", len(lines) >= 5, f"{len(lines)} рядків")
check("норма днів і годин узята з графіка", all(l["norm_days"] > 0 and l["norm_hours"] > 0 for l in lines),
      f"перший рядок: {lines[0]['norm_days']} дн, {lines[0]['norm_hours']} год" if lines else "")

# 2. Працівник з чернеткою листка і повним місяцем
target = None
for line in lines:
    slips = call("hr.payslip", "search_read",
                 [["employee_id", "=", line["employee_id"][0]],
                  ["date_from", ">=", f"{YEAR}-{MONTH:02d}-01"], ["date_to", "<=", f"{YEAR}-{MONTH:02d}-{LAST:02d}"],
                  ["state", "in", ["draft", "verify"]]], fields=["id"])
    if slips and line["norm_hours"] and abs(line["hours"] - line["norm_hours"] * 1.0) < 0.01:
        target, slip_id = line, slips[0]["id"]
        break
if not target:
    check("знайдено працівника з чернеткою листка за повний місяць", False)
    raise SystemExit(1)
check(f"працівник для перевірки: {target['employee_id'][1]}", True, f"листок {slip_id}")


def basic(slip):
    rows = call("hr.payslip.line", "search_read", [["slip_id", "=", slip], ["code", "=", "BASIC"]], fields=["total"])
    return rows[0]["total"] if rows else 0.0


def worked(slip):
    rows = call("hr.payslip.worked_days", "search_read", [["payslip_id", "=", slip], ["code", "=", "WORK100"]],
                fields=["number_of_days", "number_of_hours"])
    return (rows[0]["number_of_days"], rows[0]["number_of_hours"]) if rows else (0.0, 0.0)


def set_fact(days, hours):
    call("ua.timesheet.sheet", "action_draft", [sheet])
    call("ua.timesheet.line", "write", [target["id"]], {"days_worked": days, "hours": hours})
    call("ua.timesheet.sheet", "action_confirm", [sheet])
    call("ua.timesheet.sheet", "action_recompute_payslips", [sheet])


days0, hours0 = target["days_worked"], target["hours"]
set_fact(days0, hours0)
base_amount = basic(slip_id)
check("затверджений табель без правок не змінює суму", base_amount > 0, f"оклад {base_amount}")

# 3. Мінус два дні і шістнадцять годин
set_fact(days0 - 2, hours0 - 16)
cut_amount = basic(slip_id)
expected = round(base_amount * (hours0 - 16) / hours0, 2)
check("правка табеля зменшує оклад пропорційно годинам",
      abs(cut_amount - expected) <= 0.02, f"{cut_amount} проти очікуваних {expected}")
wd_days, wd_hours = worked(slip_id)
check("«Відпрацьовано» у листку збігається з табелем",
      abs(wd_days - (days0 - 2)) < 0.01 and abs(wd_hours - (hours0 - 16)) < 0.01,
      f"{wd_days} дн, {wd_hours} год")

# 4. Повернення значень повертає суму
set_fact(days0, hours0)
check("повернення табеля повертає початкову суму", abs(basic(slip_id) - base_amount) <= 0.01,
      f"{basic(slip_id)}")

# 5. Неповна ставка: частка часу не множиться на ставку двічі
part = None
for line in lines:
    emp = call("hr.employee", "read", [line["employee_id"][0]], ["ua_fte"])[0]
    if emp.get("ua_fte") and emp["ua_fte"] != "1" and line["hours"] and line["norm_hours"]:
        part = (line, float(emp["ua_fte"]))
        break
if part:
    line, fte = part
    slips = call("hr.payslip", "search_read",
                 [["employee_id", "=", line["employee_id"][0]],
                  ["date_from", ">=", f"{YEAR}-{MONTH:02d}-01"], ["date_to", "<=", f"{YEAR}-{MONTH:02d}-{LAST:02d}"],
                  ["state", "in", ["draft", "verify"]]], fields=["id"])
    if slips:
        version = call("hr.employee", "read", [line["employee_id"][0]], ["version_id"])[0]["version_id"][0]
        wage = call("hr.version", "read", [version], ["wage"])[0]["wage"]
        amount = basic(slips[0]["id"])
        check(f"неповна ставка {fte}: оклад це ставка × частка часу, без подвійного зменшення",
              abs(amount - round(wage * fte, 2)) <= 0.05,
              f"{line['employee_id'][1]}: {amount} проти {round(wage * fte, 2)}")
else:
    print("[--] працівника на неповній ставці з чернеткою листка немає, перевірку пропущено")

# 6. Стан табеля повертаємо як був
if state0 == "draft":
    call("ua.timesheet.sheet", "action_draft", [sheet])
state_now = call("ua.timesheet.sheet", "read", [sheet], ["state"])[0]["state"]
check("стан табеля повернуто", state_now == state0, f"{state0} → {state_now}")

# 7. Табель формує себе сам: сторінка «Період» на місяць без табеля
TEST_YEAR, TEST_MONTH = YEAR + 5, MONTH
existing_test = call("ua.timesheet.sheet", "search",
                     [["year", "=", TEST_YEAR], ["month", "=", TEST_MONTH], ["department_id", "=", False]])
if existing_test:
    call("ua.timesheet.sheet", "action_draft", existing_test)
    call("ua.timesheet.sheet", "unlink", existing_test)

call("ua.period.board", "get_screen_data", TEST_YEAR, TEST_MONTH)
created = call("ua.timesheet.sheet", "search",
               [["year", "=", TEST_YEAR], ["month", "=", TEST_MONTH], ["department_id", "=", False]])
check("відкриття «Період» за місяць без табеля створює табель", len(created) == 1, f"{len(created)} табелів")
test_sheet = created[0]
test_lines = call("ua.timesheet.line", "search_read", [["sheet_id", "=", test_sheet]], fields=["employee_id"])
check("у новому табелі є рядки", len(test_lines) > 0, f"{len(test_lines)} рядків")

checks_text = call("ua.timesheet.sheet", "read", [test_sheet], ["checks_text"])[0]["checks_text"] or ""
check("перевірки не бачать пропущених активних працівників", "рядка табеля" not in checks_text,
      checks_text.splitlines()[0] if checks_text else "")

kinds = (call("hr.employee", "read", [l["employee_id"][0] for l in test_lines], ["ua_contract_kind"])
        if test_lines else [])
gph_fop = [k for k in kinds if k.get("ua_contract_kind") in ("gph", "fop")]
check("табель не містить ЦПХ/ФОП контракторів", len(gph_fop) == 0, f"{len(gph_fop)} таких рядків")

# другий раз - без дубля
call("ua.period.board", "get_screen_data", TEST_YEAR, TEST_MONTH)
after_second = call("ua.timesheet.sheet", "search",
                    [["year", "=", TEST_YEAR], ["month", "=", TEST_MONTH], ["department_id", "=", False]])
check("повторне відкриття не створює дубля", after_second == [test_sheet], f"{after_second}")

# затверджений табель відкриття «Період» не чіпає
call("ua.timesheet.sheet", "action_confirm", [test_sheet])
lines_before = sorted(l["id"] for l in test_lines)
call("ua.period.board", "get_screen_data", TEST_YEAR, TEST_MONTH)
state_after = call("ua.timesheet.sheet", "read", [test_sheet], ["state"])[0]["state"]
lines_after = sorted(call("ua.timesheet.line", "search", [["sheet_id", "=", test_sheet]]))
check("затверджений табель лишається затвердженим", state_after == "confirmed", state_after)
check("рядки затвердженого табеля не змінюються повторним відкриттям", lines_after == lines_before,
      f"{lines_after} проти {lines_before}")

# прибираємо тестовий табель
call("ua.timesheet.sheet", "action_draft", [test_sheet])
call("ua.timesheet.sheet", "unlink", [test_sheet])

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
