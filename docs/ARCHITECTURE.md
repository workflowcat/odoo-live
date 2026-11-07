# Architecture

How odoo-live is put together and where to add things. Domain specs (payroll, accounting, documents)
are in `docs/payroll/` and `docs/base/`, in Ukrainian.

## The shape

```
 people ──▶ Odoo 19 CE web client (standard views, Ukrainian words)
                │
                ▼
     ┌──────────────────────────────────────────────────────────────┐
     │ our layer   l10n_ua_* (Ukrainian rules)   bp_* (integrations) │
     │ OCA 19.0    payroll, mis_builder, bank-statement-import, ...  │  addons/ (one addons path)
     │ Odoo 19 CE  account, hr, hr_holidays, stock, mrp, purchase... │
     └──────────────────────────────────────────────────────────────┘
                │                                 │ optional, one token
                ▼                                 ▼
          PostgreSQL 17                  bridge Worker (worker/): state register,
          (data and attachments)         KYC register; any other outside service
```

Outside clients (a separate UI, scripts, the employee assistant) talk to Odoo over its JSON-RPC API.
The supported surface for them is the model `ua.api` (`l10n_ua_api`), described in `docs/api/` and
checked against the code by `scripts/contract_check.py`.

## Rules that keep it maintainable

1. **Native first.** Our modules extend Odoo and OCA models; they do not copy them. Payroll runs on the
   OCA `payroll` engine (structures, rules, payslips); Ukrainian rules are salary rules as data plus
   dated parameters (`ua.payroll.param`: minimum wage, subsistence minimum, rates).
2. **OCA unchanged.** Vendored at a pinned commit (`addons/OCA_*.commit`); only Ukrainian translations
   are ours (`addons/OCA_translations.md`).
3. **Logic apart from interface.** Logic modules have no JavaScript and no menus. `l10n_ua_navigation`
   depends on everything, owns the three Ukrainian menu sections and the Ukrainian words of standard
   screens (`data/terms_uk.json`, applied by `hooks.py`). Installing it installs the product.
4. **Every number is tested.** `l10n_ua_payroll_tests` holds the golden scenarios
   (`golden/scenarios.json`) and cross-module tests; each logic module also tests itself under its own
   `ua_<area>` tag. `reference/payroll_core` recomputes payroll independently of Odoo to cross-check.
5. **Changes are explained.** `l10n_ua_changes` records who changed what in payroll, HR and money
   fields; `l10n_ua_explain` stores how each payslip line was computed.

## Areas

| Area | What it adds on top of Odoo and OCA |
| --- | --- |
| Payroll | Ukrainian salary rules (PDFO, military levy, ESV), average earnings (Resolution 100), indexation, civil contracts (GPH), postings, salary payment orders, payslip explanation |
| HR | personal card P-2, HR orders that post HR events, hiring case from candidate to filed notice, military registration, profession codes (KP), onboarding import |
| Tax reports | unified payroll tax report with annexes and DPS XML, VAT periods and tax invoices, profit tax return, income certificates |
| Accounting | Ukrainian chart names and short codes, trial balance and account cards, balance sheet and P&L (mis_builder), group consolidation, fixed asset tax groups, NBU exchange rates |
| Money | bank statement import (CSV, PrivatBank, Monobank APIs), cash orders and cash book |
| Documents | invoice for payment, service act, delivery note, waybill, inventory lists, production costing |
| Small business | FOP income book, migration of counterparties and opening balances, first-run questionnaire |
| Purchasing | supplier risk, supplier invoices from email (`bp_purchase_intake`: PDF text, optional AI reading, a draft bill held until the supplier is verified) |
| Counterparties | fill a partner from the state register by EDRPOU (`l10n_ua_partner_edr`), KYC cases (`bp_kyc`) |

## Outside services

Odoo never holds a vendor key. Modules that need the outside world call `env["bp.bridge"]._call()`
(`bp_bridge`): one URL and one token from `BP_BRIDGE_URL` / `BP_BRIDGE_TOKEN` (or the system
parameters `bp_bridge.url` / `bp_bridge.token`). The call is private (not reachable over RPC), allows only
`/api/...` paths on the configured host, and the caller checks the user's rights. The reference bridge
is the Cloudflare Worker in `worker/`; any HTTP service with the same routes works.

Other optional services, each read from the environment and off when unset: profession codes
(`UA_KP_URL`), document photo reading during hiring (`UA_EXTRACT_URL`), AI reading of invoices
(`CF_ACCOUNT_ID`, `CF_API_TOKEN`, `BP_AI_MODEL`). Public sources are called directly: NBU rates, bank APIs
with the token stored on the statement provider.

## Running it

- **Development:** `docker-compose.yml` - Postgres 17 and the official `odoo:19` image with `addons/`
  mounted. Tests create and drop their own database (`scripts/test.sh`).
- **Demo:** `scripts/demo_server.sh` builds a `demo` database with every module; `scripts/demo_*.py`
  fill it with invented companies over JSON-RPC (idempotent: run again to top up).
- **Server:** `deploy/` - one way to run staging and production on a single Linux host with Docker
  Compose: an image with our addons baked in, `deploy.sh <staging|prod> [ref]`, backups, restore.

## Adding a module

1. `addons/l10n_ua_<area>/` with `"version": "19.0.1.0.0"`, `"license": "LGPL-3"` (AGPL-3 if you build on
   an AGPL module and prefer to match it), `"author": "Bot&Partners"` plus yourself.
2. Depend on the smallest set of Odoo/OCA modules; add the module to `l10n_ua_navigation`'s `depends`.
3. Menus and Ukrainian words go to `l10n_ua_navigation`, not your module.
4. Tests in `addons/<module>/tests/`, tagged `ua_<area>`; add the tag to `scripts/test_full.sh`.
5. If outside clients need it, expose it through `ua.api` and document it in `docs/api/`.

Odoo 19 details that bit us: groups need a `res.groups.privilege` (`privilege_id`, not `category_id`);
a search view `<group>` takes no `expand`/`string`; kanban cards use `<t t-name="card">`; a search filter
needs a stored field; model constraints are `models.Constraint(...)` class attributes.
