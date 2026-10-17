"""Наповнення стенду даними, схожими на реальні: ТОВ «Ясен Меблі», люди, кадри і зарплата.

Склад людей - scripts/demo_world/people.json, календар подій - scripts/demo_world/events.json,
опис світу - docs/base/demo-world.md. Історія йде місяць за місяцем із січня 2025 року
(scripts/demo_history.py): місяці до липня 2026 закриті, серпень проведено і виплачено,
вересень у роботі.

Ідемпотентно: працівників шукає за РНОКПП, компанію і довідники оновлює; закритий місяць
історії повторний прогін пропускає.
Адреса і база - зі змінних ODOO_URL і PAYROLL_DB (типово http://127.0.0.1:8110 і payroll).
Запуск: python3 scripts/demo_company.py"""
import sys
import json, os, urllib.request, random
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_history

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8110").rstrip("/") + "/jsonrpc"  # ODOO_URL=https://... для хмари
DB = os.environ.get("PAYROLL_DB", "payroll").strip(); PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
# браузерний User-Agent: Cloudflare відкидає urllib на хмарній адресі
_opener = urllib.request.build_opener(); _opener.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36")]; urllib.request.install_opener(_opener)
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
LT = {c: call("hr.leave.type", "search", [["work_entry_type_id.code", "=", c]])[0]
      for c in ["VAC", "SICK", "UNPAID", "MAT", "STUDY", "CHILD_VAC", "SICK_CARE", "CHILD3", "TRIP"]}


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
    "ua_payroll_bank_mode": "many", "ua_has_disabled": True, "ua_below_min_wage": True, "ua_opening_balances": True, "ua_booking_planned": True,
})
call("res.partner", "write", [co_partner], {"name": "ТОВ «Ясен Меблі»", "company_registry": EDRPOU})
# Рахунки бюджету для відомості на податки (ПДФО, військовий збір, ЄСВ): вигадані номери
# з правильним контрольним числом, код банку 899998 - Казначейство.
call("res.company", "write", [COMPANY], {"ua_iban_pdfo": iban_ua("899998", "0313040106000013001"),
                                         "ua_iban_vz": iban_ua("899998", "0313070106000013002"),
                                         "ua_iban_esv": iban_ua("899998", "0313080106000013003")})
# МФО - не BIC: у BIC вісім або одинадцять знаків, і OCA account_payment_order це перевіряє.
# Шість цифр коду банку НБУ пишемо в res.bank.ua_mfo (поле модуля l10n_ua_docs), bic лишаємо порожнім.
MFO = {"privat": "305299", "mono": "322001", "oschad": "300465"}
HAS_UA_MFO = "ua_mfo" in call("res.bank", "fields_get", [], {"attributes": []})


def bank_ref(key, name, city):
    vals = {"name": name, "city": city, "country": UA}
    if HAS_UA_MFO:
        vals["ua_mfo"] = MFO[key]
        return upsert("res.bank", [["ua_mfo", "=", MFO[key]]], vals)
    return upsert("res.bank", [["name", "=", name]], vals)


BANKS = {"privat": bank_ref("privat", "АТ КБ «ПриватБанк»", "Дніпро"),
         "mono": bank_ref("mono", "АТ «Універсал Банк» (monobank)", "Київ"),
         "oschad": bank_ref("oschad", "АТ «Ощадбанк»", "Київ")}
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
                   ("Верстатник деревообробних верстатів", "Виробництво"), ("Комерційний директор", "Відділ продажу"), ("Технік-конструктор", "Виробництво"), ("Монтажник меблів (ФОП)", "Виробництво"),
                   ("Менеджерка з персоналу", "Адміністрація")]:   # посади людей з історії вже є в цьому переліку
    JOBS[name] = upsert("hr.job", [["name", "=", name]], {"name": name, "department_id": DEPTS[dept], "company_id": COMPANY})
office_p = upsert("res.partner", [["name", "=", "Ясен Меблі, офіс"]], {"name": "Ясен Меблі, офіс", "street": "вул. Городоцька, 174", "city": "Львів", "zip": "79022", "country_id": UA, "parent_id": co_partner, "type": "other"})
shop_p = upsert("res.partner", [["name", "=", "Ясен Меблі, цех"]], {"name": "Ясен Меблі, цех", "street": "вул. Промислова, 8", "city": "Сокільники", "zip": "81130", "country_id": UA, "parent_id": co_partner, "type": "other"})
LOC = {"office": upsert("hr.work.location", [["name", "=", "Офіс, вул. Городоцька 174"]], {"name": "Офіс, вул. Городоцька 174", "location_type": "office", "address_id": office_p, "company_id": COMPANY}),
       "shop": upsert("hr.work.location", [["name", "=", "Цех, Сокільники"]], {"name": "Цех, Сокільники", "location_type": "other", "address_id": shop_p, "company_id": COMPANY}),
       "home": upsert("hr.work.location", [["name", "=", "Віддалено"]], {"name": "Віддалено", "location_type": "home", "address_id": office_p, "company_id": COMPANY})}

# ---- працівники -------------------------------------------------------------------------
# Склад - scripts/demo_world/people.json. Перші рядки - ті самі люди й у тому самому порядку,
# що були в цьому файлі списком P: на номер у списку спираються блоки нижче (E[3], E[12] ...).
# Далі - люди, які є лише в історії (звільнені, ЦПХ 2025 року) і мобілізований працівник.
PEOPLE = demo_history.load_people()


def _dates(extra):
    out = dict(extra)
    for k in ("end", "trial"):
        if out.get(k):
            out[k] = date.fromisoformat(out[k])
    return out


P = [(r["last_name"], r["first_name"], r["middle_name"], r["sex"], date.fromisoformat(r["birthday"]), r["job"], r["department"],
      r["wage"], r["fte"], r["kind"], r["main_job"], r["esv"], r["psp"], r["psp_children"], r["insurance_years"], r["marital"],
      r["children"], date.fromisoformat(r["hire"]), r["location"], tuple(r["education"]), r["city"], r["bank"], _dates(r["extra"]))
     for r in PEOPLE]
