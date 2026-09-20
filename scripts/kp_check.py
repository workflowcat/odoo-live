"""Перевірка кодів професій (модуль l10n_ua_kp).

Код КП у штатному розписі був вільним текстом, і це вже дало помилки: код іншої
професії, скопійований із сусіднього рядка, і позиція зовсім без коду. Тут перевіряємо
і довідник, і звірку зі службою класифікатора.

Служба: https://profkod.botpartners.workers.dev (репозиторій /Users/kit/Codius/profkod).
Коли служба недоступна, перевірка не падає: пункти про звірку стають пропущеними,
бо саме так має поводитися і продукт.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/kp_check.py"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
LOGIN = ENV["ODOO_ADMIN_USER_LOGIN"].strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
SERVICE = os.environ.get("UA_KP_URL", "https://profkod.botpartners.workers.dev").rstrip("/")

LEVELS = {"ok", "warn", "crit"}
errors = []
total = 0
skipped = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def skip(label, why):
    global skipped
    skipped += 1
    print(f"[--] {label} - {why}")


def rpc(service, method, *args):
    request = urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(request, timeout=900).read())
    if "error" in data:
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:600])
    return data.get("result")


UID = rpc("common", "login", DB, LOGIN, PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як {LOGIN} на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def service_up():
    try:
        with urllib.request.urlopen(SERVICE + "/health", timeout=8) as r:
            return json.loads(r.read()).get("ok") is True
    except Exception:
        return False


# 1. модуль і модель
mod = call("ir.module.module", "search_read", [["name", "=", "l10n_ua_kp"]], fields=["state"])
check("модуль l10n_ua_kp встановлений", bool(mod) and mod[0]["state"] == "installed",
      mod[0]["state"] if mod else "немає в списку")

fields_kp = call("ua.kp.code", "fields_get", [], {"attributes": ["string"]})
check("довідник не тримає «офіційної назви» на коді", "name" not in fields_kp,
      "під одним кодом їх буває дев'яносто, назва належить позиції")
check("довідник має код, групу і кількість професій",
      {"code", "group", "names_count"} <= set(fields_kp), str(sorted(set(fields_kp) & {"code", "group", "names_count"})))

line_fields = call("ua.staff.list.line", "fields_get", [], {"attributes": ["string"]})
check("рядок розпису має посилання на довідник і офіційну назву",
      {"kp_id", "kp_official_name"} <= set(line_fields),
      str(sorted(set(line_fields) & {"kp_id", "kp_official_name"})))

# 2. довідник покриває те, що стоїть у розписах
lines = call("ua.staff.list.line", "search_read", [["kp_code", "!=", False]], fields=["kp_code", "job_title"])
used = sorted({(l.get("kp_code") or "").strip() for l in lines if (l.get("kp_code") or "").strip()})
known = {r["code"] for r in call("ua.kp.code", "search_read", [], fields=["code"])}
missing = [c for c in used if c not in known]
check("кожен код зі штатних розписів є в довіднику", not missing, str(missing[:6]))

blank = sorted({(l.get("job_title") or "").strip() for l in lines if not (l.get("kp_code") or "").strip()})
all_lines = call("ua.staff.list.line", "search_read", [], fields=["kp_code", "job_title"])
blank_all = sorted({(l.get("job_title") or "").strip() for l in all_lines
                    if (l.get("job_title") or "").strip() and not (l.get("kp_code") or "").strip()})

# 3. звірка зі службою
if not service_up():
    skip("звірка зі службою класифікатора", f"служба {SERVICE} недоступна")
    skip("позиції без коду", "потрібна служба, щоб запропонувати код")
else:
    audit = call("ua.kp.code", "audit_staff_lists")
    check("звірка повертає перелік", isinstance(audit, list), f"{len(audit)} рядків")
    bad_level = [r.get("level") for r in audit if r.get("level") not in LEVELS]
    check("рівень кожного рядка звірки зі списку", not bad_level, str(bad_level[:4]))
    no_target = [r.get("title") for r in audit if not r.get("target")]
    check("кожен рядок звірки веде до запису", not no_target, str(no_target[:4]))

    crit = [r for r in audit if r.get("level") == "crit"]
    # Помилки коду - це не «попередження на майбутнє»: у штатний розпис іде неправильна
    # професія. Тому сам факт наявності crit провалює перевірку, і це навмисно.
    check("немає позицій із неправильним або відсутнім кодом", not crit,
          "; ".join(f'{r["title"]}: {r["text"]}' for r in crit[:4]))

    warn = [r for r in audit if r.get("level") == "warn"]
    check("немає позицій, чий код не підтверджується назвою", not warn,
          "; ".join(f'{r["title"]} ({r["code"]}) -> {(r.get("suggested") or {}).get("code")}' for r in warn[:4]))

    sug = call("ua.kp.code", "suggest", "менеджерка з персоналу", 3)
    first = (sug.get("items") or [None])[0]
    check("підказка розуміє фемінітив", bool(first) and first["code"] == "1477.1",
          f'{first["code"]} {first["name"]}' if first else "нічого")
    sug = call("ua.kp.code", "suggest", "business analyst", 3)
    first = (sug.get("items") or [None])[0]
    check("підказка розуміє англійську назву", bool(first) and first["code"] == "2131.2",
          f'{first["code"]} {first["name"]}' if first else "нічого")

# 4. поведінка без служби
res = rpc("object", "execute_kw", DB, UID, PW, "ua.kp.code", "suggest", ["кладовщик"], {"limit": 1})
check("підказка завжди повертає ознаку доступності служби", "available" in res, str(sorted(res)[:4]))

print()
if blank_all:
    print(f"позиції без коду: {', '.join(blank_all)}")
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено"
          + (f", пропущено {skipped}" if skipped else ""))
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total})" + (f", пропущено {skipped}" if skipped else "") + ".")
