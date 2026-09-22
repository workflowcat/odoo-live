#!/usr/bin/env bash
# Розгортання odoo-live на сервері: deploy.sh <staging|prod> [git-ref] [прапорці]
#
#   deploy/deploy.sh staging                 # main, свіже демо, тунель уже стоїть
#   deploy/deploy.sh staging v1.4.0 --with-prod-copy
#   deploy/deploy.sh prod v1.4.0             # лише з тега; перед оновленням - pg_dump
#
# Прапорці:
#   --no-pull            не чіпати git, узяти робочу теку як є (відкат, локальна перевірка)
#   --no-tunnel          не піднімати cloudflared
#   --no-demo            staging: не наливати демо-дані (лише база і модулі)
#   --with-prod-copy     staging: підняти свіжу копію prod у базі stage_prodcopy і оновити її
#   --project NAME       інша назва проєкту docker compose (разова перевірка)
#   --env-file PATH      інший env-файл (типово deploy/env.<оточення>)
#   --keep-going         не падати на першій невдачі, дійти до підсумку
#
# Різниця між оточеннями:
#   staging - база завжди з нуля: drop, create, встановлення модулів, демо-дані.
#   prod    - база жива: pg_dump, `odoo -u <наші модулі> --stop-after-init`, перезапуск.
#
# Скрипт писаний під bash 3.2 (macOS) і bash 5 (Ubuntu): без асоціативних масивів.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_NAME="${1:-}"
case "$ENV_NAME" in
    staging | prod) shift ;;
    *)
        echo "Використання: deploy/deploy.sh <staging|prod> [git-ref] [прапорці]" >&2
        exit 2
        ;;
esac

GIT_REF=""
DO_PULL=1
DO_TUNNEL=1
DO_DEMO=1
WITH_PROD_COPY=0
KEEP_GOING=0
PROJECT_OVERRIDE=""
ENV_FILE="$ROOT/deploy/env.$ENV_NAME"

while [ $# -gt 0 ]; do
    case "$1" in
        --no-pull) DO_PULL=0 ;;
        --no-tunnel) DO_TUNNEL=0 ;;
        --no-demo) DO_DEMO=0 ;;
        --with-prod-copy) WITH_PROD_COPY=1 ;;
        --keep-going) KEEP_GOING=1 ;;
        --project)
            shift
            PROJECT_OVERRIDE="$1"
            ;;
        --env-file)
            shift
            ENV_FILE="$1"
            ;;
        -*)
            echo "Невідомий прапорець: $1" >&2
            exit 2
            ;;
        *) GIT_REF="$1" ;;
    esac
    shift
done

[ -f "$ENV_FILE" ] || {
    echo "Немає файлу оточення $ENV_FILE (зразок: deploy/env.$ENV_NAME.example)" >&2
    exit 2
}

# --- env-файл читаємо тим самим правилом, що й docker compose --env-file ----------------
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

PROJECT="${PROJECT_OVERRIDE:-${COMPOSE_PROJECT_NAME:-odoo-$ENV_NAME}}"
PG_USER="${PG_USER:-odoo}"
ODOO_DB="${ODOO_DB:?ODOO_DB не заданий у $ENV_FILE}"
ODOO_HTTP_PORT="${ODOO_HTTP_PORT:?ODOO_HTTP_PORT не заданий у $ENV_FILE}"
EDGE_NETWORK="${EDGE_NETWORK:-odoo-edge}"
ODOO_IMAGE="${ODOO_IMAGE:-odoo-live-server}"
BACKUP_DIR="$ROOT/deploy/backups/$ENV_NAME"
PRODCOPY_DB="stage_prodcopy"
STAMP="$(date +%Y-%m-%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Увесь продукт тягне один модуль. Демо-простір додає рідні застосунки Odoo
# (той самий набір, що в scripts/demo_server.sh).
PROD_MODULES="l10n_ua_navigation"
DEMO_MODULES="l10n_ua_navigation,sale_management,purchase,stock,mrp,crm,auditlog"

