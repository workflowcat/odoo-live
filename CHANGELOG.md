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
- `l10n_ua_prro`: PRRO fiscal receipts. A PRRO register is linked to cash and card terminal journals; a
  customer payment there makes a receipt: item by item when the documents are paid in full, one line per
  VAT rate when part is paid. The receipt goes through the integration bridge to the PRRO service with an
  idempotency key; a failure never undoes the payment, the receipt waits and a scheduler retries it. Returns
  refer to the fiscal number of the sale; service cash in and out; shifts with cash balance and a Z-report
  compared with the receipts in the books. Training mode works without the bridge. Bridge routes in
  `docs/base/spec-prro.md`. Tests: `ua_prro`.
- `l10n_ua_price_label`: price labels from the product list or form (Action - Друк цінників). Price for
  the buyer from a pricelist or the sales price, with the product's sales taxes; for packed goods with
  the content filled in (0,5 kg, 0,9 l) also the price per 1 kg, l or m; EAN-13, EAN-8 or Code 128 barcode;
  seller and date; copies; A4 sheet of 21 or 58x40 mm labels. Numbers written the Ukrainian way
  (1 240,00). Tests: `ua_price_label`.
- `l10n_ua_tolling`: finishing or cancelling an order no longer mixes pickings and manufacturing orders in
  one recordset (it raised a type error).
- `docs/customization.md` and `scripts/new_pack.py`: how a team adapts the product in its own module
  (data, fields, print forms, rules) without forking the core, and a generator for such a module.
- `docs/parity/README.md`: what 1C/BAS gives a Ukrainian company, what this repository covers, the gaps
  and the order of work, with the defense-manufacturer needs first.
- `ruff.toml` and a lint step in `scripts/check_static.sh`: undefined names, unused imports and variables,
  mutable defaults in our modules and scripts. Style is not enforced.
- `l10n_ua_eco`: engineering change notices (повідомлення про зміну) for defense production. A notice lists
  "was / now" lines against the current BOM (add, remove, replace, change quantity), is approved by the
  technologist and quality control, and by the military representative when the product was made under a
  defense contract; the author does not approve, a rejection needs a reason and the next submission starts
  a new round. Applying it on its effective date (or by the hourly job) copies the BOM as revision N+1,
  activates it and archives the old one; a second notice made from the old revision is refused. Orders and
  serial passports show the revision; the notice prints with the was/now table and the approvals.
- `l10n_ua_claim`: warranty claims (рекламації) on serial numbers. A claim takes the contract and customer
  from the passport, the warranty from the acceptance act (or the production date) and the product's
  warranty months, and the response and fix deadlines from the contract in calendar days; the responsible
  person gets one reminder that moves from the response deadline to the fix deadline. The investigation
  names the cause and the failed component; a manager decides (repair, replace a component or the
  product, refund, reject): an own defect in warranty cannot be rejected, a rejection or an out-of-warranty
  decision needs a reason. A design cause opens a change notice. Overdue and repeat failures show in the
  list; the conclusion prints on its own and the passport prints the claim history.
- `l10n_ua_military`: the critical-company status (статус критично важливого підприємства) as a record
  with the decision, criterion, term, reservation quota, wage floor in minimum wages and reminder days.
  The reserved list takes the status valid on its date and counts the quota: liable employees under an
  employment contract, reserved ones with a valid term, the quota as the whole part of the share. Its
  checks flag a list without a valid status, more reserved than the quota, a status about to end,
  reservations longer than the status and salaries below the floor. A daily job reminds before the status
  or an employee's reservation ends; archiving a reserved employee records an event and sets a task to
  report the dismissal. The quota, floor and day counts are settings on the status, not rules in code.
- `l10n_ua_defense`: penalty and fine for late deliveries. The contract holds the rates (a share per day,
  a fine after N days; defaults follow the usual state-contract wording and are meant to be checked against
  the contract), schedule lines hold the unit price. Quantities accepted by approved acts up to the
  calculation date fill the schedule lines in due-date order; a part accepted late counts days to the act
  date, a part not yet accepted counts days to the calculation date. The contract shows the amount as of
  today and prints the calculation with every late part.
- `l10n_ua_edo`: electronic document exchange with counterparties through the bridge (Вчасно, M.E.Doc,
  Paperless adapters live in the bridge). A posted invoice, reconciliation act or contract goes out as a PDF
  of its print form, one or many at once; a record that already has a sent document of the same kind is
  skipped; a missing ЄДРПОУ/РНОКПП leaves that one document "not sent" with the reason. Status, the
  counterparty's signature file and rejection reasons come back on a schedule; a retry reuses the same key;
  a reconciliation act becomes agreed or disputed with its document. Incoming documents are matched to
  vendor bills by number and signed or rejected from Odoo. Test mode works without the bridge. Contract:
  `docs/base/spec-edo.md`. Tests: `ua_edo`.
