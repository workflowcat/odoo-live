"""Перевірка модуля l10n_ua_card_ui на стенді, база payroll (PAYROLL_DB, типово payroll).

Гібридний скрипт, як vacation_check.py: функціональні перевірки get_card_data і
action_ua_card_* йдуть через `odoo shell` (окремий короткочасний процес у тому ж контейнері,
завжди читає .py заново з диска), а не JSON-RPC до персистентного сервера на :8110. Причина:
персистентний сервер уже працював, коли з'явився l10n_ua_card_ui; перший `-i` примусив його
імпортувати модуль вперше (реєстр Odoo re-import'ить Python-пакет модуля, якого раніше не було
в sys.modules цього процесу) - тому одразу після встановлення виклики через :8110 таки
відпрацювали. Але подальші правки models/hr_employee.py (lang=uk_UA для міток; прибрати
задвоєне слово "Наказ" у хроніці) персистентний сервер уже НЕ підхопив: Python-модуль лишається
закешованим у sys.memory процесу, і жоден `-u` цього не змінює - потрібен перезапуск контейнера,
а це заборонено умовами задачі. Тож усе, що залежить від поточного тексту get_card_data,
перевірено через odoo shell; HTTP-перевірки (збірка ресурсів, друк PDF) не залежать від
Python-коду цього модуля (ресурси читаються з диска щоразу, PDF - з XML-звітів у БД), тож ідуть
через персистентний сервер, як у card_check.py/dashboard_check.py.

Запуск: PAYROLL_DB=payroll python3 scripts/card_ui_check.py"""
import http.cookiejar
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = f"http://127.0.0.1:{PORT}"
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


