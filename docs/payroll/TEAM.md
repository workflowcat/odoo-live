# Робота командою над зарплатою

## Доступ

- Код: GitHub `workflowcat/odoo-live`, гілка `payroll` (приватний репозиторій). Доступ дає власник: Settings → Collaborators → Add people, роль Write.
- Стенд: https://odoo-demo.botpartners.workers.dev → Odoo. Користувачів створює адміністратор у Налаштування → Користувачі.
- Cloudflare і Supabase: доступ лише у власника. Команді не потрібен: викладка йде через GitHub Actions.

## Локальна розробка

1. `git clone`, гілка `payroll`.
2. `.env` у корені: `ODOO_PORT=8110`, `ODOO_ADMIN_USER_LOGIN=admin`, `ODOO_ADMIN_USER_PASSWORD=...`, `ODOO_ADMIN_PASSWD=...`, `BP_BRIDGE_TOKEN=...` (токен моста дає власник).
3. `docker compose up -d` → http://127.0.0.1:8110. Перший раз: створити базу `payroll` і встановити модулі, або взяти дамп у власника і відновити.
4. Демо-дані: `python3 scripts/demo_company.py`. Еталонна перевірка: `python3 scripts/payroll_check.py` проти бази `payroll_test` (копія стенду).

## Правила коду

- Модулі OCA у `addons/` не змінюються. Українська логіка лише в `l10n_ua_*` і `bp_*`.
- Правила зарплати як дані (XML), параметри з датами у `ua.payroll.param`.
- Інтерфейс: стандартні види Odoo, без власного JS і тем.
- Кожна зміна розрахунку: сценарій у `scripts/payroll_check.py` і рядок у `docs/payroll/golden-scenarios.md`.

## Викладка через Cloudflare Workers Builds (обраний шлях)

Cloudflare сам збирає образ і викладає Worker після push у гілку `payroll`. GitHub Actions не потрібен. Налаштування один раз у панелі Cloudflare (власник):

1. Workers & Pages → `odoo-payroll` → Settings → Builds → Connect. Дозволити застосунок Cloudflare для GitHub на репозиторій `workflowcat/odoo-live`.
2. Production branch: `payroll`. Root directory: `worker`.
3. Build command: порожньо. Deploy command: `npm run deploy:payroll`.
4. Build variables: `BRIDGE_TOKEN` = токен моста (той самий, що у секретах Worker), щоб після викладки контейнер перезапустився на новий образ.
5. Build watch paths (include): `addons/**`, `odoo/**`, `worker/**`.
6. Non-production branch builds: вимкнути. Для контейнерів вони не дають прев'ю.

Далі кожен merge у `payroll` = збірка і викладка за 5-8 хвилин. Історія збірок і логи: той самий екран Builds.

## Викладка вручну

1. Гілка від `payroll`, зміни, локальна перевірка, pull request у `payroll`.
2. Merge у `payroll` запускає GitHub Actions `deploy-payroll` (файл `docs/payroll/ci/deploy-payroll.yml` треба покласти в `.github/workflows/`; токен git на цьому Mac не має права `workflow`): збірка образу, `wrangler deploy`, перезапуск контейнера. 5-8 хвилин, стенд недоступний 2-3 хвилини.
3. Якщо змінилися модулі (новий модуль або нові поля), у тому самому pull request оновити `MODULE_OPS` і `MODULE_OPS_TAG` у `worker/wrangler.payroll.jsonc`. Контейнер виконає встановлення або оновлення один раз при старті.
4. База даних і секрети не в репозиторії. Дамп бази для локальної роботи дає власник.