- `l10n_ua_procurement_plan`: annual procurement plan (річний план закупівель). Lines carry the ДК 021 code,
  expected value, procedure, start month and funding source. Goods and services lines of one ДК 021 class
  form one subject and their values add up, so a subject split under a threshold is an error; works lines
  stay separate. Thresholds are plan settings (defaults to be checked against Law 922-VIII and Resolution
  1178) and carry over to the next plan. An approved plan is changed only by a new revision. Confirmed
  purchase orders are compared with the plan by class. Print form and a JSON file in the Prozorro plan
  structure. Tests: `ua_proc_plan`.
- `l10n_ua_unit_transfer`: hand-over of products to a military unit outside a state contract. A donor (fund,
  community, company) buys and the unit receives, or the company gives its own products free. The act is
  built from the done delivery with serial numbers and the sale price (book value for a free transfer),
  prints for three parties with the amount in words, and marks the serials: the product passport shows the
  unit and the act, and a serial cannot be handed over twice. Partners get a military-unit flag and code.
  Tests: `ua_unit_transfer`.
- `l10n_ua_offset`: mutual offset of debts (взаємозалік) with one counterparty. "Fill" takes the open
  customer debts (36) and vendor debts (63) of the partner, by contract if chosen, oldest first, up to the
  smaller side or a set limit. Posting makes one entry Дт 63 Кт 36 whose lines are reconciled with the
  documents they close, so the usual debt reports drop; the act under article 601 of the Civil Code lists
  the documents of both sides with the amount in words. Cancel unreconciles and cancels the entry. UAH
  debts only. Tests: `ua_offset`.
- `l10n_ua_commission`: commission trade and goods on consignment, both ways. Company as commissioner:
  the consignor's goods are received with the consignor as owner, so Odoo does not value them; they sell
  through ordinary sale orders; the report to the consignor fills itself from deliveries of their goods
  and, when posted, makes the consignor's bill (on the product's income account, so revenue from their
  goods nets to zero), the commission invoice and a debt offset between the two. Company as consignor:
  own goods move to a "На комісії" location next to the warehouse; the commissioner's report delivers
  what was sold from there, invoices the commissioner and books the commission bill with an offset.
  Percent commission or a fixed consignor price; cancel undoes documents and stock; unsold goods return
  in one step. Print form of the commissioner's report. Tests: `ua_commission`.
- `l10n_ua_fleet`: waybills and fuel accounting on native `fleet`. Fuel issued to a vehicle stays company
  stock in the vehicle's own "Бак" location. The waybill records odometer, tonne-km and engine hours,
  computes the norm (base l/100 km, cargo l/100 t·km, l/hour, times the sum of adjustments; adjustments
  such as winter or city are company settings that can switch on by month), takes refuels from the
  warehouse or a fuel station at the receipt price, and on closing writes off the actual use: within the
  norm to the vehicle's expense account (23/91/92/93), the excess to its own account (949 or 375).
  Opening checks the odometer and that the vehicle is not already out; cancel reverses fuel moves and the
  odometer entry. Print form, pivot by vehicle and month. Tests: `ua_fleet`.
