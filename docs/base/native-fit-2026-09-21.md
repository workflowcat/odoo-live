# Native and OCA fit - 2026-09-21

Goal (Andrii): a base that leans on native Odoo 19 CE and working OCA 19.0 modules, our Ukrainian
logic thin on top, a nicer UA interface layered over it later. This note says where we rebuilt
what upstream already gives. Source: Opus audit agent, upstream checked through the GitHub API on
2026-09-21. Hour figures are estimates, not measured.

## Upstream facts

- Odoo 19 CE ships `hr_work_entry`, `hr_work_entry_holidays`, `hr_holidays`, `hr_attendance`,
  `hr_recruitment`, `hr_timesheet`, `hr.version`. Enterprise only: `hr_payroll`, `sign`,
  `documents`, `account_batch_payment`.
- Native `l10n_ua` = chart template `ua_psbo` plus the full VAT tax set (sale and purchase
  20/14/7/0/exempt, tax groups; sale VAT on 6432, purchase on 6442) - checked inside the `odoo:19`
  image by the VAT port agent; the first audit read only the GitHub tree and missed it. No fiscal
  positions, no report templates. `l10n_ua_vat` adds no taxes, only the zero-rate kind marker.
- OCA 19.0 branches exist for every repo below, all thinner than 18.0. `payroll_account` is NOT in
  OCA/payroll 19.0. `hr_timesheet_sheet` is NOT in 19.0. OCA/l10n-ukraine 19.0 is empty.

## Verdicts

| # | Ours | Verdict | Hours |
| --- | --- | --- | --- |
| 1 | Табель `ua.timesheet.sheet` | KEEP (П-5 is a fixed form); take worked days from `hr.work.entry` instead of counting «Р» cells | 16-24 |
| 2 | Leave balances as computed fields on the employee, yearly cron | ALIGN: post `hr.leave.allocation` per type; keep the UA day-count rules as the generator. Biggest gap: we create zero allocations today | 24-40 |
| 3 | Штатний розпис `ua.staff.list` | KEEP, already reads `hr.version` | 0 |
| 4 | `ua.hr.order` | KEEP, наказ as a transaction on `hr.version` is correct | 0 |
| 4 | `ua.employee.document` | REPLACE with OCA `hr_employee_document` + thin UA extension (types, expiry, sign state, reprint link) | 8-12 |
| 4 | `ua.hire.case` | KEEP; funnel part overlaps `hr_recruitment` stages, realign later | (16) |
| 5 | `ua.payment.batch` | REPLACE with OCA `account_payment_order` (bank-payment 19.0, 14 modules, not vendored yet) + UA export format. Posts real `account.payment`, so 661/6411/651 close without regex reconcile rules. Needs a `res.partner.bank` per employee | 24-32 |
| 6 | Аванс `ua.advance.sheet` | KEEP (ст. 115 КЗпП) | 0 |
| 7 | `ua.payroll.account.map` | ALIGN: keep, rename to avoid a future clash with `payroll_account`, replace account-prefix guessing with explicit account fields | 4-6 |
| 8 | `ua.change.log` / mixin | ALIGN: capture through OCA `auditlog` (server-tools 19.0), keep our accept / period / blocker workflow; needs a filter so the queue stays readable | 16-20 |
| 8 | `ua.period.close` | KEEP, already a thin wrapper on native lock dates; add `account_lock_date_update` | - |
| 9 | `ua.checks.mixin`, `ua.explain.trace` | KEEP, nothing upstream, this is the product's own value | 0 |
| 10 | Анкета `ua.setup.*` | KEEP; answers should land in `res.config.settings` fields, not a parallel store | 8 |
| 11 | `l10n_ua_bank_online`, reconcile models | KEEP, correctly thin on `account_statement_import_online` - the pattern to copy. Bank board overlaps `account_reconcile_oca` workspace | 0 (+8) |
| 12 | Military, ДПС XML, average, indexation, rules, КП | KEEP, nothing upstream | 0 |
| 14 | `l10n_ua_chart` | KEEP, right thickness | 0 |

## Third-party suite NadozirnySvyatoslav/l10n_ua

19.0, last push 2026-09-16, ~78 modules, 14 stars, 66 open issues, one maintainer plus one
co-author, tests present, no CI, no LICENSE file at repo root (LGPL-3 only in manifests and
README). Decision stays: do not hang payroll on it. One exception worth taking: `l10n_ua_sign`
(browser-side КЕП, depends only on `web`) vendored unmodified, after the author confirms the
licence in writing. Saves ~40 h of our own signing work. Write the cabinet submitter ourselves.

## Sandbox accounting port - what to base each module on

| Sandbox module | Base |
| --- | --- |
| `ua_vat` | native `account` taxes + `l10n_ua` tag; ПН/РК and перша подія stay ours |
| `ua_finrep`, `ua_consolidation` | `mis_builder` 19.0 (fully ported) or `account_financial_report`; forms as templates, not wizards |
| `ua_ledger_reports` | `account_financial_report` general ledger + `report_xlsx` |
| `ua_cash` | native `account.payment`; КО-1/КО-2 prints ours |
| `ua_assets` | REPLACE with OCA `account_asset_management`; МНМА 100 % as a method |
| `ua_nbu` | REPLACE with OCA `currency_rate_update` + an NBU provider (~40 lines) |
| `ua_cost` | native `mrp` / `stock` valuation, thin 23/26/901 posting |
| `ua_fop` | native `account`; ЄП/ВЗ/ЄСВ ours |
| `ua_migrate` | `base_import`; keep |
| `ua_intercompany` | native inter-company rules |

## OCA repos to track (19.0 modules / 18.0 modules)

payroll 2/7 · hr 12/32 · hr-holidays 5/10 · hr-attendance 3/10 · timesheet 18/35 ·
account-financial-tools 23/42 · account-financial-reporting 5/8 · bank-statement-import 16/20 ·
account-reconcile 4/19 · bank-payment 14/22 · reporting-engine 21/35 · server-ux 17/36 ·
server-tools 30/57 · account-closing 3/8 · mis-builder 5/5 · currency 2/4 · dms 2/8 (immature) ·
helpdesk 17 · l10n-ukraine 0.

## Order

1. Leaves onto `hr.leave.allocation`.
2. Payments onto `account_payment_order`.
3. Employee documents onto `hr_employee_document`.
4. Sandbox port, starting with the two pure replacements (`ua_assets`, `ua_nbu`).
All four only after the golden tests are green, so a changed sum is seen at once.
