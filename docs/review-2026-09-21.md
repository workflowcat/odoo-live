# Odoo work review - 2026-09-21

Read-only review of every Odoo folder in `/Users/kit/Codius`. Three Opus agents read the code
(payroll logic, payroll UI, side folders); Fable measured and merged. Nothing was changed.
Goal set by Andrii: separate logic from UI, one fuller logic implementation, UI as a layer on
top, no dead code.

## 1. What exists

| Where | What | State |
| --- | --- | --- |
| `odoo-live` (main) | platform: `bp_kyc`, bridge Worker, Dockerfile + entrypoint, ARCHITECTURE.md | clean, pushed, the trunk |
| `odoo-live-payroll` (payroll) | Ukrainian payroll + HR, 32 own modules, 159 commits | the main line; 15 commits not pushed |
| `odoo-live-payroll-lite` | fork of 11 Sep; `payroll_core/` = calc + ДПС XML in pure Python, rules as JSON | tests pass; 61 commits behind payroll; also the only home of `l10n_ua_hub`, `l10n_ua_partner_edr` |
| `odoo-live-purchase` | `bp_purchase_intake` (invoice email > AI > ЄДР > draft bill), 217 lines of real Odoo tests | module already copied into payroll; branch-only: docs + scripts |
| `odoo-live-assistant` | `assistant/` Worker, employee assistant over JSON-RPC | live, but the folder is UNTRACKED - exists only on this disk; addons there are a stale copy |
| `odoo sandbox` | Odoo 18 «Дронбілд ERP», ~50 modules, 80 commits | stopped; accounting half is real (see 4) |
| `odoo-drone`, `odoo-pixelkit`, `veterans-odoo` | small Odoo 19 demos, no git | drone and pixelkit containers still running (8090, 8069) |
| `payroll-review`, `profkod`, `odoo-demo-link`, `odoo-team-plan`, `odoo-core-map`, `oblik-map` | helper sites | keep; `odoo-demo` Worker times out; `odoo-team-plan` has no git |
| `Odoo at TT` | Astro wiki, last commit 2026-06-09 | dead, overlaps `oblik-map` |
| `odoo ui review` | empty folder | delete |
| `ephemeral` | non-Odoo ERP kernel on Workers, has its own payroll rules | separate line, not part of this cleanup |

Size of the payroll line: ~16 500 lines Python, 3 700 views, 5 000 OWL (JS + templates),
2 800 SCSS, 3 200 lines of docs, 39 scripts. Own Odoo unit tests in `l10n_ua_*`: zero.

## 2. Logic - what works

Solid and worth keeping as written: salary rules and dated params (`l10n_ua_payroll_rules`),
average earnings (`l10n_ua_average`), indexation (`l10n_ua_index`), ДПС XML Д1/4ДФ/Д5/J0500111
with corrections (`l10n_ua_payroll_reports` + `l10n_ua_reporting`), orders as documents that drive
changes (`l10n_ua_hr_orders`), timesheet / staff list / ПФУ claim (`l10n_ua_hr_docs`), military
(`l10n_ua_military`), payments (`l10n_ua_payments`), hire case (`l10n_ua_hire` models), change log
and period close (`l10n_ua_changes`), explain trace (`l10n_ua_explain`), `_checks()` rows
`{level,text,fact,target}` (9 models use it), bank provider Privat/Mono (`l10n_ua_bank_online`),
`bp_purchase_intake`, `bp_kyc`.

Thin: `l10n_ua_gph` (33 lines), `l10n_ua_bank` (hook only), `l10n_ua_chart` (hook only),
`l10n_ua_payroll_account` (map without methods), `l10n_ua_kp` (data lives behind the profkod URL).

### Written twice or three times
- Salary rules: Odoo XML (27 rules) / `payroll_core/calc.py` / `payroll_core/data/rules-ua.json`.
  The Odoo copy is the fullest on every axis checked. All «виправлено 11.09» fixes are in both.
- Average, indexation, ДПС XML, rounding: same story, Odoo copy fuller (Д5, J0500111, corrections,
  maternity split, dismissal compensation, index cycle reset).
- Two check frameworks: `ua.checks.mixin` and `ua.report.check`.
- `payroll_core` golden numbers were copied from `scripts/payroll_check.py`, so it is a regression
  guard, not an independent reference.

