"""Перевірка екрана «Папери» (модуль l10n_ua_papers).

Екран своїх даних не тримає: перелік паперів, поля, перегляд і «що входить» рахуються
з наявних моделей і наявних звітів. Тому перевіряємо не текст, а контракт: кожен папір
переліку відкривається, кожна ціль веде кудись, перегляд нічого не пише в базу,
а кнопка, яку не можна натиснути, завжди пояснює чому.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/papers_check.py"""
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
LANA_LOGIN = ENV.get("LANA_LOGIN", "lana").strip()
LANA_PW = ENV.get("LANA_PASSWORD", "").strip()

STATES = {"supplied", "imported", "calculated", "missing", "stale", "manual", "not_applicable"}
MARKS = {"ok", "warn", "crit", "none"}
GROUPS = ["month", "person", "state", "register"]

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def _post(payload):
    request = urllib.request.Request(
        URL, json.dumps(payload).encode(), {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(request, timeout=900).read())


def rpc(service, method, *args):
    data = _post({"jsonrpc": "2.0", "method": "call",
                  "params": {"service": service, "method": method, "args": args}})
    if "error" in data:
        raise SystemExit(json.dumps(data["error"].get("data", {}).get("message") or data["error"], ensure_ascii=False)[:600])
    return data.get("result")


def rpc_soft(service, method, *args):
    data = _post({"jsonrpc": "2.0", "method": "call",
                  "params": {"service": service, "method": method, "args": args}})
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


def targets_in(node, out=None):
    """Усі цілі відповіді, знайдені за формою словника, а не за іменем ключа:
    так нові блоки покриваються без правок цього файла."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("xmlid") or (node.get("model") and "group" not in node):
            out.append(node)
        for v in node.values():
            targets_in(v, out)
    elif isinstance(node, list):
        for v in node:
            targets_in(v, out)
    return out


# 1. дія і меню
actions = call("ir.actions.client", "search_read", [["tag", "=", "ua_papers"]], fields=["name"])
check("клієнтська дія з тегом ua_papers існує", len(actions) == 1, str(actions))

if LANA_PW:
    lana_uid = rpc("common", "login", DB, LANA_LOGIN, LANA_PW)
    if lana_uid:
        menus = rpc("object", "execute_kw", DB, lana_uid, LANA_PW, "ir.ui.menu", "search_read",
                    [[["name", "=", "Папери"], ["parent_id", "=", False]]], {"fields": ["name"]})
        check(f"корінь «Папери» видимий звичайному користувачу ({LANA_LOGIN})", bool(menus), f"{len(menus)} пунктів")
    else:
        check(f"вхід {LANA_LOGIN}", False, "не вдалося увійти")
else:
    check(f"вхід {LANA_LOGIN}", False, "немає пароля в .env (LANA_PASSWORD)")

# 2. форма відповіді
data = call("ua.papers", "get_screen_data")
expected = {"period", "papers", "paper"}
check("get_screen_data() повертає всі ключі", expected.issubset(data.keys()),
      f"відсутні: {expected - set(data.keys())}" if not expected.issubset(data.keys()) else data["period"]["label"])

period = data.get("period") or {}
periods = period.get("periods") or []
check("шість періодів, рівно один поточний", len(periods) == 6 and sum(1 for p in periods if p.get("current")) == 1,
      f"{len(periods)} періодів, поточних {sum(1 for p in periods if p.get('current'))}")

papers = data.get("papers") or []
check("перелік паперів не порожній", len(papers) >= 10, f"{len(papers)} паперів")
check("кожен папір має ключ, назву, групу і позначку зі списку",
      all(p.get("key") and p.get("name") and p.get("group") in GROUPS and p.get("mark") in MARKS for p in papers),
      str([(p.get("key"), p.get("group"), p.get("mark")) for p in papers if p.get("mark") not in MARKS][:4]))

order = [p["group"] for p in papers]
check("групи йдуть у фіксованому порядку і не чергуються",
      order == sorted(order, key=lambda g: GROUPS.index(g)), str(order))

# 3. кожен папір відкривається
bad = []
previews = {}
for p in papers:
    res = call_soft("ua.papers", "get_screen_data", period.get("year"), period.get("month"), p["key"])
    if "__error__" in res or not isinstance(res, dict):
        bad.append((p["key"], str(res)[:80]))
        continue
    got = (res.get("paper") or {}).get("key")
    if got != p["key"]:
        bad.append((p["key"], f"повернувся {got}"))
        continue
    previews[p["key"]] = res["paper"]
check("кожен папір переліку відкривається", not bad, str(bad[:4]))

# 4. форма вибраного паперу
shape = [k for k, paper in previews.items()
         if not (paper.get("name") and "fields" in paper and "preview" in paper
                 and "actions" in paper and "sources" in paper and "checks" in paper)]
check("кожен папір має поля, перегляд, дії, джерела і перевірки", not shape, str(shape[:5]))

# 4b. «Спершу дані, потім бланк» (spec-papers.md): edit/default_mode за наявністю
# рядків, головна дія - за станом. edit тепер - модель рядка + домен + вузький вигляд
# (task 4: список рядків, а не форма запису документа).
own_doc = {k: paper for k, paper in previews.items() if (paper.get("edit") or {}).get("model")}
no_doc = {k: paper for k, paper in previews.items() if not paper.get("edit")}
check("є хоч один папір із рядками (edit)", bool(own_doc), f"{len(own_doc)} з {len(previews)}")

bad_edit_mode = [k for k, paper in own_doc.items() if paper.get("default_mode") != "edit"]
check("папір із рядками має edit і default_mode 'edit'", not bad_edit_mode, str(bad_edit_mode[:5]))

bad_edit_shape = [k for k, paper in own_doc.items()
                   if not isinstance((paper["edit"]).get("doc", {}).get("res_id"), int)
                   or not isinstance((paper["edit"]).get("editable"), bool)
                   or not isinstance((paper["edit"]).get("view_id"), int)
                   or not isinstance((paper["edit"]).get("count"), int)
                   or not paper["edit"].get("domain")
                   or not paper["edit"].get("model")]
check("edit має модель рядка, domain, view_id, count, editable і doc.res_id",
      not bad_edit_shape, str(bad_edit_shape[:5]))

bad_line_model = [k for k, paper in own_doc.items()
                   if paper["edit"]["model"] == (paper["edit"].get("doc") or {}).get("model")]
check("у паперу з рядками edit.model - модель рядка, не документа", not bad_line_model, str(bad_line_model[:5]))

view_ids = sorted({paper["edit"]["view_id"] for paper in own_doc.values()})
found_views = call("ir.ui.view", "search_count", [("id", "in", view_ids)]) if view_ids else 0
check("view_id вузького вигляду існує в ir.ui.view", found_views == len(view_ids),
      f"{found_views} з {len(view_ids)}")

if view_ids:
    archs = call("ir.ui.view", "read", view_ids, ["arch"])
    day_fields = re.compile(r"""name=["']d\d\d["']""")
    bad_days = [a["id"] for a in archs if day_fields.search(a.get("arch") or "")]
    check("вузький вигляд не містить полів d01..d31", not bad_days, str(bad_days[:5]))

bad_print_mode = [k for k, paper in no_doc.items() if paper.get("default_mode") != "print"]
check("папір без edit має default_mode 'print'", not bad_print_mode, str(bad_print_mode[:5]))


def _primary_key(paper):
    return next((a["key"] for a in (paper.get("actions") or []) if a.get("primary")), None)


bad_state_action = []
for k, paper in previews.items():
    primary = _primary_key(paper)
    if not paper.get("record"):
        # журнал (order_register) - виняток задокументований у spec-papers.md/звіті: немає
        # запису в принципі, головна дія одразу "print" через майстер, не "compose".
        if primary not in ("compose", "print"):
            bad_state_action.append((k, "немає", primary))
    elif paper.get("state") == "draft" and primary not in ("confirm", "print"):
        bad_state_action.append((k, "чернетка", primary))
    elif paper.get("state") == "confirmed" and primary != "print":
        bad_state_action.append((k, "затверджено", primary))
check("головна дія відповідає стану документа (немає/чернетка/затверджено)",
      not bad_state_action, str(bad_state_action[:6]))

# 5. кнопка, яку не можна натиснути, пояснює чому
mute = [(k, a.get("key")) for k, paper in previews.items() for a in (paper.get("actions") or [])
        if a.get("enabled") is False and not a.get("reason")]
check("вимкнена кнопка завжди має причину", not mute, str(mute[:4]))

# 6. перегляд або є, або пояснює, чому його немає
silent = [k for k, paper in previews.items()
          if not (paper.get("preview") or {}).get("html") and not (paper.get("preview") or {}).get("empty_text")]
check("папір без перегляду каже, чому його немає", not silent, str(silent[:5]))
with_html = [k for k, paper in previews.items() if (paper.get("preview") or {}).get("html")]
check("щонайменше один папір показує готовий вигляд", bool(with_html), f"{len(with_html)} з {len(previews)}")

# 7. стани джерел зі списку
bad_state = [(k, s.get("state")) for k, paper in previews.items() for s in (paper.get("sources") or [])
             if s.get("state") not in STATES]
check("стан кожного джерела зі списку explain-model", not bad_state, str(bad_state[:5]))
no_label = [k for k, paper in previews.items() for s in (paper.get("sources") or []) if not s.get("label")]
check("кожне джерело названо", not no_label, str(no_label[:5]))

# 8. рівні перевірок
bad_level = [(k, c.get("level")) for k, paper in previews.items() for c in (paper.get("checks") or [])
             if c.get("level") not in ("ok", "warn", "crit")]
check("рівень кожної перевірки зі списку", not bad_level, str(bad_level[:5]))

# 9. кожна ціль відкривається
targets = targets_in(data) + [t for paper in previews.values() for t in targets_in(paper)]
seen, uniq = set(), []
for t in targets:
    k = json.dumps(t, sort_keys=True, ensure_ascii=False)
    if k not in seen:
        seen.add(k)
        uniq.append(t)
broken = []
for t in uniq:
    res = call_soft("ua.papers", "open_target", t)
    if not isinstance(res, dict) or "__error__" in res or not res.get("type"):
        broken.append((json.dumps(t, ensure_ascii=False)[:70], str(res)[:60]))
check(f"кожна ціль відкривається ({len(uniq)} цілей)", not broken, str(broken[:3]))

# 10. перегляд нічого не пише в базу
models = sorted({paper["record"]["model"] for paper in previews.values()
                 if (paper.get("record") or {}).get("model")})
before = {m: call(m, "search_count", []) for m in models}
for key in list(previews)[:6]:
    call_soft("ua.papers", "get_screen_data", period.get("year"), period.get("month"), key)
after = {m: call(m, "search_count", []) for m in models}
grew = {m: (before[m], after[m]) for m in models if before[m] != after[m]}
check("перегляд не створює записів", not grew, str(grew) if grew else f"{len(models)} моделей без змін")

# 11. інший місяць
prev = [p for p in periods if not p.get("current")]
if prev:
    other = prev[0]
    res = call_soft("ua.papers", "get_screen_data", other["year"], other["month"])
    ok = isinstance(res, dict) and (res.get("period") or {}).get("label") != period.get("label") and res.get("paper")
    check("перемикання місяця міняє період і лишає папір", bool(ok),
          str((res.get("period") or {}).get("label") if isinstance(res, dict) else res)[:80])
else:
    check("перемикання місяця міняє період і лишає папір", False, "немає іншого періоду")

# 11a. правила складання чернетки знає модель документа, не екран
# «Створити» на екрані лише передає період; що саме містить новий табель і новий пакет
# листків, знають ua.timesheet.sheet.ua_compose() і hr.payslip.run.ua_compose().
# Табель ідемпотентний - його кличемо на місяці стенду; пакет створюється завжди, тому
# для нього беремо порожній місяць і прибираємо за собою.
COMPANY_ID = call("res.users", "read", [UID], ["company_id"])[0]["company_id"][0]
NOLOG = {"ua_no_log": True}
Y, M = period.get("year"), period.get("month")

sheet_before = call("ua.timesheet.sheet", "search_count", [])
composed = call_soft("ua.timesheet.sheet", "ua_compose", COMPANY_ID, Y, M, context=NOLOG)
sheet_id = composed[0] if isinstance(composed, list) and composed else None
screen_sheet = call("ua.timesheet.sheet", "search",
                    [["company_id", "=", COMPANY_ID], ["year", "=", Y], ["month", "=", M],
                     ["department_id", "=", False]], limit=1)
check("ua.timesheet.sheet.ua_compose віддає той самий табель, що показує екран",
      bool(sheet_id) and [sheet_id] == screen_sheet, f"{composed} проти {screen_sheet}")
check("складання табеля ідемпотентне: другого табеля не з'явилося",
      call("ua.timesheet.sheet", "search_count", []) == sheet_before,
      f"{sheet_before} -> {call('ua.timesheet.sheet', 'search_count', [])}")

RY, RM = 2027, 3
stale = call("hr.payslip.run", "search",
             [["company_id", "=", COMPANY_ID], ["date_start", "=", f"{RY}-{RM:02d}-01"]])
if stale:
    call("hr.payslip.run", "unlink", stale, context=NOLOG)
composed_run = call_soft("hr.payslip.run", "ua_compose", COMPANY_ID, RY, RM, context=NOLOG)
run_id = composed_run[0] if isinstance(composed_run, list) and composed_run else None
check("hr.payslip.run.ua_compose складає пакет прямим викликом логіки", bool(run_id), str(composed_run)[:120])
if run_id:
    run = call("hr.payslip.run", "read", [run_id], ["name", "date_start", "date_end"])[0]
    check("пакет від логіки названий місяцем і охоплює весь місяць",
          run["name"] == f"Зарплата {RM:02d}.{RY}" and str(run["date_start"]) == f"{RY}-{RM:02d}-01"
          and str(run["date_end"]) == f"{RY}-{RM:02d}-31",
          f"{run['name']} · {run['date_start']} - {run['date_end']}")
    call("hr.payslip.run", "unlink", [run_id], context=NOLOG)
    check("пакет прибрано за собою", call("hr.payslip.run", "search_count", [["id", "=", run_id]]) == 0)

# 12. збірка ресурсів реєструє файли екрана
if DB == "payroll":
    try:
        req = urllib.request.Request(BASE + "/web/assets/debug/web.assets_backend.js",
                                     headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=300).read().decode("utf-8", "ignore")
        check("бандл JS реєструє l10n_ua_papers/static/src/papers.js",
              "l10n_ua_papers/static/src/papers.js" in body)
    except Exception as exc:
        check("GET /web/assets/debug/web.assets_backend.js", False, str(exc)[:200])
else:
    print(f"[--] HTTP-перевірка збірки пропущена: PAYROLL_DB={DB}")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
