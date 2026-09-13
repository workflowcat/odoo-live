"""Наповнення стенду даними, схожими на реальні: ТОВ «Ясен Меблі», 17 працівників, усі поля, серпень 2026.
Ідемпотентно: працівників шукає за РНОКПП, компанію і довідники оновлює. Запуск: python3 scripts/demo_company.py"""
import json, urllib.request, random
from datetime import date, timedelta

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
URL = "http://127.0.0.1:8110/jsonrpc"; DB = "payroll"; PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
random.seed(2026)


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(), {"Content-Type": "application/json"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"]["data"].get("message"), ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
def call(model, method, *a, **kw): return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


# ---- коди з контрольними числами -------------------------------------------------
def rnokpp(birthday, sex, serial):
    days = (birthday - date(1899, 12, 31)).days
    body = f"{days:05d}{serial:03d}" + str((serial * 7 + (1 if sex == "male" else 0)) % 10 // 2 * 2 + (1 if sex == "male" else 0))
    w = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    chk = sum(int(c) * k for c, k in zip(body, w)) % 11 % 10
    return body + str(chk)


def edrpou(base7):
    d = [int(c) for c in base7]; n = int(base7) * 10
    w = [7, 1, 2, 3, 4, 5, 6] if 30000000 <= n <= 60000000 else [1, 2, 3, 4, 5, 6, 7]
    c = sum(a * b for a, b in zip(d, w)) % 11
    if c == 10:
        c = sum(a * (b + 2) for a, b in zip(d, w)) % 11
        c = 0 if c == 10 else c
    return base7 + str(c)


def iban_ua(mfo, acc19):
    bban = f"{mfo}{acc19}"
    num = "".join(str(int(ch, 36)) for ch in bban + "UA00")
    return f"UA{98 - int(num) % 97:02d}{bban}"


UA = call("res.country", "search", [["code", "=", "UA"]])[0]
COMPANY = 1
CAL = call("resource.calendar", "search", [["name", "ilike", "40"]])[0]
STRUCT = call("hr.payroll.structure", "search", [["code", "=", "UA_SALARY"]])[0]
_st = call("hr.payroll.structure.type", "search", ["|", ["name", "=", "Employee"], ["name", "=", "Працівник"]]) or call("hr.payroll.structure.type", "search", [])
STRUCT_TYPE = _st[0]   # назву довідника перекладено модулем l10n_ua_payroll_ui, тому шукаємо обидві
# назви видів договору перекладено модулем l10n_ua_payroll_ui, тому шукаємо і англійську, і українську
CT_UK = {"Permanent": "Безстроковий", "Part-Time": "Неповний робочий день", "Temporary": "Строковий", "Intern": "Стажування"}
CT = {n: (call("hr.contract.type", "search", ["|", ["name", "=", n], ["name", "=", CT_UK[n]]]) or call("hr.contract.type", "search", []))[0]
      for n in ["Permanent", "Part-Time", "Temporary", "Intern"]}
LT = {c: call("hr.leave.type", "search", [["work_entry_type_id.code", "=", c]])[0] for c in ["VAC", "SICK", "UNPAID", "MAT"]}


def upsert(model, domain, vals):
    ids = call(model, "search", domain)
    if ids:
        call(model, "write", [ids[0]], vals); return ids[0]
    return call(model, "create", vals)


# ---- компанія ------------------------------------------------------------------------
EDRPOU = edrpou("4381207")
co_partner = call("res.company", "read", [COMPANY], ["partner_id"])[0]["partner_id"][0]
call("res.company", "write", [COMPANY], {
    "name": "ТОВ «Ясен Меблі»", "company_registry": EDRPOU, "street": "вул. Городоцька, 174", "city": "Львів", "zip": "79022", "country_id": UA,
    "phone": "+380 32 245 10 20", "email": "office@yasen-mebli.example", "website": "https://yasen-mebli.example",
    "ua_sti_code": "1306", "ua_sti_name": "ГУ ДПС у Львівській області, Залізнична ДПІ (Залізничний район м. Львова)",
    "ua_reg": "13", "ua_raj": "06", "ua_katottg": "UA46060250010015970", "ua_kved": "31.09", "resource_calendar_id": CAL,
})
call("res.partner", "write", [co_partner], {"name": "ТОВ «Ясен Меблі»", "company_registry": EDRPOU})
BANKS = {"privat": upsert("res.bank", [["bic", "=", "305299"]], {"name": "АТ КБ «ПриватБанк»", "bic": "305299", "city": "Дніпро", "country": UA}),
         "mono": upsert("res.bank", [["bic", "=", "322001"]], {"name": "АТ «Універсал Банк» (monobank)", "bic": "322001", "city": "Київ", "country": UA}),
         "oschad": upsert("res.bank", [["bic", "=", "300465"]], {"name": "АТ «Ощадбанк»", "bic": "300465", "city": "Київ", "country": UA})}
upsert("res.partner.bank", [["acc_number", "=", iban_ua("305299", "0000026005011223344")]],
       {"acc_number": iban_ua("305299", "0000026005011223344"), "partner_id": co_partner, "bank_id": BANKS["privat"]})

# ---- підрозділи, посади, місця роботи ---------------------------------------------------
def account(code):
    ids = call("account.account", "search", [["code", "=like", f"{code}%"], ["company_ids", "in", COMPANY]], order="code", limit=1)
    return ids[0] if ids else False

DEPTS = {}
for name, acc in [("Адміністрація", "92"), ("Бухгалтерія", "92"), ("Відділ продажу", "93"), ("Виробництво", "23"), ("Склад і логістика", "91")]:
    DEPTS[name] = upsert("hr.department", [["name", "=", name]], {"name": name, "company_id": COMPANY, "ua_expense_account_id": account(acc)})
JOBS = {}
for name, dept in [("Директор", "Адміністрація"), ("Головний бухгалтер", "Бухгалтерія"), ("Бухгалтер", "Бухгалтерія"), ("Менеджер із збуту", "Відділ продажу"),
                   ("Столяр", "Виробництво"), ("Комірник", "Склад і логістика"), ("Водій автотранспортних засобів", "Склад і логістика"),
                   ("Інженер-технолог", "Виробництво"), ("Дизайнер меблів", "Виробництво"), ("Фахівець з маркетингу", "Відділ продажу"),
                   ("Прибиральник службових приміщень", "Адміністрація"), ("Пакувальник", "Склад і логістика"), ("Юрисконсульт", "Адміністрація"),
                   ("Верстатник деревообробних верстатів", "Виробництво"), ("Комерційний директор", "Відділ продажу"), ("Технік-конструктор", "Виробництво"), ("Монтажник меблів (ФОП)", "Виробництво")]:
    JOBS[name] = upsert("hr.job", [["name", "=", name]], {"name": name, "department_id": DEPTS[dept], "company_id": COMPANY})
office_p = upsert("res.partner", [["name", "=", "Ясен Меблі, офіс"]], {"name": "Ясен Меблі, офіс", "street": "вул. Городоцька, 174", "city": "Львів", "zip": "79022", "country_id": UA, "parent_id": co_partner, "type": "other"})
shop_p = upsert("res.partner", [["name", "=", "Ясен Меблі, цех"]], {"name": "Ясен Меблі, цех", "street": "вул. Промислова, 8", "city": "Сокільники", "zip": "81130", "country_id": UA, "parent_id": co_partner, "type": "other"})
LOC = {"office": upsert("hr.work.location", [["name", "=", "Офіс, вул. Городоцька 174"]], {"name": "Офіс, вул. Городоцька 174", "location_type": "office", "address_id": office_p, "company_id": COMPANY}),
       "shop": upsert("hr.work.location", [["name", "=", "Цех, Сокільники"]], {"name": "Цех, Сокільники", "location_type": "other", "address_id": shop_p, "company_id": COMPANY}),
       "home": upsert("hr.work.location", [["name", "=", "Віддалено"]], {"name": "Віддалено", "location_type": "home", "address_id": office_p, "company_id": COMPANY})}

# ---- працівники -------------------------------------------------------------------------
# (прізвище, ім'я, по батькові, стать, дата народження, посада, підрозділ, оклад, ставка, вид договору, основне місце, ЄСВ, ПСП, дітей ПСП, стаж років,
#  сімейний стан, дітей, дата прийняття, локація, освіта, місто проживання, банк, додатково)
P = [
 ("Гаврилюк", "Богдан", "Тарасович", "male", date(1978, 3, 14), "Директор", "Адміністрація", 60000, "1", "employment", True, "standard", "none", 0, 22.5, "married", 2, date(2015, 2, 2), "office", ("master", "Менеджмент організацій", "НУ «Львівська політехніка»"), "Львів", "privat", {"kp": "1210.1"}),
 ("Стефанишин", "Оксана", "Ігорівна", "female", date(1983, 7, 21), "Головний бухгалтер", "Бухгалтерія", 45000, "1", "employment", True, "standard", "none", 0, 18.0, "married", 1, date(2016, 9, 1), "office", ("master", "Облік і аудит", "ЛНУ ім. Івана Франка"), "Львів", "privat", {"kp": "1231"}),
 ("Кушнір", "Галина", "Романівна", "female", date(1991, 11, 5), "Бухгалтер", "Бухгалтерія", 25000, "1", "employment", True, "standard", "none", 0, 8.2, "single", 0, date(2021, 3, 15), "office", ("bachelor", "Облік і оподаткування", "ЛТЕУ"), "Винники", "mono", {"kp": "3433", "BONUS": 3000}),
 ("Дзюба", "Ярослав", "Михайлович", "male", date(1988, 5, 30), "Менеджер із збуту", "Відділ продажу", 20000, "1", "employment", True, "standard", "none", 0, 12.0, "married", 1, date(2019, 6, 3), "office", ("bachelor", "Маркетинг", "ЛНУ ім. Івана Франка"), "Львів", "privat", {"kp": "1475.4", "BONUS": 8000}),
 ("Ковальчук", "Роман", "Васильович", "male", date(1985, 1, 17), "Столяр", "Виробництво", 22000, "1", "employment", True, "standard", "none", 0, 15.0, "married", 3, date(2017, 4, 10), "shop", ("other", "Столяр 4 розряду", "Львівське ВПУ деревообробки"), "Сокільники", "oschad", {"kp": "7422", "leaves": [("SICK", "2026-08-10", "2026-08-19")]}),
 ("Мельничук", "Андрій", "Петрович", "male", date(1979, 9, 9), "Столяр", "Виробництво", 22000, "1", "employment", True, "standard", "none", 0, 25.0, "married", 2, date(2015, 2, 2), "shop", ("other", "Столяр 5 розряду", "Львівське ВПУ деревообробки"), "Пустомити", "privat", {"kp": "7422", "leaves": [("VAC", "2026-08-03", "2026-08-16")]}),
 ("Іваничук", "Марія", "Степанівна", "female", date(1995, 4, 12), "Комірник", "Склад і логістика", 15000, "1", "employment", True, "standard", "none", 0, 6.0, "single", 0, date(2020, 7, 1), "shop", ("bachelor", "Логістика", "НУ «Львівська політехніка»"), "Львів", "mono", {"kp": "4131", "leaves": [("UNPAID", "2026-08-24", "2026-08-28")]}),
 ("Шевчук", "Віталій", "Олегович", "male", date(1982, 12, 1), "Водій автотранспортних засобів", "Склад і логістика", 18000, "1", "employment", True, "standard", "none", 0, 20.0, "divorced", 1, date(2018, 1, 15), "shop", ("other", "Водій категорії C", "Львівський автошкола ТСО"), "Львів", "privat", {"kp": "8322", "ALIM_PCT": 25}),
 ("Прокопів", "Наталія", "Богданівна", "female", date(1976, 6, 24), "Інженер-технолог", "Виробництво", 30000, "1", "employment", True, "disabled", "none", 0, 28.0, "married", 2, date(2016, 3, 1), "shop", ("master", "Технологія деревообробки", "НЛТУ України"), "Львів", "oschad", {"kp": "2149.2", "note": "інвалідність III групи, ЄСВ 8,41 %"}),
 ("Лозинський", "Тарас", "Юрійович", "male", date(1993, 2, 8), "Дизайнер меблів", "Виробництво", 0, "1", "gph", False, "standard", "none", 0, 0.0, "single", 0, date(2026, 8, 1), "home", ("bachelor", "Дизайн", "ЛНАМ"), "Львів", "mono", {"kp": "3471", "GPH": 25000, "end": date(2026, 12, 31), "ct": "Temporary"}),
 ("Бойчук", "Соломія", "Андріївна", "female", date(1990, 8, 19), "Фахівець з маркетингу", "Відділ продажу", 10000, "0.5", "employment", False, "standard", "none", 0, 9.0, "married", 0, date(2023, 10, 2), "home", ("master", "Маркетинг", "ЛНУ ім. Івана Франка"), "Львів", "mono", {"kp": "2419.2", "ct": "Part-Time", "note": "зовнішній сумісник, 0,5 ставки"}),
 ("Романюк", "Любов", "Іванівна", "female", date(1968, 10, 2), "Прибиральник службових приміщень", "Адміністрація", 9000, "0.5", "employment", True, "standard", "base", 0, 35.0, "widower", 0, date(2012, 5, 14), "office", ("other", "Середня", "СШ № 45 м. Львова"), "Львів", "oschad", {"kp": "9132", "ct": "Part-Time"}),
 ("Федорів", "Ірина", "Василівна", "female", date(1987, 3, 27), "Пакувальник", "Склад і логістика", 9000, "1", "employment", True, "standard", "child", 2, 10.0, "divorced", 2, date(2019, 9, 2), "shop", ("other", "Середня спеціальна", "Львівський коледж легкої промисловості"), "Сокільники", "privat", {"kp": "9322", "note": "ПСП на двох дітей"}),
 ("Данилюк", "Олег", "Ігорович", "male", date(1996, 7, 14), "Юрисконсульт", "Адміністрація", 35000, "1", "employment", True, "standard", "none", 0, 4.0, "single", 0, date(2026, 8, 17), "office", ("master", "Право", "ЛНУ ім. Івана Франка"), "Львів", "mono", {"kp": "2429", "trial": date(2026, 11, 16)}),
 ("Гнатів", "Степан", "Миколайович", "male", date(1972, 4, 5), "Верстатник деревообробних верстатів", "Виробництво", 21000, "1", "employment", True, "standard", "none", 0, 30.0, "married", 2, date(2016, 3, 1), "shop", ("other", "Верстатник 4 розряду", "Львівське ВПУ деревообробки"), "Пустомити", "privat", {"kp": "8240", "end": date(2026, 8, 31), "dismissal": "п. 1 ст. 36 КЗпП (угода сторін)", "COMP_DAYS": 12}),
 ("Крамар", "Володимир", "Зіновійович", "male", date(1980, 11, 23), "Комерційний директор", "Відділ продажу", 180000, "1", "employment", True, "standard", "none", 0, 19.0, "married", 2, date(2018, 11, 5), "office", ("master", "Економіка підприємства", "КНЕУ"), "Львів", "privat", {"kp": "1233", "BONUS": 20000}),
 ("Ткачук", "Ігор", "Володимирович", "male", date(1984, 8, 30), "Столяр", "Виробництво", 22000, "1", "employment", True, "standard", "none", 0, 17.0, "married", 1, date(2026, 8, 17), "shop", ("other", "Столяр 5 розряду", "Львівське ВПУ деревообробки"), "Пустомити", "privat", {"kp": "7422", "rehire": (date(2021, 3, 1), date(2026, 5, 31)), "note": "звільнений 31.05.2026 за угодою сторін, прийнятий знову 17.08.2026: одна картка, дві версії"}),
 ("Савчук", "Олег", "Васильович", "male", date(1986, 2, 11), "Монтажник меблів (ФОП)", "Виробництво", 0, "1", "fop", False, "standard", "none", 0, 0.0, "married", 1, date(2026, 1, 12), "shop", ("other", "Монтажник", "Львівське ВПУ деревообробки"), "Львів", "privat", {"kp": "7422", "FOP_PAY": 40000, "end": date(2026, 12, 31), "ct": "Temporary", "note": "ФОП 3 групи, договір підряду; 4ДФ ознака 157, без ПДФО/ВЗ/ЄСВ"}),
 ("Гринів", "Оксана", "Романівна", "female", date(1994, 9, 3), "Менеджер із збуту", "Відділ продажу", 24000, "1", "employment", True, "standard", "none", 0, 7.0, "married", 1, date(2020, 2, 3), "office", ("bachelor", "Менеджмент", "ЛТЕУ"), "Львів", "mono", {"kp": "1475.4", "leaves": [("MAT", "2026-08-10", "2026-12-13")], "sick_number": "2026-0811-000123", "note": "декретна відпустка 126 к.д. з 10.08.2026, допомога 100 % за рахунок ПФУ"}),
 ("Панчишин", "Христина", "Олегівна", "female", date(2003, 5, 11), "Технік-конструктор", "Виробництво", 12000, "0.25", "employment", True, "standard", "base", 0, 1.0, "single", 0, date(2026, 6, 1), "shop", ("bachelor", "Дизайн меблів", "НЛТУ України"), "Львів", "mono", {"kp": "3118", "ct": "Intern", "trial": date(2026, 8, 31), "note": "студентка, 0,25 ставки"}),
]
STREETS = ["вул. Личаківська", "вул. Наукова", "просп. Червоної Калини", "вул. Замарстинівська", "вул. Шевченка", "вул. Сихівська", "вул. Зелена", "вул. Стрийська"]
created = {}
for i, (ln, fn, mn, sex, bd, job, dept, wage, fte, kind, main, esv, psp, pspk, years, marital, kids, hire, loc, edu, city, bank, extra) in enumerate(P, 1):
    code = rnokpp(bd, sex, 100 + sum(ord(c) for c in ln + fn) % 800)   # серійна частина стала для особи, не залежить від порядку в списку
    name = f"{ln} {fn} {mn}"
    email_ln = ["havryliuk", "stefanyshyn", "kushnir", "dziuba", "kovalchuk", "melnychuk", "ivanychuk", "shevchuk", "prokopiv", "lozynskyi", "boichuk", "romaniuk", "fedoriv", "danyliuk", "hnativ", "kramar", "tkachuk", "savchuk", "hryniv", "panchyshyn"][i - 1]
    vals = {
        "name": name, "sex": sex, "birthday": str(bd), "place_of_birth": city if city != "Львів" else "Львів", "country_of_birth": UA, "country_id": UA,
        "private_street": f"{random.choice(STREETS)}, {random.randint(2, 120)}, кв. {random.randint(1, 90)}", "private_city": city, "private_zip": f"79{random.randint(10, 69):03d}" if city == "Львів" else "81130",
        "private_country_id": UA, "private_phone": f"+380 67 {random.randint(100, 999)} {random.randint(10, 99)} {random.randint(10, 99)}", "private_email": f"{email_ln}@ukr.example",
        "marital": marital, "children": kids, "emergency_contact": random.choice(["Гаврилюк Олена (дружина)", "Мати", "Батько", "Брат", "Чоловік", "Дружина", "Сестра"]),
        "emergency_phone": f"+380 50 {random.randint(100, 999)} {random.randint(10, 99)} {random.randint(10, 99)}",
        "identification_id": f"ID-картка {random.randint(100000000, 999999999)}, орган 4620, {random.randint(1, 28):02d}.{random.randint(1, 12):02d}.{random.randint(2016, 2024)}",
        "passport_id": f"FL{random.randint(100000, 999999)}" if i % 3 == 0 else False,
        "work_email": f"{email_ln}@yasen-mebli.example", "work_phone": "+380 32 245 10 20", "mobile_phone": f"+380 63 {random.randint(100, 999)} {random.randint(10, 99)} {random.randint(10, 99)}",
        "job_title": job, "job_id": JOBS[job], "department_id": DEPTS[dept], "work_location_id": LOC[loc], "resource_calendar_id": CAL, "company_id": COMPANY,
        "employee_type": "contractor" if kind in ("gph", "fop") else ("trainee" if extra.get("ct") == "Intern" else "employee"),
        "certificate": edu[0], "study_field": edu[1], "study_school": edu[2], "distance_home_work": random.randint(2, 25), "lang": "uk_UA", "tz": "Europe/Kyiv",
        "ua_rnokpp": code, "ua_contract_kind": kind, "ua_main_job": main, "ua_esv_category": esv, "ua_psp": psp, "ua_psp_children": pspk, "ua_fte": fte,
        "ua_insurance_years": years, "ua_hire_date": str(hire), "ua_dismissal_date": str(extra["end"]) if extra.get("end") and kind == "employment" else False,
        "ua_last_name": ln, "ua_first_name": fn, "ua_middle_name": mn, "ua_full_time": fte == "1",
    }
    eid = call("hr.employee", "search", [["ua_rnokpp", "=", code], ["active", "in", [True, False]]])
    if eid:
        eid = eid[0]; call("hr.employee", "write", [eid], {**vals, "active": True})
    else:
        eid = call("hr.employee", "create", vals)
    created[i] = (eid, name, code, extra)
    # версія контракту (Odoo 19: hr.version)
    ver = call("hr.employee", "read", [eid], ["version_id"])[0]["version_id"][0]
    order = f"Наказ № {i + 11}-к від {hire.strftime('%d.%m.%Y')}"
    vvals = {"wage": wage, "date_version": str(hire), "contract_date_start": str(hire), "contract_date_end": str(extra["end"]) if extra.get("end") else False, "struct_id": STRUCT, "structure_type_id": STRUCT_TYPE,
             "resource_calendar_id": CAL, "contract_type_id": CT[extra.get("ct", "Permanent")], "job_title": job, "ua_order_ref": order, "ua_kp_code": extra.get("kp", ""), "ua_prof_name": job,
             "trial_date_end": str(extra["trial"]) if extra.get("trial") else False, "ua_internal_parttime": False,
             "ua_end_order_ref": f"Наказ № 44-к від {extra['end'].strftime('%d.%m.%Y')}" if extra.get("dismissal") else False, "ua_dismissal_basis": extra.get("dismissal", False)}
    if extra.get("rehire"):
        # перший період роботи: окрема версія з датою початку і кінця; поточна версія = повторне прийняття
        r1, r2 = extra["rehire"]
        vvals.update({"ua_order_ref": f"Наказ № 9-к від {hire.strftime('%d.%m.%Y')}"})
        old_v = call("hr.version", "search", [["employee_id", "=", eid], ["date_version", "=", str(r1)]])
        v1 = {"wage": 20000, "date_version": str(r1), "contract_date_start": str(r1), "contract_date_end": str(r2), "struct_id": STRUCT, "structure_type_id": STRUCT_TYPE, "resource_calendar_id": CAL,
              "contract_type_id": CT["Permanent"], "job_title": job, "ua_order_ref": f"Наказ № 4-к від {r1.strftime('%d.%m.%Y')}", "ua_end_order_ref": f"Наказ № 19-к від {r2.strftime('%d.%m.%Y')}",
              "ua_dismissal_basis": "п. 1 ст. 36 КЗпП (угода сторін)", "ua_kp_code": extra.get("kp", ""), "ua_prof_name": job}
        if old_v:
            call("hr.version", "write", [old_v[0]], v1, context={"sync_contract_dates": True})
        else:
            call("hr.version", "create", {"employee_id": eid, **v1}, context={"sync_contract_dates": True})
    call("hr.version", "write", [ver], vvals, context={"sync_contract_dates": True})
    # банківський рахунок для зарплатного проєкту
    partner = call("hr.employee", "read", [eid], ["work_contact_id"])[0]["work_contact_id"][0]
    mfo = {"privat": "305299", "mono": "322001", "oschad": "300465"}[bank]
    acc = iban_ua(mfo, f"0000026207{i:04d}{random.randint(10000, 99999)}"[:19].ljust(19, "0"))
    bid = call("res.partner.bank", "search", [["partner_id", "=", partner]])
    if bid:
        call("res.partner.bank", "write", [bid[0]], {"acc_number": acc, "bank_id": BANKS[bank], "acc_holder_name": name})
        bid = bid[0]
    else:
        bid = call("res.partner.bank", "create", {"acc_number": acc, "partner_id": partner, "bank_id": BANKS[bank], "acc_holder_name": name})
    call("hr.employee", "write", [eid], {"bank_account_ids": [(6, 0, [bid])], "primary_bank_account_id": bid})
    # історія заробітку за 12 місяців (для середньої)
    old = call("ua.earnings.history", "search", [["employee_id", "=", eid]])
    if old:
        call("ua.earnings.history", "unlink", old)
    for k in range(12):
        y, m = (2025 + (8 + k - 1) // 12, (8 + k - 1) % 12 + 1)
        first = date(y, m, 1)
        if extra.get("rehire"):
            if not (first < date(extra["rehire"][1].year, extra["rehire"][1].month, 1) + timedelta(days=31)):
                continue
        elif first < date(hire.year, hire.month, 1) or kind in ("gph", "fop"):
            continue
        gross = wage * float(fte)
        if extra.get("BONUS") and m in (3, 6, 9, 12):
            gross += extra["BONUS"]
        if job in ("Столяр", "Верстатник деревообробних верстатів") and m in (11, 12, 4):
            gross += 1500
        call("ua.earnings.history", "create", {"employee_id": eid, "month": str(first), "gross": round(gross, 2)})
    # відпустки серпня
    for lcode, d1, d2 in extra.get("leaves", []):
        existing = call("hr.leave", "search_read", [["employee_id", "=", eid], ["holiday_status_id", "=", LT[lcode]], ["request_date_from", "=", d1], ["state", "=", "validate"]], fields=["ua_sick_number", "ua_order_ref"])
        if existing and lcode in ("SICK", "MAT") and not existing[0]["ua_sick_number"]:
            call("hr.leave", "write", [existing[0]["id"]], {"ua_sick_number": extra.get("sick_number") or f"2026-08{i:02d}-{random.randint(100000, 999999)}"})
        if not existing:
            lid = call("hr.leave", "create", {"employee_id": eid, "holiday_status_id": LT[lcode], "request_date_from": d1, "request_date_to": d2,
                                              "ua_order_ref": f"Наказ № {30 + i}-в від {(date.fromisoformat(d1) - timedelta(days=3)).strftime('%d.%m.%Y')}" if lcode in ("VAC", "UNPAID") else False,
                                              "ua_sick_number": extra.get("sick_number") or (f"2026-08{i:02d}-{random.randint(100000, 999999)}" if lcode in ("SICK", "MAT") else False)})
            call("hr.leave", "action_approve", [lid])
    print(f"{i:2d}. {name} ({code}) {job}, {dept}, оклад {wage}, ставка {fte}")

# застарілі демо-картки (РНОКПП поза списком) прибираємо разом з листками
codes = {v[2] for v in created.values()}
stale = [e for e in call("hr.employee", "search_read", [["department_id", "in", list(DEPTS.values())], ["active", "in", [True, False]]], fields=["id", "ua_rnokpp"]) if e["ua_rnokpp"] not in codes]
for e in stale:
    for sl in call("hr.payslip", "search_read", [["employee_id", "=", e["id"]]], fields=["id", "state", "move_id"]):
        if sl["state"] == "done" and sl["move_id"]:
            call("account.move", "button_draft", [sl["move_id"][0]]); call("account.move", "unlink", [sl["move_id"][0]])
        if sl["state"] != "cancel":
            call("hr.payslip", "write", [sl["id"]], {"state": "cancel"})
        call("hr.payslip", "unlink", [sl["id"]])
    for h in call("ua.earnings.history", "search", [["employee_id", "=", e["id"]]]):
        call("ua.earnings.history", "unlink", [h])
    lv = call("hr.leave", "search", [["employee_id", "=", e["id"]]])
    if lv:
        call("hr.leave", "action_refuse", lv); call("hr.leave", "unlink", lv)
    we = call("hr.work.entry", "search", [["employee_id", "=", e["id"]]], context={"active_test": False})
    if we:
        call("hr.work.entry", "write", we, {"state": "draft"}); call("hr.work.entry", "unlink", we)
    try:
        call("hr.employee", "unlink", [e["id"]])
    except SystemExit:
        call("hr.employee", "write", [e["id"]], {"active": False})
    print("stale employee removed:", e["ua_rnokpp"])

# керівники підрозділів і безпосередні керівники
mgr = {"Адміністрація": created[1][0], "Бухгалтерія": created[2][0], "Відділ продажу": created[16][0], "Виробництво": created[9][0], "Склад і логістика": created[7][0]}
for d, m in mgr.items():
    call("hr.department", "write", [DEPTS[d]], {"manager_id": m})
for i, (ln, fn, mn, sex, bd, job, dept, *_rest) in enumerate(P, 1):
    eid = created[i][0]
    # керівник підрозділу підпорядкований директору; директор - корінь оргструктури без керівника
    boss = mgr[dept] if mgr[dept] != eid else (created[1][0] if eid != created[1][0] else False)
    call("hr.employee", "write", [eid], {"parent_id": boss, "coach_id": boss})
# стандартний підрозділ Odoo «Administration» порожній і англійською: архівуємо
stray = [d["id"] for d in call("hr.department", "search_read", [["name", "=", "Administration"]], fields=["member_ids"]) if not d["member_ids"]]
if stray:
    call("hr.department", "write", stray, {"active": False})
call("res.company", "write", [COMPANY], {"ua_director_name": created[1][1], "ua_director_rnokpp": created[1][2], "ua_accountant_name": created[2][1], "ua_accountant_rnokpp": created[2][2]})

# ---- пакети листків: липень (закрито), серпень (закрито), вересень (чернетки для авансу) ---------------
import calendar as _cal


def month_batch(year, month, name, close=True, advance=True):
    d1 = date(year, month, 1); d2 = date(year, month, _cal.monthrange(year, month)[1])
    run = call("hr.payslip.run", "search", [["name", "=", name]])
    run = run[0] if run else call("hr.payslip.run", "create", {"name": name, "date_start": str(d1), "date_end": str(d2), "company_id": COMPANY})
    emp_ids = [v[0] for v in created.values()]
    old = call("hr.payslip", "search_read", [["employee_id", "in", emp_ids], ["date_from", "=", str(d1)]], fields=["id", "state", "move_id"])
    for sl in old:
        if sl["state"] == "done" and sl["move_id"]:
            call("account.move", "button_draft", [sl["move_id"][0]]); call("account.move", "unlink", [sl["move_id"][0]])
        if sl["state"] != "cancel":
            call("hr.payslip", "write", [sl["id"]], {"state": "cancel"})
    if old:
        call("hr.payslip", "unlink", [sl["id"] for sl in old])
    slips = {}
    for i, (eid, name_e, code, extra) in created.items():
        v = call("hr.version", "search_read", [["employee_id", "=", eid]], fields=["id", "contract_date_start", "contract_date_end"], order="date_version desc", limit=1)[0]
        cs = date.fromisoformat(v["contract_date_start"]) if v["contract_date_start"] else None
        ce = date.fromisoformat(v["contract_date_end"]) if v["contract_date_end"] else None
        if not cs or cs > d2 or (ce and ce < d1):
            continue
        slip = call("hr.payslip", "create", {"employee_id": eid, "date_from": str(d1), "date_to": str(d2), "struct_id": STRUCT, "payslip_run_id": run,
                                             "name": f"Розрахунковий листок: {name_e}, {MONTHS[month]} {year}"})
        call("hr.payslip", "onchange_employee", [slip])
        call("hr.payslip", "write", [slip], {"name": f"Розрахунковий листок: {name_e}, {MONTHS[month]} {year}"})
        for code_in in ("BONUS", "GPH", "FOP_PAY", "ALIM_PCT", "COMP_DAYS"):
            amount = extra.get(code_in)
            if code_in == "COMP_DAYS" and not (ce and d1 <= ce <= d2):
                continue
            if code_in == "BONUS" and month not in (3, 6, 8, 9, 12) and amount and amount > 5000:
                amount = round(amount / 2)
            if amount:
                iid = call("hr.payslip.input", "search", [["payslip_id", "=", slip], ["code", "=", code_in]])
                if iid:
                    call("hr.payslip.input", "write", iid, {"amount": amount})
                else:
                    call("hr.payslip.input", "create", {"payslip_id": slip, "code": code_in, "name": code_in, "amount": amount, "contract_id": v["id"]})
        slips[i] = slip
    if advance:
        wid = call("ua.payroll.advance.wizard", "create", {"company_id": COMPANY, "year": year, "month": month, "percent": 50.0, "pay_date": str(date(year, month, 20))})
        call("ua.payroll.advance.wizard", "action_fill", [wid])
    print(f"\n{name}: {'аванс → остаточний розрахунок' if close else 'чернетки'}")
    rows = {}
    for i, slip in slips.items():
        call("hr.payslip", "compute_sheet", [slip])
        if close:
            call("hr.payslip", "action_payslip_done", [slip])
        lines = {l["code"]: round(l["total"], 2) for l in call("hr.payslip.line", "search_read", [["slip_id", "=", slip]], fields=["code", "total"])}
        wd = {w["code"]: w["number_of_days"] for w in call("hr.payslip.worked_days", "search_read", [["payslip_id", "=", slip]], fields=["code", "number_of_days"])}
        rows[i] = lines
        print(f"{i:2d}. {created[i][1]:32s} нараховано {lines.get('GROSS', 0):>10.2f}  ПДФО {-lines.get('PDFO', 0):>9.2f}  ВЗ {-lines.get('VZ', 0):>8.2f}  аванс {-lines.get('ADV_PAID', 0):>9.2f}  до виплати {lines.get('NET', 0):>10.2f}  ЄСВ {lines.get('ESV', 0):>9.2f}  дні {wd}")
    return run, rows


MONTHS = {7: "липень", 8: "серпень", 9: "вересень"}
month_batch(2026, 7, "Зарплата за липень 2026", close=True)
run_aug, aug = month_batch(2026, 8, "Зарплата за серпень 2026", close=True)
month_batch(2026, 9, "Зарплата за вересень 2026", close=False, advance=False)

# ---- виписка банку за серпень з реальних сум: аванс 20.08, податки, зарплата 04.09 ------------------
def money(x): return f"{x:.2f}".replace(".", ",")
rows = ["Дата;Номер документа;Контрагент;Рахунок контрагента;Призначення платежу;Дебет;Кредит;Валюта"]
n = 200
adv_total = 0.0
for i, lines in aug.items():
    adv = -lines.get("ADV_PAID", 0.0)
    if adv > 0:
        n += 1; adv_total += adv
        acc = call("res.partner.bank", "search_read", [["partner_id", "=", call("hr.employee", "read", [created[i][0]], ["work_contact_id"])[0]["work_contact_id"][0]]], fields=["acc_number"])[0]["acc_number"]
        rows.append(f"20.08.2026;{n};{created[i][1]};{acc};Аванс за серпень 2026 згідно відомості № 8-А;{money(adv)};;UAH")
pdfo_adv = round(adv_total * 18 / 77, 2); vz_adv = round(adv_total * 5 / 77, 2); esv_adv = round(adv_total / 0.77 * 0.22, 2)
for label, acc, amt in [("ПДФО з авансу за серпень 2026", "UA588999980313040106000026001", pdfo_adv), ("Військовий збір з авансу за серпень 2026", "UA588999980313040106000026002", vz_adv), ("Єдиний внесок (ЄСВ) з авансу за серпень 2026", "UA808999980313080106000026001", esv_adv)]:
    n += 1; rows.append(f'20.08.2026;{n};ГУ ДПС у Львівській області;{acc};"*;101;{EDRPOU};{label}";{money(amt)};;UAH')
rows.append(f"21.08.2026;{n+1};ТОВ «Меблевий дім Галичина»;UA213223130000026007233566001;Оплата за кухонні фасади згідно рахунку № 118 від 18.08.2026, у т.ч. ПДВ 20 %;;186000,00;UAH")
rows.append(f"25.08.2026;{n+2};ФОП Савчук О. В.;UA903052990000026008001122334;Оплата за фурнітуру згідно рахунку № 77 від 22.08.2026, без ПДВ;42300,00;;UAH")
n += 2
pdfo_t = vz_t = esv_t = 0.0
for i, lines in aug.items():
    net = lines.get("NET", 0.0); pdfo_t += -lines.get("PDFO", 0.0); vz_t += -lines.get("VZ", 0.0); esv_t += lines.get("ESV", 0.0)
    if net > 0:
        n += 1
        acc = call("res.partner.bank", "search_read", [["partner_id", "=", call("hr.employee", "read", [created[i][0]], ["work_contact_id"])[0]["work_contact_id"][0]]], fields=["acc_number"])[0]["acc_number"]
        kind = "Винагорода за договором ЦПХ за серпень 2026" if created[i][3].get("GPH") else ("Оплата за договором підряду № 7 від 12.01.2026, без ПДВ" if created[i][3].get("FOP_PAY") else "Заробітна плата за серпень 2026, остаточний розрахунок")
        rows.append(f"04.09.2026;{n};{created[i][1]};{acc};{kind};{money(net)};;UAH")
alim = sum(-l.get("ALIM", 0.0) for l in aug.values())
if alim:
    n += 1; rows.append(f"04.09.2026;{n};Шевчук Ольга Іванівна;UA903052990000026207000000099;Аліменти за серпень 2026 за виконавчим листом № 2-1234/24, 25 %;{money(alim)};;UAH")
for label, acc, amt in [("ПДФО із зарплати за серпень 2026, остаточний розрахунок", "UA588999980313040106000026001", round(pdfo_t - pdfo_adv, 2)), ("Військовий збір із зарплати за серпень 2026", "UA588999980313040106000026002", round(vz_t - vz_adv, 2)), ("Єдиний внесок (ЄСВ) за серпень 2026", "UA808999980313080106000026001", round(esv_t - esv_adv, 2))]:
    n += 1; rows.append(f'04.09.2026;{n};ГУ ДПС у Львівській області;{acc};"*;101;{EDRPOU};{label}";{money(amt)};;UAH')
import os; os.makedirs("demo-out", exist_ok=True)
csv_path = "demo-out/виписка-ясен-меблі-серпень-2026.csv"
open(csv_path, "w", encoding="utf-8-sig").write("\n".join(rows) + "\n")
import base64
jr = call("account.journal", "search_read", [["type", "=", "bank"], ["company_id", "=", COMPANY]], fields=["id"])[0]["id"]
mp = call("account.statement.import.sheet.mapping", "search", [["name", "ilike", "Виписка"]])[0]
for st in call("account.bank.statement", "search", [["journal_id", "=", jr]]):
    call("account.bank.statement", "unlink", [st])
for ln_ in call("account.bank.statement.line", "search", [["journal_id", "=", jr]]):
    call("account.bank.statement.line", "unlink", [ln_])
wid = call("account.statement.import", "create", {"statement_file": base64.b64encode(open(csv_path, "rb").read()).decode(), "statement_filename": os.path.basename(csv_path), "sheet_mapping_id": mp}, context={"journal_id": jr})
call("account.statement.import", "import_file_button", [wid], context={"journal_id": jr})
print(f"\nВиписка: {len(rows) - 1} операцій імпортовано у журнал банку ({csv_path})")

# ---- об'єднана звітність за серпень: XML у вкладеннях майстра ---------------------------------------
wiz = call("ua.payroll.report.wizard", "create", {"company_id": COMPANY, "year": 2026, "month": 8, "doc_type": "HZ", "number": 1, "with_d1": True, "with_4df": True, "with_d5": True})
call("ua.payroll.report.wizard", "action_generate", [wiz])
atts = call("ir.attachment", "search_read", [["res_model", "=", "ua.payroll.report.wizard"], ["res_id", "=", wiz]], fields=["name"])
print("XML:", [a["name"] for a in atts])


# ---- залишок відпустки на дату впровадження (l10n_ua_payroll_rules), окремо й ідемпотентно ----------
def set_vacation_opening_balances():
    """Дата впровадження обліку відпусток компанії = 2026-01-01; початкові залишки (3-12 днів,
    правдоподібно) - лише працівникам, прийнятим на роботу до 2026 року (за найранішою версією
    контракту, з урахуванням повторного прийняття). Ідемпотентно: значення детерміновані
    (random.seed(2026) на початку файлу), просте write без створення записів."""
    call("res.company", "write", [COMPANY], {"ua_vacation_opening_date": "2026-01-01"})
    n = 0
    for i, (eid, name, code, extra) in created.items():
        first = call("hr.version", "search_read", [["employee_id", "=", eid]], fields=["contract_date_start"], order="contract_date_start", limit=1)
        if not first or not first[0]["contract_date_start"]:
            continue
        if first[0]["contract_date_start"] < "2026-01-01":
            ob = random.randint(3, 12)
            call("hr.employee", "write", [eid], {"ua_vacation_opening_balance": ob})
            n += 1
            print(f"{name}: залишок відпустки на 2026-01-01 = {ob} дн.")
    print(f"\nПочаткові залишки відпустки встановлено для {n} працівників (прийнятих до 2026 року).")


set_vacation_opening_balances()