### Still wrong in the numbers (gap-2.0, verified in code today)
TRV-02, ESV-01, ESV-04, ESV-06, DED-02, PAY-01 (real double-proportion risk for part-time
calendars), SIC-03, SIC-07, AVG-03, AVG-05, TAX-05, COR-04, REP-05. `gap-2.0.md` itself is stale
on TAX-03 and on hourly/night pay (both done).

### Tests
Of 30 check scripts: 4 independent (`payroll_check`, `import_check`, `changes_check`,
`correction_check`), 2 mixed, 9 compare the code with itself, 15 are smoke checks.
`check_all.sh` runs 6 of them and has no `set -e`. In `golden-scenarios.md` 11 of 19 scenarios are
still «рахує Odoo, підтвердити». Scenario 17 differs between the doc and the script.

## 3. UI - what works

Nine OWL screens + the employee card widget + the rail (`l10n_ua_shell`) + `/ua/print`.
Current generation: Домівка, Період, Папери, Люди, Прийняття, Звітність, Банк, Анкета, card.
Superseded but still installed: «Зведення» screen (its model still feeds home/period/bank),
`l10n_ua_payroll_ui` (all three roots disabled), 26 menu items set `active="False"`.

Working shared pieces: `ua_act` service (plan > consequences > 20 s undo, 4 call sites),
`get_screen_data` / `run_action` / `open_target` dialect on 7 screens, `_checks()` rows.
Described in docs but not in code: `_plan()` by that name, `undo_token`, the four action classes.

### Where logic and UI are fused
- ~8 300 lines of Python sit in UI-named modules vs ~7 700 lines of front-end.
- Business methods inside screen models: `ua.period.board.action_prepare_month` (creates payslip
  run, payslips, computes), month/quarter/year close plan, accept changes; `ua.papers.run_action`
  (confirm/draft for 20+ models, creates ПФУ claim); `ua.people.run_action`; `ua.bank.board` pull /
  apply rules / create provider; card: military check event, doc pack.
- `ua.hr.order.action_post` / `action_acknowledge` + field `order_id` live in `l10n_ua_card_ui` to
  dodge a dependency cycle.
- `ua.report.run.get_screen_data` creates a record on read.
- Screen models are read-only in ACL for `base.group_user` but expose writers.
- Six logic modules depend on UI modules: gph>period, kp>navigation, setup>period,
  reporting>dashboard, bank_online>dashboard, hire>navigation+shell.

### Copy-paste instead of a kit
`ua_ui.scss` scopes everything except `.o_ua_head*` to a whitelist of six screens (line 65), so
home, papers, people, card re-declare the classes. 29 class names defined in 2+ files, six
month-strip implementations, zero shared OWL components, `open_target` copied 4 times, helpers
(`_company`, `_bounds`, `_money`, `_plural`, `MONTHS_UA`) copied into 3-10 modules. 20 modules ship
menus and `l10n_ua_navigation` patches ~30 of them.

### Dead
12 SCSS selectors (6 in dashboard), 4 rail help entries for disabled menus, 4 duplicate xml ids,
`nav_check.py` asserts 5 roots (rail has 7), `dashboard_check.py` looks for the deleted hub,
`l10n_ua_payroll_ui` almost whole, 24 scripts nobody runs. Stale docs: `spec-period.md`,
`spec-documents.md`, hub references in four specs, `README.md` lists modules that do not exist.
No doc at all for home, shell, navigation, gph.

## 4. Side folders

Odoo 18 sandbox: the accounting half is real and the payroll line has none of it - `ua_vat`
(4 700 lines: first event, ПН/РК, XML), `ua_finrep` (Баланс, Ф2, Ф1-м/Ф2-м), `ua_ledger_reports`
(ОСВ, account card), `ua_cash`, `ua_assets`, `ua_cost`, `ua_fop`, `ua_nbu`, `ua_migrate` (1С/BAS
import). `RECON-19.md` already proved all 29 modules install on Odoo 19 after 9 point fixes
(15-26 h). `scripts/regress.py` = 87 invariant checks. Sandbox `ua_payroll` / `ua_hr` are weaker
than the main line: drop. Drop `drone_*`, `ua_docs_hub`, `drukarnia_theme`.

Archive: `odoo-drone`, `odoo-pixelkit` (frees port 8069; keep theme ideas), `veterans-odoo`,
`Odoo at TT`, `odoo ui review`.

