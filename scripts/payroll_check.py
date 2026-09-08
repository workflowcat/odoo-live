#!/usr/bin/env python3
"""Еталонні сценарії: створює працівників, рахує листки за серпень 2026 і звіряє з docs/payroll/golden-scenarios.md.
Запуск: python3 scripts/payroll_check.py  (читає .env: ODOO_PORT, ODOO_ADMIN_USER_PASSWORD; база payroll)"""
import os, sys, json, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
URL = f"http://127.0.0.1:{ENV.get('ODOO_PORT', '8110')}"; DB = "payroll"; PW = ENV["ODOO_ADMIN_USER_PASSWORD"]
def rpc(service, method, *args):
    body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1, "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(f"{URL}/jsonrpc", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    if out.get("error"):
        raise RuntimeError(out["error"].get("data", {}).get("message") or out["error"])
    return out.get("result")
uid = rpc("common", "authenticate", DB, "admin", PW, {})
if not uid:
    uid = rpc("common", "authenticate", DB, "admin", "admin", {})
    rpc("object", "execute_kw", DB, uid, "admin", "res.users", "write", [[uid], {"password": PW}])
def call(model, method, *a, **kw): return rpc("object", "execute_kw", DB, uid, PW, model, method, list(a), kw)

STRUCT = call("hr.payroll.structure", "search", [["code", "=", "UA_SALARY"]])[0]
CAL = call("res.company", "read", [1], ["resource_calendar_id"])[0]["resource_calendar_id"][0]
PERIOD = ("2026-08-01", "2026-08-31")
# сценарії: назва, поля працівника, оклад, входи, очікувані рядки; поле "start" - дата прийняття, якщо не 2026-01-01
S = [
 ("1 Повний місяць, оклад", {"ua_main_job": True}, 30000, {}, {"PDFO": -5400.00, "VZ": -1500.00, "NET": 23100.00, "ESV": 6600.00}),
 ("2 Неповний місяць (з 17-го, 11 з 21 днів)", {"ua_main_job": True, "start": "2026-08-17"}, 30000, {}, {"BASIC": 15714.29, "PDFO": -2828.57, "VZ": -785.71, "NET": 12100.01, "ESV": 3457.14}),
 ("3 Сумісник", {"ua_main_job": False}, 5000, {}, {"PDFO": -900.00, "VZ": -250.00, "NET": 3850.00, "ESV": 1100.00}),
 ("4 ПСП базова", {"ua_main_job": True, "ua_psp": "base"}, 4500, {}, {"PDFO": -510.48, "VZ": -225.00, "NET": 3764.52, "ESV": 1902.34}),
 ("5 Інвалідність", {"ua_main_job": True, "ua_esv_category": "disabled"}, 20000, {}, {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 1682.00}),
 ("9 ЦПХ", {"ua_contract_kind": "gph", "ua_main_job": False}, 0, {"GPH": 20000}, {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 4400.00}),
 ("10 Аліменти + макс. база", {"ua_main_job": True}, 200000, {"ALIM_PCT": 25}, {"PDFO": -36000.00, "VZ": -10000.00, "ALIM": -38500.00, "NET": 115500.00, "ESV": 38046.80}),
]
ok = True
for name, efields, wage, inputs, expect in S:
    ename = f"Еталон {name}"
    start = efields.pop("start", "2026-01-01")
    eid = call("hr.employee", "search", [["name", "=", ename]])
    if eid:
        old = call("hr.payslip", "search", [["employee_id", "in", eid]])
        if old:
            call("hr.payslip", "write", old, {"state": "cancel"})
            call("hr.payslip", "unlink", old)
        eid = eid[0]
        call("hr.employee", "write", [eid], {"ua_main_job": True, "ua_psp": "none", "ua_esv_category": "standard", "ua_contract_kind": "employment", **efields})
    else:
        eid = call("hr.employee", "create", {"name": ename, **efields})
    ver = call("hr.employee", "read", [eid], ["version_id"])[0]["version_id"][0]
    call("hr.version", "write", [ver], {"wage": wage, "contract_date_start": start, "struct_id": STRUCT, "resource_calendar_id": CAL})
    slip = call("hr.payslip", "create", {"employee_id": eid, "date_from": PERIOD[0], "date_to": PERIOD[1], "struct_id": STRUCT, "name": ename})
    call("hr.payslip", "onchange_employee", [slip])   # кнопка OCA: контракт, відпрацьовані дні, рядки входів
    if inputs:
        for code, amount in inputs.items():
            iid = call("hr.payslip.input", "search", [["payslip_id", "=", slip], ["code", "=", code]])
            if iid:
                call("hr.payslip.input", "write", iid, {"amount": amount})
            else:
                call("hr.payslip.input", "create", {"payslip_id": slip, "code": code, "name": code, "amount": amount, "contract_id": ver})
    call("hr.payslip", "compute_sheet", [slip])
    lines = {l["code"]: round(l["total"], 2) for l in call("hr.payslip.line", "search_read", [["slip_id", "=", slip]], fields=["code", "total"])}
    wd = call("hr.payslip.worked_days", "search_read", [["payslip_id", "=", slip]], fields=["code", "number_of_days"])
    res = []
    for code, exp in expect.items():
        got = lines.get(code); good = got is not None and abs(got - exp) < 0.005; ok &= good
        res.append(f"{code} {got} {'==' if good else '!='} {exp}")
    print(("PASS " if all("==" in r for r in res) else "FAIL ") + name + " | " + "; ".join(res) + f" | worked {[(w['code'], w['number_of_days']) for w in wd]}")
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
