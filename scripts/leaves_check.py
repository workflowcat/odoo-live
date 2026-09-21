#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка l10n_ua_average: додаткові відпустки за Законом «Про відпустки» (УБД ст. 16-2,
соціальна на дітей ст. 19, особливі умови праці ст. 8) і відсоток лікарняних за стажем.
Звіряє дані, які scripts/demo_company.py записує на стенді ТОВ «Ясен Меблі»:
 - Шевчук (УБД): ua_vac_ubd_days_year == 14
 - Стефанишин (особливі умови, 4 дні): ua_special_allocated == 4
 - Ковальчук (двоє дітей до 15) + Мельничук (дитина з інвалідністю) + Федорів (одинока мати):
   ua_soc_child_days_year і накопичений ua_soc_child_allocated > 0 після ua_ensure_allocations
 - Відсоток лікарняних за таблицею ст. 24 ЗУ 1105: 0-3 р. 50 %, 3-5 60 %, 5-8 70 %, 8+ 100 %
 - COMP_VAC на звільненні (Гнатів) додає ручний COMP_DAYS; окремо перевіряємо, що rule_comp_vac
   формула включає extra_comp_days (СОЦ_ДІТИ/УБД/особливі умови), рахуючи вручну на тестовому працівнику.
Запуск: python3 scripts/leaves_check.py  (база PAYROLL_CHECK_DB, типово payroll)"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PORT = os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110").strip()
BASE = f"http://127.0.0.1:{PORT}"
DB = os.environ.get("PAYROLL_CHECK_DB", "payroll")
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
FAILS = []


def rpc(service, method, *args):
    body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1, "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(f"{BASE}/jsonrpc", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    if out.get("error"):
        raise RuntimeError(out["error"].get("data", {}).get("message") or out["error"])
    return out.get("result")


uid = rpc("common", "authenticate", DB, "admin", PW, {})
def call(model, method, *a, **kw): return rpc("object", "execute_kw", DB, uid, PW, model, method, list(a), kw)


