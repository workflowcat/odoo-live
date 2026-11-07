# Open-source plan

Goal: anyone can clone this repository, run it, understand it and keep building on it without
asking us. Written 2026-11-07 after a full audit of the repository. Phase 1 is done on this branch; the
rest is ordered work with a "done when" line each.

## Where we start (audit, 2026-11-07)

| Area | State |
| --- | --- |
| Code | 42 `l10n_ua_*` + 3 `bp_*` modules (~41k lines Python, ~14k lines XML), 24 OCA modules vendored at pinned commits |
| Tests | 104 test files, 33 tags, green in GitHub Actions on every push to `main` (~8-11 min) |
| Static checks | `layers_check.py` (210), `contract_check.py`, `words_check.py` (6446) - all pass |
| Branches | newest work sat on `show/ua-polish`, 29 commits ahead of `main` |
| License | per-module `license` keys only (37 LGPL-3, 5 AGPL-3 own); no LICENSE file; bundled fonts without their license |
| Docs | Ukrainian only, written for our own agents; no CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue templates |
| Coupling | defaults point at our Workers (`*.botpartners.workers.dev`), 1Password paths, our server names; Supabase leftovers |
| Internal notes | `docs/agents/` (agent inbox and log), dated reviews, team notes for a private repo |
| Security | 24 findings from the 2026-10 audit (1 high, ~15 medium); several still open in the tree |
| Secrets in history | none found (261 commits scanned 2026-11-06); all people and money in demo data are made up |

## Decisions taken (change any of them in one line)

1. **License.** Each module's manifest is authoritative. Our code stays LGPL-3 unless the manifest says
   AGPL-3. Vendored OCA modules keep their own licenses. Full texts live in `LICENSES/`, the default in `LICENSE`.
   Installing the full product pulls AGPL-3 OCA modules, so the combined install carries AGPL-3 duties.
2. **Language.** Public docs (README, CONTRIBUTING, SECURITY, this plan) in English, with a Ukrainian
   section in the README. Domain docs, code comments and UI words stay Ukrainian for now.
3. **Where work happens.** Issues and pull requests on GitHub. Maintainers land them through the
   upstream repository and mirror back (see `MAINTAINERS.md`). Nobody outside needs that flow.
4. **Our services stay optional.** `bp_*` modules, `worker/` and `assistant/` stay in the repo, but nothing
   points at our infrastructure by default: each URL comes from the environment and the feature is off without it.
5. **OCA stays vendored** at pinned commits for now: one clone gives a working product.
6. **CI.** The existing GitHub workflow stays; it calls the same scripts a contributor runs locally.

## Phase 1 - safe to clone (done on branch `oss/open-source`)

- [x] One line of history: `show/ua-polish` merged with `main`.
- [x] `LICENSE`, `LICENSES/` (LGPL-3, GPL-3, AGPL-3), font licenses next to the fonts, license section in README.
- [x] README for a stranger: what it is, a 10-minute start, module map, how to test, disclaimer on tax numbers.
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, issue and pull request templates.
- [x] `AGENTS.md` rewritten for any contributor's coding agent; our own workflow moved to `MAINTAINERS.md`.
- [x] No defaults pointing at our infrastructure in modules or setup files; Supabase leftovers removed.
- [x] Stale reviews and setup notes moved to `docs/archive/`; the agent notes channel (`docs/agents/`) stays, it is how roles coordinate.
- [x] `scripts/check_static.sh`: every static check in one command, including a manifest and license check; CI calls it.
- [x] The vendored OCA payroll engine pinned (`addons/OCA_payroll.commit`, matched to OCA 19.0 by content).
- [ ] Left for later: `scripts/demo_business.py` still reads one optional demo password through 1Password
      (skips that user when `op` is missing); `docs/base/` notes describe our own servers.

## Phase 2 - safe to deploy

Done when every finding of the 2026-10 audit is either fixed with a regression test or written down in
`SECURITY.md` as a known limit, and a fresh production install has no default password.