STREETS = ["вул. Личаківська", "вул. Наукова", "просп. Червоної Калини", "вул. Замарстинівська", "вул. Шевченка", "вул. Сихівська", "вул. Зелена", "вул. Стрийська"]
created = {}
for i, (ln, fn, mn, sex, bd, job, dept, wage, fte, kind, main, esv, psp, pspk, years, marital, kids, hire, loc, edu, city, bank, extra) in enumerate(P, 1):
    # Серійна частина стала для особи, не залежить від порядку в списку. extra["rnokpp"]
    # дозволяє прийняти людину, яка вже є в базі (з'явилася через справу прийняття),
    # замість того щоб завести їй двійника.
    code = extra.get("rnokpp") or rnokpp(bd, sex, 100 + sum(ord(c) for c in ln + fn) % 800)
    name = f"{ln} {fn} {mn}"
    rec = PEOPLE[i - 1]
    email_ln = rec["key"]   # латинка прізвища для пошти: стійкий ключ людини, а не позиція в списку
    vals = {
        "name": name, "sex": sex, "birthday": str(bd), "place_of_birth": city if city != "Львів" else "Львів", "country_of_birth": UA, "country_id": UA,
        "private_street": f"{random.choice(STREETS)}, {random.randint(2, 120)}, кв. {random.randint(1, 90)}", "private_city": city, "private_zip": f"79{random.randint(10, 69):03d}" if city == "Львів" else "81130",
        "private_country_id": UA, "private_phone": f"+380 67 {random.randint(100, 999)} {random.randint(10, 99)} {random.randint(10, 99)}", "private_email": f"{email_ln}@ukr.example",
        "marital": marital, "children": kids, "emergency_contact": random.choice(["Гаврилюк Олена (дружина)", "Мати", "Батько", "Брат", "Чоловік", "Дружина", "Сестра"]),
        "emergency_phone": f"+380 50 {random.randint(100, 999)} {random.randint(10, 99)} {random.randint(10, 99)}",
        "identification_id": f"ID-картка {random.randint(100000000, 999999999)}, орган 4620, {random.randint(1, 28):02d}.{random.randint(1, 12):02d}.{random.randint(2016, 2024)}",
        "passport_id": f"FL{random.randint(100000, 999999)}" if i % 3 == 0 else False,
        "work_email": f"{email_ln}@yasen-mebli.example", "work_phone": "+380 32 245 10 20", "mobile_phone": f"+380 63 {random.randint(100, 999)} {random.randint(10, 99)} {random.randint(10, 99)}",
        "company_id": COMPANY,
        "employee_type": "contractor" if kind in ("gph", "fop") else ("trainee" if extra.get("ct") == "Intern" else "employee"),
        "certificate": edu[0], "study_field": edu[1], "study_school": edu[2], "distance_home_work": random.randint(2, 25), "lang": "uk_UA", "tz": "Europe/Kyiv",
        "ua_rnokpp": code, "ua_contract_kind": kind, "ua_main_job": main, "ua_esv_category": esv, "ua_psp": psp, "ua_psp_children": pspk, "ua_fte": fte,
        "ua_insurance_years": years, "ua_hire_date": str(hire),
        "ua_last_name": ln, "ua_first_name": fn, "ua_middle_name": mn, "ua_full_time": fte == "1",
    }
    # Поля посади живуть у версії договору. Пишемо їх лише новій картці: у наявної «поточна»
    # версія може бути вже не версією прийняття (переведення, зміна окладу), і запис звідси
    # переписав би історію. З тієї ж причини не чіпаємо active і дату звільнення: їх веде наказ.
    position = {"job_title": job, "job_id": JOBS[job], "department_id": DEPTS[dept], "work_location_id": LOC[loc], "resource_calendar_id": CAL}
    eid = call("hr.employee", "search", [["ua_rnokpp", "=", code], ["active", "in", [True, False]]])
    if eid:
        eid = eid[0]; call("hr.employee", "write", [eid], vals)
    else:
        eid = call("hr.employee", "create", {**vals, **position})
    created[i] = (eid, name, code, extra)
    if kind in ("gph", "fop"):
        # Індексація - лише за трудовим договором. Правило INDEX виду відносин не питає, і без
        # цієї позначки підряднику-ФОП нараховувало індексацію, якої ніхто не виплачує.
        call("hr.employee", "write", [eid], {"ua_index_off": True})
        # Лана, 2026-09-16: ЦПХ/ФОП - контрагенти, не кадровий облік; номер/дата/строк договору для екрана «Договори ЦПХ».
        call("hr.employee", "write", [eid], {
            "ua_gph_contract_ref": f"{'Договір ЦПХ' if kind == 'gph' else 'Договір підряду'} № {i}",
            "ua_gph_contract_date": str(hire),
            "ua_gph_contract_end": str(extra["end"]) if extra.get("end") else False,
        })
    # версія контракту (Odoo 19: hr.version). Не version_id "поточної" версії: якщо працівник
    # уже отримав додаткову версію окремим кадровим наказом (переведення тощо), "поточна" на
    # сьогодні може бути саме вона, а не версія прийняття, - тоді запис ідемпотентності мав би
    # стерти дату версії наказу і зіткнути її з версією прийняття. Шукаємо версію прийняття за
    # датою; немає - як і раніше, поточну (перший запуск, до появи будь-яких наказів).
    ver_bootstrap = call("hr.version", "search_read", [["employee_id", "=", eid], ["date_version", "=", str(hire)]], fields=["contract_date_start"])
    ver = ver_bootstrap[0]["id"] if ver_bootstrap else call("hr.employee", "read", [eid], ["version_id"], context={"active_test": False})[0]["version_id"][0]
    has_contract = bool(ver_bootstrap and ver_bootstrap[0]["contract_date_start"])
    order = f"Наказ № {i + 11}-к від {hire.strftime('%d.%m.%Y')}"
    start_wage = rec.get("start_wage", wage)   # оклад на початок історії; далі його змінюють накази
    vvals = {"wage": start_wage, "date_version": str(hire), "contract_date_start": str(hire), "contract_date_end": str(extra["end"]) if extra.get("end") else False, "struct_id": STRUCT, "structure_type_id": STRUCT_TYPE,
             "resource_calendar_id": CAL, "contract_type_id": CT[extra.get("ct", "Permanent")], "job_title": job, "ua_order_ref": order, "ua_kp_code": extra.get("kp", ""), "ua_prof_name": job,
             "trial_date_end": str(extra["trial"]) if extra.get("trial") else False, "ua_internal_parttime": False,
             # погодинна оплата / скорочений тиждень (Лана, 2026-09-16): пільги за замовчуванням 40 год,
             # тут лише два виробничих працівники - HOURLY і скорочений тиждень
             "ua_pay_type": extra.get("pay_type", "monthly"), "ua_hour_rate": extra.get("hour_rate", 0.0),
             "ua_weekly_hours": extra.get("weekly_hours", 40.0), "ua_night_shifts": extra.get("night_shifts", False)}
    if has_contract:
        pass   # договір уже оформлено (цим скриптом раніше або наказом): версій не переписуємо
    elif rec.get("hire_order"):
        # прийняття проведе наказ у своєму місяці історії (demo_history.ev_hire): тут лише
        # переносимо початкову версію картки на дату прийняття, договірних полів не чіпаємо
        if not ver_bootstrap:
            call("hr.version", "write", [ver], {"date_version": str(hire)})
    else:
        call("hr.version", "write", [ver], vvals, context={"sync_contract_dates": True})
    # банківський рахунок для зарплатного проєкту
    partner = call("hr.employee", "read", [eid], ["work_contact_id"])[0]["work_contact_id"][0]
    acc = iban_ua(MFO[bank], f"0000026207{i:04d}{random.randint(10000, 99999)}"[:19].ljust(19, "0"))
    bid = call("res.partner.bank", "search", [["partner_id", "=", partner]])
    if bid:
        call("res.partner.bank", "write", [bid[0]], {"acc_number": acc, "bank_id": BANKS[bank], "acc_holder_name": name})
        bid = bid[0]
    else:
        bid = call("res.partner.bank", "create", {"acc_number": acc, "partner_id": partner, "bank_id": BANKS[bank], "acc_holder_name": name})
    call("hr.employee", "write", [eid], {"bank_account_ids": [(6, 0, [bid])], "primary_bank_account_id": bid})
    # Заробіток за 2024 рік - вхідні дані для середньої на дату впровадження обліку (2025-01-01).
    # Лише тим, хто працював до 2025 року; далі історію заробітку пишуть самі проведені листки.
    if kind == "employment" and hire < date(2025, 1, 1) and not call("ua.earnings.history", "search_count", [["employee_id", "=", eid], ["month", "<", "2025-01-01"]]):
        hist = []
        for m in range(1, 13):
            gross = start_wage * float(fte)
            if extra.get("BONUS"):
                gross += extra["BONUS"] if m in (3, 6, 9, 12) else (round(extra["BONUS"] / 2) if extra["BONUS"] > 5000 else extra["BONUS"])
            if job in ("Столяр", "Верстатник деревообробних верстатів") and m in (11, 12, 4):
                gross += 1500
            hist.append({"employee_id": eid, "month": f"2024-{m:02d}-01", "gross": round(gross, 2), "work_days": 21.0})
        call("ua.earnings.history", "create", hist)
    print(f"{i:2d}. {name} ({code}) {job}, {dept}, оклад {wage}, ставка {fte}")

