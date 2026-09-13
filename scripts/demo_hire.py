"""Демо-справи для екрана «Прийняття»: один кандидат після співбесіди і одна справа в оформленні.

Повторний запуск не створює дублів (пошук за прізвищем). Запуск: python3 scripts/demo_hire.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
from datetime import date, timedelta

Case = env["ua.hire.case"].sudo()
company = env["res.company"].search([("name", "ilike", "Ясен")], limit=1) or env.company
dept = env["hr.department"].search([("company_id", "in", [False, company.id])], limit=1)
today = date.today()

if not Case.search([("last_name", "=", "Коваленко")]):
    Case.with_company(company).create({
        "company_id": company.id, "last_name": "Коваленко", "first_name": "Ірина", "job_title": "Бухгалтер",
        "phone": "+380 67 000 00 00", "source": "рекомендація", "interview_date": today - timedelta(days=2),
        "expected_wage": 28000, "screening_note": "Досвід 4 роки, 1С і М.Е.Док. Готова вийти з 1 числа.",
    })
if not Case.search([("last_name", "=", "Бондар")]):
    c = Case.with_company(company).create({
        "company_id": company.id, "stage": "onboarding", "last_name": "Бондар", "first_name": "Олег",
        "middle_name": "Миколайович", "job_title": "Інженер з охорони праці", "department_id": dept.id,
        "birthday": date(1988, 3, 2), "sex": "male", "pd_consent": True, "date_from": today + timedelta(days=12),
        "wage": 24000, "id_doc_type": "id_card",
    })
env.cr.commit()
print("DEMO-HIRE: OK", Case.search_count([]))
"""

proc = subprocess.run(
    ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
     f"odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d {DB} --no-http --log-level=warn"],
    input=SCRIPT, capture_output=True, text=True, cwd=ROOT,
)
print(proc.stdout.strip())
if "DEMO-HIRE: OK" not in proc.stdout:
    print(proc.stderr[-3000:])
    sys.exit(1)
