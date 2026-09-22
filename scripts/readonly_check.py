"""Перевірка: відкриття екрана нічого не пише в базу (усі дев'ять екранів + картка).

Кожен екран має рівно один метод читання (`get_screen_data`, у картки - `get_card_data`).
Договір екранів каже: читання - це читання, запис робить окремий виклик на кнопку
(`run_action`, план-метод, `ensure_run`). Три екрани раніше цей договір порушували, тому
тут він перевіряється не словами в коді, а самою базою.

Як: до і після виклику читаємо лічильники рядків з pg_stat_user_tables
(n_tup_ins / n_tup_upd / n_tup_del) через `docker compose exec -T db psql` і порівнюємо.
Різниця = екран щось записав; скрипт називає і таблиці.

Лічильники Postgres оновлюються із затримкою: бекенд скидає свою статистику в кінці
транзакції, але не частіше ніж раз на секунду. Тому кожне вимірювання починається з
«заспокоєння» (`_settle`): читаємо лічильники, чекаємо і читаємо знову, поки два
поспіль не збіжаться. Без цього запис попереднього виклику приїхав би в наступний.

Службові таблиці виключені: шина повідомлень, присутність, журнали входів і помилок,
бухгалтерія планувальника, сесії. Вони пишуться самі собою від будь-якого запиту.

Відомий виняток: «Період» на місяці, де табеля ще немає, створює його при відкритті
(ua.timesheet.sheet._ua_ensure_for - навмисно, крок «Табель» завжди має що показати).
На стенді табель поточного місяця вже є, тому перевірка стабільна; на новому місяці
перший прогін чесно покаже цей запис.

База зі змінної PAYROLL_DB (типово payroll).
Запуск: PAYROLL_DB=payroll python3 scripts/readonly_check.py"""
import json
import os
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PORT = (os.environ.get("ODOO_PORT") or ENV.get("ODOO_PORT", "8110")).strip()
BASE = os.environ.get("ODOO_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
URL = BASE + "/jsonrpc"
DB = os.environ.get("PAYROLL_DB", "payroll").strip()
LOGIN = ENV.get("ODOO_ADMIN_USER_LOGIN", "admin").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()

# Таблиці, що пишуться від самого факту запиту, а не від екрана.
SKIP_EXACT = ("bus_bus", "bus_presence", "res_users_log", "ir_logging",
              "ir_cron", "ir_cron_trigger", "ir_cron_progress", "ir_attachment_mimetype")
SKIP_LIKE = ("%session%", "ir_cron%", "bus_%")

STATS_SQL = """
SELECT relname, n_tup_ins, n_tup_upd, n_tup_del
FROM pg_stat_user_tables
WHERE relname NOT IN (%s) AND %s
ORDER BY relname
""" % (", ".join("'%s'" % t for t in SKIP_EXACT),
       " AND ".join("relname NOT LIKE '%s'" % p for p in SKIP_LIKE))

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


UID = rpc("common", "login", DB, LOGIN, PW)
if not UID:
    raise SystemExit(f"Не вдалося увійти в Odoo як {LOGIN} на базі {DB}.")


def call(model, method, *a, **kw):
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def psql(sql):
    out = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-U", "odoo",
                          "-d", DB, "-At", "-F", "\t", "-c", sql],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("psql: " + (out.stderr or out.stdout)[:400])
    return out.stdout


def counters():
    """{таблиця: (ins, upd, del)}. Свій бекенд psql скидає статистику одразу."""
    psql("SELECT pg_stat_force_next_flush();")
    rows = {}
    for line in psql(STATS_SQL).splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            rows[parts[0]] = tuple(int(x) for x in parts[1:])
    return rows


def _settle(tries=12, pause=1.2, stable=1):
    """Лічильники, коли вони перестали рухатися: `stable` однакових замірів поспіль.

    Так вимірювання не бере на себе хвіст попереднього виклику - Postgres скидає
    статистику бекенда не частіше ніж раз на секунду після кінця транзакції."""
    previous = counters()
    same = 0
    for _i in range(tries):
        time.sleep(pause)
        current = counters()
        same = same + 1 if current == previous else 0
        previous = current
        if same >= stable:
            return current
    return previous


def diff(before, after):
    """Таблиці, де щось додалося, змінилося або зникло, з розкладкою."""
    out = {}
    for name, values in after.items():
        was = before.get(name, (0, 0, 0))
        delta = tuple(n - o for n, o in zip(values, was))
        if any(d > 0 for d in delta):
            out[name] = delta
    return out


def totals(delta):
    return tuple(sum(d[i] for d in delta.values()) for i in range(3))


def words(delta):
    return ", ".join("%s (+%s/~%s/-%s)" % (name, *values) for name, values in sorted(delta.items()))


# Один працівник для картки: перший активний у компанії.
employee_ids = call("hr.employee", "search", [("active", "=", True)], limit=1)
if not employee_ids:
    raise SystemExit("На стенді немає жодного активного працівника - картку перевіряти нема на кому.")
EMPLOYEE = employee_ids[0]

# Екрани в тому вигляді, в якому їх відкриває клієнт: метод читання без аргументів
# (кожен сам бере поточний місяць), картка - на одному записі.
SCREENS = [
    ("ua.home", lambda: call("ua.home", "get_screen_data")),
    ("ua.papers", lambda: call("ua.papers", "get_screen_data")),
    ("ua.people", lambda: call("ua.people", "get_screen_data")),
    ("ua.period.board", lambda: call("ua.period.board", "get_screen_data")),
    ("ua.bank.board", lambda: call("ua.bank.board", "get_screen_data")),
    ("ua.dashboard", lambda: call("ua.dashboard", "get_screen_data")),
    ("ua.report.run", lambda: call("ua.report.run", "get_screen_data")),
    ("ua.hire.case", lambda: call("ua.hire.case", "get_screen_data")),
    ("ua.setup.profile", lambda: call("ua.setup.profile", "get_screen_data")),
    ("hr.employee.get_card_data", lambda: call("hr.employee", "get_card_data", [EMPLOYEE])),
]

print(f"база {DB}, працівник картки #{EMPLOYEE}")
print()

# Перед першим екраном заспокоюємось довго. У check_all.sh попередній скрипт щойно
# прибрав за собою десятки записів; бекенд, який це зробив, віддає свою статистику
# не одразу, а коли сам вважатиме за потрібне - на цьому стенді заміряно близько
# десяти секунд після виходу скрипта. Одного збігу замірів тут мало: чекаємо, поки
# лічильники простоять нерухомо десяток секунд, інакше чужі видалення припишуться
# першому екрану.
_settle(tries=25, pause=1.5, stable=8)

for name, read in SCREENS:
    before = _settle()
    result = read()
    check(f"{name}: читання відповідає", isinstance(result, (dict, list)) and bool(result),
          type(result).__name__)
    after = _settle()
    delta = diff(before, after)
    ins, upd, dele = totals(delta)
    check(f"{name}: читання нічого не пише в базу", not delta,
          words(delta) if delta else f"+{ins}/~{upd}/-{dele}")

print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    raise SystemExit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
