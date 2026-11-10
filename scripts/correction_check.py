"""Перевірка коригування об'єднаної звітності: звітний новий і уточнюючий розрахунок.

Логіка ДПС: у коригуванні подають лише змінені рядки - старий рядок з ознакою «1» (вилучення)
і новий з ознакою «0» (введення). Перевіряємо, що майстер бере подані файли, знаходить різницю,
ставить ознаки, рахує підсумки як різницю і що XML лишається валідним за XSD.

Сценарій: формуємо звичайний розрахунок за серпень, підміняємо в Д1 одну суму (наче її подали
з помилкою), і просимо уточнюючий - у ньому має бути рівно два рядки по цій особі.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/correction_check.py"""
import base64
import json
import os
import re
import urllib.request

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
        message = json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)
        raise RuntimeError(message[:600])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def files_of(wizard):
    ids = call("ua.payroll.report.wizard", "read", [wizard], ["result_ids"])[0]["result_ids"]
    return call("ir.attachment", "read", ids, ["name", "datas"])


def rows_of(content, cols):
    """{ROWNUM: {колонка: текст}} з XML додатка."""
    text = content.decode("windows-1251", "replace")
    rows = {}
    for match in re.finditer(r'<T1RXXXX([A-Z0-9]+) ROWNUM="(\d+)"[^>]*>([^<]*)</T1RXXXX\1>', text):
        col, num, value = match.group(1), int(match.group(2)), match.group(3)
        if col in cols:
            rows.setdefault(num, {})[col] = value.strip()
    return rows


# 1. Звичайний розрахунок за серпень 2026
wizard = call("ua.payroll.report.wizard", "create", {"year": 2026, "month": 8, "number": 1, "doc_type": "HZ"})
call("ua.payroll.report.wizard", "action_generate", [wizard])
log = call("ua.payroll.report.wizard", "read", [wizard], ["log"])[0]["log"]
check("звичайний розрахунок валідний за XSD", "ПОМИЛКИ" not in log, log.splitlines()[0] if log else "")

base_files = files_of(wizard)
d1_file = next((f for f in base_files if "J0510111" in f["name"]), None)
df_file = next((f for f in base_files if "J0510411" in f["name"]), None)
check("сформовано Д1 і 4ДФ", bool(d1_file) and bool(df_file))
d1_content = base64.b64decode(d1_file["datas"])
base_rows = rows_of(d1_content, {"G7S", "G16", "G20", "G25"})
check("у Д1 є рядки з ознакою 0", bool(base_rows) and all(r.get("G25") == "0" for r in base_rows.values()),
      f"{len(base_rows)} рядків")

# 2. Підміняємо одну суму, наче її подали з помилкою
first_num = sorted(base_rows)[1] if len(base_rows) > 1 else sorted(base_rows)[0]
original = base_rows[first_num]["G16"]
wrong = "%.2f" % (float(original) - 1000.0)
text = d1_content.decode("windows-1251")
pattern = f'<T1RXXXXG16 ROWNUM="{first_num}">{original}</T1RXXXXG16>'
check("знайшли рядок для підміни", pattern in text, pattern[:60])
submitted = text.replace(pattern, f'<T1RXXXXG16 ROWNUM="{first_num}">{wrong}</T1RXXXXG16>', 1).encode("windows-1251")
att = call("ir.attachment", "create", {"name": d1_file["name"], "datas": base64.b64encode(submitted).decode(),
                                       "mimetype": "application/xml"})

# 3. Уточнюючий без змін проти поданого - має відмовити
same = call("ua.payroll.report.wizard", "create",
            {"year": 2026, "month": 8, "number": 1, "doc_type": "HZU", "with_4df": False, "with_d5": False,
             "base_attachment_ids": [(6, 0, [call("ir.attachment", "create", {"name": d1_file["name"], "datas": d1_file["datas"], "mimetype": "application/xml"})])]})
try:
    call("ua.payroll.report.wizard", "action_generate", [same])
    check("без розбіжностей уточнюючий не формується", False, "помилки не було")
except RuntimeError as error:
    check("без розбіжностей уточнюючий не формується", "Розбіжностей" in str(error), str(error)[:80])

# 4. Уточнюючий проти поданого з помилкою
correction = call("ua.payroll.report.wizard", "create",
                  {"year": 2026, "month": 8, "number": 1, "doc_type": "HZU", "with_4df": False, "with_d5": False,
                   "base_attachment_ids": [(6, 0, [att])]})
call("ua.payroll.report.wizard", "action_generate", [correction])
log = call("ua.payroll.report.wizard", "read", [correction], ["log"])[0]["log"]
check("уточнюючий валідний за XSD", "ПОМИЛКИ" not in log, log.splitlines()[0] if log else "")

corr_files = files_of(correction)
corr_d1 = next((f for f in corr_files if "J0510111" in f["name"]), None)
corr_rows = rows_of(base64.b64decode(corr_d1["datas"]), {"G7S", "G16", "G20", "G25"})
check("у коригуванні рівно два рядки", len(corr_rows) == 2, f"{len(corr_rows)} рядків: {list(corr_rows.values())}")
flags = sorted(r.get("G25") for r in corr_rows.values())
check("один рядок на вилучення (1), один на введення (0)", flags == ["0", "1"], str(flags))
removed = next((r for r in corr_rows.values() if r["G25"] == "1"), {})
added = next((r for r in corr_rows.values() if r["G25"] == "0"), {})
check("вилучається саме подана (помилкова) сума", removed.get("G16") == wrong, f"{removed.get('G16')} проти {wrong}")
check("вводиться правильна сума", added.get("G16") == original, f"{added.get('G16')} проти {original}")
check("особа в обох рядках та сама", removed.get("G7S") == added.get("G7S"), removed.get("G7S", ""))

body = base64.b64decode(corr_d1["datas"]).decode("windows-1251")
match = re.search(r"<R01G16>([^<]+)</R01G16>", body)
delta = float(match.group(1)) if match else None
check("підсумок дорівнює різниці (введення мінус вилучення)",
      delta is not None and abs(delta - 1000.0) < 0.01, str(delta))

# 5. Звітний новий працює так само
new_report = call("ua.payroll.report.wizard", "create",
                  {"year": 2026, "month": 8, "number": 1, "doc_type": "HZN", "with_4df": False, "with_d5": False,
                   "base_attachment_ids": [(6, 0, [att])]})
call("ua.payroll.report.wizard", "action_generate", [new_report])
new_files = files_of(new_report)
new_d1 = next((f for f in new_files if "J0510111" in f["name"]), None)
check("звітний новий теж дає два рядки", len(rows_of(base64.b64decode(new_d1["datas"]), {"G25"})) == 2)

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
