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
case.action_hire()
emp = case.employee_id
check("створено картку працівника", bool(emp) and emp.ua_rnokpp == good and emp.ua_middle_name == "Іванович", emp.name)
check("військові дані перенесено", emp.ua_mil_status == "liable" and emp.ua_mil_tcc == "Шевченківський РТЦК та СП")
check("файли стали документами працівника", len(emp.ua_document_ids) == 5, str(len(emp.ua_document_ids)))
check("наказ проведено з номером", case.order_id.state == "posted" and bool(case.order_id.name), case.order_id.name or "")
check("одна версія контракту з першим днем і окладом", len(emp.version_ids) == 1 and emp.version_ids.contract_date_start == start and emp.version_ids.wage == 25000, str([(v.date_version, v.wage) for v in emp.version_ids]))
run = case.j30_run_id
check("J3001005 за місяць першого дня", run.report_code == "j30" and run.month == start.month, run.name)
check("повідомлення ТЦК містить працівника", emp in case.notice_id.line_ids.mapped("employee_id"))
check("етап «Прийнято»", case.stage == "hired")
payload = case._case_payload()
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