# застарілі демо-картки (РНОКПП поза списком) прибираємо разом з листками. Працівників, узятих
# через справу прийняття (scripts/demo_hire.py, напр. Мельник) сюди не заносимо - той скрипт
# веде їх сам, і без цього винятку цей блок архівував/видаляв би їх щоразу як «застарілих»,
# бо їхній РНОКПП не входить у список demo_company.
codes = {v[2] for v in created.values()}
hired_via_case = {c["employee_id"][0] for c in
                  call("ua.hire.case", "search_read", [["employee_id", "!=", False]], fields=["employee_id"])}
stale = [e for e in call("hr.employee", "search_read", [["department_id", "in", list(DEPTS.values())], ["active", "in", [True, False]]], fields=["id", "ua_rnokpp"])
        if e["ua_rnokpp"] and e["ua_rnokpp"] not in codes and e["id"] not in hired_via_case]   # картка без РНОКПП - адміністратор бази, не демо-людина
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
# У ньому сидить лише картка адміністратора бази; українською він теж зветься «Адміністрація»,
# і в списку підрозділів їх було два. Картку переносимо до нашого підрозділу, зайвий архівуємо.
stray = [d for d in call("hr.department", "search_read", [["name", "=", "Administration"], ["id", "not in", list(DEPTS.values())]],
                         fields=["member_ids"], context={"lang": "en_US"})]
for d in stray:
    if d["member_ids"]:
        call("hr.employee", "write", d["member_ids"], {"department_id": DEPTS["Адміністрація"]})
    call("hr.department", "write", [d["id"]], {"active": False})
call("res.company", "write", [COMPANY], {"ua_director_name": created[1][1], "ua_director_rnokpp": created[1][2], "ua_accountant_name": created[2][1], "ua_accountant_rnokpp": created[2][2]})

# ---- поля картки, яких немає в P: ставка 0,75, сумісництво, інвалідність, пільги, військовий облік,
# документ, попередні місця роботи, підвищені ПСП - щоб кожне значення довідника мало хоч один приклад ---
E = {i: created[i][0] for i in created}   # id за номером у P, для стислості нижче
call("hr.employee", "write", [E[3]], {"ua_fte": "0.75"})   # Кушнір Галина: 0,75 ставки (замість повної)
romaniuk_hire_ver = call("hr.version", "search", [["employee_id", "=", E[12]], ["date_version", "=", "2012-05-14"]])   # версія прийняття, не "поточна" (вересень має власну нижче)
call("hr.version", "write", [romaniuk_hire_ver[0] if romaniuk_hire_ver else call("hr.employee", "read", [E[12]], ["version_id"])[0]["version_id"][0]], {"ua_internal_parttime": True})   # Романюк: внутрішній сумісник
call("hr.employee", "write", [E[9]], {"ua_disability_group": "3"})   # Прокопів: ЄСВ вже "disabled", тепер і сама група
call("hr.employee", "write", [E[13]], {"ua_single_parent": True})   # Федорів: одинока мати двох дітей
call("hr.employee", "write", [E[15]], {"ua_chernobyl_category": "3"})   # Гнатів: категорія ЧАЕС
call("hr.employee", "write", [E[1]], {"ua_id_doc_type": "passport_book"})   # Гаврилюк: паспорт-книжка
call("hr.employee", "write", [E[17]], {"ua_id_doc_type": "residence_permit"})   # Ткачук: посвідка на проживання
call("hr.employee", "write", [E[2]], {"ua_psp": "child150"})    # Стефанишин: ПСП на дітей 150 %
call("hr.employee", "write", [E[16]], {"ua_psp": "s150"})       # Крамар: підвищена ПСП 150 %
call("hr.employee", "write", [E[14]], {"ua_psp": "s200"})       # Данилюк: підвищена ПСП 200 %
# два різні ТЦК та СП - щоб список персонального обліку демонструвався окремо по кожному (l10n_ua_military
# веде списки саме так). Категорія обліку - лише "officers" / "ranks" (офіційна форма, постанова № 1487).
TCC1 = "Львівський РТЦК та СП"
TCC2 = "Галицький РТЦК та СП"
call("hr.employee", "write", [E[5]], {"ua_mil_status": "reserve", "ua_mil_doc_type": "ticket", "ua_mil_category": "ranks", "ua_mil_tcc": TCC1})   # Ковальчук: резервіст
call("hr.employee", "write", [E[6]], {"ua_mil_status": "removed", "ua_mil_doc_type": False})   # Мельничук
call("hr.employee", "write", [E[8]], {"ua_mil_status": "excluded", "ua_mil_doc_type": False})   # Шевчук
call("hr.employee", "write", [E[14]], {"ua_mil_status": "liable", "ua_mil_doc_type": "ticket", "ua_mil_fitness": "limited", "ua_mil_category": "officers", "ua_mil_tcc": TCC2,
                                       "ua_reserve_number": "РП-04521", "ua_reserve_date": "2026-08-15"})   # Данилюк: офіцер, резерв+ (юрисконсульт)
call("hr.employee", "write", [E[15]], {"ua_mil_status": "liable", "ua_mil_doc_type": "temp", "ua_mil_category": "ranks", "ua_mil_tcc": TCC1})   # Гнатів
call("hr.employee", "write", [E[16]], {"ua_mil_status": "liable", "ua_mil_doc_type": "ticket", "ua_mil_group": "vms", "ua_mil_category": "officers", "ua_mil_tcc": TCC2, "ua_mil_reserved": True,
                                       "ua_mil_reserve_order": "Рішення КЄК № 12 від 01.08.2026", "ua_mil_reserve_until": "2027-02-01"})   # Крамар: заброньований
call("hr.employee", "write", [E[17]], {"ua_mil_status": "liable", "ua_mil_doc_type": "ticket", "ua_mil_group": "other", "ua_mil_category": "ranks", "ua_mil_tcc": TCC1})   # Ткачук
call("hr.employee", "write", [E[2]], {"ua_mil_status": "liable", "ua_mil_doc_type": "ticket", "ua_mil_category": "ranks", "ua_mil_tcc": TCC1})   # Стефанишин: жінка, військовозобов'язана (окремий список)
PRIOR = {
    1: [("ТОВ «Львівмеблі»", "Заступник директора", date(2010, 3, 1), date(2015, 1, 30))],
    2: [("ПП «Аудит-Сервіс»", "Бухгалтер", date(2012, 6, 1), date(2016, 8, 31))],
    16: [("ТОВ «Карпати-Трейд»", "Менеджер із продажу", date(2005, 9, 1), date(2012, 10, 31)),
         ("ТОВ «Карпати-Трейд»", "Керівник відділу продажу", date(2012, 11, 1), date(2018, 10, 31))],
}
for pi, jobs in PRIOR.items():
    old = call("ua.employee.prior.job", "search", [["employee_id", "=", E[pi]]])
    if old:
        call("ua.employee.prior.job", "unlink", old)
    for company_name, job_title, d_from, d_to in jobs:
        call("ua.employee.prior.job", "create", {"employee_id": E[pi], "company_name": company_name, "job_title": job_title, "date_from": str(d_from), "date_to": str(d_to)})