Status 2026-11-07 (24 findings):

- [x] 15 fixed in October, with tests in `l10n_ua_payroll_tests/tests/test_security.py` (`ua_security`):
  payslip traces (the one high), change log, registers, VAT and cash writes, company rules, bridge
  transport, supplier status, leave allocations, military check, income certificate, P-2, bank API host,
  DPS XML parser. Production deploy refuses an empty or sample admin password.
- [x] 4 fixed on this branch with tests: assembly drawing SVG cleaned (`l10n_ua_mrp`, test_40); an emailed
  IBAN no longer lands on an existing supplier (`bp_purchase_intake`); automatic "trusted account" only on
  salary and tax orders (`l10n_ua_payments`); the OCA document flag no longer opens colleagues' scans
  (`l10n_ua_hr_card`, test_19).
- [ ] Bridge Worker: one token for staging and production. Fix: accept a list of tokens, each scoped to
  routes and an environment; constant-time compare. Needs a Worker deploy.
- [ ] `deploy/restore.sh`: neutralise a production copy (passwords, API keys, bank tokens, mail servers,
  all bridge parameters) before staging serves it.
- [ ] `assistant/`: bind login to a proven identity (Cloudflare Access JWT or a one-time code to the work
  email); picker mode only on demo data.
- [ ] `scripts/claude_extract_helper.py`: a per-run token on the local endpoint and an isolated settings
  file for the agent.
- [ ] Sample deploy workflow: separate host user for staging (warning added to the file).

## Phase 3 - easy to build on

Done when a new developer goes from clone to a running demo with one command, and every module explains itself.

- One command for a demo database: `scripts/demo_server.sh reset` works on a clean clone (no hard-coded ports,
  waits for the server, prints the login).
- A dev image with `pypdf` baked in instead of `pip install` on every run. (The Odoo image is pinned by date tag since 2026-11-07.)
- A `README.rst` per module in the OCA layout (`readme/DESCRIPTION.md`, `USAGE.md`, `CONFIGURE.md`).
- Manifests: English `name`/`summary`, `website` and `maintainers`; Ukrainian texts move to `i18n/uk.po`
  so English users get English and the UI stays Ukrainian.
- [x] ruff for mistakes (undefined and unused names, mutable defaults) in `scripts/check_static.sh`, blocking.
- `pre-commit` with ruff formatting and the OCA checks (pylint-odoo), introduced warning-only first, then blocking.
- Tests: a fast subset (`ua_smoke`) under 3 minutes for pull requests; the full run stays on `main`.
- Releases: tag `19.0.YYYY.MM.DD` on `main`, notes from `CHANGELOG.md`; module versions follow OCA rules.
- Architecture doc in English with the module map and the 9 business flows (from the map board).

## Phase 4 - a community around it

Done when someone outside the team has merged a change and we did not have to explain the codebase in chat.

- Pick a public name (the repo is `odoo-live`; something like "Odoo UA back office" says what it is).
- 10 labelled "good first issue" tickets from the open work (English UI words, module READMEs, tests).
- Ask accountants to review golden numbers in public: an issue template "the number is wrong" with the scenario id.
- Offer generic parts upstream to OCA: the NBU rate provider (`l10n_ua_nbu` -> OCA/currency), the chart and
  tax names (`l10n_ua_chart` -> OCA/l10n-ukraine), so others maintain them with us.
- Replace vendored OCA with pinned dependencies (git-aggregator or pip wheels) once the repo has contributors
  who pull often; it cuts the clone from ~45 MB to ~6 MB.
- Rename `bp_*` modules to neutral names with a migration, when the first outside user asks for them.
- GitHub Discussions on, a short roadmap pinned, monthly release.

## What stays ours

- `deploy/` server scripts are examples: they show one way to run it, nobody needs our server.
- `worker/` and `assistant/` are reference integrations on Cloudflare Workers; to use them, deploy your own.
- Demo companies, people and documents are invented. Real client data never goes into this repository.