Plain-value secret files (names only): `odoo sandbox/.mcp.json`, `odoo sandbox/.demo-secrets`,
`veterans-odoo/.env`, `odoo-live/.env`, `odoo-live/worker/.dev.vars`, `odoo-live-purchase/.env`,
`odoo-live-purchase/.cf/token`, `odoo-live-assistant/assistant/.dev.vars`, `payroll-review/.dev.vars`,
plus `odoo.conf` files in every stack.

## 5. Target shape

Logic (no OWL, no menus, no `web` dependency):
1. `l10n_ua_payroll` = payroll_rules + average + index + gph
2. `l10n_ua_hr` = hr_card + hr_orders + hr_docs + military + kp + onboarding + hire models
3. `l10n_ua_accounting` = payroll_account + payments + bank + bank_online models + chart
   (later: VAT, finrep, ledger, cash, assets, cost, fop, nbu, migrate from the sandbox)
4. `l10n_ua_reporting` = payroll_reports + reporting models
5. `l10n_ua_audit` = changes + explain + one check framework
plus `bp_kyc`, `bp_purchase_intake`, `l10n_ua_partner_edr`, vendored OCA untouched.

Engine: OCA `payroll` stays the engine. `payroll_core` becomes the independent reference that the
accountant's numbers are checked against, outside Odoo.

API between the layers: `get_screen_data` (read-only, enforced), `plan_action`, `run_action`,
`open_target`, `_checks()` rows, `explain`. One `ua.screen` mixin owns the helpers.

UI: `l10n_ua_ui_kit` (tokens, unscoped classes, OWL components, `ua_act`, `/ua/print`),
`l10n_ua_ui_shell` (rail + the only owner of menus), `l10n_ua_ui_screens` (JS/SCSS/templates,
no business Python), `l10n_ua_ui_card`. UI stays OWL inside Odoo: Папери embeds Odoo's editable
list and `run_action` returns `ir.actions.*`, both costly to rebuild outside. The same API lets the
assistant Worker read screens instead of raw tables.

## 6. Order of work

0. Save what exists only on disk: push payroll (15 commits), commit `assistant/`, git for
   `odoo-team-plan`, remotes for `profkod`, `odoo-core-map`, `oblik-map`.
1. Numbers first: accountant-confirmed golden set, `payroll_core` and Odoo both checked against it,
   as real Odoo tests that run without the stand. No module moves before this.
2. Add a "get_screen_data writes nothing" assertion to the screen checks.
3. Move business methods down, one screen at a time (period first). Reverse the six dependencies.
4. Merge logic modules into the five. Fix the open gap-2.0 defects inside the merged module.
5. UI kit: unscope `ua_ui.scss`, components, single menu owner, retire «Зведення» screen and
   `l10n_ua_payroll_ui`.
6. Delete dead code, stale specs, unused scripts. One README per layer.
7. Port the sandbox accounting modules into `l10n_ua_accounting` with `regress.py` as the gate.
8. Archive side folders, stop their containers, remove lite / purchase / assistant worktrees after
   lifting their unique parts.

Notes from the final UI pass:
- Before moving any file, freeze the API across all screens in one pass: `get_data` >
  `get_screen_data`, one `open_target` in a `ua.screen` mixin, no write in
  `ua.report.run.get_screen_data`. Home, period and bank all read `ua.dashboard`; papers reads
  `ua.explain` and `ua.period.close`. Moving screens one module at a time without this step ends in
  bridge modules.
- Split `ua.dashboard`: data methods stay as logic, the «Зведення» screen retires.
- `l10n_ua_card_ui/hooks.py:14-26` rewrites the views of every `hr.employee` action and a migration
  already repairs an older version of that hook. A changed install order re-runs it on a database
  that was already rewritten. Test on a copy of the stand.
- `bank_board.js:87` sends a method name from the client and the server dispatches it: an open
  method-name surface. Replace with `run_action(key)` and a fixed key list.
- The `period` block has four different shapes across screens; settle on
  `{year, month, label, closed, periods[]}`.
- Fix the check scripts before the first move: `nav_check.py:27` (5 areas, rail has 7),
  `nav_check.py:34-36` and `dashboard_check.py:136` (deleted hub), `home_check.py:174-200` and
  `papers_check.py:273` (exact asset paths per module - any rename breaks them).
- Menu roots Працівники and Папери both have sequence 2.
- `words.md` is enforced by nothing; build the lint or mark it manual.

Main risk: steps 3-4 move xml ids, data load order and method names that JS calls by string, and
today only one script checks money against human numbers. Hence step 1.