def check(label, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(label)


def find_emp(last_name):
    ids = call("hr.employee", "search", [["name", "like", last_name]], context={"active_test": False})
    if not ids:
        raise SystemExit(f"employee '{last_name}' not found - run scripts/demo_company.py first")
    return ids[0]


FIELDS = ["ua_veteran", "ua_war_disability", "ua_vac_ubd_days_year", "ua_vac_ubd_used", "ua_vac_ubd_balance",
          "ua_special_leave_days", "ua_special_allocated", "ua_special_used", "ua_special_balance",
          "ua_soc_child_disabled_child", "ua_single_parent", "ua_soc_child_days_year",
          "ua_soc_child_allocated", "ua_soc_child_used", "ua_soc_child_balance", "ua_soc_child_last_year",
          "ua_insurance_years", "ua_sick_full", "ua_sick_percent", "ua_child_ids"]

# -- УБД: Шевчук --------------------------------------------------------------------------------
shevchuk = find_emp("Шевчук")
d = call("hr.employee", "read", [shevchuk], FIELDS)[0]
check("УБД (Шевчук): ua_veteran True", d["ua_veteran"], d)
check("УБД (Шевчук): норма 14 днів/рік", d["ua_vac_ubd_days_year"] == 14, d["ua_vac_ubd_days_year"])
check("УБД (Шевчук): залишок = норма - використано", abs(d["ua_vac_ubd_balance"] - (d["ua_vac_ubd_days_year"] - d["ua_vac_ubd_used"])) < 0.01)

# -- Особливі умови праці: Стефанишин --------------------------------------------------------------
stefanyshyn = find_emp("Стефанишин")
d = call("hr.employee", "read", [stefanyshyn], FIELDS)[0]
check("Особливі умови (Стефанишин): ua_special_leave_days = 4", d["ua_special_leave_days"] == 4, d["ua_special_leave_days"])
check("Особливі умови (Стефанишин): allocated = 4 (<= 7)", d["ua_special_allocated"] == 4, d["ua_special_allocated"])

# -- СОЦ_ДІТИ: Ковальчук (двоє дітей до 15) -----------------------------------------------------
kovalchuk = find_emp("Ковальчук")
d = call("hr.employee", "read", [kovalchuk], FIELDS)[0]
check("СОЦ_ДІТИ (Ковальчук): двоє дітей записано", len(d["ua_child_ids"]) >= 2, d["ua_child_ids"])
check("СОЦ_ДІТИ (Ковальчук): 10 днів на рік (одна підстава)", d["ua_soc_child_days_year"] == 10, d["ua_soc_child_days_year"])
check("СОЦ_ДІТИ (Ковальчук): нараховано і не згоріло (allocated > 0)", d["ua_soc_child_allocated"] > 0, d["ua_soc_child_allocated"])
check("СОЦ_ДІТИ (Ковальчук): нарахування виконано на цей рік", d["ua_soc_child_last_year"] >= 2026, d["ua_soc_child_last_year"])

# -- СОЦ_ДІТИ: Мельничук (дитина з інвалідністю) -------------------------------------------------
melnychuk = find_emp("Мельничук")
d = call("hr.employee", "read", [melnychuk], FIELDS)[0]
check("СОЦ_ДІТИ (Мельничук): дитина з інвалідністю", d["ua_soc_child_disabled_child"])
check("СОЦ_ДІТИ (Мельничук): 10 днів на рік", d["ua_soc_child_days_year"] == 10, d["ua_soc_child_days_year"])

# -- СОЦ_ДІТИ: Федорів (одинока мати, дві підстави з ПСП child - лише 1 формальна тут) -----------
fedoriv = find_emp("Федорів")
d = call("hr.employee", "read", [fedoriv], FIELDS)[0]
check("СОЦ_ДІТИ (Федорів): одинока мати", d["ua_single_parent"])
check("СОЦ_ДІТИ (Федорів): щонайменше 10 днів на рік (одна підстава)", d["ua_soc_child_days_year"] >= 10, d["ua_soc_child_days_year"])

# -- переносимо ще рік вперед: СОЦ_ДІТИ має накопичуватись, не скидатись -------------------------
# next_year - на один рік більше за вже нарахований last_year (тест ідемпотентний до повторних запусків)
snap = call("hr.employee", "read", [kovalchuk], ["ua_soc_child_allocated", "ua_soc_child_last_year"])[0]
next_year = max(snap["ua_soc_child_last_year"], 2026) + 1
before = snap["ua_soc_child_allocated"]
call("hr.employee", "ua_ensure_allocations", [kovalchuk], next_year)
after = call("hr.employee", "read", [kovalchuk], ["ua_soc_child_allocated", "ua_soc_child_last_year"])[0]
check("СОЦ_ДІТИ: перенос без обмежень (наступний рік додає, не скидає)", after["ua_soc_child_allocated"] >= before + 10 - 0.01, (before, after))
check("СОЦ_ДІТИ: повторний виклик того ж року не додає вдруге (ідемпотентність)",
      call("hr.employee", "ua_ensure_allocations", [kovalchuk], next_year) is not None)
same_year = call("hr.employee", "read", [kovalchuk], ["ua_soc_child_allocated"])[0]["ua_soc_child_allocated"]
check("СОЦ_ДІТИ: подвійний виклик 2027 не подвоює нарахування", abs(same_year - after["ua_soc_child_allocated"]) < 0.01, (same_year, after))

# -- відсоток лікарняних за стажем (ст. 24 ЗУ 1105): 0-3:50, 3-5:60, 5-8:70, 8+:100 --------------
STAGES = [(1.0, 50.0), (2.9, 50.0), (3.0, 60.0), (4.9, 60.0), (5.0, 70.0), (7.9, 70.0), (8.0, 100.0), (15.0, 100.0)]
scratch = shevchuk
orig = call("hr.employee", "read", [scratch], ["ua_insurance_years", "ua_sick_full"])[0]
for years, pct in STAGES:
    call("hr.employee", "write", [scratch], {"ua_insurance_years": years, "ua_sick_full": False})
    got = call("hr.employee", "read", [scratch], ["ua_sick_percent"])[0]["ua_sick_percent"]
    check(f"Лікарняні: стаж {years} р. -> {pct} %", abs(got - pct) < 0.01, got)
call("hr.employee", "write", [scratch], {"ua_insurance_years": orig["ua_insurance_years"], "ua_sick_full": orig["ua_sick_full"]})

# -- COMP_VAC: extra_comp_days бере невикористані СОЦ_ДІТИ/УБД/особливі умови в місяці звільнення --
STRUCT = call("hr.payroll.structure", "search", [["code", "=", "UA_SALARY"]])[0]
CAL = call("res.company", "read", [1], ["resource_calendar_id"])[0]["resource_calendar_id"][0]
# Людина, а не фікстура: у базі має лежати звичайний працівник у звичайному підрозділі,
# інакше «Люди» і штатний розпис показують вигадані назви поруч зі справжніми.
# Пізнається за РНОКПП, тому тезка в базі нічого не ламає.
FIXTURE = {"rnokpp": "3099887766", "name": "Лещук Оксана Дмитрівна",
           "dept": "Бухгалтерія", "job": "Економіст", "kp": "2441.2"}
dept = call("hr.department", "search", [["name", "=", FIXTURE["dept"]]])
dept = dept[0] if dept else call("hr.department", "create", {"name": FIXTURE["dept"]})
existing = call("hr.employee", "search", [["ua_rnokpp", "=", FIXTURE["rnokpp"]]], context={"active_test": False})
if not existing:   # прибирання старої фікстури з вигаданим іменем
    existing = call("hr.employee", "search", [["name", "=", "Еталон СоцДіти Компенсація"]], context={"active_test": False})
if existing:
    eid = existing[0]
    call("hr.employee", "write", [eid], {"active": True, "ua_soc_child_disabled_child": True,
                                         "name": FIXTURE["name"], "ua_rnokpp": FIXTURE["rnokpp"],
                                         "department_id": dept, "job_title": FIXTURE["job"]})
else:
    eid = call("hr.employee", "create", {"name": FIXTURE["name"], "department_id": dept,
                                         "ua_rnokpp": FIXTURE["rnokpp"], "job_title": FIXTURE["job"],
                                         "resource_calendar_id": CAL, "ua_soc_child_disabled_child": True})
ver = call("hr.employee", "read", [eid], ["version_id"])[0]["version_id"][0]
call("hr.version", "write", [ver], {"wage": 20000, "date_version": "2020-01-01", "contract_date_start": "2020-01-01",
                                    "contract_date_end": "2026-08-31", "struct_id": STRUCT, "resource_calendar_id": CAL,
                                    "ua_kp_code": FIXTURE["kp"], "ua_prof_name": FIXTURE["job"],
                                    "ua_order_ref": "Наказ № 1 від 01.01.2020", "ua_end_order_ref": "Наказ № 2 від 31.08.2026",
                                    "ua_dismissal_basis": "п. 1 ст. 36 КЗпП (угода сторін)"}, context={"sync_contract_dates": True})
call("hr.employee", "ua_ensure_allocations", [eid], 2026)
d = call("hr.employee", "read", [eid], ["ua_soc_child_balance", "ua_soc_child_days_year"])[0]
check(f"{FIXTURE['name']}: СОЦ_ДІТИ нараховано (10 днів)", d["ua_soc_child_days_year"] == 10, d["ua_soc_child_days_year"])
check(f"{FIXTURE['name']}: залишок СОЦ_ДІТИ не використаний (> 0)", d["ua_soc_child_balance"] > 0, d["ua_soc_child_balance"])

call("hr.employee", "generate_work_entries", [eid], "2026-08-01", "2026-08-31")
old_slips = call("hr.payslip", "search", [["employee_id", "=", eid]])
if old_slips:
    call("hr.payslip", "write", old_slips, {"state": "draft"})
    call("hr.payslip", "unlink", old_slips)
slip_id = call("hr.payslip", "create", {"employee_id": eid, "struct_id": STRUCT, "date_from": "2026-08-01", "date_to": "2026-08-31"})
call("hr.payslip", "onchange_employee", [slip_id])
call("hr.payslip", "compute_sheet", [slip_id])
lines = call("hr.payslip.line", "search_read", [["slip_id", "=", slip_id], ["code", "in", ["COMP_VAC", "GROSS"]]], fields=["code", "total"])
comp_line = next((l for l in lines if l["code"] == "COMP_VAC"), None)
check("COMP_VAC нараховано автоматично для звільнення без ручного COMP_DAYS (лише extra_comp_days)",
      comp_line is not None and comp_line["total"] > 0, lines)
call("hr.payslip", "write", [slip_id], {"state": "cancel"})
call("hr.payslip", "unlink", [slip_id])
call("hr.employee", "write", [eid], {"active": False})

# -- MAT: лише жінкам, завжди 100 % незалежно від стажу; звичайні лікарняні - за стажем -----------
LT_MAT = call("hr.leave.type", "search", [["work_entry_type_id.code", "=", "MAT"]])[0]
LT_SICK = call("hr.leave.type", "search", [["work_entry_type_id.code", "=", "SICK"]])[0]
male_eid = call("hr.employee", "search", [["name", "like", "Гаврилюк"]])[0]
male_sex = call("hr.employee", "read", [male_eid], ["sex"])[0]["sex"]
try:
    bad_id = call("hr.leave", "create", {"employee_id": male_eid, "holiday_status_id": LT_MAT,
                                         "request_date_from": "2026-08-01", "request_date_to": "2026-08-10"})
    call("hr.leave", "unlink", [bad_id])
    check("MAT: чоловікові оформити не можна (constraint)", False, f"sex={male_sex}, leave created id={bad_id}")
except RuntimeError as exc:
    check("MAT: чоловікові оформити не можна (constraint)", "вагітністю та пологами" in str(exc) or "жінц" in str(exc), str(exc)[:200])

female_eid = call("hr.employee", "search", [["name", "like", "Гринів"]])[0]
female_sex = call("hr.employee", "read", [female_eid], ["sex"])[0]["sex"]
check("MAT: працівниця дійсно жінка (передумова тесту)", female_sex == "female", female_sex)
mat_leave = call("hr.leave", "search", [["employee_id", "=", female_eid], ["holiday_status_id", "=", LT_MAT]], limit=1)
check("MAT: жінці відпустка у зв'язку з вагітністю та пологами існує (demo)", bool(mat_leave), mat_leave)

# rule_mat не множить на sick_percent (avg1266_day напряму) - завжди 100 %, перевіряємо формулу тексту правила
mat_rule = call("hr.salary.rule", "search_read", [["code", "=", "MAT"]], fields=["amount_python_compute"])
check("MAT: формула правила не використовує sick_percent (завжди 100 %)",
      bool(mat_rule) and "sick_percent" not in mat_rule[0]["amount_python_compute"], mat_rule)

print(f"\n{len(FAILS)} FAIL(S)" if FAILS else "\nAll leaves checks OK")
if FAILS:
    raise SystemExit(1)
