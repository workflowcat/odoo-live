# Contributing

Thank you for helping. Issues and pull requests are welcome in English or Ukrainian.

## Before you start

- **A wrong number** (tax, payroll, report): open an issue with the scenario, the number you expected,
  the number you got and the rule it comes from (law, article, letter of the tax service). Numbers are
  only changed when an accountant confirms them.
- **A bug**: the steps, what you expected, what happened, the Odoo log lines.
- **A bigger change** (new module, new dependency, changed data model): open an issue first and say
  what you plan, so nobody builds the same thing twice.

## Set up

```bash
cp .env.example .env            # fill in the two passwords, any values locally
./scripts/demo_server.sh reset  # demo database on http://127.0.0.1:8131
```

The development stack (`docker compose up -d`, port `ODOO_PORT`, database `payroll`) is for working on
modules against a long-lived database; tests always use a fresh one.

## Rules of the codebase

1. **Native Odoo first, then OCA, then ours.** Before writing a model, check whether Odoo 19 CE or an
   OCA 19.0 module already does it. Vendored OCA modules in `addons/` are never edited, except their
   Ukrainian translations (`i18n/uk.po`, see `addons/OCA_translations.md`). Each one is pinned in
   `addons/OCA_<repo>.commit`.
2. **Thin Ukrainian layer.** Our modules are `l10n_ua_<area>` (Ukrainian rules) and `bp_<name>`
   (integrations). Logic modules carry no JavaScript and no menus; menus and Ukrainian UI words live in
   `l10n_ua_navigation` (`hooks.py`, `data/terms_uk.json`). `scripts/layers_check.py` enforces this.
3. **Plain Odoo UI.** Standard list, form, kanban and wizard views. No custom web client, no themes.
4. **Every module installs on an empty database and has tests.** Tests are Odoo `TransactionCase`
   (or `AccountTestInvoicingCommon`) classes tagged `post_install`, `-at_install` and `ua_<area>`; add a new tag to `scripts/test_full.sh`.
5. **Money comes from one file.** Payroll and tax expectations live in
   `addons/l10n_ua_payroll_tests/golden/scenarios.json`. A change in a calculation comes with a scenario
   there and a line in `docs/payroll/golden-scenarios.md`.
6. **Rates and limits are data with dates**, not constants: minimum wage, subsistence minimum, tax rates
   are `ua.payroll.param` rows with an effective date.
7. **Public API is a contract.** If you change a method, model or field that outside clients use
   (`l10n_ua_api`, `docs/api/`), update `docs/api/` and `docs/api/CHANGELOG.md` in the same commit;
   `scripts/contract_check.py` fails otherwise.
8. **Words.** UI words follow `docs/payroll/words.md` (`scripts/words_check.py`). Code comments and
   docstrings are in Ukrainian today; English is welcome in new code. Dates are `YYYY-MM-DD`.
9. **No secrets, no real data.** Keys go in `.env` or the environment, never in code or data files.
   Demo and test people, companies, tax ids and bank accounts are invented; use `.example` domains.

## Before you open a pull request

```bash
./scripts/check_static.sh   # under a minute, no Docker (lint needs ruff: pip install ruff)
./scripts/test.sh           # quick: payroll golden scenarios
./scripts/test_full.sh      # everything CI runs (about 10 minutes)
```

Keep a pull request to one change. Say in the description what it changes for the person using Odoo,
which tests cover it and, for money, which scenario. Bump the module `version` (`19.0.x.y.z`) when you
change data, views or fields, and add a line to `CHANGELOG.md`.

## How changes land

Maintainers review on GitHub. Because the upstream repository is mirrored to GitHub, a merged pull
request may show as closed by a maintainer's commit rather than as "merged"; your authorship is kept.

## Licensing of contributions

By contributing you agree that your contribution is licensed under the license of the module you
change (see its `__manifest__.py`), or LGPL-3 for files outside modules.
