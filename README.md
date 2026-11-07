# odoo-live

A Ukrainian back office on plain Odoo 19 Community: payroll and HR, accounting with VAT, bank and
cash, fixed assets, financial statements, primary documents, sole-proprietor (FOP) books, purchasing
with invoice intake, and counterparty checks. Free software: fork it, run it, build on it.

*Українською - нижче.*

**Status:** active development, used for demos and pilots. The tax and payroll numbers follow Ukrainian
rules as of 2026 and are tested against golden scenarios an accountant confirmed
([docs/payroll/golden-scenarios.md](docs/payroll/golden-scenarios.md)). Nothing here is tax or legal
advice: have your accountant check the numbers before you rely on them.

## How it is built

1. **Native Odoo first.** Standard lists, forms, buttons and wizards. No custom web client.
2. **OCA 19.0 next, unchanged.** 24 OCA modules are vendored at pinned commits (`addons/OCA_*.commit`).
3. **Our Ukrainian layer, thin on top.** 42 `l10n_ua_*` modules and 3 `bp_*` integration modules.
   Logic modules carry no custom JavaScript; menus live in one module, `l10n_ua_navigation`.
4. **Every module installs on an empty database and has Odoo tests.** Money is checked against one file
   of numbers ([golden/scenarios.json](addons/l10n_ua_payroll_tests/golden/scenarios.json)).

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), how a team adapts it without forking:
[docs/customization.md](docs/customization.md), what 1C/BAS has that this does not yet:
[docs/parity/README.md](docs/parity/README.md).

## Quick start

You need Docker with Compose v2 and Python 3.9+ (the helper scripts use the standard library).

```bash
git clone https://github.com/workflowcat/odoo-live.git
cd odoo-live
cp .env.example .env          # set ODOO_ADMIN_USER_PASSWORD and ODOO_ADMIN_PASSWD (any values locally)
./scripts/demo_server.sh reset # database "demo" with every module, on http://127.0.0.1:8131
python3 scripts/demo_business.py   # a made-up furniture company: payroll, sales, stock, VAT, bank, cash, assets
```

Log in as `admin` with `ODOO_ADMIN_USER_PASSWORD`. The interface is Ukrainian; the demo company,
people and documents are invented.

To install the product on your own database: `-i l10n_ua_navigation` pulls in every module.

## Tests and checks

```bash
./scripts/check_static.sh   # no Docker: layers, API contract, UI words, manifests and licenses
./scripts/test.sh           # payroll golden scenarios on a fresh database
./scripts/test_full.sh      # everything CI runs: all modules, all test tags, fresh database
```

GitHub Actions runs `check_static.sh` and `test_full.sh` on every push to `main` and on pull requests.

## What is where

| Area | Modules |
| --- | --- |
| Payroll | `l10n_ua_payroll_rules`, `l10n_ua_average`, `l10n_ua_index`, `l10n_ua_gph`, `l10n_ua_payroll_account`, `l10n_ua_payments`, `l10n_ua_explain` |
| HR | `l10n_ua_hr_card`, `l10n_ua_hr_orders`, `l10n_ua_hr_docs`, `l10n_ua_military`, `l10n_ua_kp`, `l10n_ua_onboarding`, `l10n_ua_hire` |
| Tax reports | `l10n_ua_payroll_reports`, `l10n_ua_reporting`, `l10n_ua_profit_tax` |
| Accounting | `l10n_ua_chart`, `l10n_ua_vat`, `l10n_ua_ledger`, `l10n_ua_finrep`, `l10n_ua_group`, `l10n_ua_assets`, `l10n_ua_nbu` |
| Bank and cash | `l10n_ua_bank`, `l10n_ua_bank_online` (PrivatBank, Monobank), `l10n_ua_bank_1c` (1C exchange file with any bank), `l10n_ua_cash` |
| Documents | `l10n_ua_docs`, `l10n_ua_docs_sale`, `l10n_ua_docs_stock`, `l10n_ua_stock_docs`, `l10n_ua_mrp` |
| Setup and migration | `l10n_ua_setup` (first-run questionnaire), `l10n_ua_migrate` (opening balances) |
| Sole proprietors | `l10n_ua_fop` |
| Purchasing | `l10n_ua_purchase`, `bp_purchase_intake` (supplier invoices from email), `l10n_ua_dk021` (ДК 021 procurement codes) |
| Contracts | `l10n_ua_contract` (counterparty contracts, limits, reconciliation acts) |
| Import | `l10n_ua_customs` (customs declaration: duty and fees into the cost of goods, customs VAT into credit) |
| Defense manufacturing | `l10n_ua_defense` (state contracts, Resolution 309 price calculation, acceptance acts, serial passports) |
| Industry packs | `l10n_ua_catalog`: drones, ground robots, military apparel, machining, procurement, small shop; your own as JSON ([docs/customization.md](docs/customization.md)) |
| Counterparties | `l10n_ua_partner_edr` (state register), `bp_kyc` |
| Control | `l10n_ua_changes` (who changed what, month closing), `l10n_ua_close` (month-end operations: depreciation, FX revaluation, 79 closing), checks mixin, `auditlog` |
| Interface | `l10n_ua_navigation` (menus and Ukrainian words), `l10n_ua_screen` (shared helpers), `l10n_ua_api` (one model for outside clients, contract in [docs/api/](docs/api/)) |
| Integrations | `bp_bridge` (one door to outside services) |
| Tests | `l10n_ua_payroll_tests` (golden scenarios and cross-module tests) |