print("\nДодаткові поля картки (ставка/сумісництво/інвалідність/пільги/військовий облік/попередні місця/ПСП) записано.")

# ---- залишок відпустки на дату впровадження (l10n_ua_payroll_rules), окремо й ідемпотентно ----------
# ---- поля картки і посади, які форма показує, а демо раніше лишало порожніми ---------------------------
# Заповнюємо там, де в справжньої компанії було б значення; чесно порожні поля перелічені
# в docs/base/demo-world.md.
import base64 as _b64
K = {r["key"]: created[i][0] for i, r in enumerate(PEOPLE, 1)}   # id картки за ключем людини


def _tag(name):
    ids = call("hr.employee.category", "search", [["name", "=", name]])
    return ids[0] if ids else call("hr.employee.category", "create", {"name": name})


TAGS = {n: _tag(n) for n in ["Керівництво", "Офіс", "Цех", "Склад", "Сумісництво", "Підрядник", "Матеріально відповідальна особа", "Мобілізований"]}
DEPT_TAG = {"Адміністрація": "Офіс", "Бухгалтерія": "Офіс", "Відділ продажу": "Офіс", "Виробництво": "Цех", "Склад і логістика": "Склад"}
for i, r in enumerate(PEOPLE, 1):
    tags = [TAGS[DEPT_TAG[r["department"]]]]
    if r["kind"] != "employment":
        tags = [TAGS["Підрядник"]]
    if r["key"] in ("havryliuk", "stefanyshyn", "kramar"):
        tags.append(TAGS["Керівництво"])
    if r["fte"] != "1" and r["kind"] == "employment":
        tags.append(TAGS["Сумісництво"] if r["key"] in ("boichuk", "romaniuk") else TAGS["Офіс"])
    if r["job"] == "Комірник":
        tags.append(TAGS["Матеріально відповідальна особа"])
    if r.get("mobilised_from"):
        tags.append(TAGS["Мобілізований"])
    call("hr.employee", "write", [created[i][0]], {"category_ids": [(6, 0, sorted(set(tags)))]})

# паспорт-книжка старого зразка: серія і номер (ID-картка серії не має)
for key, series, number in (("havryliuk", "КС", "418205"), ("romaniuk", "КА", "730914"), ("zakharchenko", "КВ", "256173")):
    call("hr.employee", "write", [K[key]], {"ua_id_doc_type": "passport_book", "ua_id_doc_series": series, "ua_id_doc_number": number})
call("hr.employee", "write", [K["prokopiv"]], {"ua_science_degree": "кандидат технічних наук"})
# витрати на водія - збут (доставка покупцям), а не загальновиробничі витрати підрозділу
call("hr.employee", "write", [K["shevchuk"]], {"ua_expense_account_id": account("93")})
alim_partner = upsert("res.partner", [["name", "=", "Шевчук Ольга Іванівна"]],
                      {"name": "Шевчук Ольга Іванівна", "city": "Львів", "country_id": UA, "comment": "Одержувачка аліментів за виконавчим листом № 2-1234/24"})
call("hr.employee", "write", [K["shevchuk"]], {"ua_alimony_partner_id": alim_partner})
# базовий місяць індексації - дата впровадження обліку; лише тим, кому оклад в історії не підвищували
for key in ("kovalchuk", "melnychuk", "tkachuk"):
    call("hr.employee", "write", [K[key]], {"ua_index_base": "2025-01-01"})
# наступники на посаді
call("hr.employee", "write", [K["kushnir"]], {"ua_previous_employee_id": K["lutsiv"]})
call("hr.employee", "write", [K["ivanychuk"]], {"ua_previous_employee_id": K["zakharchenko"]})
call("hr.employee", "write", [K["kramar"]], {
    "ua_reserve_file": _b64.b64encode("Витяг про бронювання військовозобов'язаного. Навчальні дані, не документ.".encode()).decode(),
    "ua_mil_note": "Заброньований за рішенням про бронювання; строк контролює кадрова служба."})
call("hr.employee", "write", [K["oliinyk"]], {"ua_mil_note": "Призваний під час мобілізації 2025-09-15. Місце роботи і посада збережені (ст. 119 КЗпП)."})
call("hr.employee", "write", [K["danyliuk"]], {"ua_mil_note": "Офіцер запасу; дані звірено з ТЦК та СП під час прийняття."})

# освіта і досвід у резюме, навички - усім
RL = {t["name"]: t["id"] for t in call("hr.resume.line.type", "search_read", [], fields=["name"], context={"lang": "en_US"})}
EDU_YEARS = {"master": 5, "bachelor": 4, "other": 3}
SKILL = {s["name"]: s["id"] for s in call("hr.skill", "search_read", [], fields=["name"], context={"lang": "en_US"})}
LEVEL = {(l["skill_type_id"][1], l["name"]): (l["id"], l["skill_type_id"][0])
         for l in call("hr.skill.level", "search_read", [], fields=["name", "skill_type_id"], context={"lang": "en_US"})}
SOFT = {"Адміністрація": "Organizational", "Бухгалтерія": "Time Management", "Відділ продажу": "Persuasion",
        "Виробництво": "Problem-Solving", "Склад і логістика": "Teamwork"}
for i, r in enumerate(PEOPLE, 1):
    eid = created[i][0]
    bd, hire_day = date.fromisoformat(r["birthday"]), date.fromisoformat(r["hire"])
    if RL.get("Education") and not call("hr.resume.line", "search_count", [["employee_id", "=", eid], ["line_type_id", "=", RL["Education"]]]):
        level, field, school = r["education"]
        start = date(bd.year + 17, 9, 1)
        lines = [{"employee_id": eid, "line_type_id": RL["Education"], "name": school, "description": field,
                  "date_start": str(start), "date_end": str(date(start.year + EDU_YEARS.get(level, 3), 6, 30))}]
        for company_name, job_title, d_from, d_to in PRIOR.get(i, []):
            lines.append({"employee_id": eid, "line_type_id": RL.get("Other Experience") or RL["Education"], "name": company_name,
                          "description": job_title, "date_start": str(d_from), "date_end": str(d_to)})
        call("hr.resume.line", "create", lines)
    if SKILL and not call("hr.employee.skill", "search_count", [["employee_id", "=", eid]]):
        english = "B2" if r["key"] in ("kramar", "dziuba", "boichuk", "danyliuk", "lozynskyi") else ("B1" if r["education"][0] != "other" else "A2")
        soft = SOFT[r["department"]]
        rows = []
        for skill, type_name, level in (("English", "Languages", english), (soft, "Soft Skills", "Advanced" if r["insurance_years"] >= 10 else "Intermediate"),
                                        ("Leadership", "Soft Skills", "Expert") if r["key"] in ("havryliuk", "stefanyshyn", "kramar") else (None, None, None)):
            if skill and SKILL.get(skill) and LEVEL.get((type_name, level)):
                rows.append({"employee_id": eid, "skill_id": SKILL[skill], "skill_level_id": LEVEL[(type_name, level)][0],
                             "skill_type_id": LEVEL[(type_name, level)][1]})
        try:
            call("hr.employee.skill", "create", rows)
        except SystemExit as exc:
            print("Навички не записано:", str(exc)[:160])

