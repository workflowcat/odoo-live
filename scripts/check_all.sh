#!/bin/bash
# Запускає ВСІ scripts/*_check.py підряд, кожен на базі, яку він очікує (див. шапку скрипта).
# Падіння одного не спиняє решту: у кінці один підсумок і ненульовий код, якщо щось провалилось.
#
#   scripts/check_all.sh              усе
#   ALLOW_SKIP=1 scripts/check_all.sh відсутня база дає SKIP, а не провал
#   ONLY=bank,nav scripts/check_all.sh лише названі перевірки
#
# Порт стенду береться з .env цього ж дерева (ODOO_PORT), а не з 8110 сусіднього.
set -uo pipefail
cd "$(dirname "$0")/.."

ALLOW_SKIP="${ALLOW_SKIP:-0}"
ONLY="${ONLY:-}"
FAILED=0
SECONDS=0
declare -a REPORT=()

ODOO_PORT="${ODOO_PORT:-$(grep -E '^ODOO_PORT=' .env | cut -d= -f2 | tr -d '[:space:]')}"
ODOO_PORT="${ODOO_PORT:-8100}"
export ODOO_PORT
export ODOO_URL="${ODOO_URL:-http://127.0.0.1:${ODOO_PORT}}"

# Один запит замість тридцяти: список баз, які реально є в контейнері db.
EXISTING_DBS="$(docker compose exec -T db psql -U odoo -lqt 2>/dev/null | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $1); print $1}')"

db_exists() {
  printf '%s\n' "$EXISTING_DBS" | grep -qx "$1"
}

# $1 = файл скрипта в scripts/, $2 = база яку він очікує ("-" якщо стенд не потрібен),
# далі - змінні середовища для запуску.
run_check() {
  local script="$1" db="$2"; shift 2
  local short="${script%_check.py}"

  if [ -n "$ONLY" ] && ! printf '%s' ",$ONLY," | grep -q ",$short,"; then
    return
  fi

  if [ "$db" != "-" ] && ! db_exists "$db"; then
    REPORT+=("SKIP $(printf '%-22s' "$script") база $db відсутня")
    [ "$ALLOW_SKIP" = "1" ] || FAILED=$((FAILED + 1))
    return
  fi

  local out code started=$SECONDS
  if [ "$#" -gt 0 ]; then
    out="$(env "$@" python3 "scripts/$script" 2>&1)"; code=$?
  else
    out="$(python3 "scripts/$script" 2>&1)"; code=$?
  fi
  local took=$((SECONDS - started))

  local summary
  summary="$(printf '%s\n' "$out" | awk 'NF{line=$0} END{print line}')"
  if [ "$code" -eq 0 ]; then
    REPORT+=("OK   $(printf '%-22s' "$script") ${took}с · $summary")
  else
    REPORT+=("FAIL $(printf '%-22s' "$script") ${took}с · $summary")
    printf '%s\n' "--- $script ---"
    printf '%s\n' "$out" | tail -n 15
    FAILED=$((FAILED + 1))
  fi
}

#          скрипт               база           змінні середовища
run_check layers_check.py       -
run_check advance_check.py      payroll_test   PAYROLL_CHECK_DB=payroll_test
run_check bank_check.py         payroll        PAYROLL_DB=payroll
run_check card_check.py         payroll        PAYROLL_DB=payroll
run_check card_ui_check.py      payroll        PAYROLL_DB=payroll
run_check changes_check.py      payroll_test   PAYROLL_CHECK_DB=payroll_test
run_check checks_check.py       payroll        PAYROLL_DB=payroll
run_check correction_check.py   payroll        PAYROLL_DB=payroll
run_check dashboard_check.py    payroll        PAYROLL_DB=payroll
run_check docs_check.py         payroll        PAYROLL_CHECK_DB=payroll
run_check documents_check.py    payroll        PAYROLL_DB=payroll
run_check explain_check.py      payroll        PAYROLL_DB=payroll
run_check gph_check.py          payroll        PAYROLL_DB=payroll
run_check hire_check.py         payroll        PAYROLL_DB=payroll
run_check home_check.py         payroll        PAYROLL_DB=payroll
run_check import_check.py       payroll        PAYROLL_DB=payroll
run_check kp_check.py           payroll        PAYROLL_DB=payroll
run_check leaves_check.py       payroll        PAYROLL_CHECK_DB=payroll
run_check military_check.py     payroll        PAYROLL_DB=payroll
run_check nav_check.py          payroll        PAYROLL_DB=payroll
run_check orders_check.py       payroll        PAYROLL_DB=payroll
run_check papers_check.py       payroll        PAYROLL_DB=payroll
run_check payments_check.py     payroll        PAYROLL_DB=payroll
run_check payroll_check.py      payroll_test   PAYROLL_CHECK_DB=payroll_test
run_check people_check.py       payroll        PAYROLL_DB=payroll
run_check period_check.py       payroll        PAYROLL_DB=payroll
run_check readonly_check.py     payroll        PAYROLL_DB=payroll
run_check reporting_check.py    payroll        PAYROLL_DB=payroll
run_check setup_check.py        payroll        PAYROLL_DB=payroll
run_check shell_check.py        payroll        PAYROLL_DB=payroll
run_check timesheet_check.py    payroll        PAYROLL_DB=payroll
run_check vacation_check.py     payroll        PAYROLL_DB=payroll

echo
printf '%s\n' "${REPORT[@]}"
echo "Час виконання: ${SECONDS} с, стенд :${ODOO_PORT}"

if [ "$FAILED" -gt 0 ]; then
  echo "Провалено перевірок: $FAILED з ${#REPORT[@]}"
  exit 1
fi
echo "Усі перевірки пройдено (${#REPORT[@]} з ${#REPORT[@]})."
exit 0
