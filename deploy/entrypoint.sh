#!/bin/bash
# Вхідна точка серверного образу (staging і prod на Hetzner).
#
# Робить три речі і не більше:
#   1. складає /tmp/odoo.conf зі статичного deploy/odoo.server.conf і змінних оточення;
#   2. чекає, поки відповість Postgres;
#   3. запускає odoo з цим конфігом, передавши далі всі аргументи.
#
# Бази не створює і модулі не ставить - це робота deploy/deploy.sh. Так разовий контейнер
# (`docker compose run --rm odoo -u модуль --stop-after-init`) поводиться передбачувано.
#
# Аргументи дописуються ПЕРЕД -c, тому працюють обидві форми:
#   odoo -u l10n_ua_vat --stop-after-init -c /tmp/odoo.conf
#   odoo shell -c /tmp/odoo.conf
#
# Змінні: PGHOST PGPORT PGUSER PGPASSWORD DB_NAME DB_FILTER ODOO_WORKERS ODOO_ADMIN_PASSWD
set -eu

CONF=/tmp/odoo.conf
DB_HOST="${PGHOST:-db}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-odoo}"
DB_PASSWORD="${PGPASSWORD:-odoo}"
DB_NAME="${DB_NAME:-odoo}"
DB_FILTER="${DB_FILTER:-^${DB_NAME}\$}"
ODOO_WORKERS="${ODOO_WORKERS:-2}"

cp /etc/odoo/odoo.server.conf "$CONF"
{
    printf 'db_host = %s\n' "$DB_HOST"
    printf 'db_port = %s\n' "$DB_PORT"
    printf 'db_user = %s\n' "$DB_USER"
    printf 'db_password = %s\n' "$DB_PASSWORD"
    printf 'db_name = %s\n' "$DB_NAME"
    printf 'dbfilter = %s\n' "$DB_FILTER"
    printf 'workers = %s\n' "$ODOO_WORKERS"
    [ -n "${ODOO_ADMIN_PASSWD:-}" ] && printf 'admin_passwd = %s\n' "$ODOO_ADMIN_PASSWD"
} >> "$CONF"
chmod 600 "$CONF"

export PGPASSWORD="$DB_PASSWORD"
tries=0
until psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -Atc "select 1" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
        echo "Postgres на $DB_HOST:$DB_PORT не відповів за 3 хвилини" >&2
        exit 1
    fi
    echo "чекаємо Postgres на $DB_HOST:$DB_PORT"
    sleep 3
done

export ODOO_RC="$CONF"

# Три випадки:
#   без аргументів або прапорці  -> odoo <прапорці> -c /tmp/odoo.conf   (сервер, -u, -i)
#   підкоманда odoo              -> odoo shell -c /tmp/odoo.conf        (shell, db, neutralize)
#   будь-що інше                 -> запускаємо як є                     (sh -c "...", psql)
# Третій випадок потрібен scripts/demo_hire.py: він сам збирає рядок `sh -c "odoo shell ..."`.
case "${1:-}" in
    "" | -*) exec odoo "$@" -c "$CONF" ;;
    odoo)
        shift
        exec odoo "$@" -c "$CONF"
        ;;
    shell | start | server | db | neutralize | populate | scaffold | cloc | deploy | upgrade_code | tsconfig)
        exec odoo "$@" -c "$CONF"
        ;;
    *) exec "$@" ;;
esac
