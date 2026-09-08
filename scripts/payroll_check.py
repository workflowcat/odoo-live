#!/usr/bin/env python3
"""Еталонні сценарії: створює працівників, рахує листки за серпень 2026 і звіряє з docs/payroll/golden-scenarios.md.
Запуск: python3 scripts/payroll_check.py  (читає .env: ODOO_PORT, ODOO_ADMIN_USER_PASSWORD; база payroll)"""
import os, sys, json, urllib.request
from collections import defaultdict
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
# сценарії: назва, поля працівника, оклад, входи, очікувані рядки; "start" - дата прийняття; "moves" - очікувані обороти проводки
# додаткові ключі: "history" (12 місяців окладу для середньої), "leaves" [(тип, від, до)], "years" (страховий стаж)
S = [
 ("1 Повний місяць, оклад", {"ua_main_job": True, "moves": {("Дт", "92"): 36600.00, ("Кт", "661"): 30000.00, ("Дт", "661"): 6900.00, ("Кт", "6411"): 5400.00, ("Кт", "6415"): 1500.00, ("Кт", "651"): 6600.00}}, 30000, {}, {"PDFO": -5400.00, "VZ": -1500.00, "NET": 23100.00, "ESV": 6600.00}),
 ("2 Неповний місяць (з 17-го, 11 з 21 днів)", {"ua_main_job": True, "start": "2026-08-17"}, 30000, {}, {"BASIC": 15714.29, "PDFO": -2828.57, "VZ": -785.71, "NET": 12100.01, "ESV": 3457.14}),
 ("3 Сумісник", {"ua_main_job": False}, 5000, {}, {"PDFO": -900.00, "VZ": -250.00, "NET": 3850.00, "ESV": 1100.00}),
 ("4 ПСП базова", {"ua_main_job": True, "ua_psp": "base"}, 4500, {}, {"PDFO": -510.48, "VZ": -225.00, "NET": 3764.52, "ESV": 1902.34}),
 ("5 Інвалідність", {"ua_main_job": True, "ua_esv_category": "disabled"}, 20000, {}, {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 1682.00}),
 ("6 Відпустка 14 к.д. (3-16 серпня)", {"ua_main_job": True, "history": 30000, "leaves": [("VAC", "2026-08-03", "2026-08-16")]}, 30000, {},
  {"BASIC": 15714.29, "VAC": 13808.22, "GROSS": 29522.51, "PDFO": -5314.05, "VZ": -1476.13, "NET": 22732.33, "ESV": 6494.95}),
 ("7 Лікарняний 10 к.д. (10-19 серпня), стаж 6 років", {"ua_main_job": True, "history": 30000, "years": 6, "leaves": [("SICK", "2026-08-10", "2026-08-19")],
   "moves": {("Дт", "92"): 27628.10, ("Дт", "378"): 3452.05, ("Кт", "661"): 25475.53, ("Кт", "6411"): 4585.60, ("Кт", "6415"): 1273.78, ("Кт", "651"): 5604.62}}, 30000, {},
  {"BASIC": 18571.43, "SICK_EMP": 3452.05, "SICK_PFU": 3452.05, "GROSS": 25475.53, "PDFO": -4585.60, "VZ": -1273.78, "NET": 19616.15, "ESV": 5604.62}),
 ("8 Звільнення 31 серпня, 10 днів компенсації", {"ua_main_job": True, "history": 30000}, 30000, {"COMP_DAYS": 10},
  {"BASIC": 30000.00, "COMP_VAC": 9863.01, "GROSS": 39863.01, "PDFO": -7175.34, "VZ": -1993.15, "NET": 30694.52, "ESV": 8769.86}),
 ("9 ЦПХ", {"ua_contract_kind": "gph", "ua_main_job": False}, 0, {"GPH": 20000}, {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 4400.00}),
 ("10 Аліменти + макс. база", {"ua_main_job": True}, 200000, {"ALIM_PCT": 25}, {"PDFO": -36000.00, "VZ": -10000.00, "ALIM": -38500.00, "NET": 115500.00, "ESV": 38046.80}),
]
ok = True
for name, efields, wage, inputs, expect in S:
    moves = efields.pop("moves", None)
    ename = f"Еталон {name}"
    start = efields.pop("start", "2026-01-01"); history = efields.pop("history", None); leaves = efields.pop("leaves", []); years = efields.pop("years", 0)
    efields["ua_insurance_years"] = years
    eid = call("hr.employee", "search", [["name", "=", ename]])
    if eid:
        old = call("hr.payslip", "search", [["employee_id", "in", eid]])
        if old:
            # прибрати проводки підтверджених листків, потім листки (OCA не скасовує done; це тільки для тестового стенда)
            for sl in call("hr.payslip", "read", old, ["move_id"]):
                if sl["move_id"]:
                    call("hr.payslip", "write", [sl["id"]], {"move_id": False})
                    call("account.move", "button_draft", [sl["move_id"][0]])
                    call("account.move", "unlink", [sl["move_id"][0]])
            call("hr.payslip", "write", old, {"state": "cancel"})
            call("hr.payslip", "unlink", old)
        eid = eid[0]
        call("hr.employee", "write", [eid], {"ua_main_job": True, "ua_psp": "none", "ua_esv_category": "standard", "ua_contract_kind": "employment", **efields})
    else:
        eid = call("hr.employee", "create", {"name": ename, **efields})
    ver = call("hr.employee", "read", [eid], ["version_id"])[0]["version_id"][0]
    call("hr.version", "write", [ver], {"wage": wage, "contract_date_start": start, "struct_id": STRUCT, "resource_calendar_id": CAL})
    # історія заробітку за 12 місяців (серпень 2025 - липень 2026)
    old_h = call("ua.earnings.history", "search", [["employee_id", "=", eid]])
    if old_h:
        call("ua.earnings.history", "unlink", old_h)
    if history:
        for k in range(12):
            y, mo = (2025, 8 + k) if 8 + k <= 12 else (2026, 8 + k - 12)
            call("ua.earnings.history", "create", {"employee_id": eid, "month": f"{y}-{mo:02d}-01", "gross": history})
    # відпустки і лікарняні: створити і затвердити, якщо ще немає
    for code, d1, d2 in leaves:
        lt = call("hr.leave.type", "search", [["work_entry_type_id.code", "=", code]])[0]
        if not call("hr.leave", "search", [["employee_id", "=", eid], ["holiday_status_id", "=", lt], ["request_date_from", "=", d1], ["state", "=", "validate"]]):
            lid = call("hr.leave", "create", {"employee_id": eid, "holiday_status_id": lt, "request_date_from": d1, "request_date_to": d2})
            call("hr.leave", "action_approve", [lid])
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
    call("hr.payslip", "action_payslip_done", [slip])   # підтвердити: проводка створюється тут
    if moves:
        mid = call("hr.payslip", "read", [slip], ["move_id"])[0]["move_id"]
        ml = call("account.move.line", "search_read", [["move_id", "=", mid[0]]], fields=["account_id", "debit", "credit"]) if mid else []
        acc_ids = list({l["account_id"][0] for l in ml})
        codes = {a["id"]: a["code"] for a in call("account.account", "read", acc_ids, ["code"], context={"allowed_company_ids": [1]})} if acc_ids else {}
        got = defaultdict(float)
        for l in ml:
            code = codes.get(l["account_id"][0], "")
            for (side, exp_code) in moves:            # порівняння за префіксом: 92 == 920000
                if code.startswith(exp_code) and (len(code) == len(exp_code) or code[len(exp_code):].strip("0") == ""):
                    got[(side, exp_code)] += l["debit"] if side == "Дт" else l["credit"]
        mres = []
        for (side, code), exp in moves.items():
            g = round(got.get((side, code), 0.0), 2); good = abs(g - exp) < 0.005; ok &= good
            mres.append(f"{side}{code} {g} {'==' if good else '!='} {exp}")
        bal = round(sum(l["debit"] for l in ml) - sum(l["credit"] for l in ml), 2); ok &= (bal == 0)
        print(("  PASS " if all("==" in r for r in mres) and bal == 0 else "  FAIL ") + f"проводка {mid[1] if mid else 'немає'} | " + "; ".join(mres) + f" | баланс {bal}")
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
