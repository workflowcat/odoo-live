#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Звірка історії «Ясен Меблів»: скільки чого є за роками і чи сходиться облік. Лише читає.

Друкує: записи за моделями і роками (листки, пакети, накази, відсутності, табелі, відомості,
закриті періоди, звітність, заяви ПФУ), людей за станом, зарплатне коло 661 - 333 - 311,
найменший залишок банку за всю історію, ОСВ (дебет = кредит) і вибіркові перевірки розрахунку.
Код виходу 1, якщо не сходиться контрольна рівність.

Запуск: DEMO_DB=hist ODOO_URL=http://127.0.0.1:8134 python3 scripts/demo_world_check.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8131").rstrip("/")
DB = (os.environ.get("DEMO_DB") or os.environ.get("PAYROLL_DB") or "demo").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
CO = 1
YEARS = (2025, 2026)


def rpc(service, method, *args):
    req = urllib.request.Request(URL + "/jsonrpc", json.dumps({
        "jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": 1,
    }).encode(), {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=600).read())
    if "error" in d:
        raise SystemExit(str(d["error"].get("data", {}).get("message") or d["error"])[:1500])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    kw["context"] = dict({"allowed_company_ids": [CO], "active_test": False}, **(kw.get("context") or {}))
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def count(model, domain):
    return call(model, "search_count", domain)


def by_year(model, date_field, domain=()):
    return [count(model, list(domain) + [[date_field, ">=", "%s-01-01" % y], [date_field, "<=", "%s-12-31" % y]]) for y in YEARS]


def by_year_int(model, domain=()):
    return [count(model, list(domain) + [["year", "=", y]]) for y in YEARS]


def balance(code, date_to=None, date_from=None):
    acc = call("account.account", "search", [["code", "=like", code + "%"], ["company_ids", "in", CO]])
    dom = [["account_id", "in", acc], ["parent_state", "=", "posted"], ["company_id", "=", CO]]
    if date_to:
        dom.append(["date", "<=", date_to])
    if date_from:
        dom.append(["date", ">=", date_from])
    got = call("account.move.line", "read_group", dom, ["balance:sum"], [])
    return round((got[0].get("balance") or 0.0) if got else 0.0, 2)


def money(x):
    return ("%.2f" % x).replace(".", ",")