STEPS=""
PROBLEMS=""
PROBLEM_COUNT=0
STEP_NAME=""
STEP_AT=$SECONDS
START_ALL=$SECONDS
BACKUP_FILE=""
SMOKE_LINE=""
DEMO_LINE=""
PRODCOPY_LINE=""

step() {
    STEP_NAME="$1"
    STEP_AT=$SECONDS
    echo
    echo "== $1 =="
}

done_step() { # час першим: українські назви кроків різної довжини в байтах, колонка б поїхала
    STEPS="$STEPS$(printf '  %5d с   %s' "$((SECONDS - STEP_AT))" "$STEP_NAME")
"
}

summary() {
    echo
    echo "========================================================================"
    echo "ДЕПЛОЙ $ENV_NAME ($PROJECT), образ $ODOO_IMAGE:${IMAGE_TAG:-?}"
    echo "коміт: ${DEPLOYED_REF:-робоча тека} ${DEPLOYED_SHA:-}"
    echo "------------------------------------------------------------------------"
    printf '%s' "$STEPS"
    echo "------------------------------------------------------------------------"
    echo "  база: $ODOO_DB   порт: 127.0.0.1:$ODOO_HTTP_PORT   тунель: $([ "$DO_TUNNEL" = 1 ] && echo так || echo ні)"
    [ -n "$BACKUP_FILE" ] && echo "  копія перед оновленням: $BACKUP_FILE"
    [ -n "$SMOKE_LINE" ] && echo "  $SMOKE_LINE"
    [ -n "$DEMO_LINE" ] && echo "  $DEMO_LINE"
    [ -n "$PRODCOPY_LINE" ] && echo "  $PRODCOPY_LINE"
    echo "  разом: $((SECONDS - START_ALL)) с"
    if [ "$PROBLEM_COUNT" -gt 0 ]; then
        echo "------------------------------------------------------------------------"
        printf '%s' "$PROBLEMS"
        echo "РЕЗУЛЬТАТ: FAIL"
    else
        echo "РЕЗУЛЬТАТ: OK"
    fi
    echo "========================================================================"
}

fail() {
    PROBLEM_COUNT=$((PROBLEM_COUNT + 1))
    PROBLEMS="$PROBLEMS  ПРОБЛЕМА: $1
"
    echo "ПРОБЛЕМА: $1" >&2
    if [ "$KEEP_GOING" = "0" ]; then
        summary
        exit 1
    fi
}

dc() {
    docker compose --env-file "$ENV_FILE" -p "$PROJECT" \
        -f "$ROOT/deploy/docker-compose.server.yml" \
        -f "$ROOT/deploy/docker-compose.$ENV_NAME.yml" "$@"
}

psql_db() { # psql_db <база> <запит>
    dc exec -T db psql -U "$PG_USER" -d "$1" -Atc "$2"
}

db_exists() {
    [ "$(psql_db postgres "select 1 from pg_database where datname='$1'" 2>/dev/null || true)" = "1" ]
}

drop_db() {
    psql_db postgres "select pg_terminate_backend(pid) from pg_stat_activity where datname='$1'" >/dev/null 2>&1 || true
    dc exec -T db dropdb -U "$PG_USER" --if-exists "$1"
}

create_db() {
    dc exec -T db createdb -U "$PG_USER" -O "$PG_USER" "$1"
}

odoo_run() { # разовий контейнер Odoo проти того самого Postgres
    dc run --rm --no-deps -T odoo "$@"
}

dump_db() { # dump_db <база> <позначка>, друкує шлях
    local db="$1" tag="$2" out
    out="$BACKUP_DIR/${tag}-${db}-${STAMP}.dump"
    dc exec -T db pg_dump -U "$PG_USER" -Fc -d "$db" >"$out"
    echo "$out"
}