| Folder | What it is |
| --- | --- |
| `addons/` | Odoo modules: ours (`l10n_ua_*`, `bp_*`) and vendored OCA |
| `scripts/` | test runner, demo builders, checks |
| `docs/` | architecture, payroll and accounting specs (mostly Ukrainian), API contract |
| `deploy/` | one way to run staging and production on a single server (Docker Compose) |
| `worker/` | optional Cloudflare Worker: the bridge to registries and the KYC register |
| `assistant/` | optional employee web assistant (Cloudflare Worker) on top of Odoo |
| `reference/payroll_core/` | an independent payroll calculator used to cross-check Odoo |

## Optional services

Each is off until you set its variable in `.env`; the rest of the product works without it.

| Variable | Feature |
| --- | --- |
| `BP_BRIDGE_URL`, `BP_BRIDGE_TOKEN` | state register lookups and the KYC register through your own bridge Worker (`worker/`) |
| `UA_KP_URL` | profession code suggestions when hiring |
| `UA_EXTRACT_URL` | reading document photos during hiring (a helper on the host, `scripts/claude_extract_helper.py`) |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `BP_AI_MODEL` | reading supplier invoices with an AI model (Cloudflare Workers AI) |

Bank API tokens (PrivatBank, Monobank) are set on the bank statement provider in Odoo, not in `.env`.

## Contributing

Issues and pull requests are welcome, in English or Ukrainian. Start with [CONTRIBUTING.md](CONTRIBUTING.md);
the roadmap is [docs/open-source-plan.md](docs/open-source-plan.md). Security problems: [SECURITY.md](SECURITY.md).

## License

Each module's `__manifest__.py` says its license. Our modules are LGPL-3 unless the manifest says AGPL-3;
vendored OCA modules keep their own (AGPL-3 or LGPL-3). The default for everything else is LGPL-3
([LICENSE](LICENSE)); all texts are in [LICENSES/](LICENSES/). A full install includes AGPL-3 modules, so
running it as a service for others carries AGPL-3 duties. Fonts in `assistant/public/fonts/` are under the
SIL Open Font License. Odoo is a trademark of Odoo S.A.; this project is not affiliated with it.

---

## Українською

Український бек-офіс на голому Odoo 19 Community: зарплата і кадри, бухоблік з ПДВ, банк і каса,
основні засоби, фінзвітність, первинні документи, ФОП, закупівлі з розбором рахунків, перевірка
контрагентів. Код відкритий: беріть, запускайте, будуйте зверху.

Правила: спершу нативний Odoo, потім OCA 19.0 без змін, наше українське - тонко зверху. Інтерфейс -
стандартні списки, форми і кнопки Odoo; меню в одному модулі `l10n_ua_navigation`. Кожен модуль
ставиться на порожню базу і має тести; гроші звіряються з одним файлом чисел, який підтвердив бухгалтер.

Швидкий старт - вище (розділ Quick start). Специфікації зарплати й обліку - у `docs/payroll/` і
`docs/base/`, українською. Питання і зміни приймаємо українською або англійською:
[CONTRIBUTING.md](CONTRIBUTING.md).

Це не податкова чи юридична консультація: перед роботою на справжніх даних числа має перевірити ваш бухгалтер.
