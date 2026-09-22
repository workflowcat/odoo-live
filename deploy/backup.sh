#!/usr/bin/env bash
# Резервні копії баз odoo-live. Запускає cron (див. deploy/server-setup.sh) або руками.
#
#   deploy/backup.sh daily     # жива база prod, тримаємо BACKUP_KEEP_DAILY (типово 14)
#   deploy/backup.sh weekly    # staging, тримаємо BACKUP_KEEP_WEEKLY (типово 4)
#   deploy/backup.sh prod      # те саме, що daily
#   deploy/backup.sh staging   # те саме, що weekly
#
# Формат - pg_dump -Fc (стиснутий, для pg_restore). Вкладення лежать у самій базі
# (ir_attachment.location = db), тому окремо копіювати файлову теку не треба.
#
# Якщо в env-файлі заданий RCLONE_REMOTE (напр. b2:bp-odoo-backups), копія ще й
# відправляється туди через rclone. Без нього копії лишаються лише на сервері.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

case "${1:-daily}" in
    daily | prod) ENV_NAME=prod; KEEP_VAR=BACKUP_KEEP_DAILY; KEEP_DEFAULT=14 ;;
    weekly | staging) ENV_NAME=staging; KEEP_VAR=BACKUP_KEEP_WEEKLY; KEEP_DEFAULT=4 ;;
    *)
        echo "Використання: deploy/backup.sh <daily|weekly|prod|staging>" >&2
        exit 2
        ;;
esac

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
ODOO_DB="${ODOO_DB:?ODOO_DB не заданий у $ENV_FILE}"
KEEP="$(eval echo "\${$KEEP_VAR:-$KEEP_DEFAULT}")"
DIR="$ROOT/deploy/backups/$ENV_NAME"
STAMP="$(date +%Y-%m-%d-%H%M%S)"
OUT="$DIR/auto-$ODOO_DB-$STAMP.dump"
mkdir -p "$DIR"

dc() {
    docker compose --env-file "$ENV_FILE" -p "$PROJECT" \
        -f "$ROOT/deploy/docker-compose.server.yml" \
        -f "$ROOT/deploy/docker-compose.$ENV_NAME.yml" "$@"
}

echo "[$(date +%Y-%m-%d\ %H:%M:%S)] копія $ENV_NAME/$ODOO_DB -> $OUT"
dc exec -T db pg_dump -U "$PG_USER" -Fc -d "$ODOO_DB" >"$OUT"

# Порожній або обрізаний файл - це не копія
SIZE="$(wc -c <"$OUT" | tr -d ' ')"
if [ "$SIZE" -lt 10000 ]; then
    echo "Копія підозріло мала ($SIZE байтів) - лишаємо файл і падаємо" >&2
    exit 1
fi
echo "готово, $(du -h "$OUT" | cut -f1 | tr -d ' ')"

# --- прибирання старих ------------------------------------------------------------------
# рахуємо лише автоматичні копії; ручні (pre-upgrade-*) не чіпаємо
ls -1t "$DIR"/auto-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
    echo "прибираємо $old"
    rm -f "$old"
done

# --- у хмару ----------------------------------------------------------------------------
if [ -n "${RCLONE_REMOTE:-}" ]; then
    if command -v rclone >/dev/null 2>&1; then
        echo "rclone -> $RCLONE_REMOTE/$ENV_NAME/"
        rclone copy "$OUT" "$RCLONE_REMOTE/$ENV_NAME/" --s3-no-check-bucket
        # у віддаленій теці тримаємо стільки ж копій
        rclone lsf "$RCLONE_REMOTE/$ENV_NAME/" --include 'auto-*.dump' |
            sort -r | tail -n +"$((KEEP + 1))" | while read -r old; do
            rclone delete "$RCLONE_REMOTE/$ENV_NAME/$old"
        done
    else
        echo "RCLONE_REMOTE заданий, але rclone не встановлений" >&2
    fi
fi
