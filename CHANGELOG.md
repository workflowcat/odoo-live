# Changelog

Notable changes for people who run or build on this code. Module-level API changes are in
`docs/api/CHANGELOG.md`. Dates are YYYY-MM-DD.

## Unreleased

### Added
- Open-source groundwork: LICENSE and license texts, README in English and Ukrainian, CONTRIBUTING,
  SECURITY, CODE_OF_CONDUCT, MAINTAINERS, issue and pull request templates, `docs/open-source-plan.md`.
- `scripts/check_static.sh` (all checks without Docker) and `scripts/test_full.sh` (what CI runs).
- `scripts/manifest_check.py`: manifests, licenses, pinned OCA sources, no defaults pointing at our servers.
- `addons/OCA_payroll.commit`: the vendored OCA payroll engine is now pinned (OCA/payroll 19.0 at 0d1b4b7).
- `ruff.toml` and a lint step in `scripts/check_static.sh`: undefined names, unused imports and variables,
  mutable defaults in our modules and scripts. Style is not enforced.

### Changed
- The newest work from `show/ua-polish` (Ukrainian words, guest access, show database, deploy fixes)
  is now on `main`.
- `l10n_ua_kp`: profession code suggestions are off unless `UA_KP_URL` is set (it pointed at our
  service by default).
- `docker-compose.yml`: `BP_BRIDGE_URL` comes from `.env` and is empty by default.
- `docker-compose.yml`: the Odoo image is pinned to `19.0-20261102` (override with `ODOO_IMAGE_TAG`).
- `.env.example`: comments on their own lines (inline comments ended up inside values).
- Labels in documents recognised during hiring match choices in Ukrainian as well as in the user's
  language (broke for English users after the English interface was added).

### Security
- `l10n_ua_mrp`: assembly drawings are returned without scripts, event handlers, embedded HTML or outside links.
- `bp_purchase_intake`: an IBAN read from an email is not added to an existing supplier's card.
- `l10n_ua_payments`: confirming a plain (non-salary) payment order no longer marks recipient accounts as trusted.
- `l10n_ua_hr_card`: the OCA `search_attachments_from_hr_employee` flag no longer opens other employees' scans.

### Removed
- `docker-compose.live.yml` and the Supabase setup it described (unused since 2026-09-22).
