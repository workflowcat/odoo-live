#!/usr/bin/env bash
# Демо-простір «Ясен Меблі» на окремій базі demo, порт 8131.
#
#   scripts/demo_server.sh            зібрати базу, якщо її немає, і подати на 8131
#   scripts/demo_server.sh stop       зупинити і прибрати контейнер демо
#   scripts/demo_server.sh reset      видалити базу і зібрати заново
#   scripts/demo_server.sh upgrade [модулі]   оновити модулі в наявній базі
#                                     (типово - усі з MODULES) і подати знову
#
# База і порт беруться зі змінних DEMO_DB і DEMO_PORT, ім'я контейнера - з бази.
# Так поруч із робочим демо можна зібрати чернетку, нічого не зачепивши:
#
#   DEMO_DB=demo2 DEMO_PORT=8132 scripts/demo_server.sh reset
#   DEMO_DB=demo2 ODOO_URL=http://127.0.0.1:8132 python3 scripts/demo_business.py
#   DEMO_DB=demo2 DEMO_PORT=8132 scripts/demo_server.sh stop
#
# База demo окрема від payroll: сусідній стенд на 8130 і теку odoo-live-payroll
# цей скрипт не чіпає. Дані наповнює scripts/demo_business.py після підняття.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB="${DEMO_DB:-demo}"
PORT="${DEMO_PORT:-8131}"
NAME="odoo-live-base-$DB"

# Повний набір демо-простору. Увесь наш продукт тягне один модуль l10n_ua_navigation
# (меню над стандартними поданнями); решта - рідні застосунки Odoo для демонстрації
# продажів, складу і виробництва. Останній рядок - закупівлі, виробництво, склад,
# група компаній і податок на прибуток: їхні залежності (purchase_request,
# account_invoice_inter_company, mis_builder, mrp_account) Odoo тягне сам.
MODULES="l10n_ua_navigation,sale_management,purchase,stock,mrp,crm,auditlog"
MODULES="$MODULES,purchase_request,l10n_ua_purchase,l10n_ua_mrp,l10n_ua_stock_docs"
MODULES="$MODULES,l10n_ua_group,l10n_ua_profit_tax"

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
# Час на екрані - київський (запит ui -> core 2026-09-24-001); ім'я - не англійське.
env["res.users"].with_context(active_test=False).search([]).write({"tz": "Europe/Kyiv"})
admin.partner_id.name = "Адміністратор"
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
    upgrade)
        # Оновлення коду модулів у наявній базі: нові поля з'являються в схемі
        # без перезбирання всього кварталу. Без аргументу оновлюємо весь набір.
        UPG="${2:-$MODULES}"
        if ! db_exists; then
            echo "Бази $DB немає - спершу scripts/demo_server.sh reset" >&2
            exit 2
        fi
        stop_container
        docker compose exec -T db psql -U odoo -d postgres -c \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB'" >/dev/null 2>&1 || true
        echo "== оновлюємо модулі: $UPG =="
        docker compose run --rm --no-deps -T odoo sh -c \
            "pip install -q --break-system-packages pypdf >/dev/null 2>&1; exec odoo $ODOO_ARGS -d '$DB' --db-filter='.*' -u '$UPG' --stop-after-init --log-level=warn"
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
echo "Наповнення даними: DEMO_DB=$DB ODOO_URL=http://127.0.0.1:$PORT python3 scripts/demo_business.py"
echo "Зупинити: DEMO_DB=$DB scripts/demo_server.sh stop"
