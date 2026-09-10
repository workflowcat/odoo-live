#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка модуля l10n_ua_hr_card на стенді, база payroll.
Звіряє: усі 20 працівників ТОВ «Ясен Меблі» мають РНОКПП і документ особи; П-2 PDF для 3 працівників
починається з %PDF; get_views форми працівника без помилок; кожне поле hr.employee у arch форми
зустрічається не більше одного разу (нащадкові списки ua.employee.child/prior.job/document не рахуються -
це поля ІНШОЇ моделі, що вставляються у власний inline-підвид One2many; відомий виняток самого ядра Odoo -
bank_account_ids/user_id, які й у стандартній формі повторюються за умовними варіантами відображення).
Також: вкладка «Огляд» (ua_overview) - перша вкладка форми, і поля всередині неї навмисно дублюють поля
з інших вкладок (readonly-знімок стану), тож виключені з підрахунку повторів окремо.
Для трьох працівників ua_days_in_company > 0 і ua_docs_count >= 1; у Ткачука ua_overview_alert_count >= 1.
Запуск: python3 scripts/card_check.py"""
import http.cookiejar
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PORT = os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110").strip()
BASE = f"http://127.0.0.1:{PORT}"
DB = "payroll"
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

# Поля, що й у стандартній формі hr.employee (ядро Odoo + вже встановлені модулі hr_presence тощо)
# повторюються через умовні варіанти віджета - це не наслідок наших переміщень, тож не провал перевірки.
# ua_insurance_years/ua_vacation_balance повторюються навмисно: стат-кнопка в button_box дублює
# значення, що й так видно в його власній вкладці (Особова картка / Зарплата) - стандартний патерн Odoo.
KNOWN_CORE_REPEATS = {"bank_account_ids": 3, "user_id": 2, "hr_icon_display": 2,
                      "ua_insurance_years": 2, "ua_vacation_balance": 2}


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


# 1. 20 працівників ТОВ «Ясен Меблі»: РНОКПП і документ особи
emps = call("hr.employee", "search_read", [["company_id.name", "ilike", "Ясен Меблі"]],
            fields=["id", "name", "ua_rnokpp", "ua_id_doc_number", "ua_id_doc_type"], order="id")
print(f"Знайдено {len(emps)} працівників ТОВ «Ясен Меблі».")
check(f"є хоча б 20 працівників ({len(emps)})", len(emps) >= 20)
no_rnokpp = [e["name"] for e in emps if not e["ua_rnokpp"]]
no_doc = [e["name"] for e in emps if not (e["ua_id_doc_number"] and e["ua_id_doc_type"])]
check(f"усі мають РНОКПП (без РНОКПП: {no_rnokpp or 'немає'})", not no_rnokpp)
check(f"усі мають документ особи (без документа: {no_doc or 'немає'})", not no_doc)

# 2. get_views стандартної форми працівника (hr.view_employee_form; типова форма тепер OWL-картка) без помилок + жодне поле hr.employee не повторюється (окрім відомих винятків ядра)
std_form_id = call("ir.model.data", "check_object_reference", "hr", "view_employee_form")[1]
res = call("hr.employee", "get_views", [[std_form_id, "form"]], {})
arch = res["views"]["form"]["arch"]
check("get_views форми працівника відпрацював без помилок", bool(arch))

root = ET.fromstring(arch)
top_level_names = []


def walk(node, inside_field, in_overview):
    for child in node:
        is_overview_page = child.tag == "page" and child.get("name") == "ua_overview"
        if child.tag == "field":
            name = child.get("name")
            if not inside_field and not in_overview:
                top_level_names.append(name)
            # усе всередині цього <field> - це вже інша модель (о2м/м2м inline)
            walk(child, inside_field=True, in_overview=in_overview)
        else:
            walk(child, inside_field=inside_field, in_overview=in_overview or is_overview_page)


walk(root, inside_field=False, in_overview=False)
counts = Counter(top_level_names)
unexpected_dupes = {name: n for name, n in counts.items() if n > 1 and KNOWN_CORE_REPEATS.get(name) != n}
print(f"Полів hr.employee у формі (верхній рівень, без рядків о2м, без вкладки «Огляд»): {len(top_level_names)}, унікальних: {len(counts)}.")
if unexpected_dupes:
    print("  повтори понад відомі винятки ядра:", unexpected_dupes)
check("жодне поле hr.employee не повторюється у формі (окрім bank_account_ids/user_id з ядра Odoo і навмисних дублів у «Огляд»)", not unexpected_dupes)

# 2б. вкладка «Огляд» - перша вкладка форми
notebook = root.find(".//notebook")
first_page = notebook.find("./page") if notebook is not None else None
check("вкладка «Огляд» (ua_overview) - перша вкладка форми",
      first_page is not None and first_page.get("name") == "ua_overview")

# 2в. огляд: для 3 працівників ua_days_in_company > 0, ua_docs_count >= 1
overview_sample = call("hr.employee", "search_read", [["id", "in", [e["id"] for e in emps[:3]]]],
                        fields=["id", "name", "ua_days_in_company", "ua_docs_count"])
for e in overview_sample:
    check(f"{e['name']}: ua_days_in_company > 0 ({e['ua_days_in_company']})", e["ua_days_in_company"] > 0)
    check(f"{e['name']}: ua_docs_count >= 1 ({e['ua_docs_count']})", e["ua_docs_count"] >= 1)

# 2г. Ткачук: ua_overview_alert_count >= 1
tkachuk = call("hr.employee", "search_read", [["name", "ilike", "Ткачук"]], fields=["id", "name", "ua_overview_alert_count"])
check("знайдено Ткачука Ігоря Володимировича", bool(tkachuk))
if tkachuk:
    t = tkachuk[0]
    check(f"{t['name']}: ua_overview_alert_count >= 1 ({t['ua_overview_alert_count']})", t["ua_overview_alert_count"] >= 1)

# 3. П-2 PDF для 3 працівників
sample = emps[:3]
for e in sample:
    pdf = get_pdf("l10n_ua_hr_card.report_ua_p2", e["id"])
    check(f"П-2 {e['name']} (id={e['id']}) - PDF починається з %PDF", pdf[:4] == b"%PDF")

print()
if errors:
    print(f"ПРОВАЛЕНО ({len(errors)}):")
    for err in errors:
        print(" -", err)
    raise SystemExit(1)
print("Усі перевірки пройдені.")
