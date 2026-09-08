"""Друкує markdown-таблицю працівників і сум за серпень 2026 зі стенду (для docs/payroll/review-guide.md)."""
import json, urllib.request
ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
URL = "http://127.0.0.1:8110/jsonrpc"; DB = "payroll"; PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(), {"Content-Type": "application/json"}))
    return json.loads(r.read()).get("result")
uid = rpc("common", "login", DB, "admin", PW)
call = lambda m, f, *a, **k: rpc("object", "execute_kw", DB, uid, PW, m, f, list(a), k)
run = call("hr.payslip.run", "search_read", [["name", "=", "Зарплата за серпень 2026"]], fields=["slip_ids"])[0]
f = lambda x: f"{x:,.2f}".replace(",", " ").replace(".", ",")
print("| № | Працівник | Посада | Особливість | Оклад | Нараховано | ПДФО | ВЗ | Інше | Аванс | До виплати | ЄСВ |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
slips = call("hr.payslip", "search_read", [["id", "in", run["slip_ids"]]], fields=["employee_id", "contract_id", "line_ids"])
rows = []
for s in slips:
    emp = call("hr.employee", "read", [s["employee_id"][0]], ["name", "job_title", "ua_fte", "ua_psp", "ua_esv_category", "ua_contract_kind", "ua_main_job", "wage", "contract_date_start", "contract_date_end"])[0]
    L = {l["code"]: l["total"] for l in call("hr.payslip.line", "search_read", [["slip_id", "=", s["id"]]], fields=["code", "total"])}
    wd = {w["code"]: w["number_of_days"] for w in call("hr.payslip.worked_days", "search_read", [["payslip_id", "=", s["id"]]], fields=["code", "number_of_days"])}
    notes = []
    if emp["ua_contract_kind"] == "gph": notes.append("ЦПХ")
    if emp["ua_contract_kind"] == "fop": notes.append("ФОП-підрядник, ознака 157")
    if wd.get("MAT"): notes.append("декрет з 10.08, допомога ПФУ %s" % f(L.get("MAT", 0)))
    if emp["ua_fte"] != "1": notes.append(f"{emp['ua_fte'].replace('.', ',')} ставки")
    if not emp["ua_main_job"] and emp["ua_contract_kind"] == "employment": notes.append("сумісник")
    if emp["ua_psp"] == "base": notes.append("ПСП")
    if emp["ua_psp"] == "child": notes.append("ПСП на дітей")
    if emp["ua_esv_category"] == "disabled": notes.append("ЄСВ 8,41 %")
    if wd.get("VAC"): notes.append("відпустка 14 к.д.")
    if wd.get("SICK"): notes.append("лікарняний 10 к.д.")
    if wd.get("UNPAID"): notes.append("без збереження 5 дн.")
    if L.get("ALIM"): notes.append("аліменти 25 %")
    if L.get("COMP_VAC"): notes.append("звільнення 31.08, компенсація 12 дн.")
    if L.get("BONUS"): notes.append("премія")
    if emp["contract_date_start"] and emp["contract_date_start"] >= "2026-08-01": notes.append("прийнято " + ".".join(reversed(emp["contract_date_start"][5:].split("-"))))
    if L.get("ESV", 0) >= 38046.8: notes.append("макс. база ЄСВ")
    other = -(L.get("ALIM", 0))
    L["NET"] = L.get("NET", 0)
    rows.append((emp["name"], emp["job_title"], "; ".join(notes) or "-", emp["wage"], L.get("GROSS", 0), -L.get("PDFO", 0), -L.get("VZ", 0), other, -L.get("ADV_PAID", 0), L.get("NET", 0), L.get("ESV", 0)))
rows.sort(key=lambda r: r[0])
for i, r in enumerate(rows, 1):
    print(f"| {i} | {r[0]} | {r[1]} | {r[2]} | {f(r[3])} | {f(r[4])} | {f(r[5])} | {f(r[6])} | {f(r[7]) if r[7] else ''} | {f(r[8]) if r[8] else ''} | {f(r[9])} | {f(r[10])} |")
tot = [sum(r[k] for r in rows) for k in range(4, 11)]
print(f"| | Разом | | | | {f(tot[0])} | {f(tot[1])} | {f(tot[2])} | {f(tot[3])} | {f(tot[4])} | {f(tot[5])} | {f(tot[6])} |")
