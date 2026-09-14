#!/usr/bin/env bash
# Викладка стенду зарплати: Worker + образ контейнера, потім перезапуск інстансу на новий образ.
# Локально: cd worker && npm run deploy:payroll. У Workers Builds: команда деплою та сама, BRIDGE_TOKEN у змінних збірки.
set -euo pipefail
cd "$(dirname "$0")/.."
# перед викладкою: модулі мають встановитися на копії хмарної бази (payroll_cloud)
if [ -n "${VERIFY_ON_CLOUD_COPY:-}" ]; then
  ( cd .. && docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll_cloud -i $VERIFY_ON_CLOUD_COPY --stop-after-init --log-level=warn" ) || { echo "встановлення на копії хмарної бази провалилося, викладку зупинено"; exit 1; }
fi
# перед викладкою: локальні перевірки (check_all.sh) мають пройти; SKIP_CHECKS=1 пропускає цей крок
if [ -z "${SKIP_CHECKS:-}" ]; then
  if ! ../scripts/check_all.sh; then
    echo "DEPLOY-PAYROLL: FAILED (checks)"
    exit 1
  fi
fi
# збірка образу інколи падає на push у реєстр; без цієї перевірки помилку ховає конвеєр
if ! npx wrangler deploy -c wrangler.payroll.jsonc; then
  echo "DEPLOY-PAYROLL: FAILED (wrangler deploy)"
  exit 1
fi
if [ -n "${BRIDGE_TOKEN:-}" ]; then
  sleep 180   # дочекатися розкатки нового образу; ранній перезапуск піднімає старий образ
  curl -fsS -m 60 -X POST -H "Authorization: Bearer $BRIDGE_TOKEN" https://odoo-payroll.botpartners.workers.dev/_container/restart || true
fi
# останній рядок виводу: якщо його немає, викладка не дійшла до кінця
echo "DEPLOY-PAYROLL: OK"
