"""Перевірка модуля l10n_ua_reporting: get_screen_data() повертає всі ключі, action_refresh() дає
перевірки (є ok на суми і error/warn за станом даних), action_generate() без помилок формує
щонайменше 4 файли XML (кожен починається з <?xml) для j05 за місяць; окремий прогін pfu формує
PDF (%PDF); action_mark_submitted() ставить стан і дату; повторне створення прогону на той самий
період відкриває наявний, а не дублює; бандл web.assets_backend містить l10n_ua_reporting.Reporting.

HTTP-перевірка збірки ресурсів працює лише коли PAYROLL_DB=payroll - dbfilter стенду (^payroll$)
блокує HTTP-доступ до інших баз (payroll_cloud, payroll_test). Коли це так, перевірку пропущено
з поясненням, як у scripts/dashboard_check.py; збірку на payroll_cloud перевірено окремо в odoo
shell через ir.qweb._get_asset_bundle() (див. звіт агента).

База читається зі змінної середовища PAYROLL_DB (типово payroll_cloud - основна база цього завдання).
Запуск: PAYROLL_DB=payroll_cloud python3 scripts/reporting_check.py"""
import http.cookiejar
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = f"http://127.0.0.1:{PORT}"
URL = f"{BASE}/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll_cloud").strip()
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
    r = urllib.request.urlopen(urllib.request.Request(
        URL, json.dumps({"jsonrpc": "2.0", "method": "call",
                         "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(),
        {"Content-Type": "application/json"}), timeout=600)
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як admin на базі {DB} (перевірте ODOO_ADMIN_USER_PASSWORD).")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


# 1. get_screen_data() без run_id повертає всі очікувані ключі (j05, поточний місяць за замовчуванням)
data = call("ua.report.run", "get_screen_data")
expected_keys = {"reports", "periods", "run", "checks", "summary", "appendices", "history"}
check("get_screen_data() повертає всі очікувані ключі", expected_keys.issubset(data.keys()),
      f"відсутні: {expected_keys - set(data.keys())}" if not expected_keys.issubset(data.keys()) else
      f"звіт за замовчуванням: {data['run']['report_code']}, стан {data['run']['state']}")
check("reports містить щонайменше 6 звітів", len(data.get("reports", [])) >= 6, f"{len(data.get('reports', []))} звітів")
check("periods містить 6 періодів", len(data.get("periods", [])) == 6, f"{len(data.get('periods', []))} періодів")

# 2. j05 за серпень 2026: action_refresh() дає перевірки; серед них ok на суми, error/warn за станом
# Податковий розрахунок подається щомісяця: прогін має місяць, а не квартал.
data_j05 = call("ua.report.run", "get_screen_data", report_code="j05", year=2026, month=8)
run_j05 = data_j05["run"]
run_j05_id = run_j05["id"]
check("j05 серпень 2026: run створено/знайдено", run_j05["report_code"] == "j05" and run_j05["year"] == 2026 and run_j05["month"] == 8,
      f"run_id={run_j05_id}, стан={run_j05['state']}")

call("ua.report.run", "action_refresh", [run_j05_id])
data_j05 = call("ua.report.run", "get_screen_data", run_id=run_j05_id)
checks_j05 = data_j05["checks"]
levels = {c["level"] for c in checks_j05}
check("j05: action_refresh() дає перевірки", len(checks_j05) >= 5, f"{len(checks_j05)} перевірок: {[c['code'] for c in checks_j05]}")
check("j05: серед перевірок є ok на суми (Д1/ЄСВ/4ДФ)",
      any(c["level"] == "ok" and c["code"].startswith("j05_") for c in checks_j05),
      f"рівні: {[(c['code'], c['level']) for c in checks_j05 if c['code'].startswith('j05_')]}")
check("j05: перевірки мають лише рівні ok/warn/error", levels <= {"ok", "warn", "error"}, str(levels))

# 3. action_generate() без помилок формує щонайменше 4 XML-файли, кожен починається з <?xml
errors_j05 = [c for c in checks_j05 if c["level"] == "error"]
if errors_j05:
    check("j05: action_generate() без помилок формує файли", False,
          f"є перевірки рівня error, генерацію пропущено: {[(c['title'], c['detail']) for c in errors_j05]}")
else:
    call("ua.report.run", "action_generate", [run_j05_id])
    data_j05 = call("ua.report.run", "get_screen_data", run_id=run_j05_id)
    run_j05 = data_j05["run"]
    files = run_j05["files"]
    xml_files = [f for f in files if f["mimetype"] == "application/xml"]
    check("j05: стан 'generated' після action_generate()", run_j05["state"] == "generated", run_j05["state"])
    check("j05: сформовано щонайменше 4 XML-файли", len(xml_files) >= 4, f"{len(xml_files)} XML з {len(files)} файлів: {[f['name'] for f in files]}")

    xml_ok = True
    for f in xml_files:
        content = call("ir.attachment", "read", [f["id"]], ["datas"])[0]["datas"]
        import base64
        raw = base64.b64decode(content)
        if not raw.startswith(b"<?xml"):
            xml_ok = False
            print(f"    ! {f['name']} не починається з <?xml: {raw[:20]!r}")
    check("j05: усі XML-файли починаються з <?xml", xml_ok)
    check("j05: є додатки (Д1/4ДФ/Д5) у get_screen_data", len(data_j05["appendices"]) > 0, f"{len(data_j05['appendices'])} додатків")

# 4. pfu за серпень 2026: генерація формує PDF, що починається з %PDF
data_pfu = call("ua.report.run", "get_screen_data", report_code="pfu", year=2026, month=8)
run_pfu_id = data_pfu["run"]["id"]
call("ua.report.run", "action_refresh", [run_pfu_id])
data_pfu = call("ua.report.run", "get_screen_data", run_id=run_pfu_id)
errors_pfu = [c for c in data_pfu["checks"] if c["level"] == "error"]
if errors_pfu:
    check("pfu серпень 2026: генерація без помилок", False, f"{[(c['title'], c['detail']) for c in errors_pfu]}")
else:
    call("ua.report.run", "action_generate", [run_pfu_id])
    data_pfu = call("ua.report.run", "get_screen_data", run_id=run_pfu_id)
    run_pfu = data_pfu["run"]
    check("pfu: стан 'generated'", run_pfu["state"] == "generated", run_pfu["state"])
    pdf_files = [f for f in run_pfu["files"] if f["mimetype"] == "application/pdf"]
    check("pfu: сформовано PDF-файл", len(pdf_files) >= 1, f"{[f['name'] for f in run_pfu['files']]}")
    if pdf_files:
        import base64
        content = call("ir.attachment", "read", [pdf_files[0]["id"]], ["datas"])[0]["datas"]
        raw = base64.b64decode(content)
        check("pfu: PDF починається з %PDF", raw.startswith(b"%PDF"), str(raw[:10]))

    # 5. action_mark_submitted() ставить стан і дату
    call("ua.report.run", "action_mark_submitted", [run_pfu_id])
    data_pfu = call("ua.report.run", "get_screen_data", run_id=run_pfu_id)
    run_pfu = data_pfu["run"]
    check("pfu: action_mark_submitted() -> стан 'submitted'", run_pfu["state"] == "submitted", run_pfu["state"])
    check("pfu: submitted_date заповнено", bool(run_pfu["submitted_date"]), run_pfu["submitted_date"])

# 6. повторне створення прогону на той самий період відкриває наявний, а не дублює
before = call("ua.report.run", "search_count", [["report_code", "=", "j05"], ["year", "=", 2026], ["month", "=", 8]])
data_again = call("ua.report.run", "get_screen_data", report_code="j05", year=2026, month=8)
after = call("ua.report.run", "search_count", [["report_code", "=", "j05"], ["year", "=", 2026], ["month", "=", 8]])
check("повторне звернення на j05 за серпень не створює дубль", before == after and data_again["run"]["id"] == run_j05_id,
      f"до={before}, після={after}, run_id={data_again['run']['id']} (очікували {run_j05_id})")

# 7. HTTP-перевірка збірки ресурсів - лише коли DB=payroll (dbfilter стенду блокує інші бази)
if DB != "payroll":
    print(f"[--] HTTP-перевірка збірки web.assets_backend пропущена: dbfilter стенду дозволяє HTTP "
          f"лише для бази payroll, поточна PAYROLL_DB={DB}. Збірку на {DB} перевірено окремо через "
          f"odoo shell (ir.qweb._get_asset_bundle), див. звіт агента.")
else:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    auth_body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode()
    opener.open(urllib.request.Request(f"{BASE}/web/session/authenticate", data=auth_body,
                headers={"Content-Type": "application/json"}), timeout=60).read()
    try:
        with opener.open(f"{BASE}/web/assets/debug/web.assets_backend.js", timeout=120) as r:
            code = r.getcode()
            body = r.read().decode("utf-8", errors="replace")
        check("GET /web/assets/debug/web.assets_backend.js -> 200", code == 200, f"code={code}")
        check("бандл містить l10n_ua_reporting.Reporting", "l10n_ua_reporting.Reporting" in body)
    except Exception as exc:
        check("GET /web/assets/debug/web.assets_backend.js", False, str(exc)[:300])

# 12. Коригування об'єднаної звітності: створення прогону і зрозуміла відмова без розбіжностей
j05_run = call("ua.report.run", "search_read",
               [["report_code", "=", "j05"], ["state", "in", ["generated", "submitted"]], ["doc_kind", "=", "HZ"]],
               fields=["id", "name"], limit=1)
if not j05_run:
    print("[--] немає сформованого звітного розрахунку, перевірку коригування пропущено")
else:
    screen = call("ua.report.run", "get_screen_data", run_id=j05_run[0]["id"])
    check("сформований розрахунок можна коригувати", screen["run"].get("can_correct") is True)
    created = call("ua.report.run", "create_correction", j05_run[0]["id"], "HZU")
    check("коригування створюється з позначкою типу", "уточнюючий" in created["name"], created["name"])
    corr = call("ua.report.run", "read", [created["id"]], ["doc_kind", "base_run_id", "state", "correction_no"])[0]
    check("у коригуванні вказано тип, основу і номер",
          corr["doc_kind"] == "HZU" and corr["base_run_id"] and corr["correction_no"] == 1,
          f"{corr['doc_kind']}, основа {corr['base_run_id'][1] if corr['base_run_id'] else '-'}, № {corr['correction_no']}")
    try:
        call("ua.report.run", "action_generate", [created["id"]])
        check("без змін коригування не формується", False, "файли сформувалися, хоча змін немає")
    except SystemExit as exc:
        check("без змін коригування не формується і пояснює чому", "Розбіжностей" in str(exc), str(exc)[:90])
    call("ua.report.run", "unlink", [created["id"]])
    check("тестове коригування прибрано", not call("ua.report.run", "search", [["id", "=", created["id"]]]))

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
