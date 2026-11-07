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
- [x] No defaults pointing at our infrastructure; no 1Password paths; Supabase leftovers removed.
- [x] Internal notes moved to `docs/archive/` (kept for history, out of the way).
- [x] `scripts/check_static.sh`: every static check in one command, including a manifest and license check; CI calls it.

## Phase 2 - safe to deploy

Done when every finding of the 2026-10 audit is either fixed with a regression test or written down in
`SECURITY.md` as a known limit, and a fresh production install has no default password.

- Fix the high finding first: frozen payslip traces readable by every internal user (`l10n_ua_explain`).
- Access rules: company record rules on own accounting and HR models; registers (VAT periods, cash books,
  change log) readable and writable only by the right groups.
- Remove public `sudo` entry points (leave allocations, military check) or put a group check in front.
- `bp_bridge.call`: group check, path allowlist, no host change through the path.
- `l10n_ua_bank_online`: https only, host allowlist, no response echo.
- `bp_purchase_intake`: supplier status writable only by managers; new IBAN on an existing supplier needs approval.
- Deploy scripts: refuse to start production without a set admin password; staging never shares tokens with production.
- Parse uploaded XML with a hardened parser; sanitise assembly SVG.
- Add a `ua_security` test per fix.

## Phase 3 - easy to build on

Done when a new developer goes from clone to a running demo with one command, and every module explains itself.

- One command for a demo database: `scripts/demo_server.sh reset` works on a clean clone (no hard-coded ports,
  waits for the server, prints the login).
- A dev image with `pypdf` baked in instead of `pip install` on every run; pin the Odoo image by date tag.
- A `README.rst` per module in the OCA layout (`readme/DESCRIPTION.md`, `USAGE.md`, `CONFIGURE.md`).
- Manifests: English `name`/`summary`, `website` and `maintainers`; Ukrainian texts move to `i18n/uk.po`
  so English users get English and the UI stays Ukrainian.
- `pre-commit` with ruff and the OCA checks (pylint-odoo), introduced warning-only first, then blocking.
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
