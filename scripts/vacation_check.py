"""Перевірка початкового залишку відпустки (l10n_ua_payroll_rules) на стенді.

База читається зі змінної середовища PAYROLL_DB (типово payroll). Виконує перевірку через
`odoo shell` (окремий короткочасний процес у тому ж контейнері) - персистентний сервер на
:8110 не перечитує .py-файли адонів без перезапуску контейнера, тож щойно додані поля йому
не видно; окремий процес odoo shell завжди читає код заново з диска.

Скрипт встановлює компанії дату впровадження обліку відпусток 2026-01-01, дає кільком
працівникам початкові залишки і перевіряє: без дати впровадження накопичення рахується
по-старому (від дати прийняття); з датою впровадження - лише від максимуму (дата впровадження,
дата контракту); відпустка до дати впровадження не входить у "використано"; залишок =
початковий + накопичене - використане. Тимчасовий тестовий листок відпустки прибирається в
кінці; дата впровадження компанії і початкові залишки лишаються встановленими (це й є мета
скрипту, а не побічний ефект).
Запуск: PAYROLL_DB=payroll_test python3 scripts/vacation_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import sys
from datetime import date

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


Employee = env['hr.employee'].sudo()
Company = env['res.company'].sudo()
Leave = env['hr.leave'].sudo()
LeaveType = env['hr.leave.type'].sudo()
Version = env['hr.version'].sudo()

company = Company.search([], limit=1)

# працівник, прийнятий у 2021 (за найранішою версією контракту) - на ньому демонструємо баг і виправлення
v2021 = Version.search([('employee_id', '!=', False), ('contract_date_start', '>=', '2021-01-01'), ('contract_date_start', '<', '2022-01-01')], order='contract_date_start', limit=1)
if not v2021:
    print('Немає працівника, прийнятого у 2021 році, в базі.')
    sys.exit(1)
emp = v2021.employee_id
emp_name = emp.name

# ---- 1. без дати впровадження (ні у працівника, ні в компанії) - поведінка як була раніше ----
company.write({'ua_vacation_opening_date': False})
emp.write({'ua_vacation_opening_date': False, 'ua_vacation_opening_balance': 0})
before_accrued, before_used, before_balance = emp.ua_vacation_accrued, emp.ua_vacation_used, emp.ua_vacation_balance
check(f"{emp_name}: без дати впровадження накопичено багато днів (стара поведінка, дата прийняття 2021)",
      before_accrued > 50, f"накопичено {before_accrued}")

# ---- 2. компанії встановлюємо дату впровадження 2026-01-01 (типова для тих, у кого своя дата порожня) ----
company.write({'ua_vacation_opening_date': '2026-01-01'})
emp.invalidate_recordset()
after_accrued, after_used, after_balance = emp.ua_vacation_accrued, emp.ua_vacation_used, emp.ua_vacation_balance
check(f"{emp_name}: з датою впровадження компанії накопичення різко менше ({after_accrued} < {before_accrued})",
      after_accrued < before_accrued)

today = date.today()
opening_date = date(2026, 1, 1)
seen = set(); days = 0
for v in emp.version_ids:
    key = (v.contract_date_start, v.contract_date_end)
    if v.contract_date_start and key not in seen:
        seen.add(key)
        start = max(v.contract_date_start, opening_date)
        end = min(v.contract_date_end or today, today)
        if end >= start:
            days += (end - start).days + 1
expected_accrued = round((emp.ua_vacation_days_year or 24) * days / 365.0, 1)
check(f"{emp_name}: накопичення рахується лише з max(дата впровадження, дата контракту) = {expected_accrued}",
      abs(after_accrued - expected_accrued) < 0.05, f"факт {after_accrued}")

# ---- 3. відпустка до дати впровадження не входить у "використано" ----
lt_vac = LeaveType.search([('work_entry_type_id.code', '=', 'VAC')], limit=1)
used_before_test = emp.ua_vacation_used
old_leave = Leave.with_company(emp.company_id).with_context(default_employee_id=emp.id, allowed_company_ids=[emp.company_id.id]).create({'employee_id': emp.id, 'holiday_status_id': lt_vac.id,
                          'request_date_from': '2024-01-08', 'request_date_to': '2024-01-10'})
old_leave.action_approve()
emp.invalidate_recordset()
used_after_test = emp.ua_vacation_used
check(f"{emp_name}: відпустка до дати впровадження (08-10.01.2024) не збільшує «використано» ({used_before_test} = {used_after_test})",
      abs(used_before_test - used_after_test) < 0.05)
old_leave.action_refuse()
old_leave.unlink()

# ---- 4. початкові залишки декільком працівникам, перевірка формули балансу ----
sample = Employee.search([('ua_rnokpp', '!=', False)], order='id', limit=5)
for i, e in enumerate(sample):
    e.write({'ua_vacation_opening_balance': 3 + i * 2})  # 3, 5, 7, 9, 11
for e in sample:
    e.invalidate_recordset()
    expected = round(e.ua_vacation_opening_balance + e.ua_vacation_accrued - e.ua_vacation_used, 1)
    check(f"{e.name}: залишок {e.ua_vacation_balance} = початковий {e.ua_vacation_opening_balance} + накопичене {e.ua_vacation_accrued} - використане {e.ua_vacation_used}",
          abs(e.ua_vacation_balance - expected) < 0.05)

env.cr.commit()
print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    sys.exit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
quit()
"""

proc = subprocess.run(
    ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
     f"odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d {DB} --no-http --log-level=warn"],
    input=SCRIPT, capture_output=True, text=True, cwd=ROOT,
)
out = proc.stdout
print(out.strip())
if proc.returncode != 0 and "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" not in out and "Усі перевірки пройдено" not in out:
    print("--- stderr ---")
    print(proc.stderr[-4000:])
    sys.exit(proc.returncode)
if "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" in out or "Усі перевірки пройдено" not in out:
    sys.exit(1)
