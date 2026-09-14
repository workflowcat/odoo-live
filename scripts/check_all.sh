#!/bin/bash
# Запускає всі чотири перевірки стенду payroll підряд, кожну на базі, яку вона очікує:
# hire_check і docs_check -> payroll; payroll_check і advance_check -> payroll_test.
# ALLOW_SKIP=1 -> відсутня база дає SKIP, але не рахується як провал.
set -uo pipefail
cd "$(dirname "$0")/.."

ALLOW_SKIP="${ALLOW_SKIP:-0}"
FAILED=0
SECONDS=0

# Один запит замість чотирьох: список баз, які реально є в контейнері db.
EXISTING_DBS="$(docker compose exec -T db psql -U odoo -lqt 2>/dev/null | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $1); print $1}')"

db_exists() {
  printf '%s\n' "$EXISTING_DBS" | grep -qx "$1"
}

run_check() {
  # $1 = файл скрипта в scripts/, $2 = база яку він очікує, $3 = "ЗМІННА=значення" (необов'язково)
  local script="$1" db="$2" envvar="${3:-}"

  if ! db_exists "$db"; then
    echo "SKIP $script · база $db відсутня"
    [ "$ALLOW_SKIP" = "1" ] || FAILED=$((FAILED + 1))
    return
  fi

  local out
  if [ -n "$envvar" ]; then
    out="$(env "$envvar" python3 "scripts/$script" 2>&1)"
  else
    out="$(python3 "scripts/$script" 2>&1)"
  fi
  local code=$?

  if [ "$code" -eq 0 ]; then
    local summary
    summary="$(printf '%s\n' "$out" | awk 'NF{line=$0} END{print line}')"
    echo "OK  $script · $summary"
  else
    echo "FAIL $script"
    printf '%s\n' "$out" | tail -n 15
    FAILED=$((FAILED + 1))
  fi
}

run_check hire_check.py    payroll      PAYROLL_DB=payroll
run_check docs_check.py    payroll
run_check payroll_check.py payroll_test PAYROLL_CHECK_DB=payroll_test
run_check advance_check.py payroll_test PAYROLL_CHECK_DB=payroll_test

echo "Час виконання: ${SECONDS} с"

if [ "$FAILED" -gt 0 ]; then
  exit 1
fi
exit 0