our_modules() { # our_modules <база>: встановлені модулі, які лежать у addons/ цього репозиторію
    local installed
    installed="$(psql_db "$1" "select name from ir_module_module where state='installed'" 2>/dev/null || true)"
    if [ -z "$installed" ]; then
        echo "all"
        return
    fi
    printf '%s\n' "$installed" | python3 -c '
import os, sys
root = sys.argv[1]
here = {d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, "__manifest__.py"))}
installed = {line.strip() for line in sys.stdin if line.strip()}
names = sorted(here & installed)
print(",".join(names) if names else "all")
' "$ROOT/addons"
}

wait_http() {
    local url="http://127.0.0.1:$ODOO_HTTP_PORT/web/login"
    for _ in $(seq 1 90); do
        if curl -sf -o /dev/null --max-time 5 "$url"; then return 0; fi
        sleep 2
    done
    return 1
}

smoke() {
    local url="http://127.0.0.1:$ODOO_HTTP_PORT" code ver
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url/web/login" || true)"
    if [ "$code" != "200" ]; then
        fail "/web/login відповів $code, очікували 200"
        return 1
    fi
    ver="$(curl -s --max-time 20 -H 'Content-Type: application/json' \
        -d '{"jsonrpc":"2.0","method":"call","params":{"service":"common","method":"version","args":[]},"id":1}' \
        "$url/jsonrpc" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["server_version"])' 2>/dev/null || true)"
    if [ -z "$ver" ]; then
        fail "JSON-RPC common.version не відповів"
        return 1
    fi
    SMOKE_LINE="перевірка: /web/login 200, JSON-RPC version $ver"
    echo "$SMOKE_LINE"
}

prepare_db() { # країна, план рахунків, пароль і мова адміністратора, вкладення в базі
    odoo_run shell -d "$1" --no-http --log-level=warn <<PY
company = env.company
company.country_id = env.ref("base.ua")
if company.chart_template != "ua_psbo":
    env["account.chart.template"].try_loading("ua_psbo", company, install_demo=False)
company.invalidate_recordset()
env["account.account"].invalidate_model(["code"])
admin = env.ref("base.user_admin")
admin.password = """${ODOO_ADMIN_USER_PASSWORD:-admin}"""
admin.lang = "uk_UA"
admin.partner_id.lang = "uk_UA"
env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "db")
env["ir.attachment"].sudo().force_storage()
env.cr.commit()
print("ПІДГОТОВКА:", company.chart_template, company.country_id.code)
PY
}

neutralize_db() { # копія prod на staging: без крону, без пошти, без токена моста
    odoo_run shell -d "$1" --no-http --log-level=warn <<'PY'
env["ir.cron"].sudo().search([]).write({"active": False})
env["ir.mail_server"].sudo().search([]).unlink()
env["ir.config_parameter"].sudo().set_param("bp_bridge.token", "")
env.cr.commit()
print("КОПІЮ ЗНЕШКОДЖЕНО: крони вимкнено, поштові сервери прибрано")
PY
}

sync_root_env() { # scripts/demo_*.py читають ODOO_ADMIN_USER_PASSWORD з .env у корені
    local have
    if [ ! -f "$ROOT/.env" ]; then
        printf 'ODOO_ADMIN_USER_LOGIN=%s\nODOO_ADMIN_USER_PASSWORD=%s\n' \
            "${ODOO_ADMIN_USER_LOGIN:-admin}" "${ODOO_ADMIN_USER_PASSWORD:-}" >"$ROOT/.env"
        chmod 600 "$ROOT/.env"
        echo ".env у корені створено для scripts/demo_*.py"
        return
    fi
    have="$(python3 -c '
import sys
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line.startswith("ODOO_ADMIN_USER_PASSWORD="):
        print(line.split("=", 1)[1].strip())
        break
' "$ROOT/.env")"
    if [ -n "$have" ] && [ "$have" != "${ODOO_ADMIN_USER_PASSWORD:-}" ]; then
        echo "УВАГА: .env у корені має інший ODOO_ADMIN_USER_PASSWORD; беремо його - його читають demo-скрипти"
        ODOO_ADMIN_USER_PASSWORD="$have"
    fi
}

