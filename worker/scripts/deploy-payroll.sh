#!/usr/bin/env bash
# Викладка стенду зарплати: Worker + образ контейнера, потім перезапуск інстансу на новий образ.
# Локально: cd worker && npm run deploy:payroll. У Workers Builds: команда деплою та сама, BRIDGE_TOKEN у змінних збірки.
set -euo pipefail
cd "$(dirname "$0")/.."
# перед викладкою: модулі мають встановитися на копії хмарної бази (payroll_cloud)
if [ -n "${VERIFY_ON_CLOUD_COPY:-}" ]; then
  ( cd .. && docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll_cloud -i $VERIFY_ON_CLOUD_COPY --stop-after-init --log-level=warn" ) || { echo "встановлення на копії хмарної бази провалилося, викладку зупинено"; exit 1; }
fi
npx wrangler deploy -c wrangler.payroll.jsonc
if [ -n "${BRIDGE_TOKEN:-}" ]; then
  sleep 180   # дочекатися розкатки нового образу; ранній перезапуск піднімає старий образ
  curl -fsS -m 60 -X POST -H "Authorization: Bearer $BRIDGE_TOKEN" https://odoo-payroll.botpartners.workers.dev/_container/restart || true
fi
