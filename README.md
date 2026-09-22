# odoo-live

Український бек-офіс на Odoo 19 Community для Bot&Partners: зарплата і кадри, бухоблік з ПДВ,
банк і каса, основні засоби, фінзвітність, первинні документи, ФОП, закупівлі з розбором рахунків,
KYC і ЄДР. Одна гілка `main`, одна система.

Правила: спершу нативний Odoo, потім OCA 19.0 без змін, наше українське - тонко зверху.
Інтерфейс - голий Odoo: стандартні списки, форми, кнопки і чарівники, меню в одному
модулі (`scripts/layers_check.py` стежить). Кожен модуль ставиться на
порожню базу і має справжні Odoo-тести. Гроші звіряються з одним файлом чисел, який підтверджує
бухгалтер.

## Швидкий старт

```bash
cp .env.example .env                 # заповнити; .env не в репозиторії
./scripts/demo_server.sh reset       # база demo з усіма модулями, сервер на http://127.0.0.1:8131
python3 scripts/demo_business.py     # ТОВ «Ясен Меблі»: зарплата, продажі, склад, виробництво, ПДВ, банк, каса, ОЗ
./scripts/test.sh                    # еталонні тести зарплати на свіжій базі (~25 с)
TEST_TAGS=ua_golden,ua_leaves,ua_payments,ua_regress,ua_changes,ua_period,ua_checks,ua_hire,ua_reporting,ua_setup,ua_bank,ua_card,ua_documents ./scripts/test.sh
./scripts/check_all.sh               # перевірки стенду (docker compose up -d, порт ODOO_PORT з .env)
```

Повне встановлення продукту на порожню базу: `-i l10n_ua_navigation` (тягне все).

## Що де

| Шар | Модулі |
| --- | --- |
| Міст назовні | `bp_bridge` (клієнт), Worker `worker/` (OpenDataBot, kyc-service) |
| Контрагенти | `l10n_ua_partner_edr`, `bp_kyc` |
| Зарплата | `l10n_ua_payroll_rules`, `l10n_ua_average`, `l10n_ua_index`, `l10n_ua_gph`, `l10n_ua_payroll_account`, `l10n_ua_payments` (на OCA `account_payment_order`) |
| Кадри | `l10n_ua_hr_card`, `l10n_ua_hr_orders`, `l10n_ua_hr_docs`, `l10n_ua_military`, `l10n_ua_kp`, `l10n_ua_onboarding`, `l10n_ua_hire` |
| Звітність ДПС | `l10n_ua_payroll_reports`, `l10n_ua_reporting` |
| Контроль | `l10n_ua_changes`, `l10n_ua_explain`, перевірки `ua.checks.mixin` |
| Бухоблік | `l10n_ua_chart`, `l10n_ua_vat`, `l10n_ua_ledger`, `l10n_ua_finrep` (mis_builder), `l10n_ua_assets` (account_asset_management), `l10n_ua_nbu` (currency_rate_update), `l10n_ua_cash`, `l10n_ua_bank`, `l10n_ua_bank_online`, `l10n_ua_docs` (+ `_sale`, `_stock`), `l10n_ua_fop`, `l10n_ua_migrate` |
| Закупівлі | `bp_purchase_intake` |
| Інтерфейс | стандартні подання Odoo; `l10n_ua_navigation` - три розділи меню (Зарплата, Кадри, Звітність) і українські назви довідників; `l10n_ua_screen` - спільні хелпери моделей (без екранів). Ітерації інтерфейсу - окремий репозиторій `odoo-ui` (workflowcat/odoo-ui), читає ядро через `docs/api/`; старі екрани OWL там у `reference/`, тег ядра `ui-owl-2026-09-22` |
| OCA без змін | див. `docs/base/oca-vendored.md` (коміти в `addons/OCA_*.commit`) |
| Поза Odoo | `assistant/` (вебасистент працівника, Worker), `reference/payroll_core` (незалежний перерахунок зарплати) |

## Документи

- `docs/ARCHITECTURE.md` - три шари: Odoo, база, міст.
- `docs/base/demo-space-plan.md` - задум демо-простору і хвилі робіт.
- `docs/base/review-2026-09-21.md`, `native-fit-2026-09-21.md` - огляд і карта «нативне / OCA / наше».
- `docs/base/spec-*.md` - опис кожного облікового модуля.
- `docs/base/questions-for-accountant.md` - усі питання до бухгалтера одним списком.
- `docs/payroll/` - зарплата: README, еталонні сценарії, аркуш для бухгалтера, специфікації.
- `docs/purchase/README.md` - розбір вхідних рахунків.
- `docs/base/demo-data.md` - як зібрати демо і що в ньому є.
- `docs/api/` - контракт для інтерфейсу; `docs/agents/` - нотатки між агентами (core / docs / ui), `CLAUDE.md` - правила.

## Стенди

- Розробка: `docker compose up -d`, порт `ODOO_PORT` з `.env`, база `payroll` (копія продукту).
- Демо: `scripts/demo_server.sh start|stop|reset`, порт 8131, база `demo`.
- Живий сервер: буде на Hetzner (Odoo + Postgres на одній машині, Worker як вхідні двері);
  `docker-compose.live.yml` і `odoo/Dockerfile` для цього.

Секрети: `.env` на Mac і секрети Worker. Ніколи в репозиторії, ніколи в Odoo.