# --- 1. код ----------------------------------------------------------------------------
step "код"
if [ "$DO_PULL" = "1" ]; then
    REF="${GIT_REF:-main}"
    git fetch --tags --prune origin
    if [ "$ENV_NAME" = "prod" ] && ! git rev-parse -q --verify "refs/tags/$REF" >/dev/null; then
        echo "УВАГА: prod розгортається з $REF, а не з тега vX.Y.Z"
    fi
    git checkout -q --detach "$(git rev-parse --verify "origin/$REF" 2>/dev/null || git rev-parse --verify "$REF")"
    DEPLOYED_REF="$REF"
else
    DEPLOYED_REF="робоча тека"
fi
DEPLOYED_SHA="$(git rev-parse --short HEAD)"
# Тег образу: типово короткий sha коміту. Закріплений тег в env-файлі (відкат) не перезбираємо,
# якщо такий образ уже є на машині.
NEED_BUILD=1
case "${IMAGE_TAG:-}" in
    "" | current | auto) IMAGE_TAG="$DEPLOYED_SHA" ;;
    *)
        if docker image inspect "$ODOO_IMAGE:$IMAGE_TAG" >/dev/null 2>&1; then
            NEED_BUILD=0
            echo "закріплений образ $ODOO_IMAGE:$IMAGE_TAG уже є - збірку пропускаємо"
        fi
        ;;
esac
export IMAGE_TAG
echo "$DEPLOYED_REF $DEPLOYED_SHA, тег образу $IMAGE_TAG"
done_step

# --- 2. мережа і тунель ----------------------------------------------------------------
step "мережа і тунель"
docker network inspect "$EDGE_NETWORK" >/dev/null 2>&1 || docker network create "$EDGE_NETWORK" >/dev/null
echo "мережа $EDGE_NETWORK на місці"
if [ "$DO_TUNNEL" = "1" ]; then
    if [ -f "$ROOT/deploy/env.tunnel" ]; then
        docker compose --env-file "$ROOT/deploy/env.tunnel" -p odoo-tunnel \
            -f "$ROOT/deploy/docker-compose.tunnel.yml" up -d
    else
        echo "УВАГА: немає deploy/env.tunnel, cloudflared не піднімаємо"
    fi
fi
done_step

# --- 3. образ --------------------------------------------------------------------------
step "збірка образу"
if [ "$NEED_BUILD" = "1" ]; then
    dc build odoo
else
    echo "пропущено"
fi
done_step

# --- 4. Postgres -----------------------------------------------------------------------
step "Postgres"
dc up -d --wait db
done_step

# --- 5. база і модулі ------------------------------------------------------------------
if [ "$ENV_NAME" = "staging" ]; then
    # звіряємо пароль адміністратора з .env у корені ДО підготовки бази: далі demo-скрипти
    # заходять саме з ним
    [ "$DO_DEMO" = "1" ] && sync_root_env

    step "база $ODOO_DB з нуля"
    if db_exists "$ODOO_DB"; then drop_db "$ODOO_DB"; fi
    create_db "$ODOO_DB"
    done_step

    step "встановлення модулів (довго)"
    odoo_run -d "$ODOO_DB" -i "$DEMO_MODULES" --load-language=uk_UA \
        --stop-after-init --max-cron-threads=0 --log-level=warn || fail "встановлення модулів впало"
    done_step

    step "країна, план рахунків, адміністратор"
    prepare_db "$ODOO_DB" || fail "підготовка бази впала"
    done_step