# посади: вид договору і короткий опис обов'язків
JOB_TEXT = {
    "Директор": "Керує підприємством, підписує накази і договори, затверджує штатний розпис і звітність.",
    "Головний бухгалтер": "Веде бухгалтерський і податковий облік, закриває місяць, подає звітність.",
    "Бухгалтер": "Первинні документи, банк, розрахунки з постачальниками і покупцями, зарплата.",
    "Менеджер із збуту": "Веде покупців, готує комерційні пропозиції і замовлення, контролює оплату.",
    "Столяр": "Виготовляє деталі й складає меблі за кресленнями і специфікаціями.",
    "Комірник": "Приймає, зберігає і видає матеріали та готову продукцію; матеріально відповідальна особа.",
    "Водій автотранспортних засобів": "Доставляє меблі покупцям і матеріали на склад, веде подорожні листи.",
    "Інженер-технолог": "Розробляє технологічні карти, норми витрат матеріалів, контролює якість.",
    "Дизайнер меблів": "Розробляє ескізи і візуалізації нових моделей.",
    "Фахівець з маркетингу": "Реклама, сайт, каталог, виставки.",
    "Прибиральник службових приміщень": "Прибирає офіс і побутові приміщення цеху.",
    "Пакувальник": "Пакує готові вироби, маркує, готує до відвантаження.",
    "Юрисконсульт": "Договори, претензії, супровід кадрових рішень.",
    "Верстатник деревообробних верстатів": "Працює на розкрійних і фрезерних верстатах, налагоджує їх.",
    "Комерційний директор": "Відповідає за продажі, ціни і ключових покупців.",
    "Технік-конструктор": "Готує креслення і специфікації виробів.",
    "Монтажник меблів (ФОП)": "Монтаж меблів у покупця за договором підряду.",
    "Менеджерка з персоналу": "Прийняття, накази, особові картки, табель, військовий облік.",
}
for job_name, text in JOB_TEXT.items():
    if job_name in JOBS:
        call("hr.job", "write", [JOBS[job_name]], {"description": "<p>%s</p>" % text,
                                                   "contract_type_id": CT["Temporary" if "ФОП" in job_name or job_name == "Дизайнер меблів" else "Permanent"]})
print("Картки: теги, серії паспортів, науковий ступінь, одержувач аліментів, резюме і навички; посади: опис і вид договору.")

OPENING_DAY = "2025-01-01"   # дата впровадження обліку: з неї йде історія місяців


def set_vacation_opening_balances():
    """Дата впровадження обліку відпусток компанії = 2025-01-01, разом з усім обліком; початкові
    залишки (3-12 днів, правдоподібно) - лише працівникам, прийнятим на роботу до 2025 року (за найранішою версією
    контракту, з урахуванням повторного прийняття). Ідемпотентно: значення детерміновані
    (random.seed(2026) на початку файлу), просте write без створення записів."""
    call("res.company", "write", [COMPANY], {"ua_vacation_opening_date": OPENING_DAY})
    n = 0
    for i, (eid, name, code, extra) in created.items():
        if call("hr.employee", "read", [eid], ["ua_vacation_opening_balance"], context={"active_test": False})[0]["ua_vacation_opening_balance"]:
            random.randint(3, 12)   # залишок уже стоїть: число тягнемо, щоб решта лишилася тією самою
            continue
        first = call("hr.version", "search_read", [["employee_id", "=", eid]], fields=["contract_date_start"], order="contract_date_start", limit=1)
        if not first or not first[0]["contract_date_start"]:
            continue
        if first[0]["contract_date_start"] < OPENING_DAY:
            ob = random.randint(3, 12)
            call("hr.employee", "write", [eid], {"ua_vacation_opening_balance": ob})
            n += 1
            print(f"{name}: залишок відпустки на {OPENING_DAY} = {ob} дн.")
    print(f"\nПочаткові залишки відпустки встановлено для {n} працівників (прийнятих до 2025 року).")


set_vacation_opening_balances()

# ---- додаткові відпустки за Законом «Про відпустки»: УБД (ст. 16-2), на дітей (ст. 19), особливі
# умови праці (ст. 8) - по одному прикладу на кожну підставу, ідемпотентно (write/search-or-create) ------
call("hr.employee", "write", [E[8]], {"ua_veteran": True})              # Шевчук: УБД, додаткова відпустка 14 днів (ст. 16-2)
call("hr.employee", "write", [E[2]], {"ua_special_leave_days": 4})      # Стефанишин: особливий характер праці (бухгалтерія, комп'ютер), 4 дні (ст. 8)
call("hr.employee", "write", [E[6]], {"ua_soc_child_disabled_child": True})  # Мельничук: дитина з інвалідністю - підстава ст. 19

for child_name, child_bd in [("Ковальчук Тарас Романович", "2015-05-20"), ("Ковальчук Софія Романівна", "2018-09-02")]:
    if not call("ua.employee.child", "search", [["employee_id", "=", E[5]], ["name", "=", child_name]]):
        call("ua.employee.child", "create", {"employee_id": E[5], "name": child_name, "birthday": child_bd})   # Ковальчук: двоє дітей до 15 років - підстава ст. 19

alloc_targets = [E[5], E[6], E[8], E[2], E[13]]   # Ковальчук (діти), Мельничук (дитина з інвалідністю), Шевчук (УБД), Стефанишин (особливі умови), Федорів (одинока мати)
call("hr.employee", "ua_ensure_allocations", alloc_targets)
print("Додаткові відпустки (УБД, на дітей, особливі умови праці): підстави записано, річне нарахування соціальної на дітей виконано.")

# ---- історія місяць за місяцем: січень 2025 - серпень 2026 ------------------------------------------
# Кожен місяць іде шляхом бухгалтера (scripts/demo_history.py): накази і відсутності місяця,
# чернетки листків, табель, аванс, розрахунок, відомості на перерахування з рядками виписки,
# заява-розрахунок ПФУ, об'єднана звітність, закриття. Закритий місяць повторний прогін пропускає.
KEYS = [r["key"] for r in PEOPLE]
EMP = {KEYS[i - 1]: created[i][0] for i in created}
HISTORY = demo_history.History(call, COMPANY, PEOPLE, EMP, {
    "depts": DEPTS, "ct": CT, "leave_types": LT, "struct": STRUCT, "struct_type": STRUCT_TYPE, "cal": CAL})
print("\nІсторія компанії: місяці з %02d.%s" % (demo_history.FIRST_MONTH[1], demo_history.FIRST_MONTH[0]))
for _y, _m in demo_history.months_range(demo_history.FIRST_MONTH, demo_history.LAST_CLOSED):
    if HISTORY.is_closed(_y, _m):
        HISTORY.catch_up(_y, _m)
        continue
    HISTORY.run_month(_y, _m, "closed")
run_aug, _aug_rows = HISTORY.run_month(*demo_history.PAID_MONTH, "paid")
aug = {i: _aug_rows[KEYS[i - 1]] for i in created if KEYS[i - 1] in _aug_rows}   # рядки серпня за номером у списку - для виписки нижче

