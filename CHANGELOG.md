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
- `l10n_ua_contract`: counterparty contracts as in 1C/BAS (number, date, kind, currency, amount, term,
  payment terms). The contract travels from orders to invoices, payments and every journal item, so debts
  show per contract; posting over the contract amount warns or is refused; a closed contract takes no
  invoices; "separate accounting" gives the contract its own analytic account that lands on order and
  invoice lines. Reconciliation act (акт звірки) by partner or contract on settlement accounts 36, 37, 63,
  68, with the usual two-sided print form and an agreed/disputed status. Tests: `ua_contract`.
- `l10n_ua_defense`: defense contracts on top of contracts (customer, procurement id, price type, advance,
  VAT rate, calculation rates), delivery schedule with late marks, price calculation by the cost items of
  Resolution 309 (01-10 plus admin, selling, other, financial, profit on purchased and on own costs, VAT),
  planned from the BOM and routing with sub-assemblies exploded, actual from done manufacturing orders of
  the contract with plan-vs-actual; acceptance acts with serial numbers that close the schedule; product
  passport per serial with component serials. Print forms for all three. Tests: `ua_defense`.
- `l10n_ua_catalog`: industry packs loaded into a company in one step (Settings - Галузеві каталоги).
  A pack is JSON in any module's `catalog/` folder; loading is idempotent, picks up existing goods and
  work centres, keeps companies apart, and has an update mode. Packs: reconnaissance drones, ground
  robotic platforms, military apparel, machining subcontractor, procurement, small shop.
  `scripts/catalog_check.py` validates packs without a database (in `check_static.sh`). Tests: `ua_catalog`,
  including the drone pack priced to the kopiyka by the Resolution 309 calculation.
- `l10n_ua_dk021`: the full ДК 021:2015 classifier (9458 codes from ProzorroUKR/standards, Apache-2.0)
  with its hierarchy, search by code prefix, the code on goods and purchase lines. Tests: `ua_dk021`.
- `l10n_ua_customs`: import customs declaration (МД). Lines filled from received goods; customs value at
  the NBU rate, duty from the product's rate, excise, VAT base and VAT (Tax Code art. 190); customs fees
  spread by customs value. Posting puts each product's own duty, excise and fees into its cost through
  native landed costs (Дт 20 / Кт 3771), takes the VAT into tax credit (Дт 6412 / Кт 3771), sends the
  share of goods already issued to expenses so 3771 always gets the full amount, and refuses when the
  same VAT was already taken from a vendor bill. Print form "Розрахунок митних платежів". Tests: `ua_customs`.
- `l10n_ua_bank_1c`: the bank exchange file most Ukrainian banks offer for 1C (`1CClientBankExchange`).
  Statements import through the usual statement import: several accounts in one file, balances merged
  across days, direction from the account, counterparty by IBAN or by ЄДРПОУ/ДРФО code, Windows, DOS and
  UTF-8 files, no duplicates on a second import. Payment orders go out as the same format: from a payment
  order with the "Клієнт-банк (файл 1С)" method or from selected payments, with the bank code taken from
  the IBAN and the VAT note added to the purpose. Tests: `ua_bank_1c`.
- `l10n_ua_close`: month-end operations on the month closing card, as 1C's "Закриття місяця": post
  depreciation, revalue foreign-currency bank balances and open customer and vendor debts at the month-end
  rate (advances excluded, reversed on the 1st), move overhead 91 to cost of sales (through the overhead
  allocation document when manufacturing is installed), close classes 7 and 9 to 79 and, in the last month
  of the fiscal year, 79 to retained earnings 441 or 442. One button runs what is pending, one undoes it;
  the closing plan warns while operations are pending. Tests: `ua_close`.
- `l10n_ua_tolling`: processing customer-owned material (давальницька сировина). Each customer gets a
  storage location beside the warehouse stock, receipts there carry the customer as owner, so the material
  is not valued and other orders cannot take it. The tolling order fills materials from the BOM, receives
  them, makes a manufacturing order that takes the customer's components from that location and our own
  from stock, delivers the products, returns leftovers, invoices the processing service and prints the
  processor's report (received, norm for the output, consumed, deviation, returned, balance); it cannot be
  finished while customer material is still with us. Tests: `ua_tolling`.
- `l10n_ua_payment_request`: payment requests with approval (заявка на витрачання коштів). The requester
  says who, how much, by when and why, and may attach vendor bills and a contract. A finance approver
  decides first; above the company limit (in hryvnia, foreign currency at the rate of the day) a director
  approves too. The requester never approves their own request; a rejection needs a reason; a resubmission
  starts a new round and earlier decisions stay in the history. The accountant makes the payment from an
  approved request: with bills through the standard payment wizard, which closes them in full or in part;
  without bills as an advance. Payment calendar (pivot and calendar by due date), print form. Tests:
  `ua_payment_request`.
- `l10n_ua_correspondence`: incoming and outgoing correspondence register (menu Канцелярія). Numbers by
  direction from the start of each year without gaps (Вх/2026/0001, Вих/2026/0001); correspondent with their
  number and date; executor and deadline become a task for the executor; overdue search; an outgoing reply
  closes the incoming that needs one; register print. Documents marked ДСК (for official use) get their own
  numbering with a -ДСК mark, only staff with clearance can register or see them, and a reply to one is ДСК
  too. Tests: `ua_correspondence`.
- `docs/customization.md` and `scripts/new_pack.py`: how a team adapts the product in its own module
  (data, fields, print forms, rules) without forking the core, and a generator for such a module.
- `docs/parity/README.md`: what 1C/BAS gives a Ukrainian company, what this repository covers, the gaps
  and the order of work, with the defense-manufacturer needs first.
- `ruff.toml` and a lint step in `scripts/check_static.sh`: undefined names, unused imports and variables,
  mutable defaults in our modules and scripts. Style is not enforced.

### Changed
- `l10n_ua_changes`: the month close card counts open payslips and the timesheet as the system, so an
  accountant without payroll rights can open the close plan (it raised an access error before).
- `l10n_ua_finrep`: Form 2 and Form 2-m skip the closing journal (code CLS), so revenue and expenses
  stay in the report after the month is closed to 79.
- `l10n_ua_defense`: quality gate. A defense contract has "Випуск лише після ВТК" (on by default): its
  manufacturing orders do not close while a check item of their operations has no answer or a "no", and
  its acceptance acts refuse serials whose production did not pass. The serial passport prints every check
  with result, note, inspector and time. Products without check items are not affected.
- `l10n_ua_vat`: tax invoices and adjustment calculations take the unit's КСПОВО code and short name
  from the line's unit (кг 0301, год 0175, м2 0123 and the rest of Odoo's standard units) instead of
  always 2009 "штука". Units carry the code and short name; codes are filled on install only where empty.
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