elif db_exists "$ODOO_DB"; then
    step "копія бази перед оновленням"
    BACKUP_FILE="$(dump_db "$ODOO_DB" pre-upgrade)"
    echo "$BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1 | tr -d ' '))"
    done_step

    step "оновлення модулів"
    UPDATE_MODULES="$(our_modules "$ODOO_DB")"
    echo "оновлюємо: $UPDATE_MODULES"
    odoo_run -d "$ODOO_DB" -u "$UPDATE_MODULES" --i18n-overwrite \
        --stop-after-init --max-cron-threads=0 --log-level=warn || fail "оновлення модулів впало"
    done_step
else
    step "перший запуск: база $ODOO_DB"
    create_db "$ODOO_DB"
    odoo_run -d "$ODOO_DB" -i "$PROD_MODULES" --load-language=uk_UA \
        --stop-after-init --max-cron-threads=0 --log-level=warn || fail "встановлення модулів впало"
    prepare_db "$ODOO_DB" || fail "підготовка бази впала"
    done_step
fi

# --- 6. сервер -------------------------------------------------------------------------
step "перезапуск Odoo"
dc up -d --force-recreate odoo
wait_http || fail "Odoo не відповів на 127.0.0.1:$ODOO_HTTP_PORT"
done_step

step "перевірка"
smoke || true
done_step

# --- 7. демо-дані (лише staging) -------------------------------------------------------
if [ "$ENV_NAME" = "staging" ] && [ "$DO_DEMO" = "1" ] && [ "$PROBLEM_COUNT" -eq 0 ]; then
    step "демо-дані (scripts/demo_business.py)"
    DEMO_LOG="$BACKUP_DIR/demo-$STAMP.log"
    # scripts/demo_hire.py сам смикає `docker compose run odoo shell`, тому показуємо йому
    # наші файли і наш проєкт, інакше він піде в стенд розробки, якого на сервері немає
    if COMPOSE_FILE="$ROOT/deploy/docker-compose.server.yml:$ROOT/deploy/docker-compose.$ENV_NAME.yml" \
        COMPOSE_PROJECT_NAME="$PROJECT" \
        ODOO_URL="http://127.0.0.1:$ODOO_HTTP_PORT" DEMO_DB="$ODOO_DB" \
        python3 "$ROOT/scripts/demo_business.py" >"$DEMO_LOG" 2>&1; then
        DEMO_LINE="демо-дані залито, лог $DEMO_LOG"
    else
        tail -30 "$DEMO_LOG" >&2
        fail "demo_business.py впав, лог: $DEMO_LOG"
    fi
    done_step
fi

# --- 8. репетиція міграції на копії prod ------------------------------------------------
if [ "$ENV_NAME" = "staging" ] && [ "$WITH_PROD_COPY" = "1" ]; then
    step "копія prod у $PRODCOPY_DB"
    LATEST="$(ls -1t "$ROOT/deploy/backups/prod/"*.dump 2>/dev/null | head -1 || true)"
    if [ -z "$LATEST" ]; then
        fail "немає жодної копії prod у deploy/backups/prod/"
    else
        echo "беремо $LATEST"
        drop_db "$PRODCOPY_DB"
        create_db "$PRODCOPY_DB"
        dc exec -T db pg_restore -U "$PG_USER" -d "$PRODCOPY_DB" --no-owner --no-acl <"$LATEST" || true
        COPY_MODULES="$(our_modules "$PRODCOPY_DB")"
        echo "оновлюємо на копії: $COPY_MODULES"
        if odoo_run -d "$PRODCOPY_DB" -u "$COPY_MODULES" --i18n-overwrite \
            --stop-after-init --max-cron-threads=0 --log-level=warn; then
            neutralize_db "$PRODCOPY_DB" || true
            PRODCOPY_LINE="репетиція міграції на копії prod: пройшла ($(basename "$LATEST"))"
        else
            fail "оновлення на копії prod впало - на живу базу не викочувати"
        fi
    fi
    done_step
fi

summary
[ "$PROBLEM_COUNT" -eq 0 ]
