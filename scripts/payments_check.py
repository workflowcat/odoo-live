"""Перевірка відомості на перерахування (модуль l10n_ua_payments).

Збираємо відомість за серпень 2026 з проведених листків, звіряємо суму з «До виплати»,
затверджуємо, формуємо файл для банку і друковану форму, перевіряємо текст призначення
(він має збігатися з правилами звірки виписки). Наприкінці відомість видаляємо.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/payments_check.py"""
import base64
import http.cookiejar
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

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


old = call("ua.payment.batch", "search", [["year", "=", 2026], ["month", "=", 8], ["kind", "=", "salary"]])
if old:
    call("ua.payment.batch", "unlink", old)

batch = call("ua.payment.batch", "create", {"year": 2026, "month": 8, "kind": "salary", "pay_date": "2026-09-04"})
call("ua.payment.batch", "action_fill", [batch])
data = call("ua.payment.batch", "read", [batch], ["total", "employee_count", "without_account", "name", "state"])[0]
check("відомість заповнилася з листків", data["employee_count"] >= 15, f"{data['employee_count']} працівників")
check("назва відомості читається", data["name"].startswith("Заробітна плата 08"), data["name"])

slips = call("hr.payslip", "search", [["date_from", ">=", "2026-08-01"], ["date_from", "<=", "2026-08-31"],
                                      ["state", "in", ["done", "verify"]]])
lines = call("hr.payslip.line", "search_read", [["slip_id", "in", slips], ["code", "=", "NET"]], fields=["total"])
net_total = round(sum(l["total"] for l in lines if l["total"] > 0), 2)
check("сума відомості дорівнює «До виплати» у листках", abs(data["total"] - net_total) < 0.01,
      f"{data['total']} проти {net_total}")

no_account = data["without_account"]
check("у всіх працівників є рахунок", no_account == 0, f"без рахунку: {no_account}")

first = call("ua.payment.line", "search_read", [["batch_id", "=", batch]], fields=["purpose", "account_number", "amount"], limit=1)[0]
check("призначення платежу збігається з правилом звірки («Заробітна плата за ... остаточний розрахунок»)",
      "Заробітна плата за серпень 2026" in (first["purpose"] or ""), first["purpose"])
check("рахунок у рядку заповнений", bool(first["account_number"]), first["account_number"])

call("ua.payment.batch", "action_confirm", [batch])
state = call("ua.payment.batch", "read", [batch], ["state"])[0]["state"]
check("відомість затверджується", state == "confirmed", state)

result = call("ua.payment.batch", "action_export", [batch])
check("кнопка «Файл для банку» віддає посилання на файл",
      isinstance(result, dict) and "/web/content/" in result.get("url", ""), result.get("url", ""))
attachments = call("ir.attachment", "search_read", [["res_model", "=", "ua.payment.batch"], ["res_id", "=", batch]],
                   fields=["name", "datas", "mimetype"])
check("файл прикріплено до відомості", bool(attachments), attachments[0]["name"] if attachments else "")
if attachments:
    content = base64.b64decode(attachments[0]["datas"]).decode("windows-1251", "replace")
    rows = [r for r in content.splitlines() if r.strip()]
    check("у файлі є заголовок і рядок на кожного працівника", len(rows) == data["employee_count"] + 1,
          f"{len(rows)} рядків проти {data['employee_count'] + 1}")
    check("у файлі є ПІБ, рахунок і призначення", rows[1].count(";") == 4 and "UA" in rows[1], rows[1][:80])

# друкована форма
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.open(urllib.request.Request(BASE + "/web/session/authenticate",
            json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode(),
            {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}), timeout=120).read()
with opener.open(BASE + "/report/pdf/l10n_ua_payments.report_ua_payment_batch/%s" % batch, timeout=300) as response:
    pdf = response.read()
check("друкована відомість формується", pdf[:4] == b"%PDF", f"{len(pdf)} байт")

# відомість лишається на стенді як приклад: позначаємо оплаченою
call("ua.payment.batch", "action_paid", [batch])
final = call("ua.payment.batch", "read", [batch], ["state"])[0]["state"]
check("відомість лишилася на стенді зі станом «оплачено»", final == "paid", final)

# ------------------------------------------------------------------ платежі до бюджету
YEAR, MONTH = 2026, 8
company = call("res.company", "read", [1], ["ua_iban_pdfo", "ua_iban_vz", "ua_iban_esv"])[0]
check("у компанії є рахунки бюджету для ПДФО, ВЗ і ЄСВ",
      all(company.get(f) for f in ("ua_iban_pdfo", "ua_iban_vz", "ua_iban_esv")),
      str({k: v for k, v in company.items() if k != "id"}))

tax = call("ua.payment.batch", "search", [["kind", "=", "tax"], ["year", "=", YEAR], ["month", "=", MONTH]], limit=1)
if not tax:
    tax = call("ua.payment.batch", "create", {"year": YEAR, "month": MONTH, "kind": "tax"})
    tax = [tax[0] if isinstance(tax, list) else tax]
call("ua.payment.batch", "action_draft", tax)
call("ua.payment.batch", "action_fill", tax)
tax_lines = call("ua.payment.line", "search_read", [["batch_id", "=", tax[0]]], ["name", "amount", "account_number", "purpose"])
check("відомість до бюджету має три рядки", len(tax_lines) == 3, str([l["name"] for l in tax_lines]))

slips = call("hr.payslip", "search", [["state", "=", "done"], ["date_from", ">=", f"{YEAR}-{MONTH:02d}-01"],
                                      ["date_from", "<=", f"{YEAR}-{MONTH:02d}-28"]])
def rule_sum(code):
    lines = call("hr.payslip.line", "search_read", [["slip_id", "in", slips], ["code", "=", code]], ["total"])
    return round(abs(sum(l["total"] for l in lines)), 2)
by_name = {l["name"]: round(l["amount"], 2) for l in tax_lines}
for label, code in (("ПДФО", "PDFO"), ("Військовий збір", "VZ"), ("Єдиний внесок (ЄСВ)", "ESV")):
    check(f"сума «{label}» дорівнює сумі листків", abs(by_name.get(label, 0) - rule_sum(code)) < 0.01,
          f"{by_name.get(label)} проти {rule_sum(code)}")
check("рядки мають рахунок бюджету", all(l["account_number"].startswith("UA") for l in tax_lines),
      str([l["account_number"][:10] for l in tax_lines]))
check("призначення платежу збігається з правилами звірки",
      all(("за " in l["purpose"]) for l in tax_lines), str([l["purpose"] for l in tax_lines]))
call("ua.payment.batch", "action_confirm", tax)
check("відомість до бюджету затверджується", call("ua.payment.batch", "read", tax, ["state"])[0]["state"] == "confirmed")
export = call("ua.payment.batch", "action_export", tax)
att = int(export["url"].split("/")[-1].split("?")[0])
content = base64.b64decode(call("ir.attachment", "read", [att], ["datas"])[0]["datas"]).decode("windows-1251")
check("файл до бюджету містить назви платежів і рахунки",
      "ПДФО" in content and "UA" in content, content.splitlines()[1][:70] if len(content.splitlines()) > 1 else "")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
