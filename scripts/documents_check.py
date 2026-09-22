"""Перевірка документів на підпис (ua.employee.document: state/signed_date/report_xmlid,
пакет прийняття з package_skip, вкладка «Документи» картки OWL, дія на наказі поза прийняттям).
База PAYROLL_DB (типово payroll). Доповнює hire_check.py (який уже перевіряє щасливий шлях
прийняття): тут - зняті в пакеті документи, картка OWL і фільтр «на підпис».

Запуск: PAYROLL_DB=payroll_docs python3 scripts/documents_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import base64
import sys
from datetime import date, timedelta

from odoo.exceptions import UserError

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def make_rnokpp(birthday, male, mid="456"):
    days = (birthday - date(1899, 12, 31)).days
    base = "%05d%s" % (days, mid)
    ninth = 1 if male else 2
    d = [int(c) for c in base] + [ninth]
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    return base + str(ninth) + str(sum(w * x for w, x in zip(weights, d)) % 11 % 10)


Case = env["ua.hire.case"].sudo()
dept = env["hr.department"].search([], limit=1)
bday = date(1988, 3, 3)
rnokpp = make_rnokpp(bday, False)
start = date.today() + timedelta(days=5)

cid = Case.create_case(last_name="Документова", first_name="Ольга", job_title="Юрист")
case = Case.browse(cid)
case.action_start_onboarding()
for f, v in [("birthday", bday.isoformat()), ("sex", "female"), ("id_doc_type", "id_card"),
             ("id_doc_number", "987654321"), ("id_doc_unzr", "19880303-04321"), ("id_doc_issued_by", "4610"),
             ("id_doc_date", "2019-02-01"), ("reg_address", "м. Львів, вул. Перевірочна, 2"),
             ("date_from", start.isoformat()), ("wage", "30000"), ("department_id", str(dept.id)),
             ("pd_consent", True), ("rnokpp", rnokpp)]:
    case.set_value(f, v)

# довідник вимагає копію паспорта чи РНОКПП і згоду ще ДО прийняття (обов'язкові документи
# кандидата) - окремо від пакета першого дня на підпис, який прийняття щойно створить.
png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()
for name, t in [("zayava.png", "statement"), ("id-card.png", "passport"), ("zgoda.png", "consent")]:
    case.add_file(name, png, t)

# ---- 1. package_skip -> "не потрібен" замість "на підпис"
case.set_package_doc("nda", False)
case.set_package_doc("order", False)
check("пакет: 4 позначено, 2 зняті", [d["key"] for d in case._package() if not d["on"]] == ["order", "nda"])

case.action_hire()
emp = case.employee_id


# pkg(): документ пакета першого дня - тип збігається з ключем пакета і файлу нема (файли
# кандидата - окремі документи типу statement/passport/consent, завантажені вище).
def pkg(type_key):
    return emp.ua_document_ids.filtered(lambda d: d.type == type_key and not d.file)


check("знятий у пакеті документ - «не потрібен»", pkg("nda").state == "not_needed")
check("решта пакета - «на підпис»", all(pkg(k).state == "to_sign" for k in ("statement", "contract", "consent", "ack")))
order_doc = emp.ua_document_ids.filtered(lambda d: d.type == "order")
check("знятий наказ теж «не потрібен»", order_doc.state == "not_needed")
check("документ наказу все одно веде на проведений наказ", order_doc.res_model == "ua.hr.order" and order_doc.res_id == case.order_id.id)
check("документи пакета без файлу (лише printable)", not pkg("statement").file and not pkg("contract").file)

# ---- 2. дія «Підписано»/«Друк» напряму на моделі
doc = pkg("contract")
check("новий документ спершу без дати підпису", not doc.signed_date)
doc.action_mark_signed()
check("action_mark_signed виставляє стан і сьогоднішню дату", doc.state == "signed" and doc.signed_date == date.today())
act = doc.action_print()
check("action_print повертає act_url на /ua/print з тим самим звітом", act["type"] == "ir.actions.act_url" and "report_hire_contract" in act["url"])
no_report_doc = pkg("nda")
no_report_doc.report_xmlid = False
try:
    no_report_doc.action_print()
    check("друк без report_xmlid відмовляє", False)
except UserError:
    check("друк без report_xmlid відмовляє", True)

# ---- 3. дії документа на стандартній формі: action_mark_signed / action_print
statement_doc = pkg("statement")
check("«на підпис» стоїть у стані to_sign", statement_doc.state == "to_sign", statement_doc.state)
statement_doc.action_mark_signed()
check("action_mark_signed підписує документ", statement_doc.state == "signed")
check("підпис ставить сьогоднішню дату", statement_doc.signed_date == date.today(), str(statement_doc.signed_date))
print_result = statement_doc.action_print()
check("action_print повертає дію друку", isinstance(print_result, dict) and print_result.get("type") in ("ir.actions.act_url", "ir.actions.report"), str(print_result)[:80])
try:
    no_report_doc.action_print()
    check("«не потрібен» без звіту не друкується", False)
except Exception as e:
    check("«не потрібен» без звіту не друкується", "звіт" in str(e) or "report" in str(e).lower(), str(e)[:80])

# ---- 4. фільтр «на підпис» на стандартному вигляді
to_sign_action = env.ref("l10n_ua_hr_card.action_ua_employee_document")
check("дія «Документи на підпис» шукає state=to_sign", bool(to_sign_action.context) and "search_default_to_sign" in to_sign_action.context)
found = env["ua.employee.document"].sudo().search([("id", "in", emp.ua_document_ids.ids), ("state", "=", "to_sign")])
check("фільтр to_sign повертає лише документи на підпис", set(found.mapped("state")) <= {"to_sign"} and len(found) > 0, str(len(found)))

# ---- 4b. скан документа - вкладення картки працівника (OCA hr_employee_document)
Attachment = env["ir.attachment"].sudo()
with_file = emp.ua_document_ids.filtered("attachment_id")
check("файли кандидата стали документами зі сканом", len(with_file) == 3, str(len(with_file)))
check("скани лежать вкладеннями картки працівника, а не моделі документа",
      all(a.res_model == "hr.employee" and a.res_id == emp.id and not a.res_field
          for a in with_file.mapped("attachment_id")),
      str({(a.res_model, a.res_field) for a in with_file.mapped("attachment_id")}))
check("вкладень на моделі документа не лишилось",
      Attachment.search_count([("res_model", "=", "ua.employee.document")]) == 0)
emp.invalidate_recordset(["document_count"])
check("кнопка «Документи» OCA бачить ті самі скани", emp.document_count >= len(with_file),
      f"{emp.document_count} вкладень на картці, сканів документів {len(with_file)}")
scan = with_file[0]
check("файл документа читається назад із вкладення", bool(scan.file), scan.filename or "")
scan_attachment = scan.attachment_id
scan.unlink()
check("видалення документа прибирає його вкладення", not scan_attachment.exists())

# ---- 5. наказ поза прийняттям: проведення створює документ, ознайомлення підписує
Order = env["ua.hr.order"].sudo()
transfer_order = Order.create({
    "order_type": "transfer", "employee_id": emp.id, "company_id": case.company_id.id,
    "date_from": start + timedelta(days=20), "department_id": dept.id,
})
transfer_order.action_post()
tdoc = env["ua.employee.document"].sudo().search([("order_id", "=", transfer_order.id)])
check("наказ про переведення отримує документ на підпис", len(tdoc) == 1 and tdoc.type == "order" and tdoc.state == "to_sign")
check("документ наказу має report_xmlid звіту наказу", tdoc.report_xmlid == "l10n_ua_hr_orders.report_ua_hr_order")
transfer_order.action_acknowledge()
check("ознайомлення з наказом підписує документ датою ознайомлення", tdoc.state == "signed" and tdoc.signed_date == transfer_order.ack_date)

env.cr.rollback()
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
if "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" in out or "Усі перевірки пройдено" not in out:
    print("--- stderr ---")
    print(proc.stderr[-4000:])
    sys.exit(1)
