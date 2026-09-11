#!/usr/bin/env python3
"""Еталонні сценарії: створює працівників, рахує листки за серпень 2026 і звіряє з docs/payroll/golden-scenarios.md.
Запуск: python3 scripts/payroll_check.py  (читає .env: ODOO_PORT, ODOO_ADMIN_USER_PASSWORD; база PAYROLL_CHECK_DB, типово payroll_test)
Прибрати еталонних працівників зі стенду: python3 scripts/payroll_check.py --purge  (база з PAYROLL_CHECK_DB або payroll)"""
import os, sys, json, urllib.request
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PURGE = "--purge" in sys.argv
URL = f"http://127.0.0.1:{ENV.get('ODOO_PORT', '8110')}"; DB = os.environ.get("PAYROLL_CHECK_DB", "payroll" if PURGE else "payroll_test"); PW = ENV["ODOO_ADMIN_USER_PASSWORD"]
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
if PURGE:
    emps = call("hr.employee", "search", [["name", "like", "Еталон %"], ["active", "in", [True, False]]])
    slips = call("hr.payslip", "search_read", [["employee_id", "in", emps]], fields=["id", "state", "move_id"])
    for sl in slips:
        if sl["state"] == "done" and sl["move_id"]:
            call("account.move", "button_draft", [sl["move_id"][0]]); call("account.move", "unlink", [sl["move_id"][0]])
        if sl["state"] != "cancel":
            call("hr.payslip", "write", [sl["id"]], {"state": "cancel"})
    if slips:
        call("hr.payslip", "unlink", [sl["id"] for sl in slips])
    for run in call("hr.payslip.run", "search", [["name", "like", "Еталонні сценарії%"]]):
        call("hr.payslip.run", "unlink", [run])
    for h in call("ua.earnings.history", "search", [["employee_id", "in", emps]]):
        call("ua.earnings.history", "unlink", [h])
    leaves = call("hr.leave", "search", [["employee_id", "in", emps]])
    if leaves:
        call("hr.leave", "action_refuse", leaves); call("hr.leave", "unlink", leaves)
    we = call("hr.work.entry", "search", [["employee_id", "in", emps]], context={"active_test": False})
    if we:
        call("hr.work.entry", "write", we, {"state": "draft"}); call("hr.work.entry", "unlink", we)
    if emps:
        try:
            call("hr.employee", "unlink", emps)
        except RuntimeError as e:
            call("hr.employee", "write", emps, {"active": False}); print("archived instead of deleted:", str(e)[:120])
    for d in call("hr.department", "search", [["name", "=", "Еталонні сценарії (тест)"]]):
        call("hr.department", "unlink", [d])
    print(f"purged {len(emps)} employees, {len(slips)} payslips from {DB}")
    sys.exit(0)
if "ua_sti_code" in call("res.company", "fields_get", [], attributes=["type"]) and call("res.company", "read", [1], ["company_registry"])[0]["company_registry"] in (False, "", "12345678"):
    call("res.company", "write", [1], {"company_registry": "12345678", "ua_sti_code": "2655", "ua_sti_name": "ГУ ДПС у м. Києві, ДПІ у Печерському районі (тест)",
         "ua_reg": "26", "ua_raj": "55", "ua_katottg": "UA80000000000093317", "ua_kved": "62.01", "street": "вул. Тестова, 1", "zip": "01001", "city": "Київ",
         "ua_director_name": "Тестовий Керівник", "ua_director_rnokpp": "1234567890", "ua_accountant_name": "Тестовий Бухгалтер", "ua_accountant_rnokpp": "1234567891"})
