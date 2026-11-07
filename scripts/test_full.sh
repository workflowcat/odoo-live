#!/usr/bin/env bash
# Everything CI runs on a fresh database: every module through l10n_ua_navigation,
# every test tag, then a clean full install. Same as .github/workflows/tests.yml.
#
#   scripts/test_full.sh            all tags
#   KEEP_DB=1 scripts/test_full.sh  keep the test database after a failure
set -euo pipefail
cd "$(dirname "$0")/.."

TAGS="ua_golden,ua_leaves,ua_payments,ua_regress,ua_changes,ua_period,ua_checks,ua_hire,ua_reporting"
TAGS="$TAGS,ua_setup,ua_bank,ua_card,ua_documents,ua_api,ua_vat,ua_cash,ua_ledger,ua_finrep,ua_assets"
TAGS="$TAGS,ua_nbu,ua_fop,ua_migrate,ua_edr,ua_docs,ua_security,ua_demo_costing,ua_group,ua_mrp"
TAGS="$TAGS,ua_profit,ua_purchase,ua_stock_docs,bp_purchase_intake,ua_contract,ua_defense,ua_dk021,ua_catalog,ua_customs,ua_bank_1c,ua_close,ua_tolling,ua_payment_request,ua_correspondence,ua_prro,ua_price_label,ua_eco,ua_claim,ua_military,ua_edo,ua_proc_plan,ua_unit_transfer,ua_offset,ua_commission,ua_fleet,ua_mrp_plan,ua_piecework"

TEST_MODULES=l10n_ua_navigation,l10n_ua_payroll_tests TEST_TAGS="$TAGS" ./scripts/test.sh

echo "== full install of l10n_ua_navigation on an empty database =="
DB="fresh_$$"
trap 'docker compose exec -T db dropdb -U odoo --force --if-exists "$DB" >/dev/null 2>&1 || true' EXIT
docker compose exec -T db createdb -U odoo -O odoo "$DB"
LOG="$(mktemp "${TMPDIR:-/tmp}/odoo_install.XXXXXX")"
docker compose run --rm --no-deps -T odoo sh -c "pip install --break-system-packages pypdf >/dev/null 2>&1; \
    odoo --addons-path=/mnt/extra-addons --db_host=db --db_user=odoo --db_password=odoo --database=$DB \
    --db-filter='.*' --init=l10n_ua_navigation --without-demo=True --stop-after-init --max-cron-threads=0" \
    >"$LOG" 2>&1 || true
grep -E 'modules loaded|ERROR|CRITICAL' "$LOG" | grep -v 'Unexpected indentation' | tail -5
if grep -E ' (ERROR|CRITICAL) ' "$LOG" | grep -v 'Unexpected indentation' | grep -q .; then
    echo "FULL INSTALL: FAIL (log: $LOG)"
    exit 1
fi
rm -f "$LOG"
echo "FULL INSTALL: PASS"
