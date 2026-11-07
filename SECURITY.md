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
- `assistant/` has a demo login mode (`DEMO_PICKER=1`) that lets anyone with the shared password act as
  any employee. Never use it with real employees.