def main():
    fail = []
    print("== історія «Ясен Меблів»: база %s на %s ==" % (DB, URL))
    rows = [
        ("проведені листки", by_year("hr.payslip", "date_from", [["state", "=", "done"], ["company_id", "=", CO]])),
        ("чернетки листків", by_year("hr.payslip", "date_from", [["state", "in", ["draft", "verify"]], ["company_id", "=", CO]])),
        ("пакети листків", by_year("hr.payslip.run", "date_start", [["company_id", "=", CO]])),
        ("  з них закриті", by_year("hr.payslip.run", "date_start", [["company_id", "=", CO], ["state", "=", "close"]])),
        ("табелі затверджені", by_year_int("ua.timesheet.sheet", [["state", "=", "confirmed"]])),
        ("авансові відомості", by_year_int("ua.advance.sheet", [["state", "=", "confirmed"]])),
        ("відомості на перерахування", [count("account.payment.order", [["ua_kind", "!=", False], ["ua_year", "=", y]]) for y in YEARS]),
        ("  з них оплачені", [count("account.payment.order", [["ua_kind", "!=", False], ["ua_year", "=", y], ["state", "=", "uploaded"]]) for y in YEARS]),
        ("накази: прийняття", by_year("ua.hr.order", "date", [["order_type", "=", "hire"], ["state", "in", ["posted", "acknowledged"]]])),
        ("накази: зміна окладу", by_year("ua.hr.order", "date", [["order_type", "=", "wage"], ["state", "in", ["posted", "acknowledged"]]])),
        ("накази: переведення", by_year("ua.hr.order", "date", [["order_type", "=", "transfer"], ["state", "in", ["posted", "acknowledged"]]])),
        ("накази: відпустка", by_year("ua.hr.order", "date", [["order_type", "=", "leave"], ["state", "in", ["posted", "acknowledged"]]])),
        ("накази: звільнення", by_year("ua.hr.order", "date", [["order_type", "=", "dismissal"], ["state", "in", ["posted", "acknowledged"]]])),
        ("накази: відрядження", by_year("ua.hr.order", "date", [["order_type", "=", "trip"], ["state", "in", ["posted", "acknowledged"]]])),
        ("накази: скасовані й чернетки", by_year("ua.hr.order", "date", [["state", "in", ["cancelled", "draft"]]])),
        ("відсутності проведені", by_year("hr.leave", "request_date_from", [["state", "=", "validate"]])),
        ("  лікарняні з е-ЛН", by_year("hr.leave", "request_date_from", [["state", "=", "validate"], ["ua_sick_number", "!=", False]])),
        ("відсутності відхилені", by_year("hr.leave", "request_date_from", [["state", "=", "refuse"]])),
        ("штатні розписи затверджені", by_year("ua.staff.list", "date", [["state", "=", "confirmed"]])),
        ("закриті місяці", by_year_int("ua.period.close", [["kind", "=", "month"], ["state", "=", "closed"]])),
        ("закриті квартали", by_year_int("ua.period.close", [["kind", "=", "quarter"], ["state", "=", "closed"]])),
        ("об'єднана звітність подана", by_year_int("ua.report.run", [["report_code", "=", "j05"], ["state", "=", "submitted"], ["doc_kind", "=", "HZ"]])),
        ("  уточнюючі розрахунки", by_year_int("ua.report.run", [["report_code", "=", "j05"], ["doc_kind", "in", ["HZN", "HZU"]]])),
        ("заяви-розрахунки ПФУ", by_year("ua.pfu.claim", "date", [])),
        ("події військового обліку", by_year("ua.military.event", "date", [])),
        ("рядки журналу змін", by_year_int("ua.change.log", [])),
        ("історія заробітку з листків", by_year("ua.earnings.history", "month", [["source", "=", "payslip"]])),
    ]
    print("%-36s %8s %8s" % ("", *YEARS))
    for label, values in rows:
        print("%-36s %8s %8s" % (label, *values))

    emps = call("hr.employee", "search_read", [["company_id", "=", CO], ["ua_rnokpp", "!=", False]],
                fields=["name", "active", "ua_contract_kind"])
    active = [e for e in emps if e["active"]]
    print("\nЛюди з РНОКПП: %s, з них працюють %s (трудовий договір %s, ЦПХ і ФОП %s), звільнені і з закінченим договором %s" % (
        len(emps), len(active), sum(1 for e in active if e["ua_contract_kind"] == "employment"),
        sum(1 for e in active if e["ua_contract_kind"] != "employment"), len(emps) - len(active)))
    for month in ("2025-01", "2025-07", "2026-01", "2026-07", "2026-09"):
        n = count("hr.payslip", [["date_from", "=", month + "-01"], ["state", "!=", "cancel"], ["company_id", "=", CO]])
        print("  листків за %s: %s" % (month, n))

    # ---- вибіркові перевірки розрахунку
    print("\nВибіркові перевірки розрахунку")
    def line(name, month, code):
        got = call("hr.payslip.line", "search_read", [["slip_id.employee_id.name", "=", name], ["slip_id.date_from", "=", month + "-01"],
                                                      ["slip_id.state", "!=", "cancel"], ["code", "=", code]], fields=["total"])
        return round(sum(l["total"] for l in got), 2)
    checks = [
        ("Гаврилюк, оклад 01.2025 / 07.2025 / 01.2026", [line("Гаврилюк Богдан Тарасович", m, "BASIC") for m in ("2025-01", "2025-07", "2026-01")]),
        ("Гаврилюк, відпускні 03.2025 (середня з 2024 року)", [line("Гаврилюк Богдан Тарасович", "2025-03", "VAC")]),
        ("Гринів, відпускні 10.2025 (середня з власних листків)", [line("Гринів Оксана Романівна", "2025-10", "VAC")]),
        ("Гринів, декретні 08.2026", [line("Гринів Оксана Романівна", "2026-08", "MAT")]),
        ("Прокопів, лікарняні 02.2025: підприємство / ПФУ", [line("Прокопів Наталія Богданівна", "2025-02", c) for c in ("SICK_EMP", "SICK_PFU")]),
        ("Прокопів, ЄСВ 8,41 % 01.2025", [line("Прокопів Наталія Богданівна", "2025-01", "ESV")]),
        ("Крамар, нараховано і ЄСВ 07.2025 (база не більша за 160 000)", [line("Крамар Володимир Зіновійович", "2025-07", c) for c in ("GROSS", "ESV")]),
        ("Романюк, нараховано 12.2025 / 01.2026 (оклад 8 000 -> 9 000, 0,5 ставки)", [line("Романюк Любов Іванівна", m, "GROSS") for m in ("2025-12", "2026-01")]),
        ("Романюк, доплата до мінімальної 09.2026", [line("Романюк Любов Іванівна", "2026-09", "MINSAL")]),
        ("Семенюк, 12.2025: вихідна допомога / компенсація відпустки", [line("Семенюк Вадим Олегович", "2025-12", c) for c in ("SEVERANCE", "COMP_VAC")]),
        ("Луців, 03.2025 (до 14 числа): оклад / компенсація", [line("Луців Катерина Андріївна", "2025-03", c) for c in ("BASIC", "COMP_VAC")]),
        ("Шевчук, аліменти 06.2025", [line("Шевчук Віталій Олегович", "2025-06", "ALIM")]),
        ("Ковальчук, погодинна і нічні 03.2025", [line("Ковальчук Роман Васильович", "2025-03", c) for c in ("HOURLY", "NIGHT")]),
        ("Дзюба, премія 10.2025 після перерахунку", [line("Дзюба Ярослав Михайлович", "2025-10", "BONUS")]),
        ("Вовк (ЦПХ), винагорода 04.2025", [line("Вовк Данило Сергійович", "2025-04", "GPH")]),
        ("Савчук (ФОП), оплата 03.2026", [line("Савчук Олег Васильович", "2026-03", "FOP")]),
    ]
    for label, values in checks:
        print("  %-72s %s" % (label, " / ".join(money(v) for v in values)))
    index = call("hr.payslip.line", "read_group", [["code", "=", "INDEX"], ["total", ">", 0], ["slip_id.state", "=", "done"]], ["total:sum"], [])
    n_index = count("hr.payslip.line", [["code", "=", "INDEX"], ["total", ">", 0], ["slip_id.state", "=", "done"]])
    print("  %-72s %s рядків на %s" % ("Індексація (правило INDEX) у проведених листках", n_index, money((index[0].get("total") or 0.0) if index else 0.0)))

    # ---- зарплатне коло
    print("\nЗарплатне коло і банк")
    for code, label, day in (("661", "розрахунки за заробітною платою", "2026-07-31"), ("661", "те саме", "2026-09-30"),
                             ("6411", "ПДФО", "2026-07-31"), ("6415", "військовий збір", "2026-07-31"), ("651", "ЄСВ", "2026-07-31"),
                             ("333", "грошові кошти в дорозі", "2026-09-30"), ("311", "поточний рахунок", "2026-09-30")):
        print("  %-5s на %s: %14s  %s" % (code, day, money(balance(code, day)), label))
    unrec = count("account.bank.statement.line", [["company_id", "=", CO], ["is_reconciled", "=", False], ["date", "<=", "2026-07-31"]])
    print("  незведених рядків виписки до 2026-07-31: %s" % unrec)
    if unrec:
        fail.append("є незведені рядки виписки в закритих місяцях")
    # найменший залишок банку: рух по днях
    acc = call("account.account", "search", [["code", "=like", "311%"], ["company_ids", "in", CO]])
    days = call("account.move.line", "read_group", [["account_id", "in", acc], ["parent_state", "=", "posted"], ["company_id", "=", CO]],
                ["balance:sum"], ["date:day"], orderby="date:day", lazy=False)
    running, low, low_day = 0.0, None, ""
    for d in days:
        running += d.get("balance") or 0.0
        if low is None or running < low:
            low, low_day = running, d.get("date:day")
    print("  найменший залишок 311 за всю історію: %s (%s)" % (money(low or 0.0), low_day))
    if low is not None and low < 0:
        fail.append("залишок банку буває від'ємним")

    # ---- книги
    got = call("account.move.line", "read_group", [["parent_state", "=", "posted"], ["company_id", "=", CO]], ["debit:sum", "credit:sum"], [])
    debit, credit = round(got[0].get("debit") or 0.0, 2), round(got[0].get("credit") or 0.0, 2)
    print("\nПроведені проводки компанії: Дт %s = Кт %s  %s" % (money(debit), money(credit), "сходиться" if debit == credit else "НЕ СХОДИТЬСЯ"))
    if debit != credit:
        fail.append("дебет не дорівнює кредиту")
    drafts = count("account.move", [["company_id", "=", CO], ["state", "=", "draft"], ["date", "<=", "2026-07-31"]])
    print("Чернеток проводок у закритих місяцях: %s" % drafts)
    locks = call("res.company", "read", [CO], ["fiscalyear_lock_date", "tax_lock_date", "hard_lock_date"])[0]
    print("Дати блокування: облік %s, податки %s, остаточна %s" % (locks["fiscalyear_lock_date"], locks["tax_lock_date"], locks["hard_lock_date"]))
    if fail:
        print("\nНЕ СХОДИТЬСЯ: " + "; ".join(fail))
        sys.exit(1)
    print("\nКонтрольні рівності сходяться.")


if __name__ == "__main__":
    main()