# ---- MINSAL (доплата до мінімальної) на одному листку за один місяць: правило порівнює оклад із
# мінімальною зарплатою (8647 грн з 2026-01-01), пропорційно ставці - обидві частини пропорції
# масштабуються однаково, тож окладу нижче мінімалки не уникнути жодним відпрацьованим часом чи
# ставкою. Жоден із окладів у P не нижчий за мінімалку, тому MINSAL ніколи не мала прикладу -
# додаємо окрему версію контракту лише на вересень (серпень і раніше лишаються з чинним окладом).
minsal_ver = call("hr.version", "search", [["employee_id", "=", E[12]], ["date_version", "=", "2026-09-01"]])   # Романюк
if not minsal_ver:
    cur12 = call("hr.employee", "read", [E[12]], ["version_id"])[0]["version_id"][0]
    base12 = call("hr.version", "read", [cur12], ["contract_date_start", "contract_date_end", "struct_id", "structure_type_id",
                                                   "resource_calendar_id", "contract_type_id", "job_title", "ua_kp_code", "ua_prof_name"])[0]
    call("hr.version", "create", {
        "employee_id": E[12], "date_version": "2026-09-01", "wage": 8000,   # нижче мінімалки 8647 (2026)
        "contract_date_start": base12["contract_date_start"], "contract_date_end": base12["contract_date_end"],
        "struct_id": base12["struct_id"][0], "structure_type_id": base12["structure_type_id"][0],
        "resource_calendar_id": base12["resource_calendar_id"][0], "contract_type_id": base12["contract_type_id"][0],
        "job_title": base12["job_title"], "ua_kp_code": base12["ua_kp_code"], "ua_prof_name": base12["ua_prof_name"],
        "ua_order_ref": "Наказ № 64-к від 28.08.2026 (тимчасове зниження окладу до 8000 грн на вересень)",
    }, context={"sync_contract_dates": True})
    print("Романюк: окрема версія на вересень 2026, оклад 8000 грн (нижче мінімалки) - для перевірки MINSAL.")

# ---- відпустки і відрядження поза стандартним списком extra["leaves"]: навчальна, на дітей, догляд,
# догляд за дитиною до 3, відрядження (з наказом), одна на розгляді, одна відхилена ------------------
def leave_upsert(eid, lcode, d1, d2, order_ref=False, sick_number=False):
    ids = call("hr.leave", "search", [["employee_id", "=", eid], ["holiday_status_id", "=", LT2[lcode]], ["request_date_from", "=", d1]])
    if ids:
        return ids[0]
    return call("hr.leave", "create", {"employee_id": eid, "holiday_status_id": LT2[lcode], "request_date_from": d1, "request_date_to": d2,
                                       "ua_order_ref": order_ref, "ua_sick_number": sick_number})


LT2 = LT

study_id = leave_upsert(E[14], "STUDY", "2026-09-07", "2026-09-18", "Наказ № 60-в від 04.09.2026")   # Данилюк: сесія
if call("hr.leave", "read", [study_id], ["state"])[0]["state"] not in ("validate",):
    call("hr.leave", "action_approve", [study_id])

childvac_id = leave_upsert(E[13], "CHILD_VAC", "2026-09-14", "2026-09-17", "Наказ № 61-в від 11.09.2026")   # Федорів: додаткова на дітей
if call("hr.leave", "read", [childvac_id], ["state"])[0]["state"] not in ("validate",):
    call("hr.leave", "action_approve", [childvac_id])

sickcare_id = leave_upsert(E[7], "SICK_CARE", "2026-09-21", "2026-09-23")   # Іваничук: догляд за хворою дитиною
if call("hr.leave", "read", [sickcare_id], ["state"])[0]["state"] not in ("validate",):
    call("hr.leave", "action_approve", [sickcare_id])

child3_id = leave_upsert(E[13], "CHILD3", "2026-10-01", "2026-10-31", "Наказ № 62-в від 28.09.2026")   # Федорів: догляд за дитиною до 3 років, жовтень
if call("hr.leave", "read", [child3_id], ["state"])[0]["state"] not in ("validate",):
    call("hr.leave", "action_approve", [child3_id])

# відрядження: і як лист відсутності (TRIP), і окремим наказом типу trip (реєстрація/друк, даних не чіпає)
trip_id = leave_upsert(E[4], "TRIP", "2026-09-28", "2026-09-30", "Наказ № 63-в від 25.09.2026")   # Дзюба: відрядження до Києва
if call("hr.leave", "read", [trip_id], ["state"])[0]["state"] not in ("validate",):
    call("hr.leave", "action_approve", [trip_id])
trip_orders = call("ua.hr.order", "search", [["employee_id", "=", E[4]], ["order_type", "=", "trip"], ["date_from", "=", "2026-09-28"]])
if not trip_orders:
    trip_oid = call("ua.hr.order", "create", {"order_type": "trip", "employee_id": E[4], "company_id": COMPANY, "date": "2026-09-25",
                                               "date_from": "2026-09-28", "date_to": "2026-09-30", "destination": "Київ, ТОВ «Меблевий дім Галичина»",
                                               "purpose": "перемовини щодо постачання фасадів"})
    call("ua.hr.order", "action_post", [trip_oid])
else:
    trip_oid = trip_orders[0]

# одна відпустка на розгляді (state=confirm), не проведена - навмисно без action_approve
pending_ids = call("hr.leave", "search", [["employee_id", "=", E[11]], ["request_date_from", "<=", "2026-09-22"], ["request_date_to", ">=", "2026-09-21"], ["state", "not in", ["refuse", "cancel"]]])  # будь-яка відпустка, що перетинає ці дні
if not pending_ids:
    call("hr.leave", "create", {"employee_id": E[11], "holiday_status_id": LT["UNPAID"], "request_date_from": "2026-09-21", "request_date_to": "2026-09-22"})   # Бойчук: заявка ще не розглянута

# одна відпустка відхилена (state=refuse)
refused_ids = call("hr.leave", "search", [["employee_id", "=", E[3]], ["holiday_status_id", "=", LT["VAC"]], ["request_date_from", "=", "2026-09-14"]])
if refused_ids:
    refused_id = refused_ids[0]
    if call("hr.leave", "read", [refused_id], ["state"])[0]["state"] == "refuse":
        pass
    else:
        call("hr.leave", "action_refuse", [refused_id])
else:
    refused_id = call("hr.leave", "create", {"employee_id": E[3], "holiday_status_id": LT["VAC"], "request_date_from": "2026-09-14", "request_date_to": "2026-09-16"})
    call("hr.leave", "action_approve", [refused_id])
    call("hr.leave", "action_refuse", [refused_id])
print("Відпустки/відрядження поза стандартним переліком (навчальна, на дітей, догляд, до 3 років, відрядження, на розгляді, відхилена) записано.")

# ---- кадрові накази поза hire/leave/dismissal, що вже проводяться автоматично: переведення,
# скасоване звільнення, чернетка зміни окладу, наказ, доведений до "ознайомлено" ------------------------
def order_upsert(order_type, eid, extra_domain, vals):
    ids = call("ua.hr.order", "search", [["employee_id", "=", eid], ["order_type", "=", order_type]] + extra_domain)
    return ids[0] if ids else call("ua.hr.order", "create", {"order_type": order_type, "employee_id": eid, "company_id": COMPANY, **vals})


# переведення Панчишин з Виробництва до Відділу продажу
transfer_id = order_upsert("transfer", E[20], [["date_from", "=", "2026-09-01"]],
                           {"date": "2026-08-28", "date_from": "2026-09-01", "department_id": DEPTS["Відділ продажу"], "prof_name": "Менеджер із збуту"})
