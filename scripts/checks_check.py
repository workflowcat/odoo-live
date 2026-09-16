"""Перевірка спільної форми перевірок (ua.checks.mixin) на стенді, база PAYROLL_DB (типово payroll).

Запускається через `odoo shell`; нічого не записує (тільки читає й одразу rollback).
Для кожної моделі документа (табель, штатний розпис, авансова відомість, відомість на
перерахування, заява-розрахунок ПФУ, військові список/повідомлення/заброньовані) бере
записи вересня (демоданих) і бере записи, якщо демоданих вересня немає, і перевіряє:
  - _checks() повертає список рядків {level, text, fact, target};
  - кожен рядок з target можна відкрити - domain шукається без помилки / res_id існує / xmlid існує;
  - серед документів вересня є хоч один warn або error (демодані: 19 чернеток листків,
    чернетка табеля - мають дати привід для попереджень).

Запуск: python3 scripts/checks_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import sys

errors = []
total = 0
any_warn_or_error = False


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def resolve_target(target):
    # True якщо ціль можна відкрити: domain шукається, res_id існує, xmlid існує.
    if target is None:
        return True, "немає цілі"
    if target.get("xmlid"):
        try:
            env.ref(target["xmlid"])
            return True, "xmlid"
        except Exception as e:
            return False, f"xmlid не знайдено: {e}"
    if target.get("model") and target.get("res_id"):
        rec = env[target["model"]].sudo().browse(target["res_id"])
        return rec.exists(), "res_id не існує" if not rec.exists() else "res_id"
    if target.get("model") and target.get("domain") is not None:
        try:
            env[target["model"]].sudo().search(target["domain"], limit=1)
            return True, "domain"
        except Exception as e:
            return False, f"domain не шукається: {e}"
    return False, "ціль без моделі"


def check_record_checks(record, label):
    # Рахує перевірки одного запису і перевіряє їхню форму та цілі.
    global any_warn_or_error
    checks = record._checks()
    check(f"{label}: _checks() повертає список", isinstance(checks, list), f"{len(checks) if isinstance(checks, list) else type(checks)}")
    for c in checks:
        check(f"{label}: рядок має level/text/fact/target", set(c.keys()) >= {"level", "text", "fact", "target"})
        check(f"{label}: level коректний", c["level"] in ("ok", "warn", "error"), c["level"])
        ok, detail = resolve_target(c.get("target"))
        check(f"{label}: ціль «{c['text'][:40]}» відкривається", ok, detail)
        if c["level"] in ("warn", "error"):
            any_warn_or_error = True
    # checks_text: комп'ютерне поле, не введене руками
    check(f"{label}: checks_text рахується", isinstance(record.checks_text, str))
    return checks


company = env.company

# ---- Табель
sheets = env["ua.timesheet.sheet"].sudo().search([("company_id", "=", company.id)], limit=5)
for s in sheets:
    check_record_checks(s, f"Табель {s.name}")
check("є хоч один табель для перевірки", bool(sheets), str(len(sheets)))

# ---- Штатний розпис
lists = env["ua.staff.list"].sudo().search([("company_id", "=", company.id)], limit=5)
if not lists:
    lists = env["ua.staff.list"].sudo().create({"company_id": company.id})
    lists.action_refill()
for s in lists:
    check_record_checks(s, f"Штатний розпис {s.name}")

# ---- Авансова відомість
advances = env["ua.advance.sheet"].sudo().search([("company_id", "=", company.id)], limit=5)
for a in advances:
    check_record_checks(a, f"Аванс {a.name}")

# ---- Відомість на перерахування
batches = env["ua.payment.batch"].sudo().search([("company_id", "=", company.id)], limit=5)
for b in batches:
    check_record_checks(b, f"Відомість {b.name}")
if not batches:
    print("(немає відомостей на перерахування в демоданих - пропущено)")

# ---- Заява-розрахунок ПФУ
claims = env["ua.pfu.claim"].sudo().search([("company_id", "=", company.id)], limit=5)
for c in claims:
    check_record_checks(c, f"ПФУ {c.name}")
if not claims:
    print("(немає заяв ПФУ в демоданих - пропущено)")

# ---- Військовий облік: список, повідомлення, заброньовані
mlist = env["ua.military.list"].sudo().search([("company_id", "=", company.id)], limit=1)
if not mlist:
    mlist = env["ua.military.list"].sudo().create({"company_id": company.id})
    mlist.action_refill()
check_record_checks(mlist, f"Військовий облік {mlist.name}")

mnotice = env["ua.military.notice"].sudo().search([("company_id", "=", company.id)], limit=1)
if not mnotice:
    from datetime import date
    mnotice = env["ua.military.notice"].sudo().create({
        "company_id": company.id, "date_from": date(2026, 9, 1), "date_to": date(2026, 9, 30)})
    mnotice.action_refill()
check_record_checks(mnotice, f"Повідомлення ТЦК {mnotice.name}")

mres = env["ua.military.reserved"].sudo().search([("company_id", "=", company.id)], limit=1)
if not mres:
    mres = env["ua.military.reserved"].sudo().create({"company_id": company.id})
    mres.action_refill()
check_record_checks(mres, f"Заброньовані {mres.name}")

# ---- Сторінка «Період»: документи вересня позначені checks_available, а get_doc_checks
# рахує перевірки лениво (документи більше не несуть готовий checks на завантаженні -
# інакше board рахував би _checks() для кожного документа кожного кроку щоразу).
board = env["ua.period.board"]
docs = board._documents(company, 2026, 9, __import__("datetime").date(2026, 9, 1), __import__("datetime").date(2026, 9, 30))
markable = [d for group in docs.values() for d in group if d.get("checks_available")]
lazy_checks = any(board.get_doc_checks(d["target"]["model"], d["target"]["res_id"]) for d in markable)
check("документи сторінки «Період» позначають checks_available", bool(markable))
check("документи сторінки «Період» несуть перевірки (хоч один)", lazy_checks)

check("серед перевірених документів є хоч один warn/error", any_warn_or_error)

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
