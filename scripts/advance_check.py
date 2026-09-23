# -*- coding: utf-8 -*-
"""Перевірка Документа 4 (Авансова відомість) на стенді payroll_test.

Створює (якщо нема) чернетки листків за 10.2026, створює авансову відомість
через майстер, затверджує, перевіряє входи ADVANCE у листках, повертає
в чернетку, перевіряє що входи зникли, друкує PDF.
Запуск: python3 scripts/advance_check.py
"""
import http.cookiejar
import json
import os
import urllib.request

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
# Порт стенду береться з .env цього ж дерева: інакше скрипт стукав у сусідній стенд на 8110.
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = f"{BASE}/jsonrpc"
DB = os.environ.get("PAYROLL_CHECK_DB", "payroll_test")
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"], ensure_ascii=False)[:3000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


COMPANY = 1
YEAR, MONTH = 2026, 10
D1, D2 = "2026-10-01", "2026-10-31"
STRUCT = call("hr.payroll.structure", "search", [["code", "=", "UA_SALARY"]])[0]

# ---- 1. чернетки листків за жовтень 2026, якщо їх ще нема -------------------------------
oct_slips = call("hr.payslip", "search", [["date_from", "=", D1], ["company_id", "=", COMPANY]])
if not oct_slips:
    run = call("hr.payslip.run", "search", [["name", "=", "Зарплата за жовтень 2026"]])
    run = run[0] if run else call("hr.payslip.run", "create", {
        "name": "Зарплата за жовтень 2026", "date_start": D1, "date_end": D2, "company_id": COMPANY})
    versions = call("hr.version", "search_read", [["contract_date_start", "<=", D2]],
                    fields=["id", "employee_id", "contract_date_end"], order="employee_id, date_version desc")
    seen = set()
    created = 0
    for v in versions:
        if not v["employee_id"]:
            continue
        eid = v["employee_id"][0]
        if eid in seen:
            continue
        seen.add(eid)
        if v["contract_date_end"] and v["contract_date_end"] < D1:
            continue
        slip = call("hr.payslip", "create", {"employee_id": eid, "date_from": D1, "date_to": D2, "struct_id": STRUCT, "payslip_run_id": run})
        call("hr.payslip", "onchange_employee", [slip])
        created += 1
    print(f"Створено чернеток листків за 10.2026: {created}")
else:
    print(f"Чернетки листків за 10.2026 вже є: {len(oct_slips)}")

# ---- 2. прибрати стару чернетку/відомість за цей період, якщо лишилась з попереднього запуску ---
old = call("ua.advance.sheet", "search", [["company_id", "=", COMPANY], ["year", "=", YEAR], ["month", "=", MONTH]])
if old:
    st = call("ua.advance.sheet", "read", old, ["state"])
    for s in st:
        if s["state"] != "draft":
            call("ua.advance.sheet", "action_draft", [s["id"]])
    call("ua.advance.sheet", "unlink", old)
    print(f"Прибрано стару відомість(и): {old}")

# ---- 3. ua_compose складає відомість -----------------------------------------------------
sheet_id = call("ua.advance.sheet", "ua_compose", COMPANY, YEAR, MONTH)[0]
call("ua.advance.sheet", "write", [sheet_id], {"percent": 50.0, "pay_date": "2026-10-20"})
call("ua.advance.sheet", "action_refill", [sheet_id])
sheet = call("ua.advance.sheet", "read", [sheet_id], ["name", "state", "total", "line_ids"])[0]
print(f"Відомість: {sheet['name']} (id={sheet_id}), стан={sheet['state']}, рядків={len(sheet['line_ids'])}, разом={sheet['total']:.2f}")
assert sheet["state"] == "draft"
assert len(sheet["line_ids"]) > 0, "Немає рядків авансу — перевірте, що є активні трудові листки за 10.2026"

lines = call("ua.advance.line", "read", sheet["line_ids"], ["employee_id", "payslip_id", "amount"])
assert abs(sum(l["amount"] for l in lines) - sheet["total"]) < 0.01

# ---- 4. затвердити: входи ADVANCE мають з'явитись у листках з такими самими сумами -------
call("ua.advance.sheet", "action_confirm", [sheet_id])
state = call("ua.advance.sheet", "read", [sheet_id], ["state"])[0]["state"]
assert state == "confirmed", state
print("Затверджено.")

mismatches = []
for l in lines:
    slip_id = l["payslip_id"][0]
    inputs = call("hr.payslip.input", "search_read", [["payslip_id", "=", slip_id], ["code", "=", "ADVANCE"]], fields=["amount"])
    if not inputs or abs(inputs[0]["amount"] - l["amount"]) > 0.01:
        mismatches.append((l["employee_id"], slip_id, l["amount"], inputs))
assert not mismatches, f"Невідповідність входів ADVANCE: {mismatches}"
print(f"Входи ADVANCE перевірено в {len(lines)} листках: суми збігаються з рядками відомості.")

# ---- 5. повернути в чернетку: входи ADVANCE мають зникнути --------------------------------
call("ua.advance.sheet", "action_draft", [sheet_id])
state = call("ua.advance.sheet", "read", [sheet_id], ["state"])[0]["state"]
assert state == "draft", state
print("Повернено в чернетку.")

leftover = []
for l in lines:
    slip_id = l["payslip_id"][0]
    inputs = call("hr.payslip.input", "search", [["payslip_id", "=", slip_id], ["code", "=", "ADVANCE"]])
    if inputs:
        leftover.append((slip_id, inputs))
assert not leftover, f"Входи ADVANCE лишились після повернення в чернетку: {leftover}"
print("Входи ADVANCE прибрано з усіх листків.")

# ---- 6. PDF ------------------------------------------------------------------------------
# HTTP стенду відповідає лише базі payroll (dbfilter), тому на копії друк пропускаємо.
if DB == "payroll":
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(urllib.request.Request(f"{BASE}/web/session/authenticate",
        json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode(),
        {"Content-Type": "application/json"})).read()
    pdf = opener.open(f"{BASE}/report/pdf/l10n_ua_payroll_reports.report_ua_advance_sheet/{sheet_id}").read()
    assert pdf[:4] == b"%PDF", pdf[:200]
    print(f"PDF відомості: {len(pdf)} байт, починається з %PDF.")
else:
    print(f"[--] друк PDF пропущено: HTTP стенду дозволяє лише базу payroll (зараз {DB}).")

print("\nOK: усі перевірки Документа 4 (Авансова відомість) пройдено.")
