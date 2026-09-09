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
exec /entrypoint.sh odoo -c /etc/odoo/odoo.conf