if call("ua.hr.order", "read", [transfer_id], ["state"])[0]["state"] == "draft":
    call("ua.hr.order", "action_post", [transfer_id])
if call("ua.hr.order", "read", [transfer_id], ["state"])[0]["state"] == "posted":
    call("ua.hr.order", "action_acknowledge", [transfer_id])   # наказ, доведений до "ознайомлено"

# звільнення Шевчука, потім скасоване (перше проведення - помилка кадровика). Проведення і
# скасування скидають наказ назад у "чернетка", тому саму лише перевірку стану не можна брати
# за ознаку "вже показали цей сценарій" - на повторному запуску вона знову провела б і
# скасувала наказ. Ознака - чи знайдено ІСНУЮЧИЙ запис: дію робимо лише для щойно створеного.
dismiss_ids = call("ua.hr.order", "search", [["employee_id", "=", E[8]], ["order_type", "=", "dismissal"],
                                             ["date_to", "=", "2026-09-30"]])
if dismiss_ids:
    dismiss_id = dismiss_ids[0]
else:
    dismiss_id = call("ua.hr.order", "create", {"order_type": "dismissal", "employee_id": E[8], "company_id": COMPANY,
                                                "date": "2026-09-25", "date_to": "2026-09-30",
                                                "dismissal_basis": "ст. 38 КЗпП (заява працівника)"})
    call("ua.hr.order", "action_post", [dismiss_id])
    call("ua.hr.order", "action_cancel", [dismiss_id])   # наказ про звільнення скасовано

# чернетка зміни окладу (Кушнір) - не проводиться навмисно
wage_draft_id = order_upsert("wage", E[3], [["date_from", "=", "2026-10-01"]], {"date": "2026-09-22", "date_from": "2026-10-01", "wage": 28000})
print("Накази поза автоматичними гаками (переведення, скасоване звільнення, чернетка окладу, ознайомлення) записано.")

# розхідна консистентність: _post_dismissal тепер архівує працівника (фікс баг-репорту), але
# накази, проведені ДО фіксу (напр. Гнатів, 44-к), лишились активними - виправляємо разово,
# ідемпотентно, за будь-якого проведеного наказу про звільнення.
# Наказ про звільнення - не остаточне слово: людину могли прийняти знову (Ткачук,
# звільнений 31.05.2026 і прийнятий 17.08.2026). Архівуємо лише тих, чия поточна версія
# вже закінчилася. Інакше працівник, який зараз працює, зникає з «Людей», зі штатного
# розпису і з повідомлення до ТЦК - саме так Ткачук і випав.
posted_dismissals = call("ua.hr.order", "search_read", [["order_type", "=", "dismissal"], ["state", "=", "posted"]],
                         fields=["employee_id"])
to_archive, to_restore = [], []
for d in {x["employee_id"][0] for x in posted_dismissals}:
    emp = call("hr.employee", "read", [d], ["active", "version_id"], context={"active_test": False})[0]
    ver = emp["version_id"] and call("hr.version", "read", [emp["version_id"][0]], ["contract_date_end"])[0]
    end = ver and ver.get("contract_date_end")
    works_now = not end or str(end) >= str(date.today())
    if works_now and not emp["active"]:
        to_restore.append(d)
    elif not works_now and emp["active"]:
        to_archive.append(d)
if to_archive:
    call("hr.employee", "write", to_archive, {"active": False})
    print("Архівовано за проведеним наказом про звільнення:", to_archive)
if to_restore:
    call("hr.employee", "write", to_restore, {"active": True})
    print("Повернуто з архіву (прийняті знову після звільнення):", to_restore)

# ---- документи працівника (ua.employee.document): типи й стани підпису на чотирьох картках -------------
def doc_upsert(eid, dtype, name, **extra):
    ids = call("ua.employee.document", "search", [["employee_id", "=", eid], ["type", "=", dtype], ["name", "=", name]])
    vals = {"employee_id": eid, "type": dtype, "name": name, **extra}
    if ids:
        call("ua.employee.document", "write", [ids[0]], vals); return ids[0]
    return call("ua.employee.document", "create", vals)


d1 = doc_upsert(E[1], "contract", "Трудовий договір № 1", number="1", date="2015-02-02", state="to_sign")
call("ua.employee.document", "action_mark_signed", [d1])
d2 = doc_upsert(E[1], "nda", "Договір про нерозголошення", date="2015-02-02", state="to_sign")
call("ua.employee.document", "action_mark_signed", [d2])
doc_upsert(E[1], "labor_book", "Трудова книжка", number="АА № 123456", date="2000-08-15")
d4 = doc_upsert(E[2], "consent", "Згода на обробку персональних даних", date="2016-09-01", state="to_sign")
call("ua.employee.document", "action_mark_signed", [d4])
doc_upsert(E[2], "ack", "Лист ознайомлення з Положенням про облік і оплату праці", date="2026-09-01", state="to_sign")   # лишається "на підпис"
doc_upsert(E[5], "military_id", "Військовий квиток", number="ВК 112233")
doc_upsert(E[5], "order", "Наказ про прийняття на роботу", report_xmlid="", state="to_sign")   # наказ на підпис, ще не проведений як звіт
doc_upsert(E[9], "medical", "Медична довідка про придатність", date="2025-06-01", valid_until="2026-06-01")   # прострочена (валідна до минулого)
print("Документи працівників (трудова, військовий, договір, NDA, згода, ознайомлення, наказ; на підпис/підписано/прострочений) записано.")

# ---- штатний розпис, авансова відомість, відомості на виплату, військовий облік, довідка про доходи ----
staff_ids = call("ua.staff.list", "search", [["date", "=", "2026-09-01"]])
staff_id = staff_ids[0] if staff_ids else call("ua.staff.list", "create", {"company_id": COMPANY, "date": "2026-09-01"})
# Розпис перераховуємо щоразу, навіть затверджений. У продукті затверджений документ - це
# історія, і переписувати його не можна; тут документ породжує сам генератор демо, і якщо
# його не оновити, він назавжди лишиться таким, яким був до появи нових людей: рядок без
# коду КП (Мельник) і без тих, кого повернули з архіву (Ткачук).
if call("ua.staff.list", "read", [staff_id], ["state"])[0]["state"] != "draft":
    call("ua.staff.list", "action_draft", [staff_id])
call("ua.staff.list", "action_refill", [staff_id])
call("ua.staff.list", "action_confirm", [staff_id])

print("Штатний розпис (затверджено) записано.")
# Відомості на виплату (аванс за серпень, інша за вересень) заповнюються нижче, ПІСЛЯ
# month_batch(2026, 8, ...): action_fill для kind="advance" читає рядки ua.advance.sheet за
# рік/місяць, а та відомість наповнюється й затверджується лише всередині month_batch, коли
# серпневі листки вже створені (advance=True, рядки 505+). На свіжій базі (хмара) до
# month_batch тут ще нема жодного серпневого листка - виклик тут (до створення листків) завжди
# давав порожню відомість і action_confirm падав на «Немає рядків. Натисніть «Перерахувати»».

# три документи військового обліку: список персонального обліку, список заброньованих, повідомлення
# список персонального обліку - по одному документу на кожен ТЦК (TCC1, TCC2 вище), розділ "Усі розділи"
mlist_ids_all = call("ua.military.list", "action_create_all_tcc", COMPANY, "2026-09-15", "all")
for mlist_id in mlist_ids_all:
    if call("ua.military.list", "read", [mlist_id], ["state"])[0]["state"] == "draft":
        call("ua.military.list", "action_confirm", [mlist_id])

