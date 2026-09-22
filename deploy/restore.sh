#!/usr/bin/env bash
# Відновлення бази з копії pg_dump -Fc.
#
#   deploy/restore.sh staging deploy/backups/prod/auto-odoo-2026-09-30-002000.dump
#   deploy/restore.sh staging <файл> --db stage_prodcopy          # копія prod для репетиції
#   deploy/restore.sh prod <файл> --yes                           # відкат живої бази
#
# Прапорці:
#   --db NAME   куди відновлювати (типово ODOO_DB з env-файлу)
#   --yes       не питати підтвердження (для prod питає завжди, поки не заданий)
#   --upgrade   після відновлення прогнати `odoo -u <наші модулі> --stop-after-init`
#   --latest    замість файлу взяти найсвіжішу копію того оточення, з якого відновлюємо
#
# Odoo на час відновлення зупиняється і піднімається назад у кінці.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_NAME="${1:-}"
case "$ENV_NAME" in
    staging | prod) shift ;;
    *)
        echo "Використання: deploy/restore.sh <staging|prod> <файл.dump|--latest> [прапорці]" >&2
        exit 2
        ;;
esac

DUMP=""
TARGET_DB=""
ASSUME_YES=0
DO_UPGRADE=0
USE_LATEST=0
while [ $# -gt 0 ]; do
    case "$1" in
        --db)
            shift
            TARGET_DB="$1"
            ;;
        --yes) ASSUME_YES=1 ;;
        --upgrade) DO_UPGRADE=1 ;;
        --latest) USE_LATEST=1 ;;
        -*)
            echo "Невідомий прапорець: $1" >&2
            exit 2
            ;;
        *) DUMP="$1" ;;
    esac
    shift
done

ENV_FILE="$ROOT/deploy/env.$ENV_NAME"
[ -f "$ENV_FILE" ] || {
    echo "Немає $ENV_FILE" >&2
    exit 2
}

eval "$(python3 - "$ENV_FILE" <<'PY'
import shlex, sys
for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key, value = key.strip(), value.strip()
    if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) > 1:
        value = value[1:-1]
    else:
        cut = value.find(" #")
        if cut >= 0:
            value = value[:cut].rstrip()
    print("export %s=%s" % (key, shlex.quote(value)))
PY
)"

PROJECT="${COMPOSE_PROJECT_NAME:-odoo-$ENV_NAME}"
PG_USER="${PG_USER:-odoo}"
TARGET_DB="${TARGET_DB:-${ODOO_DB:?ODOO_DB не заданий у $ENV_FILE}}"

if [ "$USE_LATEST" = "1" ]; then
    DUMP="$(ls -1t "$ROOT/deploy/backups/$ENV_NAME/"*.dump 2>/dev/null | head -1 || true)"
fi
[ -n "$DUMP" ] && [ -f "$DUMP" ] || {
    echo "Немає файлу копії (задайте шлях або --latest)" >&2
    exit 2
}

dc() {
    docker compose --env-file "$ENV_FILE" -p "$PROJECT" \
        -f "$ROOT/deploy/docker-compose.server.yml" \
        -f "$ROOT/deploy/docker-compose.$ENV_NAME.yml" "$@"
}

echo "Відновлення: $DUMP -> $ENV_NAME/$TARGET_DB (проєкт $PROJECT)"
echo "База $TARGET_DB буде видалена і створена заново."
if [ "$ASSUME_YES" != "1" ]; then
    printf 'Писати "так" для продовження: '
    read -r answer
    [ "$answer" = "так" ] || {
        echo "Скасовано."
        exit 1
    }
fi

dc up -d --wait db

if [ "$TARGET_DB" = "${ODOO_DB:-}" ]; then
    echo "== зупиняємо Odoo =="
    dc stop odoo || true
fi

echo "== скидаємо базу $TARGET_DB =="
dc exec -T db psql -U "$PG_USER" -d postgres -Atc \
    "select pg_terminate_backend(pid) from pg_stat_activity where datname='$TARGET_DB'" >/dev/null 2>&1 || true
dc exec -T db dropdb -U "$PG_USER" --if-exists "$TARGET_DB"
dc exec -T db createdb -U "$PG_USER" -O "$PG_USER" "$TARGET_DB"

echo "== pg_restore =="
# --no-owner --no-acl: копія могла бути зроблена під іншим користувачем
dc exec -T db pg_restore -U "$PG_USER" -d "$TARGET_DB" --no-owner --no-acl <"$DUMP" || true
TABLES="$(dc exec -T db psql -U "$PG_USER" -d "$TARGET_DB" -Atc \
    "select count(*) from information_schema.tables where table_schema='public'")"
echo "таблиць у public: $TABLES"
[ "${TABLES:-0}" -gt 100 ] || {
    echo "Схоже, відновлення не вдалося (таблиць $TABLES)" >&2
    exit 1
}

if [ "$DO_UPGRADE" = "1" ]; then
    echo "== оновлення модулів =="
    INSTALLED="$(dc exec -T db psql -U "$PG_USER" -d "$TARGET_DB" -Atc \
        "select name from ir_module_module where state='installed'" || true)"
    MODULES="$(printf '%s\n' "$INSTALLED" | python3 -c '
import os, sys
root = sys.argv[1]
here = {d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, "__manifest__.py"))}
got = {line.strip() for line in sys.stdin if line.strip()}
names = sorted(here & got)
print(",".join(names) if names else "all")
' "$ROOT/addons")"
    echo "оновлюємо: $MODULES"
    dc run --rm --no-deps -T odoo -d "$TARGET_DB" -u "$MODULES" \
        --stop-after-init --max-cron-threads=0 --log-level=warn
fi

if [ "$TARGET_DB" = "${ODOO_DB:-}" ]; then
    echo "== піднімаємо Odoo =="
    dc up -d odoo
    for _ in $(seq 1 60); do
        curl -sf -o /dev/null --max-time 5 "http://127.0.0.1:${ODOO_HTTP_PORT}/web/login" && break
        sleep 2
    done
    curl -s -o /dev/null -w 'перевірка /web/login: %{http_code}\n' "http://127.0.0.1:${ODOO_HTTP_PORT}/web/login"
fi

echo "Готово: $TARGET_DB відновлено з $(basename "$DUMP")"
