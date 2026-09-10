#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка документів 1-3 (табель, штатний розпис, заява-розрахунок ПФУ) на стенді, база payroll.
Створює табель за 08.2026, штатний розпис на 2026-08-31, заяву-розрахунок ПФУ для пакета
«Зарплата за серпень 2026»; друкує PDF трьох документів; звіряє мінімальні очікування.
Запуск: python3 scripts/docs_check.py  (читає .env: ODOO_PORT, ODOO_ADMIN_USER_PASSWORD)"""
import http.cookiejar
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PORT = os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110").strip()
BASE = f"http://127.0.0.1:{PORT}"
DB = "payroll"
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
RUN_NAME = "Зарплата за серпень 2026"


def rpc(service, method, *args):
    body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1, "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(f"{BASE}/jsonrpc", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    if out.get("error"):
        raise RuntimeError(out["error"].get("data", {}).get("message") or out["error"])
    return out.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise RuntimeError("Не вдалося увійти в Odoo (перевірте ODOO_ADMIN_USER_PASSWORD).")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def get_pdf(report_name, res_id):
    """Автентифікація через HTTP-сесію (cookiejar) і GET /report/pdf/<report>/<id>; тіло має починатись з %PDF."""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    auth_body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode()
    opener.open(urllib.request.Request(f"{BASE}/web/session/authenticate", data=auth_body, headers={"Content-Type": "application/json"}), timeout=60).read()
    with opener.open(f"{BASE}/report/pdf/{report_name}/{res_id}", timeout=120) as r:
        return r.read()


errors = []


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        errors.append(label)


# 1. Табель обліку робочого часу за 08.2026
wiz_id = call("ua.timesheet.wizard", "create", {"year": 2026, "month": 8})
action = call("ua.timesheet.wizard", "action_create", [wiz_id])
timesheet_id = action["res_id"]
timesheet = call("ua.timesheet.sheet", "read", [timesheet_id], ["name", "line_ids", "state"])[0]
print(f"Табель: {timesheet['name']} (id={timesheet_id}, стан={timesheet['state']}, рядків={len(timesheet['line_ids'])})")
check(f"табель має >= 15 рядків ({len(timesheet['line_ids'])})", len(timesheet["line_ids"]) >= 15)

# 2. Штатний розпис на 2026-08-31
wiz_id = call("ua.staff.list.wizard", "create", {"date": "2026-08-31"})
action = call("ua.staff.list.wizard", "action_create", [wiz_id])
staff_list_id = action["res_id"]
staff_list = call("ua.staff.list", "read", [staff_list_id], ["name", "total_units", "total_fund", "state"])[0]
print(f"Штатний розпис: {staff_list['name']} (id={staff_list_id}, стан={staff_list['state']}, штатних одиниць={staff_list['total_units']}, фонд={staff_list['total_fund']})")
check(f"штатний розпис total_units > 10 ({staff_list['total_units']})", staff_list["total_units"] > 10)

# 3. Заява-розрахунок ПФУ для пакета RUN_NAME
run_ids = call("hr.payslip.run", "search", [["name", "=", RUN_NAME]])
if not run_ids:
    raise RuntimeError(f"Не знайдено пакет листків «{RUN_NAME}» у базі {DB}.")
action = call("hr.payslip.run", "action_ua_pfu_claim", [run_ids[0]])
claim_id = action["res_id"]
claim = call("ua.pfu.claim", "read", [claim_id], ["name", "line_ids", "total", "state"])[0]
print(f"Заява-розрахунок ПФУ: {claim['name']} (id={claim_id}, стан={claim['state']}, рядків={len(claim['line_ids'])}, разом={claim['total']})")
check(f"заява-розрахунок total > 0 ({claim['total']})", claim["total"] > 0)

# PDF трьох документів
for label, report_name, res_id in [
    ("Табель", "l10n_ua_hr_docs.report_ua_timesheet", timesheet_id),
    ("Штатний розпис", "l10n_ua_hr_docs.report_ua_staff_list", staff_list_id),
    ("Заява-розрахунок ПФУ", "l10n_ua_hr_docs.report_ua_pfu_claim", claim_id),
]:
    pdf = get_pdf(report_name, res_id)
    print(f"PDF {label}: {len(pdf)} байт")
    check(f"PDF {label} починається з %PDF", pdf[:4] == b"%PDF")

# Довідка про доходи: майстер рахує суми з проведених листків і друкує PDF
emp_ids = call("hr.employee", "search", [["active", "=", True], ["name", "like", "Крамар"]], limit=1)
if emp_ids:
    cert_id = call("ua.income.certificate.wizard", "create",
                   {"employee_id": emp_ids[0], "date_from": "2026-07-01", "date_to": "2026-08-31",
                    "purpose": "для подання до банку"})
    slips = call("hr.payslip", "search_read",
                 [["employee_id", "=", emp_ids[0]], ["state", "=", "done"],
                  ["date_from", ">=", "2026-07-01"], ["date_to", "<=", "2026-08-31"]],
                 fields=["line_ids"])
    check(f"довідка про доходи: є проведені листки за період ({len(slips)})", len(slips) >= 1)
    pdf = get_pdf("l10n_ua_payroll_reports.report_ua_income_certificate", cert_id)
    print(f"PDF Довідка про доходи: {len(pdf)} байт")
    check("PDF довідки про доходи починається з %PDF", pdf[:4] == b"%PDF")
else:
    check("довідка про доходи: знайдено працівника Крамар", False)

print()
if errors:
    print(f"ПОМИЛКИ: {len(errors)}")
    for e in errors:
        print(f" - {e}")
    sys.exit(1)
print("Усі перевірки пройдено.")
