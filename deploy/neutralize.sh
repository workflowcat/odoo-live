# shellcheck shell=bash
# Знешкодження копії бази, перш ніж її подасть staging. Підключають deploy/restore.sh і
# deploy/deploy.sh; потрібні їхня функція dc і змінна PG_USER.
#
#   neutralize_copy <база>
#
# Що робить:
#   1. `odoo neutralize`: Odoo вимикає крони, вихідну і вхідну пошту, вебхуки, ставить
#      database.is_neutralized; наші модулі (addons/*/data/neutralize.sql) прибирають
#      параметри моста, токени й сертифікати банку, паролі пошти, ключі API.
#   2. Паролі всіх користувачів і всі ключі API скинуто: паролі prod на staging не діють.
#   3. Адміністратор отримує пароль staging (ODOO_ADMIN_USER_PASSWORD з env-файлу);
#      пароль іде в контейнер через змінну середовища, не через командний рядок.
#   4. Перевірка, що база позначена як знешкоджена. Будь-яка помилка - код 1.

neutralize_copy() {
    local db="$1" flag
    echo "== знешкодження копії $db =="
    dc run --rm --no-deps -T odoo neutralize -d "$db" --log-level=warn || return 1
    dc exec -T db psql -U "$PG_USER" -d "$db" -v ON_ERROR_STOP=1 -qAtc \
        "UPDATE res_users SET password = NULL; DELETE FROM res_users_apikeys;" || return 1
    if [ -n "${ODOO_ADMIN_USER_PASSWORD:-}" ]; then
        UA_ADMIN_PW="$ODOO_ADMIN_USER_PASSWORD" dc run --rm --no-deps -T -e UA_ADMIN_PW odoo \
            shell -d "$db" --no-http --log-level=warn <<'PY' || return 1
import os
env.ref("base.user_admin").password = os.environ["UA_ADMIN_PW"]
env.cr.commit()
PY
    else
        echo "УВАГА: ODOO_ADMIN_USER_PASSWORD не заданий - у копію не ввійде ніхто, поки не задасте пароль" >&2
    fi
    flag="$(dc exec -T db psql -U "$PG_USER" -d "$db" -Atc \
        "select lower(value) from ir_config_parameter where key = 'database.is_neutralized'")"
    if [ "$flag" != "true" ]; then
        echo "копію $db не позначено як знешкоджену" >&2
        return 1
    fi
    echo "копію $db знешкоджено: крони, пошта, міст, банк, ключі API вимкнено; паролі скинуто"
}
