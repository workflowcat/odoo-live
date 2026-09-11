"""Перевірка імпорту працівників і залишків (модуль l10n_ua_onboarding).

Робимо файл Excel з двома новими працівниками і заробітком за три місяці, проганяємо
«Тільки перевірити», потім справжній імпорт і звіряємо: картки створені, оклад і дати
в версії контракту, залишок відпустки, базовий місяць індексації, рядки заробітку.
Наприкінці прибираємо створене, щоб стенд лишався як був.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/import_check.py"""
import base64
import io
import json
import os
import urllib.request

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/") + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

RNOKPP_A, RNOKPP_B = "9900000001", "9900000002"
errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def rpc(service, method, *args):
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(request, timeout=900).read())
    if "error" in data:
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:800])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def make_file():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Працівники"
    header = ["Прізвище", "Ім'я", "По батькові", "РНОКПП", "Стать (ч/ж)", "Дата народження", "Посада",
              "Підрозділ", "Дата прийняття", "Оклад", "Ставка", "Вид договору", "Основне місце (так/ні)",
              "Категорія ЄСВ", "ПСП", "Дітей для ПСП", "Код КП", "Наказ про прийняття", "IBAN",
              "Телефон", "Email", "Страховий стаж, років", "Залишок відпустки на дату",
              "Дата залишку відпустки", "Базовий місяць індексації"]
    sheet.append(header)
    sheet.append(["Тестенко", "Олег", "Іванович", RNOKPP_A, "ч", "1990-05-14", "Столяр", "Виробництво",
                  "2024-03-01", "27000", "1", "трудовий", "так", "загальна", "немає", "", "7422",
                  "Наказ № 7-к від 29.02.2024", "UA213052990000026007233566001", "+380 67 000 11 22",
                  "test.a@example.com", "9", "11,5", "2026-01-01", "2026-05-01"])
    sheet.append(["Тестенко", "Ірина", "Петрівна", RNOKPP_B, "ж", "1993-11-02", "Бухгалтер", "Бухгалтерія",
                  "2025-01-20", "24000", "0,5", "трудовий", "так", "загальна", "на дітей", "2", "3433",
                  "Наказ № 2-к від 17.01.2025", "", "+380 63 000 33 44", "", "4", "6", "2026-01-01", ""])
    sheet.append(["Помилкова", "Ганна", "", "123", "ж", "", "", "", "2025-01-01", "0", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    earnings = book.create_sheet("Заробіток")
    earnings.append(["РНОКПП", "Місяць (РРРР-ММ)", "Нараховано"])
    for month, amount in (("2026-06", 27000), ("2026-07", 27000), ("2026-08", 28500)):
        earnings.append([RNOKPP_A, month, amount])
    stream = io.BytesIO()
    book.save(stream)
    return base64.b64encode(stream.getvalue()).decode()


def cleanup():
    employees = call("hr.employee", "search", [["ua_rnokpp", "in", [RNOKPP_A, RNOKPP_B]]])
    if not employees:
        return 0
    history = call("ua.earnings.history", "search", [["employee_id", "in", employees]])
    if history:
        call("ua.earnings.history", "unlink", history)
    call("hr.employee", "unlink", employees)
    return len(employees)


cleanup()
data = make_file()

# 1. Тільки перевірити: нічого не створює
wizard = call("ua.employee.import", "create", {"file": data, "filename": "test.xlsx", "dry_run": True})
call("ua.employee.import", "action_import", [wizard])
log = call("ua.employee.import", "read", [wizard], ["log"])[0]["log"]
check("перевірка рахує двох нових працівників", "Нових працівників: 2" in log, log.splitlines()[1] if log else "")
check("перевірка бачить помилковий рядок", "рядок 4" in log, [l for l in log.splitlines() if "рядок 4" in l][:1])
check("перевірка нічого не створює", not call("hr.employee", "search", [["ua_rnokpp", "in", [RNOKPP_A, RNOKPP_B]]]))

# 2. Справжній імпорт
wizard = call("ua.employee.import", "create", {"file": data, "filename": "test.xlsx", "dry_run": False})
call("ua.employee.import", "action_import", [wizard])
log = call("ua.employee.import", "read", [wizard], ["log"])[0]["log"]
check("імпорт створив двох працівників", "Нових працівників: 2" in log)
check("імпорт переніс три рядки заробітку", "Рядків заробітку: 3" in log)

emp_a = call("hr.employee", "search_read", [["ua_rnokpp", "=", RNOKPP_A]],
             fields=["name", "job_title", "department_id", "ua_fte", "ua_psp", "ua_insurance_years",
                     "ua_vacation_opening_balance", "ua_vacation_opening_date", "ua_index_base", "version_id"])
check("картку створено з ПІБ і посадою", bool(emp_a) and emp_a[0]["name"] == "Тестенко Олег Іванович",
      emp_a[0]["name"] if emp_a else "немає")
check("підрозділ і посада підставлені", bool(emp_a[0]["department_id"]) and emp_a[0]["job_title"] == "Столяр",
      f"{emp_a[0]['department_id'][1] if emp_a[0]['department_id'] else '-'} / {emp_a[0]['job_title']}")
check("залишок відпустки перенесено", abs(emp_a[0]["ua_vacation_opening_balance"] - 11.5) < 0.01,
      str(emp_a[0]["ua_vacation_opening_balance"]))
check("дата залишку відпустки перенесена", emp_a[0]["ua_vacation_opening_date"] == "2026-01-01",
      str(emp_a[0]["ua_vacation_opening_date"]))
check("базовий місяць індексації перенесено", emp_a[0]["ua_index_base"] == "2026-05-01",
      str(emp_a[0]["ua_index_base"]))
check("страховий стаж перенесено", emp_a[0]["ua_insurance_years"] == 9, str(emp_a[0]["ua_insurance_years"]))

version = call("hr.version", "read", [emp_a[0]["version_id"][0]], ["wage", "contract_date_start", "ua_kp_code", "struct_id"])[0]
check("оклад у версії контракту", abs(version["wage"] - 27000) < 0.01, str(version["wage"]))
check("дата прийняття у версії контракту", version["contract_date_start"] == "2024-03-01", str(version["contract_date_start"]))
check("код КП перенесено", version["ua_kp_code"] == "7422", str(version["ua_kp_code"]))
check("структура зарплати підставлена", bool(version["struct_id"]), str(version["struct_id"]))

emp_b = call("hr.employee", "search_read", [["ua_rnokpp", "=", RNOKPP_B]], fields=["ua_fte", "ua_psp", "ua_psp_children"])
check("неповна ставка перенесена", emp_b[0]["ua_fte"] == "0.5", emp_b[0]["ua_fte"])
check("ПСП на дітей перенесено", emp_b[0]["ua_psp"] == "child" and emp_b[0]["ua_psp_children"] == 2,
      f"{emp_b[0]['ua_psp']} / {emp_b[0]['ua_psp_children']}")

history = call("ua.earnings.history", "search_read", [["employee_id", "=", emp_a[0]["id"]]], fields=["month", "gross"])
check("історія заробітку створена", len(history) == 3, f"{len(history)} рядків")
check("суми заробітку правильні", abs(sum(h["gross"] for h in history) - 82500) < 0.01,
      str(sum(h["gross"] for h in history)))

# 3. Повторний імпорт оновлює, а не дублює
wizard = call("ua.employee.import", "create", {"file": data, "filename": "test.xlsx", "dry_run": False})
call("ua.employee.import", "action_import", [wizard])
log = call("ua.employee.import", "read", [wizard], ["log"])[0]["log"]
check("повторний імпорт оновлює картки", "Оновлених карток: 2" in log and "Нових працівників: 0" in log)
check("дублів працівників немає", len(call("hr.employee", "search", [["ua_rnokpp", "=", RNOKPP_A]])) == 1)
check("дублів заробітку немає", len(call("ua.earnings.history", "search", [["employee_id", "=", emp_a[0]["id"]]])) == 3)

# 4. Шаблон файлу
template = call("ua.employee.import", "action_template", [wizard])
check("кнопка «Шаблон файлу» дає файл на завантаження",
      isinstance(template, dict) and template.get("type") == "ir.actions.act_url" and "/web/content/" in template.get("url", ""),
      template.get("url", "") if isinstance(template, dict) else str(template))

removed = cleanup()
check("тестових працівників прибрано", removed == 2, f"видалено {removed}")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