CAL = call("res.company", "read", [1], ["resource_calendar_id"])[0]["resource_calendar_id"][0]
EMP_FIELDS = call("hr.employee", "fields_get", [], attributes=["type"])
PERIOD = ("2026-08-01", "2026-08-31")
# сценарії: назва, поля працівника, оклад, входи, очікувані рядки; "start" - дата прийняття; "moves" - очікувані обороти проводки
# додаткові ключі: "history" (12 місяців окладу для середньої), "leaves" [(тип, від, до)], "years" (страховий стаж)
S = [
 ("1 Повний місяць, оклад", {"ua_main_job": True, "moves": {("Дт", "92"): 40113.60, ("Кт", "661"): 30000.00, ("Дт", "661"): 6900.00, ("Кт", "6411"): 5400.00, ("Кт", "6415"): 1500.00, ("Кт", "651"): 6600.00, ("Кт", "471"): 3513.60}}, 30000, {}, {"PDFO": -5400.00, "VZ": -1500.00, "NET": 23100.00, "ESV": 6600.00}),
 ("2 Неповний місяць (з 17-го, 11 з 21 днів)", {"ua_main_job": True, "start": "2026-08-17"}, 30000, {}, {"BASIC": 15714.29, "PDFO": -2828.57, "VZ": -785.71, "NET": 12100.01, "ESV": 3457.14}),
 ("3 Сумісник (0,5 ставки, оклад 10 000)", {"ua_main_job": False, "ua_fte": "0.5"}, 10000, {}, {"BASIC": 5000.00, "PDFO": -900.00, "VZ": -250.00, "NET": 3850.00, "ESV": 1100.00}),
 ("4 ПСП базова (0,5 ставки, оклад 9 000)", {"ua_main_job": True, "ua_psp": "base", "ua_fte": "0.5"}, 9000, {}, {"BASIC": 4500.00, "PDFO": -510.48, "VZ": -225.00, "NET": 3764.52, "ESV": 1902.34}),
 ("5 Інвалідність", {"ua_main_job": True, "ua_esv_category": "disabled"}, 20000, {}, {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 1682.00}),
 ("6 Відпустка 14 к.д. (3-16 серпня)", {"ua_main_job": True, "history": 30000, "leaves": [("VAC", "2026-08-03", "2026-08-16")]}, 30000, {},
  {"BASIC": 15714.29, "VAC": 13808.22, "GROSS": 29522.51, "PDFO": -5314.05, "VZ": -1476.13, "NET": 22732.33, "ESV": 6494.95}),
 ("7 Лікарняний 10 к.д. (10-19 серпня), стаж 6 років", {"ua_main_job": True, "history": 30000, "years": 6, "leaves": [("SICK", "2026-08-10", "2026-08-19")],
   "moves": {("Дт", "92"): 29803.19, ("Дт", "378"): 3452.05, ("Кт", "661"): 25475.53, ("Кт", "6411"): 4585.60, ("Кт", "6415"): 1273.78, ("Кт", "651"): 5604.62, ("Кт", "471"): 2175.09}}, 30000, {},
  {"BASIC": 18571.43, "SICK_EMP": 3452.05, "SICK_PFU": 3452.05, "GROSS": 25475.53, "PDFO": -4585.60, "VZ": -1273.78, "NET": 19616.15, "ESV": 5604.62}),
 ("8 Звільнення 31 серпня, 10 днів компенсації", {"ua_main_job": True, "history": 30000, "end": "2026-08-31"}, 30000, {"COMP_DAYS": 10},
  {"BASIC": 30000.00, "COMP_VAC": 9863.01, "GROSS": 39863.01, "PDFO": -7175.34, "VZ": -1993.15, "NET": 30694.52, "ESV": 8769.86}),
 ("11 Повторне прийняття 17 серпня після звільнення 31 травня", {"ua_main_job": True, "rehire": True}, 30000, {},
  {"BASIC": 15714.29, "PDFO": -2828.57, "VZ": -785.71, "NET": 12100.01, "ESV": 3457.14}),
 ("12 Половина ставки (0,5), оклад 20 000", {"ua_main_job": True, "ua_fte": "0.5"}, 20000, {},
  {"BASIC": 10000.00, "PDFO": -1800.00, "VZ": -500.00, "NET": 7700.00, "ESV": 2200.00}),
 ("13 Аванс 50 % 20-го, остаточний розрахунок", {"ua_main_job": True, "moves": {("Дт", "92"): 40113.60, ("Кт", "661"): 30000.00, ("Дт", "661"): 6900.00, ("Кт", "6411"): 5400.00, ("Кт", "6415"): 1500.00, ("Кт", "651"): 6600.00, ("Кт", "471"): 3513.60}}, 30000, {"ADVANCE": 15000},
  {"GROSS": 30000.00, "PDFO": -5400.00, "VZ": -1500.00, "ADV_PAID": -15000.00, "NET": 8100.00, "ESV": 6600.00}),
 ("14 ФОП-підрядник (ознака 157)", {"ua_contract_kind": "fop", "ua_main_job": False}, 0, {"FOP_PAY": 40000}, {"GROSS": 40000.00, "PDFO": 0.0, "VZ": 0.0, "NET": 40000.00, "ESV": 0.0}),
 ("15 Декретна відпустка 126 к.д. з 10 серпня", {"ua_main_job": True, "history": 30000, "leaves": [("MAT", "2026-08-10", "2026-12-13")]}, 30000, {},
  {"BASIC": 7142.86, "MAT": 124273.97, "GROSS": 7142.86, "PDFO": -1285.71, "VZ": -357.14, "NET": 129773.98, "ESV": 28911.70}),
 ("16 Індексація 500", {"ua_main_job": True}, 30000, {"INDEX": 500}, {"INDEX": 500.00, "GROSS": 30500.00, "PDFO": -5490.00, "VZ": -1525.00, "NET": 23485.00, "ESV": 6710.00}),
 ("17 Індексація автоматично (базовий місяць липень, індекс серпня 101,0)", {"ua_main_job": True, "index_base": "2026-07-01"}, 30000, {},
  {"INDEX": 33.28, "GROSS": 30033.28, "PDFO": -5405.99, "VZ": -1501.66, "NET": 23125.63, "ESV": 6607.32}),
 ("18 Навчальна відпустка 10 к.д. (3-12 серпня)", {"ua_main_job": True, "history": 30000, "leaves": [("STUDY", "2026-08-03", "2026-08-12")],
   "moves": {("Дт", "92"): 36865.11, ("Кт", "661"): 28434.44, ("Дт", "661"): 6539.92, ("Кт", "6411"): 5118.20, ("Кт", "6415"): 1421.72, ("Кт", "651"): 6255.58, ("Кт", "471"): 2175.09}}, 30000, {},
  {"BASIC": 18571.43, "STUDY_PAY": 9863.01, "GROSS": 28434.44, "PDFO": -5118.20, "VZ": -1421.72, "NET": 21894.52, "ESV": 6255.58}),
 ("19 Відрядження 5 робочих днів (3-7 серпня) з добовими", {"ua_main_job": True, "history": 30000, "leaves": [("TRIP", "2026-08-03", "2026-08-07")],
   "moves": {("Дт", "92"): 40777.03, ("Кт", "661"): 31500.00, ("Дт", "661"): 6900.00, ("Кт", "6411"): 5400.00, ("Кт", "6415"): 1500.00, ("Кт", "651"): 6600.00, ("Кт", "471"): 2677.03}}, 30000, {"DAILY": 1500},
  {"BASIC": 22857.14, "TRIP_PAY": 7142.86, "DAILY": 1500.00, "GROSS": 30000.00, "PDFO": -5400.00, "VZ": -1500.00, "NET": 24600.00, "ESV": 6600.00}),
 ("20 Догляд за хворою дитиною 7 к.д. (10-16 серпня), стаж 6 років", {"ua_main_job": True, "history": 30000, "years": 6, "leaves": [("SICK_CARE", "2026-08-10", "2026-08-16")]}, 30000, {},
  {"BASIC": 22857.14, "SICK_CARE_PAY": 4832.88, "GROSS": 27690.02, "PDFO": -4984.20, "VZ": -1384.50, "NET": 21321.32, "ESV": 6091.80}),
 ("21 Доплата до мінімальної зарплати (оклад 8 000, повний місяць)", {"ua_main_job": True,
   "moves": {("Дт", "92"): 11562.07, ("Кт", "661"): 8647.00, ("Дт", "661"): 1988.81, ("Кт", "6411"): 1556.46, ("Кт", "6415"): 432.35, ("Кт", "651"): 1902.34, ("Кт", "471"): 1012.73}}, 8000, {},
  {"BASIC": 8000.00, "MINSAL": 647.00, "GROSS": 8647.00, "PDFO": -1556.46, "VZ": -432.35, "NET": 6658.19, "ESV": 1902.34}),
 ("22 Доплати до мінімальної немає: оклад вищий", {"ua_main_job": True}, 12000, {},
  {"BASIC": 12000.00, "GROSS": 12000.00, "PDFO": -2160.00, "VZ": -600.00, "NET": 9240.00, "ESV": 2640.00}),
 ("23 Матеріальна допомога 6 000 (межа 4 660 на рік)", {"ua_main_job": True}, 30000, {"AID": 6000},
  {"BASIC": 30000.00, "AID_FREE": 4660.00, "AID_TAX": 1340.00, "GROSS": 30000.00, "PDFO": -5641.20, "VZ": -1567.00, "NET": 28791.80, "ESV": 6600.00}),
 ("24 Подарунок 3 000 (межа 25 % МЗП = 2 161,75)", {"ua_main_job": True}, 20000, {"GIFT": 3000},
  {"BASIC": 20000.00, "GIFT_FREE": 2161.75, "GIFT_TAX": 838.25, "GROSS": 20000.00, "PDFO": -3750.89, "VZ": -1041.91, "NET": 18207.20, "ESV": 4400.00}),
 ("25 Вихідна допомога 30 000 і виконавчий документ 20 %", {"ua_main_job": True}, 30000, {"SEVERANCE": 30000, "EXEC_PCT": 20},
  {"BASIC": 30000.00, "SEVERANCE": 30000.00, "GROSS": 30000.00, "PDFO": -10800.00, "VZ": -3000.00, "EXEC_DOC": -9240.00, "NET": 36960.00, "ESV": 6600.00}),
 ("26 Профспілковий внесок 1 % і відшкодування шкоди 500", {"ua_main_job": True}, 25000, {"UNION_PCT": 1, "DAMAGE_AMT": 500},
  {"BASIC": 25000.00, "GROSS": 25000.00, "PDFO": -4500.00, "VZ": -1250.00, "UNION": -250.00, "DAMAGE": -500.00, "NET": 18500.00, "ESV": 5500.00}),
 ("9 ЦПХ", {"ua_contract_kind": "gph", "ua_main_job": False}, 0, {"GPH": 20000}, {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 4400.00}),
 ("10 Аліменти + макс. база", {"ua_main_job": True}, 200000, {"ALIM_PCT": 25}, {"PDFO": -36000.00, "VZ": -10000.00, "ALIM": -38500.00, "NET": 115500.00, "ESV": 38046.80}),
]
ok = True
USED_CODES = set()
# Ці коди навмисно не проводяться: підсумки листка і аванс, який уже проведений при виплаті.
NO_MOVE_CODES = {"GROSS", "NET", "ADV_PAID"}
NAMES = {"1": ("Коваленко", "Ірина", "Петрівна", "female"), "2": ("Шевчук", "Андрій", "Миколайович", "male"), "3": ("Бондаренко", "Олена", "Василівна", "female"),
         "4": ("Ткаченко", "Марія", "Іванівна", "female"), "5": ("Мельник", "Олег", "Степанович", "male"), "6": ("Кравченко", "Наталія", "Богданівна", "female"),
         "7": ("Поліщук", "Василь", "Романович", "male"), "8": ("Савченко", "Тетяна", "Олексіївна", "female"), "9": ("Лисенко", "Дмитро", "Ігорович", "male"),
         "10": ("Гончар", "Сергій", "Павлович", "male"), "11": ("Руденко", "Юлія", "Анатоліївна", "female"), "12": ("Марченко", "Оксана", "Вікторівна", "female"),
         "13": ("Петренко", "Максим", "Юрійович", "male"), "14": ("Романенко", "Ігор", "Степанович", "male"), "15": ("Литвин", "Ольга", "Михайлівна", "female"), "16": ("Ткач", "Роман", "Олегович", "male"), "17": ("Сидорук", "Ганна", "Василівна", "female"), "18": ("Гаврилів", "Софія", "Тарасівна", "female"),
         "19": ("Пилипенко", "Артем", "Русланович", "male"), "20": ("Данильчук", "Віра", "Олегівна", "female"),
         "21": ("Кушнір", "Лариса", "Петрівна", "female"), "22": ("Бойчук", "Тарас", "Володимирович", "male"),
         "23": ("Мазур", "Ірина", "Степанівна", "female"), "24": ("Ковальчук", "Павло", "Ігорович", "male"),
         "25": ("Гнатюк", "Оксана", "Андріївна", "female"), "26": ("Шевченко", "Юрій", "Миколайович", "male")}
