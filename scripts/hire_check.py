"""Перевірка модуля l10n_ua_hire («Прийняття») на стенді, база PAYROLL_DB (типово payroll).

Запускається через `odoo shell`; усі зміни відкочуються в кінці (крім номера К-1, який бере postgres-послідовність).
Перевіряє: РНОКПП (контрольна цифра, дата, стать); стани полів і обов'язкові поля за етапом; військовий облік
за статтю і віком; документи з довідника; пропозиції з розпізнавання (підробна відповідь помічника) - нормалізація,
прийняття, відхилення, слід рішення; блок «Прийняти» при помилках; прийняття створює картку, документи,
проведений наказ, J3001005 з цим працівником і повідомлення ТЦК; дані екрана.

Запуск: python3 scripts/hire_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import base64
import sys
import json
from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.addons.l10n_ua_hire.models import ua_hire_case as hc

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def make_rnokpp(birthday, male, mid="123"):
    days = (birthday - date(1899, 12, 31)).days
    base = "%05d%s" % (days, mid)
    ninth = 1 if male else 2
    d = [int(c) for c in base] + [ninth]
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    return base + str(ninth) + str(sum(w * x for w, x in zip(weights, d)) % 11 % 10)


Case = env["ua.hire.case"].sudo()
bday = date(1990, 5, 14)
good = make_rnokpp(bday, True)

# ---- 1. РНОКПП
check("правильний РНОКПП без зауважень", hc.rnokpp_problems(good, bday, "male") == [], good)
bad_sum = good[:9] + str((int(good[9]) + 1) % 10)
check("хибна контрольна цифра", any("контрольна" in p for p in hc.rnokpp_problems(bad_sum)))
check("дата народження не збігається", any("дату народження" in p for p in hc.rnokpp_problems(good, date(1991, 1, 1))))
check("стать не збігається", any("статі" in p for p in hc.rnokpp_problems(good, bday, "female")))
check("не 10 цифр", hc.rnokpp_problems("12345") == ["має бути 10 цифр"])

# ---- 2. кандидат: мінімум полів
dept = env["hr.department"].search([], limit=1)
cid = Case.create_case(last_name="Перевірочний", first_name="Тарас", job_title="Бухгалтер")
case = Case.browse(cid)
states = case._field_states()
check("кандидат: обов'язкові лише ПІБ і посада", states["rnokpp"] == "empty" and states["last_name"] == "provided", states["rnokpp"])
check("кандидат: немає помилок", not [c for c in case._checks() if c["level"] == "error"])

# ---- 3. оформлення: нові обов'язкові поля
case.action_start_onboarding()
check("етап «Оформлення»", case.stage == "onboarding")
states = case._field_states()
check("оформлення: РНОКПП і перший день обов'язкові", states["rnokpp"] == "missing" and states["date_from"] == "missing")
check("оформлення: ким виданий/дата видачі/УНЗР не обов'язкові", states["id_doc_issued_by"] == "empty" and states["id_doc_date"] == "empty" and states["id_doc_unzr"] == "empty")
check("«Прийняття» пропонує лише трудовий договір", [k for k, _v in case._field_meta(case)["contract_kind"]["options"]] == ["employment"])
check("оформлення: «Прийняти» заблоковано", case._case_payload()["can_hire"] is False)
try:
    case.action_hire()
    check("action_hire відмовляє при помилках", False)
except UserError:
    check("action_hire відмовляє при помилках", True)

# ---- 4. ручне введення
start = date.today() + timedelta(days=10)
for f, v in [("birthday", bday.isoformat()), ("sex", "male"), ("id_doc_type", "id_card"), ("id_doc_number", "123456789"),
             ("id_doc_unzr", "19900514-01234"), ("id_doc_issued_by", "4610"), ("id_doc_date", "2020-01-10"),
             ("reg_address", "м. Київ, вул. Перевірочна, 1"), ("date_from", start.isoformat()), ("wage", "25000"),
             ("department_id", str(dept.id)), ("pd_consent", True), ("rnokpp", bad_sum)]:
    case.set_value(f, v)
check("set_value пише дату, число і підрозділ", case.birthday == bday and case.wage == 25000 and case.department_id == dept)
titles = [c["title"] for c in case._checks()]
check("хибний РНОКПП дає помилку", "РНОКПП не проходить перевірку" in titles)
case.set_value("rnokpp", good)
check("військовий облік обов'язковий для чоловіка 36 років", case._military_required() and case._field_states()["mil_status"] == "missing")
case.set_value("sex", "female")
check("жінці облік не обов'язковий", not case._military_required())
case.set_value("sex", "male")
try:
    case.set_value("employee_id", 1)
    check("службові поля не редагуються з екрана", False)
except UserError:
    check("службові поля не редагуються з екрана", True)

# ---- 4a. пакет першого дня
pkg = case._package()
check("пакет: 7 документів (включно з описом справи), усі позначені",
      len(pkg) == 7 and all(d["on"] for d in pkg), str([d["key"] for d in pkg]))
check("умови оплати: значення за замовчуванням з компанії",
      case.pay_advance_percent == case.company_id.ua_pay_advance_percent and case.pay_advance_day == case.company_id.ua_pay_advance_day)
case.set_package_doc("nda", False)
check("пакет: документ можна зняти", [d["key"] for d in case._package() if not d["on"]] == ["nda"])
case.set_package_doc("nda", True)
Report = env["ir.actions.report"].sudo()
for d in pkg:
    html, _fmt = Report._render_qweb_html(d["item"]["r"], d["item"]["ids"])
    text = html.decode()
    check("пакет: «%s» містить ПІБ" % d["label"], "Перевірочний" in text or "ПЕРЕВІРОЧНИЙ" in text)
contract_html = Report._render_qweb_html("l10n_ua_hire.report_hire_contract", [case.id])[0].decode()
check("договір: оклад і перший день у тексті", "25" in contract_html and start.strftime("%d.%m.%Y") in contract_html)
inventory_html = Report._render_qweb_html("l10n_ua_hire.report_hire_file_inventory", [case.id])[0].decode()
check("опис справи: назва звіту і документи в тексті", "ОПИС ДОКУМЕНТІВ" in inventory_html and "Заява про прийняття" in inventory_html)

reqs = {r["code"]: r["state"] for r in case._requirements()}
check("довідник: заява і паспорт бракує, наказ створить система",
      reqs.get("statement") == "missing" and reqs.get("passport_rnokpp") == "missing" and reqs.get("hire_order") == "later", str(reqs))

# ---- 5. файли і розпізнавання (підробна відповідь помічника)
png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()
for name, t in [("zayava.png", "statement"), ("id-card.png", "passport"), ("rnokpp.png", "rnokpp"),
                ("vijskovyj.png", "military_id"), ("zgoda.png", "consent")]:
    case.add_file(name, png, t)


class FakeResp:
    ok = True
    status_code = 200

    def json(self):
        return {"model": "claude-test", "proposals": [
            {"field": "middle_name", "value": "Іванович", "file": "id-card.png", "quote": "ІВАНОВИЧ", "confidence": "high"},
            {"field": "mil_status", "value": "Військовозобов'язаний", "file": "vijskovyj.png", "quote": "військовозобов'язаний", "confidence": "high"},
            {"field": "mil_tcc", "value": "Шевченківський РТЦК та СП", "file": "vijskovyj.png", "quote": "Шевченківський", "confidence": "medium"},
            {"field": "mil_doc_type", "value": "ticket", "file": "vijskovyj.png", "quote": "", "confidence": "high"},
            {"field": "mil_doc_number", "value": "АА 123456", "file": "vijskovyj.png", "quote": "123456", "confidence": "high"},
            {"field": "birthday", "value": "14.05.1991", "file": "id-card.png", "quote": "14.05.1991", "confidence": "low"},
            {"field": "wage", "value": "99999", "file": "zayava.png", "quote": "", "confidence": "high"},
            {"field": "sex", "value": "невідомо", "file": "id-card.png", "quote": "", "confidence": "low"},
        ]}


case.write({"pd_consent": False})
try:
    case.action_extract()
    check("без згоди розпізнавання не йде", False)
except UserError:
    check("без згоди розпізнавання не йде", True)
case.write({"pd_consent": True})
with patch.object(hc.requests, "post", return_value=FakeResp()) as post:
    res = case.action_extract()
    sent = json.loads(post.call_args.kwargs["data"])
check("у помічник ідуть лише поля з документів", "wage" not in sent["fields"] and "rnokpp" in sent["fields"])
check("у помічник ідуть 5 файлів", len(sent["files"]) == 5)
check("пропозицій 6: умови роботи і хибна стать відкинуті", res["created"] == 6, str(res))
props = {p.field_name: p for p in case.proposal_ids}
check("вибір за назвою перетворено на ключ", props["mil_status"].value == "liable", props["mil_status"].value)
check("дата 14.05.1991 перетворена в ISO", props["birthday"].value == "1991-05-14")
check("значення не записані без підтвердження", not case.middle_name and not case.mil_status)
check("поле з пропозицією має стан «запропоновано»", case._field_states()["middle_name"] == "proposed")
payload = case._case_payload()
check("конфлікт з наявним значенням позначено", payload["proposals"]["birthday"][0]["conflict"] is True)
check("файли позначено як розпізнані", set(case.file_ids.mapped("extract_state")) == {"done"})

for f in ("middle_name", "mil_status", "mil_tcc", "mil_doc_type", "mil_doc_number"):
    props[f].action_accept()
props["birthday"].action_reject()
check("прийняті значення в полях", case.middle_name == "Іванович" and case.mil_status == "liable" and case.mil_doc_type == "ticket")
check("відхилена пропозиція не змінила дату", case.birthday == bday)
check("слід рішення: хто і коли", props["mil_tcc"].decided_by.id == env.uid and props["mil_tcc"].decided_at)
with patch.object(hc.requests, "post", return_value=FakeResp()):
    res2 = case.action_extract()
check("повтор не дублює прийняті значення", res2["created"] <= 2, str(res2))
case.proposal_ids.filtered(lambda p: p.state == "pending").action_reject()

# ---- 6. прийняття
payload = case._case_payload()
errs = [c["title"] + ": " + c["detail"] for c in payload["checks"] if c["level"] == "error"]
check("після даних і файлів помилок немає", not errs, "; ".join(errs))
check("«Прийняти» доступне", payload["can_hire"] is True)

# ---- 5a. пакет документів (package_for) до прийняття: справжня справа, документів ще нема
Requirement = env["ua.hr.doc.requirement"].sudo()
all_reqs = Requirement.search([], order="sequence")
check("довідник: усі вимоги мають джерело employee/company",
      all(r.source in ("employee", "company") for r in all_reqs), str(all_reqs.mapped("source")))
# Від компанії - усе, що вона складає і підписує сама: заява, наказ, трудовий договір,
# договір ЦПХ, згода, інструктаж з охорони праці. Від працівника лишається те, що ми
# тільки приймаємо і зберігаємо (паспорт із РНОКПП, військовий документ, медогляд).
check("довідник: «від компанії» - те, що компанія складає сама",
      set(all_reqs.filtered(lambda r: r.source == "company").mapped("code"))
      == {"statement", "hire_order", "contract", "consent", "safety_briefing", "gph_contract"},
      str(all_reqs.filtered(lambda r: r.source == "company").mapped("code")))
# Медогляд у довіднику вимкнений (active=False), тому серед чинних вимог його немає.
check("довідник: «від працівника» - лише те, що приносять",
      set(all_reqs.filtered(lambda r: r.source == "employee").mapped("code"))
      == {"passport_rnokpp", "military_id"},
      str(all_reqs.filtered(lambda r: r.source == "employee").mapped("code")))

pkg_pre = Requirement.package_for(case=case)
pre_emp_codes = {r["code"] for r in pkg_pre["employee"]["rows"]}
pre_co_codes = {r["code"] for r in pkg_pre["company"]["rows"]}
check("пакет до прийняття: коди employee і company не перетинаються",
      not (pre_emp_codes & pre_co_codes), str(pre_emp_codes & pre_co_codes))
check("пакет до прийняття: company - пакет першого дня і папери компанії",
      pre_co_codes == {"statement", "hire_order", "contract", "nda", "consent", "ack",
                       "inventory", "safety_briefing", "gph_contract"}, str(pre_co_codes))
# Підпис до прийняття має рівно одне джерело: повернутий підписаний скан. Типи файлів
# справи так і звуться («Трудовий договір, підписаний»), тому такий рядок стоїть signed,
# а решта company-рядків лишається без підпису, бо документа ще нема.
signed_pre = {r["code"] for r in pkg_pre["company"]["rows"] if r["sign"] == "signed"}
scan_types = {f.doc_type for f in case.file_ids}
alias = {"acknowledgement": "ack"}
expect_signed = {alias.get(t, t) for t in scan_types} & pre_co_codes
check("пакет до прийняття: signed лише там, де є підписаний скан",
      signed_pre == expect_signed, f"{sorted(signed_pre)} проти {sorted(expect_signed)}")
check("пакет до прийняття: решта company без підпису",
      all(r["sign"] is None for r in pkg_pre["company"]["rows"] if r["code"] not in signed_pre),
      str([(r["code"], r["sign"]) for r in pkg_pre["company"]["rows"]
           if r["code"] not in signed_pre and r["sign"] is not None]))
gph_row_pre = next((r for r in pkg_pre["company"]["rows"] if r["code"] == "gph_contract"), None)
check("пакет до прийняття: ЦПХ-договір для штатного - not_needed",
      gph_row_pre is not None and gph_row_pre["state"] == "not_needed", gph_row_pre)
check("пакет до прийняття: not_needed не рахується в need",
      pkg_pre["company"]["need"] == sum(1 for r in pkg_pre["company"]["rows"] if r["state"] != "not_needed")
      and pkg_pre["company"]["need"] < len(pkg_pre["company"]["rows"]),
      (pkg_pre["company"]["need"], len(pkg_pre["company"]["rows"])))
check("пакет до прийняття: стани лише have/missing/expired/not_needed",
      {r["state"] for b in (pkg_pre["employee"], pkg_pre["company"]) for r in b["rows"]} <= {"have", "missing", "expired", "not_needed"})

case.action_hire()
emp = case.employee_id
check("створено картку працівника", bool(emp) and emp.ua_rnokpp == good and emp.ua_middle_name == "Іванович", emp.name)
check("військові дані перенесено", emp.ua_mil_status == "liable" and emp.ua_mil_tcc == "Шевченківський РТЦК та СП")
check("файли стали документами працівника", len(emp.ua_document_ids.filtered("file")) == 5, str(len(emp.ua_document_ids.filtered("file"))))
check("наказ проведено з номером", case.order_id.state == "posted" and bool(case.order_id.name), case.order_id.name or "")
check("одна версія контракту з першим днем і окладом", len(emp.version_ids) == 1 and emp.version_ids.contract_date_start == start and emp.version_ids.wage == 25000, str([(v.date_version, v.wage) for v in emp.version_ids]))

# ---- 5b. пакет документів після прийняття: картка й справа дають однакові рядки
pkg_emp = Requirement.package_for(employee=emp)
pkg_case_after = Requirement.package_for(case=case)


def _counts_ok(pkg):
    e, c = pkg["employee"], pkg["company"]
    e_have = sum(1 for r in e["rows"] if r["state"] == "have")
    e_need = sum(1 for r in e["rows"] if r["state"] != "not_needed")
    c_done = sum(1 for r in c["rows"] if r["state"] == "have")
    c_need = sum(1 for r in c["rows"] if r["state"] != "not_needed")
    c_signed = sum(1 for r in c["rows"] if r["sign"] == "signed")
    return (e["have"], e["need"], c["done"], c["need"], c["signed"]) == (e_have, e_need, c_done, c_need, c_signed)


check("пакет: have/need/done/signed збігаються з рядками", _counts_ok(pkg_emp))
check("пакет: sign заповнений лише в company", all(r["sign"] is None for r in pkg_emp["employee"]["rows"]))


def _target_opens(row):
    t = row.get("target")
    return t is None or bool(env[t["model"]].sudo().browse(t["res_id"]).exists())


all_rows = pkg_emp["employee"]["rows"] + pkg_emp["company"]["rows"]
bad_targets = [r["code"] for r in all_rows if not _target_opens(r)]
check("пакет: кожен target відкривається", not bad_targets, str(bad_targets))


def _rows_by_code(pkg):
    return {r["code"]: {k: v for k, v in r.items() if k != "target"}
            for block in ("employee", "company") for r in pkg[block]["rows"]}


rows_emp, rows_case = _rows_by_code(pkg_emp), _rows_by_code(pkg_case_after)
diff = {k: (v, rows_case.get(k)) for k, v in rows_emp.items() if v != rows_case.get(k)}
check("пакет: картка й справа того самого працівника дають однакові рядки", not diff, str(diff))

card_pkg = emp.get_ua_doc_package()
check("hr.employee.get_ua_doc_package - той самий спільний метод, не копія", card_pkg == pkg_emp)

payload_after = case._case_payload()
check("справа: package_split у payload", payload_after["package_split"] == pkg_case_after)
check("справа: requirements/package/checks лишились у payload",
      all(k in payload_after for k in ("requirements", "package", "checks")))
check("справа: other_files - список {name, doc_type, target}",
      isinstance(payload_after["other_files"], list)
      and all({"name", "doc_type", "target"} <= set(f) for f in payload_after["other_files"]))

run = case.j30_run_id
check("J3001005 за місяць першого дня", run.report_code == "j30" and run.month == start.month, run.name)
check("повідомлення ТЦК містить працівника", emp in case.notice_id.line_ids.mapped("employee_id"))
check("етап «Прийнято»", case.stage == "hired")
payload = case._case_payload()
check("пакет після прийняття друкує проведений наказ", [d["item"]["r"] for d in case._package() if d["key"] == "order"] == ["l10n_ua_hr_orders.report_ua_hr_order"])
check("результати: картка, наказ, J30, ТЦК", [r["key"] for r in payload["results"]] == ["employee", "order", "j30", "notice"])
try:
    case.set_value("phone", "123")
    check("закрита справа не редагується", False)
except UserError:
    check("закрита справа не редагується", True)

# ---- 7. екран
data = Case.get_screen_data(case_id=case.id)
check("екран: справа в списку і обрана", any(r["id"] == case.id for r in data["cases"]) and data["case"]["id"] == case.id)
check("екран: метадані всіх полів", all(f in data["meta"] for _k, _t, names in hc.SECTIONS for f in names))
check("екран: перелік підрозділів і видів документів", bool(data["departments"]) and bool(data["doc_types"]))
check("меню «Прийняття» у «Працівниках»", env.ref("l10n_ua_hire.menu_ua_hire").parent_id == env.ref("l10n_ua_navigation.menu_ua_people_root"))
check("«Новий працівник» у списку відключено - оформлюють через «Прийняття»",
      env.ref("l10n_ua_hire.hr_employee_view_list_no_create").exists())

# ---- 8. документи на підпис (пакет першого дня + наказ) - виконується після всіх перевірок
# прийняття, щоб не зачепити «одна версія контракту» додатковим наказом про зміну окладу нижче.
to_sign = emp.ua_document_ids.filtered(lambda d: d.state == "to_sign")
check("6 документів пакета (включно з описом справи) плюс наказ - на підпис", len(to_sign) == 7, str(sorted(to_sign.mapped("type"))))
inventory_rows = case._file_inventory()
check("опис справи: файли кандидата і згенеровані документи пораховані",
      len(inventory_rows) == len(case.file_ids.filtered("file")) + 6, str(len(inventory_rows)))
check("опис справи: сторінки - число, не порожнє", all(isinstance(r["pages"], int) and r["pages"] >= 1 for r in inventory_rows))
check("усі документи на підпис мають звіт і джерело", all(d.report_xmlid and d.res_id and d.res_model for d in to_sign))
order_doc = emp.ua_document_ids.filtered(lambda d: d.type == "order")
check("документ наказу веде на проведений наказ", order_doc.res_model == "ua.hr.order" and order_doc.res_id == case.order_id.id, order_doc.res_id)
statement_doc = emp.ua_document_ids.filtered(lambda d: d.type == "statement" and d.state == "to_sign")
statement_doc.action_mark_signed()
check("«Підписано» проставляє стан і дату", statement_doc.state == "signed" and bool(statement_doc.signed_date))
print_action = statement_doc.action_print()
check("«Друк» відкриває пакет /ua/print з тим самим звітом", print_action["url"].startswith("/ua/print?") and "report_hire_statement" in print_action["url"])

# ---- 8a. наказ поза прийняттям (зміна окладу): проведення створює документ, ознайомлення підписує
Order = env["ua.hr.order"].sudo()
wage_order = Order.create({
    "order_type": "wage", "employee_id": emp.id, "company_id": case.company_id.id,
    "date_from": start + timedelta(days=30), "wage": 27000,
})
wage_order.action_post()
wage_doc = env["ua.employee.document"].sudo().search([("order_id", "=", wage_order.id)])
check("проведення наказу створює документ на підпис", len(wage_doc) == 1 and wage_doc.state == "to_sign", str(len(wage_doc)))
wage_order.action_acknowledge()
check("ознайомлення підписує документ наказу", wage_doc.state == "signed" and wage_doc.signed_date == wage_order.ack_date)
wage_order.action_cancel()
wage_order.action_post()
wage_doc2 = env["ua.employee.document"].sudo().search([("order_id", "=", wage_order.id)])
check("повторне проведення не дублює документ", len(wage_doc2) == 1, str(len(wage_doc2)))

# ---- 8b. звільнення і повторне прийняття: нова картка, стара архівна, посилання «Попередня картка»
# Окремий кандидат (не «emp» із секції 8a - у нього вже дві версії контракту через повторне
# проведення наказу про оклад, і третя версія там штучно конфліктувала б за датами).
bday3 = date(1985, 3, 20)
good3 = make_rnokpp(bday3, False, mid="777")
cid3 = Case.create_case(last_name="Рехайрна", first_name="Богдана", job_title="Комірниця")
case3 = Case.browse(cid3)
case3.action_start_onboarding()
start3 = date.today() + timedelta(days=5)
for f, v in [("birthday", bday3.isoformat()), ("sex", "female"), ("id_doc_type", "id_card"), ("id_doc_number", "223456789"),
             ("reg_address", "м. Київ, вул. Перша, 2"), ("date_from", start3.isoformat()),
             ("wage", "20000"), ("department_id", str(dept.id)), ("pd_consent", True), ("rnokpp", good3)]:
    case3.set_value(f, v)
for name, t in [("zayava3.png", "statement"), ("id3.png", "passport"), ("zgoda3.png", "consent")]:
    case3.add_file(name, png, t)
errs3 = [c["title"] for c in case3._checks() if c["level"] == "error"]
check("перше прийняття кандидата для тесту рехайру: без помилок", not errs3, "; ".join(errs3))
case3.action_hire()
emp3 = case3.employee_id
check("перша картка створена", bool(emp3))

dismiss_order = Order.create({
    "order_type": "dismissal", "employee_id": emp3.id, "company_id": case3.company_id.id,
    "date_to": start3 + timedelta(days=60), "dismissal_basis": "п. 1 ст. 36 КЗпП",
})
dismiss_order.action_post()
check("звільнення архівує працівника", not emp3.active, emp3.active)

cid4 = Case.create_case(last_name="Рехайрна", first_name="Богдана", job_title="Комірниця")
case4 = Case.browse(cid4)
case4.action_start_onboarding()
start4 = start3 + timedelta(days=120)
for f, v in [("birthday", bday3.isoformat()), ("sex", "female"), ("id_doc_type", "id_card"), ("id_doc_number", "223456789"),
             ("reg_address", "м. Київ, вул. Перша, 2"), ("date_from", start4.isoformat()),
             ("wage", "21000"), ("department_id", str(dept.id)), ("pd_consent", True), ("rnokpp", good3)]:
    case4.set_value(f, v)
for name, t in [("zayava4.png", "statement"), ("id4.png", "passport"), ("zgoda4.png", "consent")]:
    case4.add_file(name, png, t)
errs4 = [c["title"] for c in case4._checks() if c["level"] == "error"]
check("повторне прийняття: помилок немає", not errs4, "; ".join(errs4))
case4.action_hire()
emp4 = case4.employee_id
check("повторне прийняття створює НОВУ картку", emp4.id != emp3.id, (emp4.id, emp3.id))
check("нова картка посилається на попередню", emp4.ua_previous_employee_id.id == emp3.id, emp4.ua_previous_employee_id.id)
check("стара картка лишається архівною", not emp3.active)
card4 = emp4.get_card_data()
check("шапка картки показує «Попередня картка»",
      card4["header"]["previous_employee"] and card4["header"]["previous_employee"]["id"] == emp3.id, card4["header"].get("previous_employee"))

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
