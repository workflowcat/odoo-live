# odoo-live - rules for coding agents

Read by Claude Code, Codex and any other agent working in this repository. People: the same rules,
explained, are in [CONTRIBUTING.md](CONTRIBUTING.md).

This is the CORE: Ukrainian back-office logic on Odoo 19 CE. Interface experiments live in a separate
repository (`odoo-ui`) and read the core through the contract in `docs/api/`. Code comments and UI
words are Ukrainian; no long dashes (only "-"); dates YYYY-MM-DD.

## Layers
- Native Odoo first, then OCA 19.0 unchanged (pinned in `addons/OCA_*.commit`; only `i18n/uk.po` may
  be edited), ours thin on top.
- A logic module has no `static/src`, does not depend on UI, and adds no menus: menus only in
  `l10n_ua_navigation`. `python3 scripts/layers_check.py` is the law.
- Every module installs on an empty database and has Odoo tests tagged `ua_<area>`. Money comes only
  from `addons/l10n_ua_payroll_tests/golden/scenarios.json`; an accountant confirms the numbers.
- No URL of our own servers inside a module: outside services come from the environment
  (`scripts/manifest_check.py`).

## Before a commit
```
./scripts/check_static.sh                 # no Docker: layers, contract, words, manifests, licenses
TEST_TAGS=<tags you touched> ./scripts/test.sh   # fresh database
./scripts/test_full.sh                    # everything CI runs
```
Dev stack: `docker compose` (project `odoo-live-base`, port from `.env`, database `payroll`). Demo:
`scripts/demo_server.sh` (port 8131, database `demo`). Several agents in one checkout: different
modules, own database prefixes, one-off `docker compose run`; only one agent restarts the `odoo`
service and the `payroll` database.

## Contract with other roles (core, docs, UI)
The channel is files in git, not chat. Protocol: `docs/agents/README.md`, tool `scripts/agent_note.py`.
- Changed a public method, model or field the UI sees: update `docs/api/` and `docs/api/CHANGELOG.md`
  in the same commit, or `contract_check.py` fails.
- Need something from another role: `python3 scripts/agent_note.py new request --to core|docs|ui "..."`.
- Took a decision that affects others: `agent_note.py new decision`.
- At the start of a session: `python3 scripts/agent_note.py list --open --to <your role>`.

## Never
- Secrets or real people's data in any commit: the repository is public. Keys go in `.env`
  (ignored) or the environment; demo data is invented, emails use `.example` domains.
- Edits to vendored OCA code.
- Pushing to GitHub directly. Maintainers' push and mirror flow is in [MAINTAINERS.md](MAINTAINERS.md).
