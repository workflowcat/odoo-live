#!/usr/bin/env bash
# Викладка стенду зарплати: Worker + образ контейнера, потім перезапуск інстансу на новий образ.
# Локально: cd worker && npm run deploy:payroll. У Workers Builds: команда деплою та сама, BRIDGE_TOKEN у змінних збірки.
set -euo pipefail
cd "$(dirname "$0")/.."
npx wrangler deploy -c wrangler.payroll.jsonc
if [ -n "${BRIDGE_TOKEN:-}" ]; then
  sleep 180   # дочекатися розкатки нового образу; ранній перезапуск піднімає старий образ
  curl -fsS -m 60 -X POST -H "Authorization: Bearer $BRIDGE_TOKEN" https://odoo-payroll.botpartners.workers.dev/_container/restart || true
fi
