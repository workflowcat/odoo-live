#!/usr/bin/env bash
# Еталонні сценарії зарплати на чистій базі. Стенд не потрібен - лише docker.
#
#   scripts/test.sh              звичайний запуск, база після прогону видаляється
#   KEEP_DB=1 scripts/test.sh    базу залишити (подивитися дані після падіння)
#   TEST_TAGS=ua_golden,ua_leaves  які тести запускати (типово обидва набори)
#
# Встановлення всього ланцюга модулів на порожню базу - теж частина перевірки:
# якщо якийсь модуль не ставиться, скрипт падає і показує голову трейсбека.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODULE="${TEST_MODULES:-l10n_ua_payroll_tests}"   # TEST_MODULES=l10n_ua_navigation - весь продукт (тести ua_vat, ua_cash... живуть у своїх модулях)
TEST_TAGS="${TEST_TAGS:-ua_golden,ua_leaves}"
DB="${TEST_DB:-payroll_golden_$$}"
LOG="$(mktemp "${TMPDIR:-/tmp}/payroll_test.XXXXXX")"   # GNU mktemp вимагає XXXXXX
STARTED_AT=$SECONDS

# Проєкт docker compose зветься за текою (odoo-live-base), тому томи і контейнери
# тут свої: сусідній odoo-live-payroll не чіпаємо.
PROJECT="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
if [ "$PROJECT" != "odoo-live-base" ]; then
    echo "Несподіваний проєкт docker compose: $PROJECT (очікували odoo-live-base)" >&2
    exit 2
fi

cleanup() {
    local code=$?
    if [ "${KEEP_DB:-0}" = "1" ]; then
        echo "Базу залишено: $DB (лог: $LOG)"
    else
        docker compose exec -T db dropdb -U odoo --force --if-exists "$DB" >/dev/null 2>&1 || true
        rm -f "$LOG"
    fi
    exit $code
}
trap cleanup EXIT

echo "== піднімаємо лише базу даних =="
docker compose up -d --wait db

echo "== створюємо порожню базу $DB =="
docker compose exec -T db dropdb -U odoo --force --if-exists "$DB" >/dev/null
docker compose exec -T db createdb -U odoo -O odoo "$DB"

echo "== встановлюємо $MODULE і ганяємо тести (теги: $TEST_TAGS) =="
set +e
# Конфіг стенда (/etc/odoo/odoo.conf) лишається чинним для db_host і addons_path,
# але його dbfilter = ^payroll$ і db_name тут ні до чого - перекриваємо в рядку команди.
docker compose run --rm --no-deps -T \
    odoo sh -c "pip install --break-system-packages pypdf >/dev/null 2>&1; exec odoo \
    --addons-path=/mnt/extra-addons \
    --db_host=db --db_user=odoo --db_password=odoo \
    --database=$DB \
    --db-filter='.*' \
    --init=$MODULE \
    --without-demo=True \
    --test-tags=$TEST_TAGS \
    --stop-after-init \
    --max-cron-threads=0 \
    --log-level=test" \
    2>&1 | tee "$LOG"
ODOO_CODE=${PIPESTATUS[0]}
set -e

ELAPSED=$((SECONDS - STARTED_AT))
echo
python3 - "$LOG" "$ODOO_CODE" "$ELAPSED" "$TEST_TAGS" <<'PY'
import json, os, re, sys

log_path, odoo_code, elapsed, tags = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
# Еталонні сценарії числяться пропущеними лише тоді, коли їх замовляли: з TEST_TAGS без
# ua_golden таблиця показує те, що справді запускалось, і не вигадує провалів.
golden_requested = "ua_golden" in [t.strip() for t in tags.split(",")]
golden = os.path.join(os.getcwd(), "addons", "l10n_ua_payroll_tests", "golden", "scenarios.json")
with open(golden, encoding="utf-8") as fh:
    scenarios = json.load(fh)["scenarios"]
titles = {"test_%02d" % s["id"]: s["title"] for s in scenarios} if golden_requested else {}
if golden_requested:
    titles["test_00_account_map_covers_rules"] = "карта проводок покриває всі правила"

log = open(log_path, encoding="utf-8", errors="replace").read()
lines = log.splitlines()

started = set(re.findall(r"Starting\s+\S*?(test_\w+)\s", log))
bad = {}
for i, line in enumerate(lines):
    m = re.search(r"\b(FAIL|ERROR):\s+\S*?(test_\w+)\b", line)
    if not m:
        continue
    name = m.group(2)
    detail = ""
    for follow in lines[i + 1:i + 40]:
        hit = re.search(r"(AssertionError|Error|Exception)[:\s].*", follow)
        if hit:
            detail = hit.group(0).strip()
            break
    bad.setdefault(name, (m.group(1), detail))

install_problem = [ln for ln in lines if "Failed to initialize database" in ln or "Module loading" in ln and "failed" in ln]

names = sorted(started | set(bad) | set(titles))
width = max(len(n) for n in names) if names else 10
print("=" * 100)
print("ЕТАЛОННІ СЦЕНАРІЇ")
print("=" * 100)
fails = 0
for name in names:
    title = titles.get(name, "")
    if name in bad:
        fails += 1
        flavour, detail = bad[name]
        print("%-*s  %-5s  %s" % (width, name, flavour, title))
        if detail:
            print("%s   %s" % (" " * width, detail[:300]))
    elif name in started:
        print("%-*s  %-5s  %s" % (width, name, "PASS", title))
    else:
        fails += 1
        print("%-*s  %-5s  %s" % (width, name, "MISS", title + " (тест не запускався)"))
print("=" * 100)
print("теги: %s; сценаріїв у наборі: %d; тестів запущено: %d; провалів: %d; час: %d с"
      % (tags, len(scenarios), len(started), fails, elapsed))
if install_problem:
    print("проблеми встановлення:")
    for ln in install_problem[:5]:
        print("  " + ln[:300])
if fails or odoo_code != 0:
    print("РЕЗУЛЬТАТ: FAIL (код odoo %d)" % odoo_code)
    sys.exit(1)
print("РЕЗУЛЬТАТ: PASS")
PY