# ============================================================================================
# Частина 1: усе, що залежить від поточного коду models/hr_employee.py - через odoo shell.
# ============================================================================================
SCRIPT = r"""
import sys

from odoo import fields

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


Employee = env['hr.employee']

# 1. get_card_data для трьох працівників повертає всі очікувані ключі
EXPECTED_KEYS = {"header", "person", "pay", "vacation", "military", "documents", "timeline", "actions"}
sample = Employee.search([], order='id', limit=3)
check(f"є принаймні 3 працівники для вибірки ({len(sample)})", len(sample) == 3)
for e in sample:
    data = e.get_card_data()
    missing = EXPECTED_KEYS - set(data.keys())
    check(f"{e.name}: get_card_data повертає всі ключі", not missing, f"відсутні: {missing}" if missing else "")
    check(f"{e.name}: header.name заповнено", bool(data.get("header", {}).get("name")))

# 2. Ткачук: у timeline є прийняття 01.03.2021, звільнення 31.05.2026, зміна окладу 17.08.2026
# (наказ 17.08.2026 - зміна окладу, не нове прийняття: contract_date_start лишається 01.03.2021
# на всіх версіях, а тип події бере наказ, що провів версію, - фікс мапінгу хроніки).
# Ткачук має проведений наказ про звільнення (31.05.2026) - архівований по-справжньому (фікс
# консистентності звільнення), тож шукаємо з active_test=False, як і будь-якого колишнього працівника.
tk = Employee.with_context(active_test=False).search([('name', 'ilike', 'Ткачук')], limit=1)
check("знайдено Ткачука Ігоря Володимировича", bool(tk))
if tk:
    tdata = tk.get_card_data()
    events = [(ev['date'], ev['kind']) for ev in tdata['timeline']]
    check("у хроніці Ткачука є прийняття 01.03.2021", ('01.03.2021', 'hire') in events, str(events))
    check("у хроніці Ткачука є звільнення 31.05.2026", ('31.05.2026', 'dismiss') in events, str(events))
    check("у хроніці Ткачука є зміна окладу 17.08.2026", ('17.08.2026', 'wage') in events, str(events))
    order_details = [ev['detail'] for ev in tdata['timeline'] if ev['kind'] in ('hire', 'dismiss', 'wage', 'transfer')]
    check("рядки наказів у хроніці не задвоюють слово «Наказ»",
          all(d.count('Наказ') <= 1 for d in order_details), str(order_details))
    check("actions містить дію «Стандартна форма»",
          any(a['key'] == 'standard_form' for a in tdata['actions']))
    check("actions розкладені на header/footer",
          {a['group'] for a in tdata['actions']} == {'header', 'footer'})

# 3. Вид-обгортка існує і має пріоритет нижчий за стандартний (16) - тобто відкривається першим
card_view = env.ref('l10n_ua_card_ui.view_employee_form_ua_card_wrapper', raise_if_not_found=False)
check("вид-обгортка view_employee_form_ua_card_wrapper існує", bool(card_view))
if card_view:
    std_view = env.ref('hr.view_employee_form')
    check(f"пріоритет обгортки ({card_view.priority}) нижчий за стандартний ({std_view.priority})",
          card_view.priority < std_view.priority)
    check("вид-обгортка - для моделі hr.employee", card_view.model == 'hr.employee')
    check("арка обгортки містить widget ua_employee_card", 'ua_employee_card' in (card_view.arch_db or ''))

# 4. Дія «Співробітники» (hr.open_view_employee_list_my) відкриває саме нашу форму
act = env.ref('hr.open_view_employee_list_my')
form_entries = [v for v in act.views if v[1] == 'form']
check("дія «Співробітники» має рядок form у views", len(form_entries) == 1, str(act.views))
if form_entries and card_view:
    check("форма дії «Співробітники» - це наша картка",
          form_entries[0][0] == card_view.id, f"view_id={form_entries[0][0]}, card_view.id={card_view.id}")

# додатково: та сама перевірка на дії іншого модуля (military), щоб підтвердити - хук
# перезаписує форму для БУДЬ-ЯКОЇ дії на hr.employee, не лише для однієї, названої в спеці
act2 = env.ref('l10n_ua_military.action_ua_military_liable', raise_if_not_found=False)
if act2 and card_view:
    form_entries2 = [v for v in act2.views if v[1] == 'form']
    # форма може бути прописана явно або братися за пріоритетом: картка має priority=1
    default_form = env['hr.employee'].get_views([(False, 'form')])['views']['form']['id']
    effective = form_entries2[0][0] or default_form if form_entries2 else None
    check("дія «Військовозобов'язані» також відкриває нашу картку (форма)",
          effective == card_view.id, f"views={act2.views}, форма за замовчуванням={default_form}")
    check("дія «Військовозобов'язані» відкривається списком, а не формою",
          act2.views and act2.views[0][1] != 'form', str(act2.views))

# 5. Дії кнопок повертають коректні словники (без реальних записів для Ткачука - лише форма/друк)
if tk:
    for method, res_model in [
        ('action_ua_card_open_payslips', 'hr.payslip'),
        ('action_ua_card_new_version', 'hr.version'),
        ('action_ua_card_dismiss', 'hr.version'),
        ('action_ua_card_new_leave', 'hr.leave'),
        ('action_ua_card_new_document', 'ua.employee.document'),
        ('action_ua_card_open_standard_form', 'hr.employee'),
    ]:
        res = getattr(tk, method)()
        ok = isinstance(res, dict) and res.get('type') == 'ir.actions.act_window' and res.get('res_model') == res_model
        check(f"{method} повертає act_window на {res_model}", ok, str(res)[:200])

    for method in ('action_ua_card_print_p2', 'action_ua_card_print_order'):
        res = getattr(tk, method)()
        is_report = isinstance(res, dict) and res.get('type') == 'ir.actions.report'
        # компанія без налаштованого шаблону документа -> report_action() спершу відкриває
        # майстер «Налаштуйте шаблон документу», а сам звіт лежить у context.report_action -
        # це поведінка ядра Odoo (report_action()), не помилка картки; приймаємо обидва варіанти.
        is_wrapped = (isinstance(res, dict) and res.get('type') == 'ir.actions.act_window'
                      and isinstance(res.get('context'), dict)
                      and (res['context'].get('report_action') or {}).get('type') == 'ir.actions.report')
        check(f"{method} повертає звіт (напряму або через майстер шаблону документа)",
              is_report or is_wrapped, str(res)[:200])

# 6. «Записати звірку ТЦК»: створює подію і оновлює дату звірки, без форми - на одноразовому працівнику
company = env['res.company'].search([], limit=1)
tmp = Employee.create({'name': 'ТЕСТ Тимчасовий (card_ui_check)', 'company_id': company.id})
today = fields.Date.context_today(tmp)
result = tmp.action_ua_card_register_mil_check()
tmp.invalidate_recordset()
check("action_ua_card_register_mil_check не повертає дію (лише перезавантаження картки)", result in (False, None), str(result))
check("звірка створила подію ua.military.event з видом check", tmp.ua_mil_event_ids.mapped('kind') == ['check'])
check("звірка оновила ua_mil_last_check на сьогодні", tmp.ua_mil_last_check == today, str(tmp.ua_mil_last_check))
tmp_id = tmp.id
tmp.unlink()
check("одноразовий працівник прибраний після перевірки", not Employee.browse(tmp_id).exists())

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
shell_out = proc.stdout
print(shell_out.strip())
if proc.returncode != 0 and "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" not in shell_out and "Усі перевірки пройдено" not in shell_out:
    print("--- stderr (odoo shell) ---")
    print(proc.stderr[-4000:])
    sys.exit(proc.returncode)
shell_failed = "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" in shell_out or "Усі перевірки пройдено" not in shell_out
shell_total_line = [l for l in shell_out.splitlines() if l.startswith("[OK]") or l.startswith("[FAIL]")]
total += len(shell_total_line)
errors += [l for l in shell_total_line if l.startswith("[FAIL]")]

# ============================================================================================
# Частина 2: HTTP-перевірки через персистентний сервер (:8110) - не залежать від Python-коду
# модуля (ресурси на диску, PDF-звіти в БД), тож стан кешованого Python їм не заважає.
# ============================================================================================
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
auth_body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"db": DB, "login": "admin", "password": PW}}).encode()
opener.open(urllib.request.Request(f"{BASE}/web/session/authenticate", data=auth_body,
            headers={"Content-Type": "application/json"}), timeout=60).read()

# 4. Бандл web.assets_backend збирається без помилок і містить рядок l10n_ua_card_ui.EmployeeCard
try:
    with opener.open(f"{BASE}/web/assets/debug/web.assets_backend.js", timeout=120) as r:
        code = r.getcode()
        body = r.read().decode("utf-8", errors="replace")
    check("GET /web/assets/debug/web.assets_backend.js -> 200", code == 200, f"code={code}")
    check("бандл містить l10n_ua_card_ui.EmployeeCard", "l10n_ua_card_ui.EmployeeCard" in body)
    check("бандл реєструє віджет ua_employee_card", "ua_employee_card" in body)
except Exception as exc:
    check("GET /web/assets/debug/web.assets_backend.js", False, str(exc)[:300])


def rpc(service, method, *args):
    r = urllib.request.urlopen(urllib.request.Request(
        f"{BASE}/jsonrpc", json.dumps({"jsonrpc": "2.0", "method": "call",
                                        "params": {"service": service, "method": method, "args": args}, "id": 1}).encode(),
        {"Content-Type": "application/json"}))
    d = json.loads(r.read())
    if "error" in d:
        raise SystemExit(json.dumps(d["error"].get("data", {}).get("message") or d["error"], ensure_ascii=False)[:2000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як admin на базі {DB} (перевірте ODOO_ADMIN_USER_PASSWORD).")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def get_pdf(report_name, res_id):
    with opener.open(f"{BASE}/report/pdf/{report_name}/{res_id}", timeout=120) as r:
        return r.read()


# 5. Звіт П-2 і далі друкується (регресія) - для 3 працівників
emps = call("hr.employee", "search_read", [], fields=["id", "name"], order="id", limit=3)
for e in emps:
    pdf = get_pdf("l10n_ua_hr_card.report_ua_p2", e["id"])
    check(f"П-2 {e['name']} (id={e['id']}) - PDF починається з %PDF", pdf[:4] == b"%PDF")

# бонус: наказ П-1 (l10n_ua_hr_docs) на поточну версію Ткачука теж рендериться - той самий звіт,
# що його викликає кнопка «Наказ» картки
tk = call("hr.employee", "search_read", [["name", "ilike", "Ткачук"]], fields=["id", "current_version_id"],
         context={"active_test": False})
if tk and tk[0].get("current_version_id"):
    version_id = tk[0]["current_version_id"][0]
    pdf = get_pdf("l10n_ua_hr_docs.report_ua_order_hire", version_id)
    check(f"наказ П-1 для поточної версії Ткачука (id={version_id}) - PDF починається з %PDF", pdf[:4] == b"%PDF")

print()
if errors:
    print(f"ПІДСУМОК: ПРОВАЛЕНО {len(errors)} з {total} пунктів")
    for err in errors:
        print(" -", err)
    sys.exit(1)
print(f"ПІДСУМОК: усі перевірки пройдено ({total} з {total}).")
