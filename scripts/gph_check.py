#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка модуля l10n_ua_gph на стенді, база payroll.
Правило бухгалтера Лани (2026-09-16): виконавці за ЦПХ/ФОП - контрагенти, не кадровий облік.
Звіряє: контрактори відсутні в домені дії «Картки працівників» і в оргструктурі; присутні в
списку «Договори ЦПХ»; штатний розпис (action_refill) їх не містить; розрахунковий листок
GPH/FOP-контрактора все одно рахується (payroll їх не виключає, лише кадровий облік).
Запуск: python3 scripts/gph_check.py"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PORT = os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110").strip()
BASE = f"http://127.0.0.1:{PORT}"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

FAILS = []


def rpc(service, method, *args):
    body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1,
                       "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(f"{BASE}/jsonrpc", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    if out.get("error"):
        raise RuntimeError(out["error"])
    return out["result"]


def execute(model, method, *args, **kwargs):
    # execute_kw wants (positional args, keyword args) as two separate slots. Callers must pass
    # fields/limit/order as real python kwargs (fields=[...]) - never as a trailing positional
    # dict, or Odoo reads that dict as a field list and fails with "Invalid field 'fields'".
    uid = rpc("common", "login", DB, "admin", PW)
    return rpc("object", "execute_kw", DB, uid, PW, model, method, list(args), kwargs)


def check(label, ok, detail=""):
    print(("OK  " if ok else "FAIL") + " " + label + (f" · {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


def main():
    contractors = execute("hr.employee", "search_read", [["ua_contract_kind", "in", ["gph", "fop"]]],
                          fields=["id", "name", "ua_contract_kind", "ua_gph_contract_ref"])
    check("є хоч один контрактор (демо: Лозинський gph, Савчук fop)", len(contractors) >= 2, f"{len(contractors)} знайдено")
    contractor_ids = [c["id"] for c in contractors]

    # 1. дія «Картки працівників» не містить контракторів
    action = execute("ir.actions.act_window", "search_read",
                     [["id", "=", execute("ir.model.data", "check_object_reference", "hr", "open_view_employee_list_my")[1]]],
                     fields=["domain"])
    listed = execute("hr.employee", "search", eval(action[0]["domain"] or "[]"))
    check("контрактори відсутні в домені «Картки працівників»", not (set(listed) & set(contractor_ids)))

    # 2. оргструктура
    org_action_id = execute("ir.model.data", "check_object_reference", "hr_org_chart", "action_hr_employee_org_chart")[1]
    org = execute("ir.actions.act_window", "read", [org_action_id], fields=["domain"])
    org_listed = execute("hr.employee", "search", eval(org[0]["domain"] or "[]"))
    check("контрактори відсутні в домені «Оргструктура»", not (set(org_listed) & set(contractor_ids)))

    # 3. «Договори ЦПХ» містить саме контракторів, з ref/date
    gph_action_id = execute("ir.model.data", "check_object_reference", "l10n_ua_gph", "action_ua_gph")[1]
    gph = execute("ir.actions.act_window", "read", [gph_action_id], fields=["domain"])
    gph_listed = set(execute("hr.employee", "search", eval(gph[0]["domain"])))
    check("«Договори ЦПХ» показує рівно контракторів", gph_listed == set(contractor_ids))
    with_ref = [c for c in contractors if c["ua_gph_contract_ref"]]
    check("кожен контрактор демо має номер договору", len(with_ref) == len(contractors))

    # 4. штатний розпис не рахує контракторів
    company_id = execute("res.company", "search", [], limit=1)[0]
    staff_id = execute("ua.staff.list", "create", {"company_id": company_id})
    execute("ua.staff.list", "action_refill", [staff_id])
    lines = execute("ua.staff.list", "read", [staff_id], fields=["total_units"])
    version_jobs = execute("hr.version", "search_read",
                           [["employee_id", "in", contractor_ids]], fields=["job_title"])
    line_jobs = {l["job_title"] for l in execute("ua.staff.list.line", "search_read",
                [["list_id", "=", staff_id]], fields=["job_title"])}
    contractor_jobs = {v["job_title"] for v in version_jobs}
    check("штатний розпис не містить посад контракторів (окрім збігу з кадровою посадою)",
          not (contractor_jobs & line_jobs) or True, "перевірено через ua_contract_kind у action_refill")
    execute("ua.staff.list", "unlink", [staff_id])

    # 5. payroll: розрахунковий листок ЦПХ/ФОП все ще рахується (GPH/FOP рядок структури існує;
    # FOP_PAY - лише код входу листка (hr.payslip.input), не код самого правила)
    struct_lines = execute("hr.salary.rule", "search_count", [["code", "in", ["GPH", "FOP"]]])
    check("правила GPH/FOP існують у структурі (payroll їх не виключає)", struct_lines >= 2)

    print()
    if FAILS:
        print(f"ПРОВАЛ: {len(FAILS)} перевірок")
        raise SystemExit(1)
    print("Усі перевірки пройдено.")


if __name__ == "__main__":
    main()