- `l10n_ua_mrp_plan`: multi-level production planning from defense contracts. Vendors OCA `mrp_multi_level`
  with `mrp_warehouse_calendar` (OCA/manufacture) and `stock_warehouse_calendar`
  (OCA/stock-logistics-warehouse), pinned in `addons/OCA_*.commit`. The open part of each defense delivery
  schedule (minus accepted or shipped, minus open deliveries of the contract's orders) becomes MRP demand
  on the line's date, so planned manufacturing and purchase orders appear through every BOM level before
  the customer's orders exist. One MRP area per company takes this demand (flag on the area). Tests:
  `ua_mrp_plan`.
- `l10n_ua_piecework`: piece-rate pay from production output (1C "Виробіток"). A rate per routing operation;
  the document takes the period's finished work orders with a rate, splits each quantity between workers by
  their minutes in the work order time log (no log: the worker is picked by hand), and on approval sends
  quantity × rate into open payslips as the PIECE input. Cancelling takes it out again unless the payslip is
  posted; a manual PIECE amount next to an approved document is refused, so nobody is paid twice. Print
  form "Наряд на відрядну роботу" with totals per worker; pivot by worker and operation. Tests: `ua_piecework`.
- Payroll: new rule PIECE (basic pay from an input) in the UA salary structure, mapped to expense / 661; golden
  scenario 31 and the reference calculator cover it.
- `l10n_ua_mrp_substitute`: approved component substitutes (1C "аналоги"). Each BOM line can list substitutes
  with a factor and priority; only rows approved by a production manager with a basis are used, and editing the
  product or factor drops the approval (a copied BOM revision starts unapproved). "Замінити відсутні" on a
  manufacturing order takes each component's shortage from free stock of approved substitutes, lowers the
  original demand, adds the substitute marked "instead of", and logs it in the chatter. Finishing the order
  counts the swap as consumption of the original, so no consumption warning. Tests: `ua_mrp_substitute`.
- `l10n_ua_guarantee`: advances and guarantees on contracts. A register of bank guarantees and other security
  (tender, performance, advance return, warranty), given (05) or received (06), with guarantor, amount, expiry
  and claim; a daily job reminds the responsible person before expiry and marks lapsed ones. Each sale or
  purchase contract shows its open advance from settlement entries, how much active advance-return guarantees
  cover, the deadline to work it off, and filters for open, unsecured and overdue advances. A received
  advance-return guarantee cannot be released while the advance stays open and uncovered. Tests: `ua_guarantee`.
- `l10n_ua_metrology`: measuring instruments on native maintenance equipment (range, accuracy, legally regulated
  or not, interval as a setting). Verification and calibration records with result, certificate, lab, cost and
  validity; reminders before expiry and a "do not use" reminder after; a yearly schedule print. Routing
  operations list the instruments for their quality checks: a "yes" answer is refused while any is overdue,
  failed or conserved, the answer keeps a snapshot of what was used, and the product passport prints it.
  Tests: `ua_metrology`.
- `l10n_ua_workwear`: workwear and other items issued to staff (1C "передача в експлуатацію"). Norms per job
  (item, quantity, wear period), an issue sheet that fills what selected employees lack, posts the cost from 22
  to the sheet's expense account and keeps quantities per employee with wear-until dates. Return puts the item
  back at the issue cost, write-off prints an act, and the personal card shows norms and everything issued.
  Tests: `ua_workwear`.
- `l10n_ua_grant`: grants and targeted financing. A grant agreement gets its own analytic account and a
  budget by items, each with its expense accounts; tagged entries on those accounts are the use of the grant,
  with overspend per item. Receipts are credits to 484 from the grantor (a button tags untagged ones);
  income is recognised as funds are used, never above what was received (Dr 484 Cr 718). Usage report print.
  Tests: `ua_grant`.
- `l10n_ua_export_control`: export control. A product is marked as military or dual-use with its control
  list position. A permit for an international transfer holds the importer, end user, country, term and the
  products with quantities. A delivery of such goods to a partner in another country is not validated without
  a valid permit for that partner, country and product, or above what the permit has left; a single matching
  permit is set on the delivery by itself. Expiry reminders and a usage report. Tests: `ua_export_control`.
- `l10n_ua_precious_metals`: precious metals in products. Grams of gold, silver, platinum, palladium and
  the other metals per unit on a component; a product with a BOM adds up its parts on every level plus its own
  content. The product passport prints "Відомості про вміст дорогоцінних металів". A period statement per
  metal: received from suppliers, used in production, in finished products, shipped, written off, on hand.
  Tests: `ua_precious`.
- `l10n_ua_supplier_approval`: approved suppliers of critical components. A product marked critical is bought
  only from a supplier with a valid approval (for the product, its category with subcategories, or everything;
  with decision number, basis, who approved and term). Purchase confirmation and receipt validation check it;
  an approval can be suspended after claims and withdrawn. Expiry reminders, printed list.
  Tests: `ua_supplier_approval`.
- `l10n_ua_limit_card`: limit cards (form М-8). One material, one workshop location, one month. The limit is
  set by hand or from the material demand of chosen manufacturing orders. Issues and returns are posted
  transfers with a running total; over the limit only a stock manager may issue, with a reason, and the line
  is marked. A closed card takes no issues. М-8 print. Tests: `ua_limit_card`.
- `l10n_ua_product_tests`: periodic and type tests of serial products. A product gets a test period in
  months and a first due date; protocols (periodic, type, qualification) record samples by serial number,
  result, place and the customer's representative. The acceptance act is refused while periodic tests failed
  or expired, or while type tests are pending after a design change that asks for them. Reminders and a
  protocol print. Tests: `ua_product_tests`.
- `l10n_ua_safety`: labour safety. A job says whether the work is hazardous, how often the repeat briefing
  and the medical exam are due and which instructions apply. Briefings (introductory, primary, repeat,
  unscheduled, targeted) are recorded for a group of employees; the next repeat is counted from the last passed
  primary, repeat or unscheduled one. Medical exams carry the result and validity. The employee card shows what
  blocks work today; an overdue list, reminders to the manager and the briefings journal print.
  Tests: `ua_safety`.
- `l10n_ua_military`: reservation request (заявка на бронювання). Candidates are liable employees on an
  employment contract who are not reserved or whose reservation ends within a set number of days. Each line
  shows what the Дія request lacks (tax number, birth date, military document number); the request cannot be
  marked as filed while data is missing or the reservations that stay plus the request exceed the quota.
  CSV working list, print, and the decision per line (reserved until a date or refused) carried to the
  employee card and the military events. Tests: `ua_military`.
- `l10n_ua_local_tax`: property tax, land payment and environmental tax. Objects (non-residential buildings,
  owned land plots, land rent) carry area, valuation or rent, the community's rate, ownership dates and an
  exempt flag with its basis. A yearly calculation counts the months of ownership (from the month acquired to
  the month before it was lost), posts property tax by quarters and land payment by months (Dr 92, Cr tax
  settlements), and reverses its entries when returned to draft. Environmental tax per quarter by substance,
  quantity and rate, with the list copied from the previous quarter. Print. Rates are settings: check the
  current decision of the community and the Tax Code. Tests: `ua_local_tax`.
- `l10n_ua_price_set`: price types and the price setting document. A pricelist gets a kind (retail, wholesale,
  purchase), a markup on cost and a rounding rule. The document fills from a category, a receipt or the goods
  already priced in the chosen types, shows the price in force the day before its date, computes new prices
  from cost or takes them by hand, and on posting creates fixed prices from its date and closes the previous
  ones, so the price on any date stays in history. A later price is never overwritten; cancel restores the
  previous price. Order print and price labels. Tests: `ua_price_set`.
- `l10n_ua_bad_debt`: doubtful debts reserve by aging (НП(С)БО 10). Each customer invoice's balance on the
  date counts only payments made by that date; days overdue from the due date put it into one of five groups
  whose percentages come from the accounting policy and carry over to the next calculation. A debtor can be
  assessed separately with a basis. Posting compares the result with the reserve on account 38: Dr 944 Cr 38
  for a shortfall, Dr 38 Cr 719 for an excess; return to draft reverses it. Print. Tests: `ua_bad_debt`.
- `l10n_ua_cashflow`: cash flow statement, form 3, direct method (НП(С)БО 1). Every posted entry that touches
  a cash account (prefixes 30, 31, 33 by default, as balance line 1165) is a flow; moves between cash accounts
  are left out. The cash flow item comes from the journal item, the entry (and so the bank statement line) or
  the payment; otherwise a rule by the counter account picks it (longest code match, company rules before
  shared ones, 54 default rules). Flows without an item land in 3095/3190 and are listed for the accountant,
  who can set the item from that list. Current period and the same period last year, sub-rows 3006 and
  3116-3118, opening 3405, FX effect 3410, closing 3415 checked against the cash accounts before approval,
  drill-down from each row, print with ДКУД 1801004. Tests: `ua_cashflow`.
- `l10n_ua_budget`: cash flow budget (БДДС) for a year, plan per Ф3 cash flow item and month, filled from a
  previous year's actuals with a percentage. Actuals come from the same item rules as Ф3; an item with
  actuals but no plan gets a zero-plan line so unplanned spending shows. Open payment requests count as
  committed. One approved budget per company and year checks payment requests on submit: an item is
  required, and an amount over the month's remainder either adds the director step or stops the request
  (budget setting). The request's item is written to the payment. Plan-actual pivot, print. Tests: `ua_budget`.
- `l10n_ua_vacation_plan`: vacation schedule for a year (articles 10 and 12 of the Law on Vacations). Fill
  from the company or a department (employment contracts only); parts with dates in calendar days; checks
  for missing dates, overlaps, no continuous part of 14 days, more days than available (balance on 1 January
  plus the yearly right) and employees left out. Approval needs the body it was agreed with. A daily job
  gives HR a task two weeks before each start, with a printed notice; moves keep the old dates and the basis;
  leave requests are created from the schedule. Print, calendar. Numbers are settings. Tests: `ua_vacation_plan`.
- `l10n_ua_defect`: production defect act (account 24). Opened from a manufacturing order with the materials cost
  per unit; product, serials, quantity, final or correctable, cause, culprit, supplier. Final defects move
  their cost from work in progress (Dr 24 Cr 23), correctable ones list correction costs by account. Posting
  clears 24 to salvage (209), recovery from the culprit (375, with the employee as partner), a claim to the
  supplier (374) and losses to production cost (23) or other expenses (949); return to draft reverses.
  Analysis by cause and product, print. Tests: `ua_defect`.
- `l10n_ua_equity`: statement of changes in equity (form 4). Columns by equity accounts 40-46 as balance lines
  1400-1430; profit or loss of classes 7-9 goes to row 4100 as one sum, so closing 79 to 44 nets to zero inside
  the column. Each equity journal item gets its row from a mark on the item or entry (adjustments 4005, 4010,
  4090), else from the most specific rule by equity account, debit or credit, and counter account; 39 default
  rules (dividends, reserve, contributions, buyback, revaluation and others), company rules first, the rest in
  4290 and listed. Current and previous year, closing checked against account balances per column, rows 4205
  and 4210 checked to net to zero, drill-down, landscape print. Tests: `ua_equity`.
- `l10n_ua_notes`: notes to the annual financial statements (form 5), main sections. I and II: movement of
  intangible and fixed assets by account group in columns 3-15, every journal item in exactly one column
  (revaluation by counter 41/746/975, transfers between groups as other changes, impairment by 972/742),
  depreciation split by the asset on the item, else by the counter account, unassigned rows flagged. III
  capital investments, IV financial investments (row and measurement basis set on the account), V other
  income and expenses by row (checked against classes 71-74 and 94-97), VI cash, VII provisions (accrued,
  used, reversed), VIII inventories with write-downs and increases of net realisable value, IX receivables by age (each partner's balance laid on its newest debits),
  X shortages, XII income tax, XIII depreciation charged checked against I and II. Landscape print.
  Tests: `ua_notes`.
- `l10n_ua_headcount`: average headcount (середньооблікова кількість) by month and for a quarter or a year,
  from the П-5 timesheets: weekends count as the previous working day, part-time staff by hours worked,
  maternity and childcare leave left out (codes are a setting); headcount at month end, hires, dismissals,
  hours worked; missing timesheets are created the same way as the daily cron does; print.
  Tests: `ua_headcount`.
- `l10n_ua_asset_inventory`: inventory count of fixed assets and intangibles: count sheet from the asset
  register (filters by custodian, place, profile) with cost, depreciation and residual value on the date;
  the commission marks found items, place, custodian and condition and adds surplus items. Posting the
  results removes missing assets through the OCA removal wizard with the residual value on 947, books the
  culprit's share Dr 375 Cr 716, books surplus Dr asset account Cr 746 (OCA creates the asset) and writes the
  new place and custodian into the asset. Count sheet and comparison sheet print. Tests: `ua_asset_inventory`.
- `l10n_ua_disability_quota`: quarterly employment norm for persons with disabilities and the targeted
  contribution that replaced the sanctions in 2026: average headcount for the quarter from the timesheets
  (shared with `l10n_ua_headcount`), the norm, employees with disabilities counted by month (main job, pay
  above the minimum wage, group I counted twice) with the reason when not, unfilled places, the average
  wage from payslips without sick pay and the contribution with the martial-law factor. All numbers are
  fields of the document; the DPS report form is not produced. Tests: `ua_disability_quota`.
- `l10n_ua_cash_count`: cash count act (акт інвентаризації наявних коштів): the book balance of the cash
  journal account on the date from posted entries, the count by banknotes and coins (one button adds the
  usual hryvnia set) or as one sum, and on approval the difference is posted: shortage Dr 375 with the
  cashier or another person, or Dr 947, Cr cash; surplus Dr cash Cr 719. The act prints with the cashier
  statement and the last order numbers. Tests: `ua_cash_count`.

### Changed
- Packs: defense packs bring their typical jobs with labour safety terms (hazardous work, repeat briefing and
  medical exam periods, instructions) and the shop pack brings retail and wholesale price types with markup and
  rounding, through the generic `records` section. A record whose model is not installed is skipped and
  reported, like an unknown field.
- Defense packs `defense_uav` and `defense_ugv`: finished products are marked dual-use under export control
  with periodic tests once a year, and flight electronics, data links and optics are critical components
  bought only from approved suppliers (applied when those modules are installed; notes say to check).
- `l10n_ua_correspondence`: a reply made with the "Відповісти" button now gets an outgoing number
  (Вих/...), and a restricted flag passed the same way needs clearance like a typed one.
- `l10n_ua_prro`: a sale right after the Z-report in the same transaction opens a new shift instead of
  hitting the "one open shift" rule.
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
