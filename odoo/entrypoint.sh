#!/bin/bash
# Live entrypoint: wait for Postgres, initialize the database on first boot, then run Odoo.
# Env: HOST PORT USER PASSWORD (Postgres), DB_NAME (default odoo), ODOO_ADMIN_PASSWD (db manager master password)
set -eu
DB_NAME="${DB_NAME:-odoo}"; export PGPASSWORD="$PASSWORD"; export PGSSLMODE=require
# one image, any database: the config follows DB_NAME
sed -i "s/^db_name *=.*/db_name = $DB_NAME/; s/^dbfilter *=.*/dbfilter = ^$DB_NAME\$/" /etc/odoo/odoo.conf
until psql -h "$HOST" -p "${PORT:-5432}" -U "$USER" -d postgres -Atc "select 1" >/dev/null 2>&1; do echo "waiting for postgres at $HOST"; sleep 3; done
if [ -n "${ODOO_ADMIN_PASSWD:-}" ]; then sed -i '/^admin_passwd *=/d' /etc/odoo/odoo.conf; printf 'admin_passwd = %s\n' "$ODOO_ADMIN_PASSWD" >> /etc/odoo/odoo.conf; fi
if ! psql -h "$HOST" -p "${PORT:-5432}" -U "$USER" -d "$DB_NAME" -Atc "select 1 from information_schema.tables where table_name='ir_module_module'" 2>/dev/null | grep -q 1; then
  echo "first boot: initializing $DB_NAME"
  odoo -c /etc/odoo/odoo.conf -d "$DB_NAME" --db_host="$HOST" --db_port="${PORT:-5432}" --db_user="$USER" --db_password="$PASSWORD" \
       -i "${INIT_MODULES:-base,contacts,mail,bp_kyc}" --without-demo=all --load-language=uk_UA --stop-after-init
  # keep the database self-contained: attachments live in Postgres, not on this disposable disk
  printf 'env["ir.config_parameter"].sudo().set_param("ir_attachment.location","db")\nenv["ir.attachment"].sudo().force_storage()\nenv.cr.commit()\n' | \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB_NAME" --no-http --db_host="$HOST" --db_port="${PORT:-5432}" --db_user="$USER" --db_password="$PASSWORD" >/dev/null 2>&1 || true
fi
# one-shot module operations for a running database, keyed by a marker so every container start does not repeat them:
#   MODULE_OPS="i:bp_kyc,l10n_ua_partner_edr;u:l10n_ua_payroll_rules" MODULE_OPS_TAG="2026-09-09a"
if [ -n "${MODULE_OPS:-}" ] && [ -n "${MODULE_OPS_TAG:-}" ]; then
  applied=$(psql -h "$HOST" -p "${PORT:-5432}" -U "$USER" -d "$DB_NAME" -Atc "select value from ir_config_parameter where key='bp.module_ops_tag'" 2>/dev/null || true)
  if [ "$applied" != "$MODULE_OPS_TAG" ]; then
    echo "module ops $MODULE_OPS_TAG: $MODULE_OPS"
    IFS=';' read -ra OPS <<< "$MODULE_OPS"
    for op in "${OPS[@]}"; do
      kind="${op%%:*}"; mods="${op#*:}"
      case "$kind" in
        i) odoo -c /etc/odoo/odoo.conf -d "$DB_NAME" --db_host="$HOST" --db_port="${PORT:-5432}" --db_user="$USER" --db_password="$PASSWORD" -i "$mods" --stop-after-init ;;
        u) odoo -c /etc/odoo/odoo.conf -d "$DB_NAME" --db_host="$HOST" --db_port="${PORT:-5432}" --db_user="$USER" --db_password="$PASSWORD" -u "$mods" --i18n-overwrite --stop-after-init ;;
      esac
    done
    psql -h "$HOST" -p "${PORT:-5432}" -U "$USER" -d "$DB_NAME" -Atc "insert into ir_config_parameter (key, value, create_date, write_date) values ('bp.module_ops_tag', '$MODULE_OPS_TAG', now(), now()) on conflict (key) do update set value = excluded.value, write_date = now()" >/dev/null
  fi
fi
# переклади ядра і всіх модулів українською, коли їх ще не завантажено або після MODULE_OPS
if [ -n "${RELOAD_TRANSLATIONS:-}" ]; then
  printf 'w = env["base.language.install"].create({"lang_ids": [(6, 0, env["res.lang"].with_context(active_test=False).search([("code","=","uk_UA")]).ids)], "overwrite": True})\nw.lang_install()\nenv.cr.commit()\n' | \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB_NAME" --no-http --db_host="$HOST" --db_port="${PORT:-5432}" --db_user="$USER" --db_password="$PASSWORD" >/dev/null 2>&1 || true
fi
exec /entrypoint.sh odoo -c /etc/odoo/odoo.conf