mres_ids = call("ua.military.reserved", "search", [["date", "=", "2026-09-15"]])
mres_id = mres_ids[0] if mres_ids else call("ua.military.reserved", "create", {"company_id": COMPANY, "date": "2026-09-15"})
if call("ua.military.reserved", "read", [mres_id], ["state"])[0]["state"] == "draft":
    call("ua.military.reserved", "action_refill", [mres_id])
    call("ua.military.reserved", "action_confirm", [mres_id])

mnotice_ids = call("ua.military.notice", "search", [["date_from", "=", "2026-08-01"], ["date_to", "=", "2026-08-31"]])
mnotice_id = mnotice_ids[0] if mnotice_ids else call("ua.military.notice", "create", {"company_id": COMPANY, "date_from": "2026-08-01", "date_to": "2026-08-31"})   # у серпні прийняті Данилюк і Ткачук (обидва підлягають обліку)
if call("ua.military.notice", "read", [mnotice_id], ["state"])[0]["state"] == "draft":
    call("ua.military.notice", "action_refill", [mnotice_id])
    call("ua.military.notice", "action_confirm", [mnotice_id])
# другий, окремий: change_kind = "change" (зміна облікових даних, не прийняття/звільнення)
mnotice2_ids = call("ua.military.notice", "search", [["date_from", "=", "2026-09-16"], ["date_to", "=", "2026-09-30"]])
if mnotice2_ids:
    mnotice2_id = mnotice2_ids[0]
else:
    mnotice2_id = call("ua.military.notice", "create", {"company_id": COMPANY, "date_from": "2026-09-16", "date_to": "2026-09-30",
                                                         "line_ids": [(0, 0, {"employee_id": E[16], "full_name": created[16][1], "birthday": "1980-11-23",
                                                                              "rnokpp": created[16][2], "change_kind": "change",
                                                                              "date": "2026-09-16", "tcc": TCC2})]})
if call("ua.military.notice", "read", [mnotice2_id], ["state"])[0]["state"] == "draft":
    call("ua.military.notice", "action_confirm", [mnotice2_id])
print("Три документи військового обліку (список обліку, заброньовані, повідомлення) затверджено; друге повідомлення (зміна даних) додано.")

# довідка про доходи стоїть нижче, після пакетів листків: майстер читає проведені листки
# за період і на чистій базі падав би з «За цей період немає проведених розрахункових листків».

# Люди, які лишилися тільки в історії: картка в архіві. Звільнених архівує наказ; договір ЦПХ
# закінчується без наказу, тому картку підрядника 2025 року прибираємо з активних тут.
_left = [EMP[r["key"]] for r in PEOPLE if r.get("left")]
_still = call("hr.employee", "search", [["id", "in", _left], ["active", "=", True]])
if _still:
    call("hr.employee", "write", _still, {"active": False})

# ---- вересень 2026: місяць у роботі, чернетки листків ------------------------------------------------
HISTORY.run_month(*demo_history.DRAFT_MONTH, "draft")

# довідка про доходи - документ ua.income.certificate (список довідок і є реєстром).
# Місце має значення - листки за лютий-липень мають бути проведені до виклику,
# інакше документ без рядків і видати його не можна.
cert_ids = call("ua.income.certificate", "search", [["employee_id", "=", E[1]], ["date_from", "=", "2026-02-01"]])
if not cert_ids:
    cert_ids = call("ua.income.certificate", "ua_compose", COMPANY, employee=E[1], date_from="2026-02-01", date_to="2026-07-31")
    call("ua.income.certificate", "write", cert_ids, {"purpose": "для подання до банку"})
    call("ua.income.certificate", "action_confirm", cert_ids)
print("Довідка про доходи видана (список довідок про доходи).")


# ---- відомість «Інша виплата» за вересень: чернетка, щоб список мав і незавершений документ ---------
# Відомість на перерахування - це платіжне доручення OCA (account.payment.order). Аванс і зарплату
# кожного місяця історії проводить demo_history; тут лише чернетка іншої виплати.
PAY_SETUP = call("res.company", "ua_payment_setup", [COMPANY])
if not call("account.payment.order", "search", [["ua_year", "=", 2026], ["ua_month", "=", 9], ["ua_kind", "=", "other"]]):
    call("account.payment.order", "create", {
        "payment_mode_id": PAY_SETUP["salary"], "journal_id": PAY_SETUP["journal"], "date_prefered": "now",
        "ua_kind": "other", "ua_year": 2026, "ua_month": 9, "ua_pay_date": "2026-09-25",
        "ua_note": "Матеріальна допомога і компенсація за наказом окремо від зарплатного циклу"})
print("Відомості на виплату: аванс і зарплата кожного місяця проведені, інша виплата за вересень - чернетка.")

# ---- далі скрипт ще пише в закриті місяці ------------------------------------------------------------
# Перезбір банківської виписки видаляє рядки виписки журналу і імпортує їх заново. На другому
# прогоні серед них уже є липневі (їх дописує demo_business.py під липневі платежі), і видалення
# впирається в глобальну дату блокування, яку цей самий скрипт щойно поставив. Знімаємо її до
# кінця файлу і повертаємо в останньому рядку - так само, як demo_business.py робить навколо
# своєї частини.
_saved_lock = call("res.company", "read", [COMPANY], ["fiscalyear_lock_date"])[0]["fiscalyear_lock_date"]
if _saved_lock:
    call("res.company", "write", [COMPANY], {"fiscalyear_lock_date": False})
    print(f"Дату блокування {_saved_lock} тимчасово знято до кінця скрипта.")

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
# Імпортуємо один раз. Раніше тут спершу вимітало ВСІ виписки і рядки журналу, а на
# другому прогоні серед них уже були липневі рядки і рядки під платежі постачальникам,
# які дописує demo_business.py: видалення впиралося в дату блокування, а те, що встигло
# зникнути, ніхто не відновлював - гроші зависали на 333 «в дорозі».
if call("account.bank.statement", "search_count", [["journal_id", "=", jr]]):
    print(f"\nВиписка за серпень уже в журналі банку - імпорт пропущено ({csv_path}).")
else:
    wid = call("account.statement.import", "create", {"statement_file": base64.b64encode(open(csv_path, "rb").read()).decode(), "statement_filename": os.path.basename(csv_path), "sheet_mapping_id": mp}, context={"journal_id": jr})
    call("account.statement.import", "import_file_button", [wid], context={"journal_id": jr})
    print(f"\nВиписка: {len(rows) - 1} операцій імпортовано у журнал банку ({csv_path})")

# ---- об'єднана звітність за серпень: XML у вкладеннях майстра ---------------------------------------
wiz = call("ua.payroll.report.wizard", "create", {"company_id": COMPANY, "year": 2026, "month": 8, "doc_type": "HZ", "number": 1, "with_d1": True, "with_4df": True, "with_d5": True})
call("ua.payroll.report.wizard", "action_generate", [wiz])
atts = call("ir.attachment", "search_read", [["res_model", "=", "ua.payroll.report.wizard"], ["res_id", "=", wiz]], fields=["name"])
print("XML:", [a["name"] for a in atts])


# ---- повертаємо дату блокування, зняту після закриття липня ----------------------------------------
if _saved_lock:
    call("res.company", "write", [COMPANY], {"fiscalyear_lock_date": _saved_lock})
    print(f"Дату блокування повернуто: {_saved_lock}.")

HISTORY.summary()
