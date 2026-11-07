# Security

This code handles salaries, tax ids, bank accounts and personal data of employees. Please report
weaknesses privately, not in a public issue.

## How to report

Open a private report: https://github.com/workflowcat/odoo-live/security/advisories/new

Say which module and file, how to reproduce it on a fresh database (`./scripts/test.sh` style is ideal)
and what an attacker gains. We answer within a week and credit you in the fix unless you ask us not to.

## What is in scope

- Our modules (`addons/l10n_ua_*`, `addons/bp_*`), `worker/`, `assistant/`, `deploy/`, `scripts/`.
- Vendored OCA modules: report upstream to the OCA repository named in the module manifest; tell us
  too if our pinned version is affected.
- Odoo itself: report to Odoo S.A.

## Known limits

- The full product is built for one company per database. Multi-company record rules on our own
  registers and HR documents are being added (see `docs/open-source-plan.md`, phase 2); until then,
  do not give users of one company access to another company in the same database.
- `deploy/` and `worker/` are examples of how we run it. Review them before you run them in production:
  set every password and token yourself, never reuse staging tokens in production.
- Staging copies of production: `deploy/restore.sh` and `deploy/deploy.sh` run `odoo neutralize` plus our
  rules (`deploy/neutralize.sh`, `addons/*/data/neutralize.sql`): crons, mail, bridge, bank tokens, API keys
  off, every password reset. A copy that cannot be neutralised is dropped. Files in the filestore
  (attachments, scans) stay: treat a staging server that holds a production copy as production-sensitive.
- The bridge Worker takes one token per environment with its own routes (`worker/src/auth.js`); the old
  single `BRIDGE_TOKEN` keeps working until `BRIDGE_TOKENS` is set (see `MAINTAINERS.md`).
- `scripts/claude_extract_helper.py` runs your Claude Code login on candidate documents, limited to a
  temporary folder, read-only, behind a token. Run it only on a machine where that is acceptable.
- `assistant/`: employees sign in through Cloudflare Access (verified token, exact work email). The test
  login (`DEMO_PICKER=1`) lets anyone with the shared password act as any employee: invented data only.
