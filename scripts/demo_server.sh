#!/usr/bin/env bash
# Демо-простір «Ясен Меблі» на окремій базі demo, порт 8131.
#
#   scripts/demo_server.sh            зібрати базу, якщо її немає, і подати на 8131
#   scripts/demo_server.sh stop       зупинити і прибрати контейнер демо
#   scripts/demo_server.sh reset      видалити базу і зібрати заново
#
# База demo окрема від payroll: сусідній стенд на 8130 і теку odoo-live-payroll
# цей скрипт не чіпає. Дані наповнює scripts/demo_business.py після підняття.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB="${DEMO_DB:-demo}"
PORT="${DEMO_PORT:-8131}"
NAME="odoo-live-base-demo"

# Повний набір демо-простору. Решту тягнуть залежності: l10n_ua_home дає зарплату
# і кадри, l10n_ua_assets - account_asset_management, l10n_ua_finrep - mis_builder,
# l10n_ua_nbu - currency_rate_update, l10n_ua_ledger - account_financial_report.
MODULES="l10n_ua_home,l10n_ua_papers,l10n_ua_explain,l10n_ua_chart,l10n_ua_vat,l10n_ua_cash,l10n_ua_ledger,l10n_ua_finrep,l10n_ua_assets,l10n_ua_nbu,l10n_ua_docs,l10n_ua_migrate,l10n_ua_partner_edr,account_payment_order,sale_management,purchase,stock,mrp,crm,contacts,auditlog,hr_employee_document"

ODOO_ARGS="--addons-path=/mnt/extra-addons --db_host=db --db_user=odoo --db_password=odoo --max-cron-threads=0"

PROJECT="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
if [ "$PROJECT" != "odoo-live-base" ]; then
    echo "Несподіваний проєкт docker compose: $PROJECT (очікували odoo-live-base)" >&2
    exit 2
fi

ADMIN_PW="$(python3 - <<'PY'
env = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
print(env["ODOO_ADMIN_USER_PASSWORD"].strip())
PY
)"

db_exists() {
    docker compose exec -T db psql -U odoo -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='$DB'" 2>/dev/null | grep -q 1
}

stop_container() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
}

# Підготовка компанії: країна Україна, план ua_psbo, пароль і мова адміністратора.
# Короткі коди рахунків, українські назви, правила звірки, профілі активів, групи ПДВ
# і журнал каси навішують самі модулі на завантаження плану (_post_load_data), тому
# доганяти хуки тут більше не треба. Рецепт - той самий, що в
# addons/l10n_ua_payroll_tests/tests/test_golden.py (setUpClass).
prepare_company() {
    docker compose run --rm --no-deps -T odoo sh -c \
        "exec odoo shell $ODOO_ARGS -d '$DB' --db-filter='.*' --log-level=warn" <<PY
company = env.company
company.country_id = env.ref("base.ua")
if company.chart_template != "ua_psbo":
    env["account.chart.template"].try_loading("ua_psbo", company, install_demo=False)
company.invalidate_recordset()
env["account.account"].invalidate_model(["code"])
admin = env.ref("base.user_admin")
admin.password = """$ADMIN_PW"""
admin.lang = "uk_UA"
admin.partner_id.lang = "uk_UA"
env.cr.commit()
print("ПІДГОТОВКА: план", company.chart_template, "країна", company.country_id.code)
PY
}

build_db() {
    echo "== піднімаємо базу даних =="
    docker compose up -d --wait db
    echo "== створюємо базу $DB =="
    docker compose exec -T db createdb -U odoo -O odoo "$DB"
    echo "== ставимо модулі (це довго) =="
    docker compose run --rm --no-deps -T odoo sh -c \
        "pip install -q --break-system-packages pypdf >/dev/null 2>&1; exec odoo $ODOO_ARGS -d '$DB' --db-filter='.*' -i '$MODULES' --without-demo=all --stop-after-init --log-level=warn"
    echo "== країна, план рахунків, адміністратор =="
    prepare_company
}

case "${1:-start}" in
    stop)
        stop_container
        echo "Демо зупинено ($NAME прибрано). База $DB на місці."
        exit 0
        ;;
    reset)
        stop_container
        docker compose up -d --wait db
        # контейнер прибрано, але з'єднання Postgres ще можуть добігати - закриваємо їх
        docker compose exec -T db psql -U odoo -d postgres -c \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB'" >/dev/null 2>&1 || true
        docker compose exec -T db dropdb -U odoo --if-exists "$DB"
        echo "Базу $DB видалено."
        build_db
        ;;
    start)
        docker compose up -d --wait db
        if db_exists; then
            echo "База $DB уже є - ставимо лише сервер."
        else
            build_db
        fi
        ;;
    *)
        echo "Невідома команда: $1 (start | stop | reset)" >&2
        exit 2
        ;;
esac

stop_container
docker compose run -d --name "$NAME" -p "127.0.0.1:$PORT:8069" odoo sh -c \
    "pip install -q --break-system-packages pypdf >/dev/null 2>&1; exec odoo $ODOO_ARGS -d '$DB' --db-filter='^${DB}\$' --workers=0" >/dev/null

# чекаємо, поки веб відповість
for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "http://127.0.0.1:$PORT/web/login"; then
        break
    fi
    sleep 2
done

echo
echo "Демо: http://127.0.0.1:$PORT  (база $DB, логін admin, пароль - ODOO_ADMIN_USER_PASSWORD з .env)"
echo "Наповнення даними: python3 scripts/demo_business.py"
echo "Зупинити: scripts/demo_server.sh stop"
