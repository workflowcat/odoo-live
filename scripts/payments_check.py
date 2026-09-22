"""Перевірка відомості на перерахування (модуль l10n_ua_payments на account_payment_order).

Збираємо відомість за серпень 2026 з проведених листків, звіряємо суму з «До виплати»,
затверджуємо (OCA складає платежі), формуємо файл для банку і друковану форму, перевіряємо
текст призначення (він має збігатися з правилами звірки виписки), позначаємо оплаченою і
дивимось, що платежі проведені й закрили 661 кожному працівникові.

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


def drop_orders(domain):
    """Прибрати відомості попереднього прогону. Оплачену спершу скасовуємо: OCA не дає
    видалити вивантажене доручення, поки за ним стоять проведені платежі."""
    ids = call("account.payment.order", "search", domain)
    if not ids:
        return
    for oid in ids:
        state = call("account.payment.order", "read", [oid], ["state"])[0]["state"]
        if state != "draft":
            call("account.payment.order", "action_cancel", [oid])
    call("account.payment.order", "unlink", ids)


SETUP = call("res.company", "ua_payment_setup", [1])


def compose(year, month, kind, pay_date):
    """Нова відомість місяця. Те саме, що робить ua_compose на екрані «Папери»,
    але через create - recordset по RPC не передаси."""
    drop_orders([["ua_year", "=", year], ["ua_month", "=", month], ["ua_kind", "=", kind]])
    oid = call("account.payment.order", "create", {
        "payment_mode_id": SETUP["tax" if kind == "tax" else "salary"],
        "journal_id": SETUP["journal"], "date_prefered": "now",
        "ua_kind": kind, "ua_year": year, "ua_month": month, "ua_pay_date": pay_date})
    call("account.payment.order", "action_fill", [oid])
    return oid


company = call("res.company", "read", [1], ["ua_iban_pdfo", "ua_iban_vz", "ua_iban_esv"])[0]
batch = compose(2026, 8, "salary", "2026-09-04")
data = call("account.payment.order", "read", [batch],
            ["total_company_currency", "ua_line_count", "ua_without_account", "ua_label", "state",
             "payment_mode_id", "journal_id", "name"])[0]
check("відомість заповнилася з листків", data["ua_line_count"] >= 15, f"{data['ua_line_count']} працівників")
check("назва відомості читається", data["ua_label"].startswith("Заробітна плата 08"), data["ua_label"])
check("відомість має номер платіжного доручення", bool(data["name"]), str(data["name"]))
check("відомість іде способом оплати «Зарплата»",
      data["payment_mode_id"] and data["payment_mode_id"][1] == "Зарплата", str(data["payment_mode_id"]))
check("на відомості стоїть банк", bool(data["journal_id"]), str(data["journal_id"]))

slips = call("hr.payslip", "search", [["date_from", ">=", "2026-08-01"], ["date_from", "<=", "2026-08-31"],
                                      ["state", "in", ["done", "verify"]]])
lines = call("hr.payslip.line", "search_read", [["slip_id", "in", slips], ["code", "=", "NET"]], fields=["total"])
net_total = round(sum(l["total"] for l in lines if l["total"] > 0), 2)
check("сума відомості дорівнює «До виплати» у листках", abs(data["total_company_currency"] - net_total) < 0.01,
      f"{data['total_company_currency']} проти {net_total}")

no_account = data["ua_without_account"]
check("у всіх працівників є рахунок", no_account == 0, f"без рахунку: {no_account}")

first = call("account.payment.line", "search_read", [["order_id", "=", batch]],
             fields=["communication", "partner_bank_id", "amount_currency", "ua_employee_id",
                     "ua_account_id", "partner_id"], limit=1)[0]
check("призначення платежу збігається з правилом звірки («Заробітна плата за ... остаточний розрахунок»)",
      "Заробітна плата за серпень 2026" in (first["communication"] or ""), first["communication"])
check("рахунок у рядку заповнений", bool(first["partner_bank_id"]), str(first["partner_bank_id"]))
check("рядок знає працівника", bool(first["ua_employee_id"]), str(first["ua_employee_id"]))
check("рядок закриває рахунок 661", (first["ua_account_id"] or ["", ""])[1].startswith("661"),
      str(first["ua_account_id"]))

call("account.payment.order", "action_confirm", [batch])
state = call("account.payment.order", "read", [batch], ["state", "payment_count"])[0]
check("відомість затверджується", state["state"] == "open", state["state"])
check("затвердження склало платежі на кожного працівника", state["payment_count"] == data["ua_line_count"],
      f"{state['payment_count']} платежів проти {data['ua_line_count']} рядків")

result = call("account.payment.order", "action_export", [batch])
check("кнопка «Файл для банку» віддає посилання на файл",
      isinstance(result, dict) and "/web/content/" in result.get("url", ""), result.get("url", ""))
attachments = call("ir.attachment", "search_read", [["res_model", "=", "account.payment.order"], ["res_id", "=", batch]],
                   fields=["name", "datas", "mimetype"])
check("файл прикріплено до відомості", bool(attachments), attachments[0]["name"] if attachments else "")
if attachments:
    content = base64.b64decode(attachments[0]["datas"]).decode("windows-1251", "replace")
    rows = [r for r in content.splitlines() if r.strip()]
    check("у файлі є заголовок і рядок на кожного працівника", len(rows) == data["ua_line_count"] + 1,
          f"{len(rows)} рядків проти {data['ua_line_count'] + 1}")
    check("у файлі є ПІБ, рахунок і призначення", rows[1].count(";") == 4 and "UA" in rows[1], rows[1][:80])

# друкована форма
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.open(urllib.request.Request(BASE + "/web/session/authenticate",
            json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode(),
            {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}), timeout=120).read()
with opener.open(BASE + "/report/pdf/l10n_ua_payments.report_ua_payment_order/%s" % batch, timeout=300) as response:
    pdf = response.read()
check("друкована відомість формується", pdf[:4] == b"%PDF", f"{len(pdf)} байт")

# ---- оплата: платежі проводяться і закривають 661 ------------------------------------
def open_debt(pairs):
    """Незакритий залишок за серпень на тих самих парах «рахунок - контрагент», які закриває
    відомість. ФОП-підрядник висить на 6851, решта - на 661, тому рахунок беремо з рядка."""
    total = 0.0
    for account_id, partner_id in pairs:
        rows = call("account.move.line", "search_read",
                    [["account_id", "=", account_id], ["partner_id", "=", partner_id],
                     ["parent_state", "=", "posted"], ["reconciled", "=", False],
                     ["date", ">=", "2026-08-01"], ["date", "<=", "2026-08-31"]],
                    ["amount_residual"])
        total += sum(r["amount_residual"] for r in rows)
    return round(total, 2)


PAIRS = sorted({(l["ua_account_id"][0], l["partner_id"][0]) for l in call(
    "account.payment.line", "search_read", [["order_id", "=", batch]],
    ["partner_id", "ua_account_id"])})
before = open_debt(PAIRS)
call("account.payment.order", "action_paid", [batch])
final = call("account.payment.order", "read", [batch], ["state", "payment_count", "move_count"])[0]
check("відомість лишилася на стенді зі станом «оплачено»", final["state"] == "uploaded", final["state"])
check("за відомістю стоять проводки", final["move_count"] > 0, str(final["move_count"]))

payments = call("account.payment", "search_read", [["payment_order_id", "=", batch]],
                ["state", "amount", "partner_id", "destination_account_id"])
check("усі платежі проведені", payments and all(p["state"] in ("posted", "paid", "in_process") for p in payments),
      str(sorted({p["state"] for p in payments})))
# ФОП-підрядник висить на 6851, працівник і ЦПХ - на 661: платіж дебетує рахунок свого рядка.
line_account = {(l["partner_id"][0]): l["ua_account_id"][0] for l in call(
    "account.payment.line", "search_read", [["order_id", "=", batch]], ["partner_id", "ua_account_id"])}
check("платіж дебетує той самий рахунок, що стоїть у рядку (661, ФОП - 6851)",
      all(p["destination_account_id"][0] == line_account[p["partner_id"][0]] for p in payments),
      str({(p["destination_account_id"] or ["", ""])[1] for p in payments}))
check("сума платежів дорівнює сумі відомості", abs(round(sum(p["amount"] for p in payments), 2) - net_total) < 0.01,
      f"{round(sum(p['amount'] for p in payments), 2)} проти {net_total}")

# Стенд несе історію: серпневий аванс перенесено як історію без платежів, тому нуля на 661
# не буде. Перевіряємо саме дію відомості - оплата закриває рівно свою суму.
after = open_debt(PAIRS)
check("оплата закрила рівно суму відомості", abs((after - before) - net_total) < 0.01,
      f"залишок закрито на {round(after - before, 2)}, у відомості {net_total}")
residuals = []
for account_id, partner_id in PAIRS:
    residuals += [r["amount_residual"] for r in call(
        "account.move.line", "search_read",
        [["account_id", "=", account_id], ["partner_id", "=", partner_id],
         ["parent_state", "=", "posted"], ["reconciled", "=", False],
         ["date", ">=", "2026-08-01"], ["date", "<=", "2026-08-31"]], ["amount_residual"])]
check("оплата нікого не переплатила: дебетових залишків на 661 / 6851 не лишилось",
      all(r <= 0.01 for r in residuals), str(sorted(r for r in residuals if r > 0.01)[:5]))

# ------------------------------------------------------------------ платежі до бюджету
YEAR, MONTH = 2026, 8
check("у компанії є рахунки бюджету для ПДФО, ВЗ і ЄСВ",
      all(company.get(f) for f in ("ua_iban_pdfo", "ua_iban_vz", "ua_iban_esv")),
      str({k: v for k, v in company.items() if k != "id"}))

tax = compose(YEAR, MONTH, "tax", "2026-09-20")
tax_lines = call("account.payment.line", "search_read", [["order_id", "=", tax]],
                 ["ua_label", "amount_currency", "partner_bank_id", "communication", "partner_id",
                  "ua_account_id"])
check("відомість до бюджету має три рядки", len(tax_lines) == 3, str([l["ua_label"] for l in tax_lines]))

slips = call("hr.payslip", "search", [["state", "=", "done"], ["date_from", ">=", f"{YEAR}-{MONTH:02d}-01"],
                                      ["date_from", "<=", f"{YEAR}-{MONTH:02d}-28"]])


def rule_sum(code):
    lines = call("hr.payslip.line", "search_read", [["slip_id", "in", slips], ["code", "=", code]], ["total"])
    return round(abs(sum(l["total"] for l in lines)), 2)


by_name = {l["ua_label"]: round(l["amount_currency"], 2) for l in tax_lines}
for label, code in (("ПДФО", "PDFO"), ("Військовий збір", "VZ"), ("Єдиний внесок (ЄСВ)", "ESV")):
    check(f"сума «{label}» дорівнює сумі листків", abs(by_name.get(label, 0) - rule_sum(code)) < 0.01,
          f"{by_name.get(label)} проти {rule_sum(code)}")
check("рядки мають рахунок бюджету", all(l["partner_bank_id"] for l in tax_lines),
      str([(l["partner_bank_id"] or ["", ""])[1][:32] for l in tax_lines]))
check("одержувач рядків бюджету - ДПС", all("ДПС" in (l["partner_id"] or ["", ""])[1] for l in tax_lines),
      str({(l["partner_id"] or ["", ""])[1] for l in tax_lines}))
check("кожен рядок закриває свій рахунок (6411, 6415, 651)",
      sorted((l["ua_account_id"] or ["", ""])[1].split()[0] for l in tax_lines) ==
      ["6411", "6415", "651"],
      str(sorted((l["ua_account_id"] or ["", ""])[1] for l in tax_lines)))
check("призначення платежу збігається з правилами звірки",
      all(("за " in l["communication"]) for l in tax_lines), str([l["communication"] for l in tax_lines]))
call("account.payment.order", "action_confirm", [tax])
check("відомість до бюджету затверджується", call("account.payment.order", "read", [tax], ["state"])[0]["state"] == "open")
export = call("account.payment.order", "action_export", [tax])
att = int(export["url"].split("/")[-1].split("?")[0])
content = base64.b64decode(call("ir.attachment", "read", [att], ["datas"])[0]["datas"]).decode("windows-1251")
check("файл до бюджету містить назви платежів і рахунки",
      "ПДФО" in content and "UA" in content, content.splitlines()[1][:70] if len(content.splitlines()) > 1 else "")
call("account.payment.order", "action_paid", [tax])
tax_payments = call("account.payment", "search_read", [["payment_order_id", "=", tax]],
                    ["destination_account_id", "amount", "state"])
check("платежі до бюджету проведені на 6411, 6415 і 651",
      sorted((p["destination_account_id"] or ["", ""])[1].split()[0] for p in tax_payments) == ["6411", "6415", "651"],
      str(sorted((p["destination_account_id"] or ["", ""])[1] for p in tax_payments)))

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
