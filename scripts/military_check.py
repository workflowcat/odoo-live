"""Перевірка модуля l10n_ua_military після scripts/demo_military.py.

База читається зі змінної середовища PAYROLL_DB (типово payroll).
PDF перевіряється через odoo shell (окремий короткочасний процес в тому ж контейнері), бо HTTP-сесія
з dbfilter віддає PDF лише для бази payroll. Запуск: PAYROLL_DB=payroll_test python3 scripts/military_check.py"""
import json
import os
import subprocess
import sys
import urllib.request

ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
URL = "http://127.0.0.1:8110/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(), {"Content-Type": "application/json"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


COMPANY = call("res.company", "search", [["name", "ilike", "Ясен Меблі"]])
COMPANY = COMPANY[0] if COMPANY else 1

# 1. >= 8 військовозобов'язаних (ua_mil_status == liable)
liable_ids = call("hr.employee", "search", [["company_id", "=", COMPANY], ["ua_mil_status", "=", "liable"]])
check("≥ 8 військовозобов'язаних (liable) після демо", len(liable_ids) >= 8, f"{len(liable_ids)} знайдено")

# усі, хто підлягає обліку (для порівняння з рядками списку)
scope_ids = call("hr.employee", "search", [["company_id", "=", COMPANY], ["ua_mil_status", "in", ["conscript", "liable", "reserve"]]])

# 2. Список персонального обліку на 2026-09-30
list_doc = call("ua.military.list", "search", [["company_id", "=", COMPANY], ["date", "=", "2026-09-30"], ["state", "=", "draft"]], limit=1)
list_id = list_doc[0] if list_doc else call("ua.military.list", "create", {"company_id": COMPANY, "date": "2026-09-30"})
call("ua.military.list", "action_refill", [list_id])
list_lines = call("ua.military.list", "read", [list_id], ["line_ids"])[0]["line_ids"]
check("список персонального обліку на 2026-09-30 = кількість тих, хто підлягає обліку", len(list_lines) == len(scope_ids),
      f"{len(list_lines)} рядків, {len(scope_ids)} підлягають обліку")

# 3. Повідомлення за 08.2026: Данилюк (прийнятий 17.08) і Гнатів (звільнений 31.08), якщо підлягають обліку; Ткачук - якщо є в базі
notice_doc = call("ua.military.notice", "search", [["company_id", "=", COMPANY], ["date_from", "=", "2026-08-01"], ["date_to", "=", "2026-08-31"], ["state", "=", "draft"]], limit=1)
notice_id = notice_doc[0] if notice_doc else call("ua.military.notice", "create", {"company_id": COMPANY, "date_from": "2026-08-01", "date_to": "2026-08-31"})
call("ua.military.notice", "action_refill", [notice_id])
notice_lines = call("ua.military.notice", "read", [notice_id], ["line_ids"])[0]["line_ids"]
notice_rows = call("ua.military.notice.line", "read", notice_lines, ["full_name", "change_kind", "date"])
names_hire = {r["full_name"] for r in notice_rows if r["change_kind"] == "hire"}
names_dismiss = {r["full_name"] for r in notice_rows if r["change_kind"] == "dismiss"}

for surname, kind, names in [("Данилюк", "прийняття 17.08", names_hire), ("Гнатів", "звільнення 31.08", names_dismiss), ("Ткачук", "прийняття 17.08", names_hire)]:
    emp = call("hr.employee", "search_read", [["company_id", "=", COMPANY], ["name", "ilike", surname]], fields=["name", "ua_mil_status"])
    if not emp:
        print(f"[--] {surname}: немає в базі {DB}, пропущено")
        continue
    liable_now = emp[0]["ua_mil_status"] in ("conscript", "liable", "reserve")
    if not liable_now:
        print(f"[--] {surname}: не підлягає обліку (ua_mil_status={emp[0]['ua_mil_status']}), у повідомленні не очікується")
        continue
    check(f"повідомлення 08.2026 містить {surname} ({kind})", any(emp[0]["name"] in n for n in names), f"рядки {kind}: {names}")

# 4. Список заброньованих = 2
reserved_doc = call("ua.military.reserved", "search", [["company_id", "=", COMPANY], ["date", "=", "2026-09-30"], ["state", "=", "draft"]], limit=1)
reserved_id = reserved_doc[0] if reserved_doc else call("ua.military.reserved", "create", {"company_id": COMPANY, "date": "2026-09-30"})
call("ua.military.reserved", "action_refill", [reserved_id])
reserved_lines = call("ua.military.reserved", "read", [reserved_id], ["line_ids"])[0]["line_ids"]
check("список заброньованих = 2", len(reserved_lines) == 2, f"{len(reserved_lines)} рядків")

# 5. три PDF починаються з %PDF (через odoo shell, бо HTTP dbfilter обмежений базою payroll)
script = f"""
list_id, notice_id, reserved_id = {list_id}, {notice_id}, {reserved_id}
pdf1, _ = env['ir.actions.report']._render_qweb_pdf('l10n_ua_military.action_report_ua_military_list', [list_id])
pdf2, _ = env['ir.actions.report']._render_qweb_pdf('l10n_ua_military.action_report_ua_military_notice', [notice_id])
pdf3, _ = env['ir.actions.report']._render_qweb_pdf('l10n_ua_military.action_report_ua_military_reserved', [reserved_id])
print('PDF_CHECK', pdf1[:4] == b'%PDF', pdf2[:4] == b'%PDF', pdf3[:4] == b'%PDF', len(pdf1), len(pdf2), len(pdf3))
env.cr.rollback()
quit()
"""
proc = subprocess.run(
    ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
     f"odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d {DB} --no-http --log-level=warn"],
    input=script, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
line = next((l for l in proc.stdout.splitlines() if l.startswith("PDF_CHECK")), "")
if not line:
    print(proc.stdout[-3000:]); print(proc.stderr[-3000:])
parts = line.split()
pdf_ok = len(parts) >= 4 and parts[1] == "True" and parts[2] == "True" and parts[3] == "True"
check("три PDF починаються з %PDF (odoo shell)", pdf_ok, line or "немає виводу PDF_CHECK")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    sys.exit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
