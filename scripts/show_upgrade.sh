#!/usr/bin/env bash
# Оновлення показової бази разом з перекладами: те саме, що demo_server.sh upgrade,
# але з --i18n-overwrite, щоб нові uk.po перекрили вже завантажені рядки.
#   DEMO_DB=show DEMO_PORT=8133 scripts/show_upgrade.sh модуль1,модуль2
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
DB="${DEMO_DB:-demo}"; PORT="${DEMO_PORT:-8131}"; NAME="odoo-live-base-$DB"
UPG="${1:?перелік модулів через кому}"
ARGS="--addons-path=/mnt/extra-addons --db_host=db --db_user=odoo --db_password=odoo --max-cron-threads=0"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker compose exec -T db psql -U odoo -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB'" >/dev/null 2>&1 || true
docker compose run --rm --no-deps -T odoo sh -c \
    "pip install -q --break-system-packages pypdf >/dev/null 2>&1; exec odoo $ARGS -d '$DB' --db-filter='.*' -u '$UPG' --i18n-overwrite --stop-after-init --log-level=warn"
docker compose run -d --name "$NAME" -p "127.0.0.1:$PORT:8069" odoo sh -c \
    "pip install -q --break-system-packages pypdf >/dev/null 2>&1; exec odoo $ARGS -d '$DB' --db-filter='^${DB}\$' --workers=0" >/dev/null
for _ in $(seq 1 60); do curl -sf -o /dev/null "http://127.0.0.1:$PORT/web/login" && break; sleep 2; done
echo "Оновлено: $UPG; сервер на http://127.0.0.1:$PORT"