# індекс споживчих цін для сценарію 17: серпень 2026 = 101,0 (тестове число, не дані Держстату)
HAS_INDEX = "ua_index_off" in EMP_FIELDS
if HAS_INDEX:
    cpi = call("ua.cpi.index", "search", [["year", "=", 2026], ["month", "=", 8]])
    if cpi:
        call("ua.cpi.index", "write", cpi, {"value": 101.0, "note": "тестове число для еталонного сценарію"})
    else:
        call("ua.cpi.index", "create", {"year": 2026, "month": 8, "value": 101.0, "note": "тестове число для еталонного сценарію"})

RUN = call("hr.payslip.run", "search", [["name", "=", "Еталонні сценарії, серпень 2026"]])
RUN = RUN[0] if RUN else call("hr.payslip.run", "create", {"name": "Еталонні сценарії, серпень 2026", "date_start": PERIOD[0], "date_end": PERIOD[1]})
DEPT = call("hr.department", "search", [["name", "=", "Еталонні сценарії (тест)"]])
DEPT = DEPT[0] if DEPT else call("hr.department", "create", {"name": "Еталонні сценарії (тест)"})
for name, efields, wage, inputs, expect in S:
    moves = efields.pop("moves", None)
    ename = f"Еталон {name}"
    ln, fn, mn, sex = NAMES[name.split()[0]]
    efields = {"ua_last_name": ln, "ua_first_name": fn, "ua_middle_name": mn, "sex": sex, "department_id": DEPT, **efields}
    start = efields.pop("start", "2026-01-01"); end = efields.pop("end", False); history = efields.pop("history", None); leaves = efields.pop("leaves", []); years = efields.pop("years", 0); rehire = efields.pop("rehire", False)
    efields.setdefault("ua_fte", "1")
    index_base = efields.pop("index_base", None)
    if HAS_INDEX:
        efields["ua_index_off"] = not index_base          # індексація лише там, де її перевіряють
        efields["ua_index_base"] = index_base or False
    efields["ua_insurance_years"] = years
    n = int(name.split()[0]); efields.update({"ua_rnokpp": f"30000000{n:02d}", "sex": "male" if n % 2 else "female"})
    efields.update({"ua_hire_date": start, "ua_dismissal_date": end or False} if "ua_hire_date" in EMP_FIELDS else {})
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
    if rehire:
        # перша версія: 2026-01-01 .. 2026-05-31 (звільнений); друга версія: з 2026-08-17 (прийнятий знову) - одна картка працівника
        call("hr.version", "write", [ver], {"wage": wage, "contract_date_start": "2026-01-01", "contract_date_end": "2026-05-31", "struct_id": STRUCT, "resource_calendar_id": CAL,
                                            "ua_order_ref": "Наказ № 3 від 30.12.2025", "ua_end_order_ref": "Наказ № 21 від 29.05.2026", "ua_dismissal_basis": "п. 1 ст. 36 КЗпП (угода сторін)"}, context={"sync_contract_dates": True})
        old2 = call("hr.version", "search", [["employee_id", "=", eid], ["date_version", "=", "2026-08-17"]])
        v2 = old2[0] if old2 else call("hr.version", "create", {"employee_id": eid, "date_version": "2026-08-17", "wage": wage, "contract_date_start": "2026-08-17", "struct_id": STRUCT, "resource_calendar_id": CAL})
        call("hr.version", "write", [v2], {"wage": wage, "contract_date_start": "2026-08-17", "contract_date_end": False, "struct_id": STRUCT, "resource_calendar_id": CAL,
                                           "ua_order_ref": "Наказ № 40 від 14.08.2026", "ua_kp_code": "3431", "ua_prof_name": "Секретар адміністративний"}, context={"sync_contract_dates": True})
        ver = v2
    else:
        vvals = {"wage": wage, "date_version": start, "contract_date_start": start, "contract_date_end": end, "struct_id": STRUCT, "resource_calendar_id": CAL, "ua_kp_code": "2411.2", "ua_prof_name": "Економіст",
                 "ua_order_ref": f"Наказ № {int(name.split()[0]) + 10} від {start[8:10]}.{start[5:7]}.{start[:4]}"}
        if end:
            vvals.update({"ua_end_order_ref": "Наказ № 44 від 31.08.2026", "ua_dismissal_basis": "п. 1 ст. 36 КЗпП (угода сторін)"})
        call("hr.version", "write", [ver], vvals, context={"sync_contract_dates": True})
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
    slip = call("hr.payslip", "create", {"employee_id": eid, "date_from": PERIOD[0], "date_to": PERIOD[1], "struct_id": STRUCT, "name": ename, "payslip_run_id": RUN})
    call("hr.payslip", "onchange_employee", [slip])   # кнопка OCA: контракт, відпрацьовані дні, рядки входів
    call("hr.payslip", "write", [slip], {"name": f"Розрахунковий листок: {ename}, серпень 2026"})
    if inputs:
        for code, amount in inputs.items():
            iid = call("hr.payslip.input", "search", [["payslip_id", "=", slip], ["code", "=", code]])
            if iid:
                call("hr.payslip.input", "write", iid, {"amount": amount})
            else:
                call("hr.payslip.input", "create", {"payslip_id": slip, "code": code, "name": code, "amount": amount, "contract_id": ver})
    call("hr.payslip", "compute_sheet", [slip])
    lines = {l["code"]: round(l["total"], 2) for l in call("hr.payslip.line", "search_read", [["slip_id", "=", slip]], fields=["code", "total"])}
    USED_CODES.update(code for code, total in lines.items() if abs(total) > 0.005)
    wd = call("hr.payslip.worked_days", "search_read", [["payslip_id", "=", slip]], fields=["code", "number_of_days"])
    res = []
    for code, exp in expect.items():
        got = lines.get(code, 0.0 if exp == 0 else None); good = got is not None and abs(got - exp) < 0.005; ok &= good
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
# Кожне правило з ненульовою сумою має мати рядок у карті проводок, інакше сума мовчки не потрапить в облік.
mapped = {m["rule_code"] for m in call("ua.payroll.account.map", "search_read", [], fields=["rule_code"])}
missing = sorted(USED_CODES - mapped - NO_MOVE_CODES)
ok &= not missing
print(("PASS " if not missing else "FAIL ") + f"карта проводок покриває всі правила | без проводки: {missing or 'немає'}")

