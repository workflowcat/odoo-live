"""Перевірка анкети компанії (модуль l10n_ua_setup).

Анкета - каталог питань бухгалтера плюс відповіді компанії. Перевіряємо: питання
завантажені з файла анкети, відповідь має стан і джерело, відоме системі підставляється
саме, опис компанії дає пропозиції, обов'язкові питання блокують активацію.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/setup_check.py"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
URL = (os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")) + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

errors, total = [], 0


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
        raise RuntimeError(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:400])
    return data.get("result")


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def fails(fn):
    try:
        fn()
        return ""
    except RuntimeError as error:
        return str(error)


# 1. каталог питань
questions = call("ua.setup.question", "search_read", [], ["code", "section", "name", "required", "kind", "options"])
check("каталог питань завантажено", len(questions) >= 60, f"{len(questions)} питань")
sections = sorted({q["section"] for q in questions})
check("питання розкладені по розділах", len(sections) >= 10, "; ".join(s.split(". ")[1] for s in sections[:6]))
required = [q for q in questions if q["required"]]
check("обов'язкові питання позначені", len(required) >= 5, f"{len(required)} з позначкою уваги")
check("варіанти відповіді збережені", any(q["options"] for q in questions),
      next((q["options"][:60] for q in questions if q["options"]), ""))
check("текст питань узятий з анкети",
      any("ЄДРПОУ" in q["name"] for q in questions) and any("бронювання" in q["name"] for q in questions))

# 2. анкета компанії
data = call("ua.setup.profile", "get_screen_data")
pid = data["id"]
check("анкета створюється сама", bool(pid), f"id={pid}, питань {data['total']}")
call("ua.setup.profile", "action_fill", [pid])
answers = call("ua.setup.answer", "search_read", [["profile_id", "=", pid]], ["name", "state", "value", "source"])
check("рядок є на кожне питання", len(answers) == len(questions), f"{len(answers)} з {len(questions)}")
states = {a["state"] for a in answers}
check("стани відповідей із чотирьох значень", states <= {"missing", "supplied", "proposed", "confirmed"}, str(states))
supplied = [a for a in answers if a["state"] == "supplied"]
check("відоме системі підставлено само", len(supplied) >= 3,
      "; ".join(f"{a['name'][:28]}={a['value']}" for a in supplied[:3]))

# 3. пропозиції з опису
call("ua.setup.profile", "write", [pid], {"description":
     "Українське ТОВ, меблі, 20 працівників, більшість на окладі, двоє на пів ставки, "
     "розрахунки в гривні, один банк для зарплати"})
call("ua.setup.profile", "action_propose", [pid])
proposed = call("ua.setup.answer", "search_read", [["profile_id", "=", pid], ["state", "=", "proposed"]],
                ["name", "value", "source"])
check("опис компанії дає пропозиції", len(proposed) >= 4, f"{len(proposed)} відповідей")
check("пропозиція знає своє джерело", all(p["source"] == "description" for p in proposed))
check("форма власності впізнана з опису",
      any(p["value"] == "ТОВ" for p in proposed), str([p["value"] for p in proposed][:4]))

# 4. обов'язкові питання блокують старт
state = call("ua.setup.profile", "read", [pid], ["required_missing"])[0]
if state["required_missing"]:
    err = fails(lambda: call("ua.setup.profile", "action_activate", [pid]))
    check("без обов'язкових відповідей активація заборонена", "обов'язкових" in err, err[:90])
else:
    check("без обов'язкових відповідей активація заборонена", True, "усі обов'язкові вже закриті")

# 5. підтвердження відповіді
one = call("ua.setup.answer", "search", [["profile_id", "=", pid], ["state", "=", "missing"]], limit=1)
err = fails(lambda: call("ua.setup.answer", "action_confirm", one))
check("порожню відповідь підтвердити не можна", "впишіть" in err.lower(), err[:80])
call("ua.setup.answer", "write", one, {"value": "тестова відповідь"})
call("ua.setup.answer", "action_confirm", one)
check("відповідь підтверджується", call("ua.setup.answer", "read", one, ["state"])[0]["state"] == "confirmed")
call("ua.setup.answer", "action_reset", one)

# 6. пробний місяць
result = call("ua.setup.profile", "action_test_month", [pid])
check("пробний місяць відповідає повідомленням", bool(result.get("message")), str(result)[:80])

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    for e in errors:
        print("  -", e)
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
