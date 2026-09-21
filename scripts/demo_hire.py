"""Демо-справи для екрана «Прийняття»: по одній справі на кожен етап (кандидат, оформлення, прийнято,
відмова), файли всіх видів документів і пропозиції розпізнавання в усіх станах на справі в оформленні.

Повторний запуск не створює дублів (пошук за прізвищем чи назвою файлу).
База - зі змінної PAYROLL_DB (типово payroll); працює через одноразовий контейнер, тому
годиться для будь-якої бази, не лише для тієї, під яку піднятий стенд.
Запуск: PAYROLL_DB=payroll python3 scripts/demo_hire.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import base64
from datetime import date, timedelta

Case = env["ua.hire.case"].sudo()
File = env["ua.hire.file"].sudo()
Proposal = env["ua.hire.proposal"].sudo()
company = env["res.company"].search([("name", "ilike", "Ясен")], limit=1) or env.company
dept = env["hr.department"].search([("company_id", "in", [False, company.id])], limit=1)
today = date.today()
png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def make_rnokpp(birthday, male, mid="123"):
    days = (birthday - date(1899, 12, 31)).days
    base = "%05d%s" % (days, mid)
    ninth = 1 if male else 2
    d = [int(c) for c in base] + [ninth]
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    return base + str(ninth) + str(sum(w * x for w, x in zip(weights, d)) % 11 % 10)


if not Case.search([("last_name", "=", "Коваленко")]):
    Case.with_company(company).create({
        "company_id": company.id, "last_name": "Коваленко", "first_name": "Ірина", "job_title": "Бухгалтер",
        "phone": "+380 67 000 00 00", "source": "рекомендація", "interview_date": today - timedelta(days=2),
        "expected_wage": 28000, "screening_note": "Досвід 4 роки, 1С і М.Е.Док. Готова вийти з 1 числа.",
    })

bondar = Case.search([("last_name", "=", "Бондар")], limit=1)
if not bondar:
    bondar = Case.with_company(company).create({
        "company_id": company.id, "stage": "onboarding", "last_name": "Бондар", "first_name": "Олег",
        "middle_name": "Миколайович", "job_title": "Інженер з охорони праці", "department_id": dept.id,
        "birthday": date(1988, 3, 2), "sex": "male", "pd_consent": True, "date_from": today + timedelta(days=12),
        "wage": 24000, "id_doc_type": "id_card",
    })

# ---- файли всіх видів на справі Бондаря: більшість розпізнано, одна помилка, одна ще не розпізнана
if not File.search([("case_id", "=", bondar.id), ("name", "=", "dovidka_bondar.pdf")]):
    for name, t, state, note in [
        ("zayava_bondar.pdf", "statement", "done", False),
        ("id-card_bondar.png", "passport", "done", False),
        ("rnokpp_bondar.png", "rnokpp", "done", False),
        ("vijskovyj_bondar.png", "military_id", "done", False),
        ("diplom_bondar.pdf", "diploma", "done", False),
        ("trudova_bondar.pdf", "labor_book", "done", False),
        ("zgoda_bondar.png", "consent", "done", False),
        ("dogovir_bondar.pdf", "contract", "done", False),
        ("nda_bondar.pdf", "nda", "done", False),
        ("inshe_bondar.pdf", "other", "done", False),
        ("lyst_oznaiomlennia_bondar.pdf", "acknowledgement", "failed", "Скан нечіткий, розпізнати не вдалося"),
        ("dovidka_bondar.pdf", "medical", "none", False),
    ]:
        File.create({"case_id": bondar.id, "name": name, "filename": name, "file": png, "doc_type": t,
                     "extract_state": state, "extract_note": note})

    rnokpp_file = File.search([("case_id", "=", bondar.id), ("doc_type", "=", "rnokpp")], limit=1)
    passport_file = File.search([("case_id", "=", bondar.id), ("doc_type", "=", "passport")], limit=1)

    # ---- пропозиції: чекають (3+ поля), прийнято, відхилено; впевненість висока/середня/низька;
    # цитата з документа; конфлікт із наявним значенням (стать уже "чоловіча")
    Proposal.create({"case_id": bondar.id, "field_name": "rnokpp", "value": make_rnokpp(bondar.birthday, True),
                     "file_id": rnokpp_file.id, "quote": "1234567890", "confidence": "high",
                     "model": "claude-demo", "state": "pending"})
    Proposal.create({"case_id": bondar.id, "field_name": "id_doc_number", "value": "123456789",
                     "file_id": passport_file.id, "quote": "№ 123456789", "confidence": "medium",
                     "model": "claude-demo", "state": "pending"})
    Proposal.create({"case_id": bondar.id, "field_name": "reg_address", "value": "м. Київ, вул. Пробна, 10",
                     "file_id": passport_file.id, "confidence": "low", "model": "claude-demo", "state": "pending"})
    Proposal.create({"case_id": bondar.id, "field_name": "sex", "value": "female",
                     "file_id": passport_file.id, "confidence": "high", "model": "claude-demo", "state": "pending"})

    accepted = Proposal.create({"case_id": bondar.id, "field_name": "middle_name", "value": "Олегович",
                                "file_id": passport_file.id, "confidence": "medium", "model": "claude-demo"})
    accepted.action_accept()
    rejected = Proposal.create({"case_id": bondar.id, "field_name": "id_doc_issued_by", "value": "4610",
                                "file_id": passport_file.id, "confidence": "low", "model": "claude-demo"})
    rejected.action_reject()

# ---- прийнята: Мельник Ірина, перший день у вересні 2026, потім два документи позначені підписаними
if not Case.search([("last_name", "=", "Мельник")]):
    bday = date(1990, 5, 10)
    melnyk = Case.with_company(company).create({
        "company_id": company.id, "stage": "onboarding", "last_name": "Мельник", "first_name": "Ірина",
        "job_title": "Менеджерка з персоналу", "department_id": dept.id, "birthday": bday, "sex": "female",
        "rnokpp": make_rnokpp(bday, False), "id_doc_type": "id_card", "id_doc_number": "234567890",
        "id_doc_unzr": "19900510" + "01234", "id_doc_issued_by": "ГУ ДМС у Київській області",
        "id_doc_date": date(2020, 3, 15), "reg_address": "м. Київ, вул. Демонстраційна, 5",
        "pd_consent": True, "date_from": date(2026, 9, 1), "wage": 32000,
        "mil_status": "liable", "mil_tcc": "Оболонський РТЦК та СП", "mil_doc_type": "ticket",
        "mil_doc_number": "АБ 654321",
    })
    for name, t in [("zayava_melnyk.pdf", "statement"), ("id-card_melnyk.png", "passport"),
                    ("rnokpp_melnyk.png", "rnokpp"), ("vijskovyj_melnyk.png", "military_id"),
                    ("zgoda_melnyk.png", "consent")]:
        melnyk.add_file(name, png, t)
    errs = [c for c in melnyk._checks() if c["level"] == "error"]
    if errs:
        raise Exception("Мельник: справу не можна прийняти: %s" % errs)
    melnyk.action_hire()
    to_sign = melnyk.employee_id.ua_document_ids.filtered(lambda d: d.state == "to_sign")
    for d in to_sign[:2]:
        d.action_mark_signed()

# ---- відмова, з причиною
if not Case.search([("last_name", "=", "Гриценко")]):
    Case.with_company(company).create({
        "company_id": company.id, "stage": "declined", "last_name": "Гриценко", "first_name": "Павло",
        "job_title": "Водій", "phone": "+380 67 111 22 33", "source": "оголошення",
        "interview_date": today - timedelta(days=5), "expected_wage": 22000,
        "decline_reason": "Кандидат відмовився: прийняв іншу пропозицію.",
    })

env.cr.commit()
print("DEMO-HIRE: OK", Case.search_count([]))

# ---- перевірка _checks() на справі в оформленні: має бути і помилка, і попередження
bondar = Case.search([("last_name", "=", "Бондар")], limit=1)
print("БОНДАР _checks():")
for c in bondar._checks():
    print(" -", c["level"], "|", c["title"], "|", c["detail"])

# ---- зведення покриття
print()
print("Справи за етапом:")
for stage in ("candidate", "onboarding", "hired", "declined"):
    print(" ", stage, Case.search_count([("stage", "=", stage)]))

print("Файли за видом документа (справа Бондаря):")
for dt, _label in File._fields["doc_type"].selection:
    n = File.search_count([("case_id", "=", bondar.id), ("doc_type", "=", dt)])
    if n:
        print(" ", dt, n)
print("Файли за станом розпізнавання (справа Бондаря):")
for st, _label in File._fields["extract_state"].selection:
    n = File.search_count([("case_id", "=", bondar.id), ("extract_state", "=", st)])
    if n:
        print(" ", st, n)

print("Пропозиції за станом (справа Бондаря):")
for st, _label in Proposal._fields["state"].selection:
    n = Proposal.search_count([("case_id", "=", bondar.id), ("state", "=", st)])
    if n:
        print(" ", st, n)
print("Пропозиції за впевненістю (справа Бондаря):")
for cf, _label in Proposal._fields["confidence"].selection:
    n = Proposal.search_count([("case_id", "=", bondar.id), ("confidence", "=", cf)])
    if n:
        print(" ", cf, n)

melnyk = Case.search([("last_name", "=", "Мельник")], limit=1)
# Мельник не звільнена - раніше demo_company.py помилково архівував її як «застарілу» демо-картку
# (виправлено там). Тут - разова підстраховка на випадок, якщо запис уже встиг заархівуватись.
if melnyk.employee_id and not melnyk.employee_id.active:
    melnyk.employee_id.sudo().write({"active": True})
    env.cr.commit()
Doc = env["ua.employee.document"].sudo()
print("Документи працівниці Мельник за станом:")
for st, _label in Doc._fields["state"].selection:
    n = Doc.search_count([("employee_id", "=", melnyk.employee_id.id), ("state", "=", st)])
    if n:
        print(" ", st, n)
"""

# `docker compose run --rm` замість `exec`: `exec` заходить у довгоживучий контейнер стенду,
# а той піднятий з --db-filter під свою базу і для будь-якої іншої бази не годиться.
# Одноразовий контейнер бере базу з рядка команди, тому працює для payroll, demo і тестових.
proc = subprocess.run(
    ["docker", "compose", "run", "--rm", "--no-deps", "-T", "odoo", "sh", "-c",
     f"odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d {DB} --no-http --log-level=warn"],
    input=SCRIPT, capture_output=True, text=True, cwd=ROOT,
)
print(proc.stdout.strip())
if "DEMO-HIRE: OK" not in proc.stdout:
    print(proc.stderr[-3000:])
    sys.exit(1)
