"""Перевірка пояснення розрахунку (модуль l10n_ua_explain).

Слід розрахунку має вироблятися тим самим кодом, що рахує гроші. Тому перевіряємо не
текст пояснення, а збіг сліду з реальним листком: кожен рядок із сумою має крок,
кожен вхід кроку названий і має джерело, проведений листок має заморожений слід,
а перегляд сліду нічого не змінює в базі.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/explain_check.py"""
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

STATES = {"supplied", "imported", "calculated", "missing", "stale", "manual", "not_applicable"}
# Числа, які в формулі не є правилом: округлення до копійок, переведення відсотка в частку,
# нейтральні нуль і одиниця. Будь-яке інше число у формулі - ставка без дати і без підстави.
ALLOWED_NUMBERS = {"0", "1", "2", "0.0", "1.0", "100", "100.0"}

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
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:600])
    return data.get("result")


def rpc_soft(service, method, *args):
    """Той самий виклик, але помилка сервера повертається текстом, а не валить скрипт."""
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(request, timeout=900).read())
    if "error" in data:
        return {"__error__": str(data["error"].get("data", {}).get("message") or data["error"])}
    return data.get("result")


UID = rpc("common", "login", DB, LOGIN, PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як {LOGIN} на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def call_soft(model, method, *a, **kw):
    return rpc_soft("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


# 1. модуль встановлений
mod = call("ir.module.module", "search_read", [["name", "=", "l10n_ua_explain"]], fields=["state"])
check("модуль l10n_ua_explain встановлений", bool(mod) and mod[0]["state"] == "installed",
      mod[0]["state"] if mod else "немає в списку модулів")

models = call("ir.model", "search_read", [["model", "in", ["ua.explain", "ua.explain.trace"]]], fields=["model"])
check("моделі ua.explain і ua.explain.trace зареєстровані",
      {m["model"] for m in models} == {"ua.explain", "ua.explain.trace"}, str([m["model"] for m in models]))

# 2. проведений листок для сліду
done = call("hr.payslip", "search_read", [["state", "in", ["done", "paid"]]],
            fields=["number", "employee_id", "date_from"], limit=1, order="date_from desc, id desc")
draft = call("hr.payslip", "search_read", [["state", "=", "draft"]],
             fields=["number", "employee_id"], limit=1, order="id desc")
check("у базі є проведений листок для перевірки сліду", bool(done),
      (done[0].get("number") or done[0]["employee_id"][1]) if done else "немає жодного done/paid")

payload = {}
if done:
    slip_id = done[0]["id"]
    res = call_soft("ua.explain", "explain", "hr.payslip", slip_id)
    if "__error__" in res:
        check("ua.explain.explain() відповідає на проведений листок", False, res["__error__"][:200])
    else:
        payload = res
        check("ua.explain.explain() відповідає на проведений листок", True,
              f"{len(res.get('steps') or [])} кроків")

    keys = {"version", "subject", "inputs", "steps", "totals"}
    check("слід містить усі ключі форми", keys.issubset(payload.keys()),
          f"відсутні: {keys - set(payload.keys())}" if payload else "порожній слід")

    steps = payload.get("steps") or []
    inputs = payload.get("inputs") or {}

    # 3. кожен рядок із сумою має крок
    lines = call("hr.payslip.line", "search_read", [["slip_id", "=", slip_id], ["total", "!=", 0]],
                 fields=["code", "total"])
    step_codes = {s.get("code") for s in steps}
    missing_steps = [l["code"] for l in lines if l["code"] not in step_codes]
    check("кожен рядок листка з ненульовою сумою має крок у сліді", not missing_steps,
          f"без кроку: {missing_steps}" if missing_steps else f"{len(lines)} рядків")

    # 4. форма кроку
    bad_shape = [s.get("code") for s in steps if not (s.get("code") and s.get("label") and "output" in s)]
    check("кожен крок має код, назву і результат", not bad_shape, str(bad_shape))

    # 5. сума кроку збігається з сумою рядка
    by_code = {l["code"]: l["total"] for l in lines}
    drift = [(s["code"], s.get("output"), by_code[s["code"]]) for s in steps
             if s.get("code") in by_code and abs((s.get("output") or 0) - by_code[s["code"]]) > 0.011]
    check("результат кроку збігається з сумою рядка листка", not drift, str(drift[:4]))

    # 6. слід справді знятий з розрахунку, а не порожній
    with_reads = [s for s in steps if s.get("reads")]
    check("щонайменше один крок має прочитані входи", bool(with_reads),
          f"{len(with_reads)} з {len(steps)} кроків")

    # 7. кожен крок пояснює себе: або читає входи, або посилається на інші правила, або має note
    silent = [s.get("code") for s in steps
              if not s.get("reads") and not s.get("uses_rules") and not s.get("note")]
    check("жоден крок не мовчить: є входи, посилання на правила або пояснення", not silent, str(silent))

    # 8. кожен прочитаний ключ описаний у входах
    unknown = sorted({k for s in steps for k in (s.get("reads") or []) if k not in inputs})
    check("кожен прочитаний вхід описаний у inputs", not unknown, str(unknown[:8]))

    # 9. стани входів з дозволеного списку
    bad_state = {k: v.get("state") for k, v in inputs.items() if v.get("state") not in STATES}
    check("кожен вхід має стан з дозволеного списку", not bad_state, str(list(bad_state.items())[:6]))

    # 10. назва людською мовою в кожного входу
    no_label = [k for k, v in inputs.items() if not v.get("label")]
    check("кожен вхід має назву людською мовою", not no_label, str(no_label[:8]))

    # 11. введене і завантажене має джерело, пораховане і порожнє - пояснення
    no_source = [k for k, v in inputs.items()
                 if v.get("state") in ("supplied", "imported") and not v.get("source")]
    check("введені і завантажені входи вказують на запис-джерело", not no_source, str(no_source[:8]))
    no_note = [k for k, v in inputs.items()
               if v.get("state") in ("calculated", "missing", "not_applicable", "stale")
               and not v.get("note") and not v.get("source")]
    check("пораховані і порожні входи пояснюють себе рядком note", not no_note, str(no_note[:8]))

    # 12. параметр закону веде на ua.payroll.param із підставою
    param_inputs = {k: v for k, v in inputs.items()
                    if (v.get("source") or {}).get("model") == "ua.payroll.param"}
    check("входи-параметри ведуть на записи ua.payroll.param", bool(param_inputs),
          f"{len(param_inputs)} параметрів")
    no_basis = [k for k, v in param_inputs.items() if not (v.get("source") or {}).get("basis")]
    check("кожен параметр закону несе підставу", not no_basis, str(no_basis[:8]))

    # 13. порожнє не стає нулем мовчки: якщо вхід missing, крок, що його прочитав, це показує
    missing_keys = {k for k, v in inputs.items() if v.get("state") == "missing"}
    if missing_keys:
        hidden = [s.get("code") for s in steps
                  if set(s.get("reads") or []) & missing_keys and not s.get("has_missing")]
        check("крок із порожнім входом позначений ознакою has_missing", not hidden, str(hidden))
    else:
        check("крок із порожнім входом позначений ознакою has_missing", True, "порожніх входів немає")

    # 14. заморожений слід: або він є і читається як committed, або відповідь чесно
    # каже, що його немає. Листок, проведений до появи механізму, сліду не має і мати
    # не може; підміняти його сьогоднішнім перерахунком не можна.
    trace = call("ua.explain.trace", "search_read",
                 [["model_name", "=", "hr.payslip"], ["res_id", "=", slip_id]],
                 fields=["frozen_at", "frozen_by"], limit=1, order="frozen_at desc, id desc")
    if trace:
        check("проведений листок читається із замороженого сліду",
              payload.get("state") == "committed" and payload.get("frozen") is True,
              f"{payload.get('state')}, frozen={payload.get('frozen')}")
    else:
        check("листок без замороженого сліду не видає перерахунок за історію",
              payload.get("state") == "preview" and payload.get("frozen") is False
              and bool(payload.get("note")),
              f"{payload.get('state')}, frozen={payload.get('frozen')}, note={bool(payload.get('note'))}")

    # 15. перегляд сліду нічого не змінює в базі
    before = call("hr.payslip.line", "search_count", [["slip_id", "=", slip_id]])
    state_before = call("hr.payslip", "read", [slip_id], fields=["state"])[0]["state"]
    call_soft("ua.explain", "explain", "hr.payslip", slip_id, None, "now")
    after = call("hr.payslip.line", "search_count", [["slip_id", "=", slip_id]])
    state_after = call("hr.payslip", "read", [slip_id], fields=["state"])[0]["state"]
    check("перерахунок для перегляду не змінює рядки листка", before == after, f"{before} -> {after}")
    check("перерахунок для перегляду не змінює стан листка", state_before == state_after,
          f"{state_before} -> {state_after}")

    # 16. заморожений слід не підміняється поточним перерахунком
    frozen = call_soft("ua.explain", "explain", "hr.payslip", slip_id, None, "frozen")
    check("заморожений слід читається окремо від поточного",
          isinstance(frozen, dict) and frozen.get("state") in ("committed", "none"),
          str(frozen.get("state") if isinstance(frozen, dict) else frozen)[:120])

if draft:
    res = call_soft("ua.explain", "explain", "hr.payslip", draft[0]["id"])
    check("чернетка листка пояснюється як попередній перегляд",
          isinstance(res, dict) and res.get("state") == "preview",
          str(res.get("state") if isinstance(res, dict) else res)[:160])
else:
    check("чернетка листка пояснюється як попередній перегляд", True, "чернеток немає, пункт пропущено")

# 16a. заморозка сліду при проведенні. Пише в базу, тому вмикається окремо і не на стенді:
# EXPLAIN_CHECK_FREEZE=1 PAYROLL_DB=<копія> python3 scripts/explain_check.py
if os.environ.get("EXPLAIN_CHECK_FREEZE") == "1":
    if DB == "payroll":
        raise SystemExit("EXPLAIN_CHECK_FREEZE проводить листок і пише в базу. Запускайте на копії, не на payroll.")
    fresh = call("hr.payslip", "search_read", [["state", "=", "draft"]], fields=["number"], limit=1, order="id desc")
    if not fresh:
        check("заморозка сліду при проведенні", False, "немає чернетки листка для проведення")
    else:
        fid = fresh[0]["id"]
        call("hr.payslip", "compute_sheet", [fid])
        call("hr.payslip", "action_payslip_done", [fid])
        rows = call("ua.explain.trace", "search_read",
                    [["model_name", "=", "hr.payslip"], ["res_id", "=", fid]],
                    fields=["frozen_at", "frozen_by", "payload"], limit=1, order="frozen_at desc, id desc")
        check("проведення листка заморожує слід", bool(rows), f"листок {fid}")
        if rows:
            stored = json.loads(rows[0]["payload"])
            check("заморожений слід несе кроки і входи",
                  bool(stored.get("steps")) and bool(stored.get("inputs")),
                  f"{len(stored.get('steps') or [])} кроків, {len(stored.get('inputs') or {})} входів")
            after = call_soft("ua.explain", "explain", "hr.payslip", fid)
            check("після проведення пояснення читається як committed",
                  isinstance(after, dict) and after.get("state") == "committed" and after.get("frozen") is True,
                  str(after.get("state") if isinstance(after, dict) else after)[:120])
            check("заморожений слід називає автора і час", bool(rows[0]["frozen_at"]) and bool(rows[0]["frozen_by"]),
                  f"{rows[0]['frozen_at']} · {rows[0]['frozen_by'][1] if rows[0]['frozen_by'] else ''}")

# 17. модель без підтримки дає зрозумілу відмову українською
res = call_soft("ua.explain", "explain", "res.partner", 1)
msg = res.get("__error__", "") if isinstance(res, dict) else ""
check("модель без сліду дає зрозумілу відмову українською",
      bool(msg) and any(ch in msg for ch in "іїєґабвгдежзклмнопрстуфхцчшщюя"), msg[:160])

# 18. у формулах правил немає ставок без дати і підстави
rules = call("hr.salary.rule", "search_read", [["amount_select", "=", "code"]],
             fields=["code", "amount_python_compute", "note"])
literal_rules = []
for r in rules:
    text = r.get("amount_python_compute") or ""
    text = re.sub(r"#.*", "", text)
    for num in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text):
        if num not in ALLOWED_NUMBERS:
            literal_rules.append(f"{r['code']}: {num}")
            break
check("у формулах правил немає числових ставок замість параметра", not literal_rules,
      str(literal_rules[:6]))

no_note_rules = [r["code"] for r in rules if not (r.get("note") or "").strip()]
check("кожне правило пояснене полем note", not no_note_rules, str(no_note_rules[:8]))

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