print("ALL PASS" if ok else "SOME FAIL")
if ok and "ua.payroll.report.wizard" in [m["model"] for m in call("ir.model", "search_read", [["model", "=", "ua.payroll.report.wizard"]], fields=["model"])]:
    wid = call("ua.payroll.report.wizard", "create", {"company_id": 1, "year": 2026, "month": 8, "doc_type": "HZ", "number": 1, "with_d1": True, "with_4df": True})
    call("ua.payroll.report.wizard", "action_generate", [wid])
    w = call("ua.payroll.report.wizard", "read", [wid], ["log", "result_ids"])[0]
    print("=== об'єднана звітність за серпень 2026 ==="); print(w["log"])
    out = os.path.join(ROOT, "demo-out"); os.makedirs(out, exist_ok=True)
    import base64
    for a in call("ir.attachment", "read", w["result_ids"], ["name", "datas"]):
        open(os.path.join(out, a["name"]), "wb").write(base64.b64decode(a["datas"])); print("  saved", a["name"])
    # 4ДФ: виплати поза зарплатою мають свої ознаки доходу
    import re as _re
    df = [f for f in os.listdir(out) if "J0510411" in f]
    if df:
        newest = max(df, key=lambda f: os.path.getmtime(os.path.join(out, f)))
        text = open(os.path.join(out, newest), encoding="windows-1251", errors="replace").read()
        signs = set(_re.findall(r'<T1RXXXXG05[^>]*>(\d+)</T1RXXXXG05>', text))
        want = {"169", "160", "127"}
        print(("PASS " if want <= signs else "FAIL ") + f"ознаки доходу у 4ДФ | є: {sorted(signs)}")
        if not want <= signs:
            sys.exit(1)
sys.exit(0 if ok else 1)
