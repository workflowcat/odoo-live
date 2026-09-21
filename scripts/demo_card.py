#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Демо-дані для модуля l10n_ua_hr_card: особова картка, документи працівника - ТОВ «Ясен Меблі».
Ідемпотентно: пошук нащадкових записів (діти, попередні місця роботи, документи) за (employee_id, name),
основні поля employee завжди перезаписуються тими самими (детермінований seed на працівника) значеннями.
Адреса і база - зі змінних ODOO_URL і PAYROLL_DB (типово http://127.0.0.1:8110 і payroll).
Запуск: python3 scripts/demo_card.py"""
import json
import os
import random
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/") + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
TODAY = date(2026, 9, 9)


def rpc(service, method, *args):
    body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1, "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    if d.get("error"):
        raise SystemExit(json.dumps(d["error"], ensure_ascii=False)[:4000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit("Не вдалося увійти в Odoo (перевірте ODOO_ADMIN_USER_PASSWORD).")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


UKR_FIRST_M = ["Максим", "Артем", "Данило", "Богдан", "Тимур", "Іван", "Назар"]
UKR_FIRST_F = ["Софія", "Марія", "Анна", "Дарина", "Христина", "Оленка", "Вікторія"]
PATRONYMIC_M = ["Богданович", "Романович", "Ярославович", "Андрійович", "Тарасович"]
PATRONYMIC_F = ["Богданівна", "Романівна", "Ярославівна", "Андріївна", "Тарасівна"]
PRIOR_COMPANIES = [
    "ТОВ «Львівдеревпром»", "ПП «Карпатський стиль»", "ТОВ «Мебльова фабрика Осокір»",
    "ФОП Гнатюк В.Р.", "ТОВ «Захід-Логістик»", "ТзОВ «Інтер’єр Львів»", "ТОВ «Дім і Сад»",
    "ПрАТ «Львівхолод»", "ТОВ «Ясен Плюс»", "ФОП Ковальська О.М.",
]
PRIOR_JOBS = ["столяр", "менеджер", "комірник", "бухгалтер", "адміністратор", "продавець-консультант", "різноробочий"]
STREETS = ["вул. Городоцька", "вул. Пасічна", "вул. Кульпарківська", "вул. Замарстинівська", "вул. Шевченка", "вул. Сихівська"]

emps = call("hr.employee", "search_read", [["company_id.name", "ilike", "Ясен Меблі"]],
            fields=["id", "name", "sex", "birthday", "children", "ua_hire_date"], order="id")
if len(emps) < 20:
    raise SystemExit(f"Знайдено лише {len(emps)} працівників ТОВ «Ясен Меблі» (очікувалось >= 20). Спершу запустіть scripts/demo_company.py.")

expiring_soon = {emps[2]["id"], emps[6]["id"]}  # двоє працівників з документом, що закінчується за 20 днів

for i, e in enumerate(emps, 1):
    rnd = random.Random(f"ua_hr_card::{e['id']}")
    last_name = e["name"].split()[0]
    bd = date.fromisoformat(e["birthday"]) if e["birthday"] else date(1990, 1, 1)
    hire = date.fromisoformat(e["ua_hire_date"]) if e.get("ua_hire_date") else date(2020, 1, 1)

    # -- Документ, що посвідчує особу: ID-картка, орган 4620 -------------------------------------------
    id_number = str(rnd.randint(100000000, 999999999))
    id_date = date(rnd.randint(2015, 2023), rnd.randint(1, 12), rnd.randint(1, 28))
    unzr = f"{bd.year:04d}{bd.month:02d}{bd.day:02d}{rnd.randint(10000, 99999)}"  # 4+2+2+5 = 13 символів

    # -- Фактична адреса ------------------------------------------------------------------------------
    actual_address = f"{rnd.choice(STREETS)}, {rnd.randint(2, 140)}, кв. {rnd.randint(1, 95)}, м. Львів, 79{rnd.randint(10, 69):03d}"

    # -- Освіта -----------------------------------------------------------------------------------------
    edu_year = max(bd.year + 17, min(hire.year, bd.year + 23))
    diploma_no = f"{rnd.choice(['ЛВ', 'ЛА', 'ЛТ'])} № {rnd.randint(100000, 999999)}"

    # -- Трудова книжка --------------------------------------------------------------------------------
    labor_date = date(min(bd.year + 18, hire.year), rnd.randint(1, 12), rnd.randint(1, 28))
    electronic = rnd.random() < 0.4

    vals = {
        "ua_id_doc_type": "id_card",
        "ua_id_doc_number": id_number,
        "ua_id_doc_issued_by": "4620",
        "ua_id_doc_date": str(id_date),
        "ua_id_doc_unzr": unzr,
        "ua_actual_address": actual_address,
        "ua_education_year": edu_year,
        "ua_diploma_number": diploma_no,
        "ua_languages": "українська" + (", англійська" if rnd.random() < 0.5 else ""),
        "ua_labor_book_number": f"{rnd.randint(1000000, 9999999)}",
        "ua_labor_book_date": str(labor_date),
        "ua_electronic_labor_book": electronic,
        "ua_large_family": (e["children"] or 0) >= 3,
        "ua_single_parent": False,
        "ua_veteran": rnd.random() < 0.1,
    }
    call("hr.employee", "write", [e["id"]], vals)

    # -- Діти (для тих, у кого children > 0) ------------------------------------------------------------
    kids = e["children"] or 0
    existing_kids = call("ua.employee.child", "search", [["employee_id", "=", e["id"]]])
    if existing_kids:
        call("ua.employee.child", "unlink", existing_kids)
    used_first_names = set()
    for k in range(kids):
        pool_first, pool_pat = (UKR_FIRST_M, PATRONYMIC_M) if rnd.random() < 0.5 else (UKR_FIRST_F, PATRONYMIC_F)
        first = rnd.choice([n for n in pool_first if n not in used_first_names] or pool_first)
        used_first_names.add(first)
        child_bd = bd + timedelta(days=rnd.randint(365 * 3, 365 * 20))
        if child_bd >= TODAY:
            child_bd = TODAY - timedelta(days=rnd.randint(365, 365 * 15))
        call("ua.employee.child", "create", {
            "employee_id": e["id"],
            "name": f"{last_name} {first} {rnd.choice(pool_pat)}",
            "birthday": str(child_bd),
        })

    # -- Попередні місця роботи (1-2) --------------------------------------------------------------------
    n_prior = rnd.choice([1, 2])
    existing_prior = call("ua.employee.prior.job", "search", [["employee_id", "=", e["id"]]])
    if existing_prior:
        call("ua.employee.prior.job", "unlink", existing_prior)
    cursor = hire
    for _ in range(n_prior):
        span_days = rnd.randint(200, 900)
        date_to = cursor - timedelta(days=rnd.randint(10, 60))
        date_from = date_to - timedelta(days=span_days)
        if date_from.year < bd.year + 18:
            break
        call("ua.employee.prior.job", "create", {
            "employee_id": e["id"],
            "company_name": rnd.choice(PRIOR_COMPANIES),
            "job_title": rnd.choice(PRIOR_JOBS),
            "date_from": str(date_from),
            "date_to": str(date_to),
        })
        cursor = date_from

    # -- Документи (2-3) -----------------------------------------------------------------------------------
    is_passport = rnd.random() < 0.4   # вид і назва мають збігатися, тому один кидок
    docs = [
        {"type": "passport" if is_passport else "rnokpp",
         "name": "Паспорт громадянина України" if is_passport else "Довідка про присвоєння РНОКПП",
         "number": id_number, "date": str(id_date), "valid_until": False},
        {"type": "diploma", "name": f"Диплом, {edu_year} р.", "number": diploma_no, "date": f"{edu_year}-07-01", "valid_until": False},
        {"type": "statement", "name": "Заява про прийняття на роботу", "number": False, "date": str(hire), "valid_until": False},
    ]
    if e["id"] in expiring_soon:
        docs.append({"type": "medical", "name": "Медична довідка (форма 086/о)", "number": f"{rnd.randint(1000, 9999)}",
                     "date": str(TODAY - timedelta(days=345)), "valid_until": str(TODAY + timedelta(days=20))})
    existing_docs = call("ua.employee.document", "search", [["employee_id", "=", e["id"]]])
    if existing_docs:
        call("ua.employee.document", "unlink", existing_docs)
    for d in docs:
        call("ua.employee.document", "create", dict(d, employee_id=e["id"]))

    print(f"{i:2d}. {e['name']}: ID-картка {id_number}, УНЗР {unzr}, {kids} дит., {n_prior} попер. місце(-я), {len(docs)} документ(и)")

print("Готово.")
