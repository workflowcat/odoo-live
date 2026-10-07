"""Наповнення військового обліку демо-даними для ТОВ «Ясен Меблі».

Ідемпотентно: шукає працівників за company_id + сектю/вік, пише поля ua_mil_* напряму (без create).
База читається зі змінної середовища PAYROLL_DB (типово payroll). Запуск: PAYROLL_DB=payroll_test python3 scripts/demo_military.py"""
import json
import os
import urllib.request
from datetime import date

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8110").rstrip("/") + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
TODAY = date(2026, 9, 9)


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(), {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def age(birthday, on=TODAY):
    b = date.fromisoformat(birthday)
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


COMPANY = call("res.company", "search", [["name", "ilike", "Ясен Меблі"]])
COMPANY = COMPANY[0] if COMPANY else 1

employees = call("hr.employee", "search_read", [
    ["company_id", "=", COMPANY], ["name", "not ilike", "Еталон"], ["name", "not in", ["Administrator", "Адміністратор"]],
], fields=["id", "name", "sex", "birthday"], order="name")

men = [e for e in employees if e["sex"] == "male" and e["birthday"] and 18 <= age(e["birthday"]) <= 60]
women = [e for e in employees if e["sex"] != "male"]
print(f"компанія {COMPANY}: {len(employees)} працівників, {len(men)} чоловіків 18-60, {len(women)} жінок")

# жінки поза обліком, крім однієї - демонструє окремий список військовозобов'язаних жінок
# (ua_mil_women_list рахується автоматично зі статі й стану обліку, категорія тут - лише для прикладу)
woman_liable_id = women[0]["id"] if women else None
for e in women:
    if e["id"] == woman_liable_id:
        call("hr.employee", "write", [e["id"]], {
            "ua_mil_status": "liable", "ua_mil_category": "ranks", "ua_mil_tcc": "Львівський районний ТЦК та СП",
            "ua_mil_doc_type": "ticket", "ua_mil_doc_number": f"{200000 + e['id']}", "ua_mil_doc_date": "2018-03-01",
            "ua_mil_fitness": "fit",
        })
    else:
        call("hr.employee", "write", [e["id"]], {"ua_mil_status": "none"})

# хто вже звільнений (контракт має дату закінчення) - не пропонуємо на бронювання/відстрочку
dismissed_ids = set()
for e in men:
    ends = call("hr.version", "search_count", [["employee_id", "=", e["id"]], ["contract_date_end", "!=", False]])
    if ends:
        dismissed_ids.add(e["id"])

RANKS = ["солдат", "старший солдат", "сержант", "старший сержант", "лейтенант"]
VOS_BY_RANK = {"солдат": "021", "старший солдат": "021", "сержант": "100", "старший сержант": "100", "лейтенант": "021"}
# Лише дві офіційні категорії (постанова КМУ № 1487): лейтенант - офіцерський склад, решта - рядовий,
# сержантський і старшинський склад.
CATEGORY_BY_RANK = {"солдат": "ranks", "старший солдат": "ranks", "сержант": "ranks", "старший сержант": "ranks", "лейтенант": "officers"}
# Два ТЦК та СП - список персонального обліку ведеться окремо по кожному.
TCC_BY_PARITY = ["Львівський районний ТЦК та СП", "Галицький районний ТЦК та СП"]

men_sorted = sorted(men, key=lambda e: e["name"])
active_sorted = [e for e in men_sorted if e["id"] not in dismissed_ids] or men_sorted   # бронювання/відстрочка - лише для тих, хто працює
conscript_id = active_sorted[0]["id"] if active_sorted else None
liable = [e for e in men_sorted if e["id"] != conscript_id]
active_liable = [e for e in active_sorted if e["id"] != conscript_id] or liable
reserved_ids = {e["id"] for e in active_liable[:2]}          # двоє заброньовані
deferment_id = active_liable[2]["id"] if len(active_liable) > 2 else None   # один з відстрочкою
unfit_id = active_liable[3]["id"] if len(active_liable) > 3 else (liable[-1]["id"] if liable else None)   # один непридатний

# один резервіст (стан обліку, не бронювання) - для прикладу необов'язкового блоку «Резерв+ (витяг)»
reserve_plus_id = active_liable[4]["id"] if len(active_liable) > 4 else (liable[0]["id"] if liable else None)

events_created = 0
checked = 0
for i, e in enumerate(men_sorted):
    is_conscript = e["id"] == conscript_id
    is_reserve_plus = e["id"] == reserve_plus_id and not is_conscript
    rank = "" if is_conscript else RANKS[i % len(RANKS)]
    vals = {
        "ua_mil_status": "reserve" if is_reserve_plus else ("conscript" if is_conscript else "liable"),
        "ua_mil_category": None if is_conscript else CATEGORY_BY_RANK[rank],
        "ua_mil_group": "sv",
        "ua_mil_rank": rank,
        "ua_mil_vos": "" if is_conscript else VOS_BY_RANK[rank],
        "ua_mil_tcc": TCC_BY_PARITY[i % len(TCC_BY_PARITY)],
        "ua_mil_doc_type": "registration" if is_conscript else "ticket",
        "ua_mil_doc_series": "" if is_conscript else "АА",
        "ua_mil_doc_number": f"{100000 + e['id']}",
        "ua_mil_doc_date": "2020-05-15",
        "ua_mil_fitness": "unfit" if e["id"] == unfit_id else ("undefined" if is_conscript else "fit"),
        "ua_mil_vlk_date": "2025-04-10" if e["id"] == unfit_id else False,
        "ua_mil_reserved": e["id"] in reserved_ids,
        "ua_mil_reserve_order": "Наказ про бронювання № 8 від 15.01.2027" if e["id"] in reserved_ids else "",
        "ua_mil_reserve_until": "2027-03-31" if e["id"] in reserved_ids else False,
        "ua_mil_deferment": "Відстрочка за сімейними обставинами (ст. 25 ЗУ «Про мобілізаційну підготовку...»)" if e["id"] == deferment_id else "",
        "ua_mil_deferment_until": "2027-06-30" if e["id"] == deferment_id else False,
        "ua_reserve_number": f"РП-{10000 + e['id']}" if is_reserve_plus else False,
        "ua_reserve_date": "2026-06-01" if is_reserve_plus else False,
    }
    # звірка в липні 2026 для половини
    if i % 2 == 0:
        vals["ua_mil_last_check"] = "2026-07-15"
        checked += 1
    call("hr.employee", "write", [e["id"]], vals)

    # подія «взято на облік» на дату прийняття (перша активна версія)
    versions = call("hr.version", "search_read", [["employee_id", "=", e["id"]], ["contract_date_start", "!=", False]], fields=["contract_date_start"], order="contract_date_start")
    hire_date = versions[0]["contract_date_start"] if versions else "2020-01-01"
    existing = call("ua.military.event", "search", [["employee_id", "=", e["id"]], ["kind", "=", "register"]])
    if not existing:
        call("ua.military.event", "create", {"employee_id": e["id"], "date": hire_date, "kind": "register", "note": "Взято на військовий облік при прийнятті на роботу"})
        events_created += 1
    if "ua_mil_last_check" in vals:
        existing_check = call("ua.military.event", "search", [["employee_id", "=", e["id"]], ["kind", "=", "check"], ["date", "=", vals["ua_mil_last_check"]]])
        if not existing_check:
            call("ua.military.event", "create", {"employee_id": e["id"], "date": vals["ua_mil_last_check"], "kind": "check", "note": "Звірка даних з ТЦК та СП"})
            events_created += 1

    label = "призовник" if is_conscript else ("заброньований" if e["id"] in reserved_ids else ("відстрочка" if e["id"] == deferment_id else ("непридатний" if e["id"] == unfit_id else rank)))
    print(f"{i + 1:2d}. {e['name']}: {label}")

print(f"звірку записано для {checked} з {len(men_sorted)} чоловіків; подій створено {events_created}")
