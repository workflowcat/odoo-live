# Parity with 1C / BAS

What a Ukrainian company gets from a typical 1C/BAS setup (Бухгалтерія, ЗУП, Управління торгівлею,
КУП/ERP, Роздріб, Документообіг, plus the platform and the partner ecosystem), what this repository does
today, and what is missing. Written 2026-11-07 against `main`; the order of work is at the bottom.

Legend: **done** - covered, with tests; **part** - the basics work, named pieces missing; **gap** - not here.
"Odoo" means Odoo 19 Community, "OCA" a community module we can vendor.

## 1. Accounting and tax (BAS Бухгалтерія)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Chart of accounts, short codes, sub-accounts | done | `l10n_ua_chart` on Odoo's `ua_psbo` |
| Trial balance (ОСВ), account card, account analysis | done | `l10n_ua_ledger` |
| Primary documents: invoice for payment, act, delivery note, waybill | done | `l10n_ua_docs*` |
| VAT: first event, tax invoices, adjustments, ЄРПН XML, customs VAT | done | `l10n_ua_vat` |
| VAT return with annexes in DPS XML | done | `l10n_ua_vat_return`: the monthly return J0200126 from the VAT summary, rows 16.1-21 carried between months, annex Д2 by period and supplier, both files validated by the DPS schemas; annexes Д1, Д3-Д6 and the clarifying return are not built |
| Profit tax return | done | `l10n_ua_profit_tax`: the annual return with annex РІ (book and tax amortisation, prior-year loss with the large-taxpayer share), yearly or quarterly payer, and the DPS XML J0100129 + J0111829 linked and validated by the bundled schemas |
| Single tax (FOP group 3) book and return | done | `l10n_ua_fop` |
| Financial statements Ф1/Ф2 (full and small) | done | `l10n_ua_finrep` (mis_builder), small forms in the rows of the current form; `l10n_ua_finrep_dps`: the filing for a quarter, half-year, 9 months or year with both columns (start and end of year for the balance, this and last year for results) in thousands, totals rechecked after rounding with manual correction, and the DPS XML J0900108, J0900207, J0901107 validated by the bundled schemas. Signing and sending stay in the reporting program |
| Cash flow statement Ф3 (direct method) with cash flow items (статті руху коштів) | done | `l10n_ua_cashflow`: every entry that touches cash accounts (30, 31, 33, as balance line 1165) is a flow, moves between cash accounts are not; the item comes from the journal item, the entry or bank statement line, or the payment, otherwise from a rule by the counter account (longest code match, company rules first); flows without an item listed for the accountant; current and same period last year, opening 3405, FX effect 3410, closing 3415 checked against the books, drill-down from every line to the entries, print |
| Statement of changes in equity Ф4 | done | `l10n_ua_equity`: columns 3-9 by equity accounts 40-46 as balance lines 1400-1430, profit or loss of classes 7-9 in row 4100 as one sum so closing account 79 never doubles it; the row for each equity movement comes from a mark on the journal item or entry (adjustments 4005, 4010, 4090), otherwise from a rule by equity account, side and counter account (39 default rules after the Ministry of Finance guidance, company rules first); movements without a rule listed for the accountant; current and previous year, 4095, 4295, 4300 checked against the books per column, rows 4205 and 4210 checked to net to zero, drill-down from every row, landscape print |
| Notes to the financial statements Ф5 | partial | `l10n_ua_notes`: sections I and II (movement of intangible and fixed assets by account group: additions, revaluation, disposals, depreciation, impairment, other changes; depreciation split by the asset on the journal item, else by the counter account, the rest flagged), III capital investments, IV financial investments (row and measurement basis set on accounts 14 and 352; 141 without a row shown as associates and flagged), V other income and expenses by row (sums checked against classes 71-74 and 94-97, closing to 79 left out), VI cash, VII provisions, VIII inventories with write-downs, IX receivables by age (each partner's balance laid on its newest debits), X shortages, XII income tax, XIII depreciation charged; closing balances checked against the books, landscape print. Sections XI, XIV, XV (construction contracts, biological assets) not filled yet |
| Fixed assets, low-value items, intangibles, tax groups | done | `l10n_ua_assets` + OCA asset management |
| Inventory count of fixed assets and intangibles (інвентаризація необоротних активів) | done | `l10n_ua_asset_inventory`: count sheet from the asset register with book values on the date, commission marks (found, place, custodian, condition), surplus items; results: shortage written off through the OCA removal at residual value to 947 and the culprit's share 375/716, surplus to 746 creating the asset; count sheet and comparison sheet print |
| Cash desk: ПКО/ВКО, cash book КО-4, limit | done | `l10n_ua_cash` |
| Cash count act (акт інвентаризації наявних коштів) | done | `l10n_ua_cash_count`: book balance of the cash account on the date, cash counted by denominations or as a sum, shortage to the cashier or another person (375) or to expenses (947), surplus to income (719), the act with the cashier statement prints |
| Bank statements: file, PrivatBank, Monobank | done | `l10n_ua_bank`, `l10n_ua_bank_online` |
| Bank exchange file `1CClientBankExchange` (most Ukrainian banks) | done | `l10n_ua_bank_1c`: statements in through the usual import, payment orders out from payments or payment orders |
| NBU rates, FX differences | done | `l10n_ua_nbu` + native |
| **Counterparty contracts** (settlements by contract, currency, limits) | done | `l10n_ua_contract`: contract on invoices, payments and orders, limits that warn or block, analytic per contract |
| **Reconciliation act** with a counterparty (акт звірки) | done | `l10n_ua_contract`: by partner or contract, two-sided print form, agreed or disputed |
| Mutual offset of debts (взаємозалік) | done | `l10n_ua_offset`: open customer and vendor debts of one counterparty (by contract if chosen), oldest first, one entry 63 to 36 reconciled with the documents it closes, two-sided act under article 601 of the Civil Code, cancel restores the debts; UAH only |
| Doubtful debts reserve (резерв сумнівних боргів) | done | `l10n_ua_bad_debt`: aging of customer invoices on a date (only payments made by that date count), five groups with percentages from the accounting policy carried to the next calculation, a debtor assessed separately with its basis, the difference with the reserve on 38 posted as Dr 944 Cr 38 or Dr 38 Cr 719, reversal on return to draft, print |
| Month-end closing assistant (закриття місяця) | yes | `l10n_ua_close`: depreciation, FX revaluation with reversal, overhead 91, 7/9 to 79, 79 to 44 in order, with undo; period lock and change review in `l10n_ua_changes` |
| Property and land tax, environmental tax | yes | `l10n_ua_local_tax`: buildings and land plots (owned or rented) with area, valuation, the community's rate and ownership dates, exempt objects with their basis; yearly calculation counting months of ownership, property tax by quarters and land payment by months as entries Dr 92 Cr tax settlements, reversal on return to draft; environmental tax per quarter by substance with the list copied from the previous quarter; print. DPS XML of the declarations is still a gap |
| Statistical reports (Держстат) | gap | low priority |
| E-signature (КЕП) and sending reports, ЄРПН registration | gap | XML files are produced; signing and sending stay in M.E.Doc/Вчасно or a bridge route |
| Electronic document exchange with counterparties | done | `l10n_ua_edo`: invoices, acts, waybills, contracts and reconciliation acts out as PDF through the bridge (one or many at once, no double sends), status and the counterparty's signature back, rejection with a task, paper signature; incoming documents matched to vendor bills, signed or rejected from Odoo. Service adapters in the bridge are separate work |

## 2. Payroll and HR (ЗУП)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Payroll with Ukrainian rules, average earnings, indexation | done | `l10n_ua_payroll_rules`, `l10n_ua_average`, `l10n_ua_index`, 38 golden scenarios; military service with the job kept (no pay, no minimum ЄСВ in a month with nothing accrued); piece-rate pay from production (`l10n_ua_piecework`) |
| Sick leave (employer and PFU parts), vacations, business trips | done | `l10n_ua_average` |
| Unified tax report (ПДФО/ВЗ/ЄСВ) with annexes, XML | done | `l10n_ua_payroll_reports`: Д1 marks 21-24 and 26 from the contract (special seniority, new workplace, unfixed hours), staff on military service without a payslip as zero rows, a late correction payslip reported in the current month with its sick and maternity pay as rows for their own month (code 13), rows shown and edited before the files are built. Vacation pay spread to later months (code 10) and annex Д6 are not built |
| Payroll statement with balances per employee | done | `l10n_ua_payroll_account`: «Розрахункова відомість з сальдо» - opening balance, accrued, withheld, paid and closing balance on 661 per employee from posted entries, printed with signatures |
| HR orders, staff list, timesheet П-5, personal card П-2 | done | `l10n_ua_hr_*` |
| Hiring case to filed notice | done | `l10n_ua_hire` |
| Employee documents from Diia (шеринг) instead of scans | gap | Researched in `docs/base/spec-diia.md`: one document per request is free (an ID card fills 12 hiring fields and comes as a signed PDF), each employer connects on its own, the package arrives through the bridge and is decrypted on the company's server. The check that the e-military document was formed no more than 72 hours before the first working day (from 2026-06-27) is not built yet |
| Military registration, TCC notices | done | `l10n_ua_military` |
| **Reservation of employees** (бронювання) of critically important companies | done | `l10n_ua_military`: data on the employee card; the critical-company status with its term, quota and wage floor; quota and deadline checks on the reserved list; reminders before the status or a reservation ends; a task when a reserved employee leaves; a reservation request: candidates (not reserved or ending soon), missing data that blocks the Дія request, quota with the reservations that stay, CSV working list and print, decisions carried to employee cards and military events (check the current Дія form) |
| Civil contracts (ЦПХ) | done | `l10n_ua_gph` |
| Diia City payroll: employees and gig specialists | part | `l10n_ua_payroll_rules`: resident flag on the company, ПДФО 5 % from pay and gig rewards (gifts and other non-pay income stay at 18 %), ЄСВ as one minimum contribution a month, a month marked non-compliant falls back to general rates, «Дія Сіті за місяцями» with headcount, average reward in euro and the 240 000 EUR yearly limit; `l10n_ua_diia_city`: gig fee in the contract currency, act at the NBU rate on the act date printed in both currencies, reward and bonus into the payslip; report codes 102 (4ДФ) and 83/82 (Д1); payroll accounts from the employee card. Golden scenarios 32-36 wait for an accountant. Separate Д1 rows 29 and 42 for residents are not built |
| Labour safety: briefings journal, repeat terms by job, medical exams (охорона праці) | done | `l10n_ua_safety`: jobs marked as hazardous with repeat-briefing and medical-exam periods (company settings, check the current edition of the standard regulation), briefings of five kinds for a group of employees with instructor and instructions, a not-passed line does not count, medical exams with result and validity, what blocks an employee today, overdue list, reminders to the manager, journal print |
| Vacation schedule (графік відпусток) | done | `l10n_ua_vacation_plan`: yearly schedule for the company or a department (employment contracts only), parts with dates in calendar days, checks for missing dates, overlaps, a continuous part of at least 14 days and more days than the employee has (balance on 1 January plus the yearly right), approval only with the body it was agreed with, a task for HR two weeks before each start with a printed notice, moves with a basis keeping the old dates, leave requests from the schedule, print and calendar |
| Average headcount (середньооблікова кількість) by month, quarter, year | done | `l10n_ua_headcount`: from the П-5 timesheets, weekends as the previous working day, part-time by hours, maternity and childcare leave left out (codes are a setting), headcount at month end, hires, dismissals, hours worked; print |
| Employment norm for persons with disabilities and the 2026 targeted contribution (норматив робочих місць, цільовий внесок) | done | `l10n_ua_disability_quota`: quarterly average headcount from the timesheets, the norm (one place for 8-25, 4 % above), employees with disabilities counted by month (main job, pay above the minimum wage, group I twice), unfilled places, average wage from payslips without sick pay, the contribution with the martial-law factor; every number is a setting. The DPS report J0500701 itself is not produced |
| Labour statistics forms, vacancy reports | gap | the numbers come from `l10n_ua_headcount` and payslips; the Держстат form itself is low priority |

## 3. Trade and procurement (Управління торгівлею)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Sales and purchase orders, deliveries, returns | done | native |
| Price types, discounts | done | native pricelists and discounts; `l10n_ua_price_set`: a pricelist becomes a price type (retail, wholesale, purchase) with a markup on cost and a rounding rule; the price setting document (встановлення цін) fills from a category, a receipt or the type's current goods, shows the price in force, computes new prices or takes them by hand, and sets them from its date while the previous price stays in history; a later price is never overwritten, cancel restores the previous one; order print and price labels |
| Purchase requests and approvals | done | OCA `purchase_request`, `l10n_ua_purchase` |
| Supplier risk, invoices from email | done | `l10n_ua_purchase`, `bp_purchase_intake`, `bp_kyc` |
| Debt control by contract, credit limits | done | `l10n_ua_contract`: balance by contract, contract amount as a limit |
| Commission trade, consignment | done | `l10n_ua_commission`: both roles. As commissioner the consignor's goods sit in stock with the consignor as owner (not valued), sell through normal orders, and the report to the consignor fills itself from those deliveries and makes the consignor's bill, the commission invoice and the offset. As consignor own goods move to a "На комісії" location; the commissioner's report writes off what was sold and makes the invoice, the commission bill and the offset. Percent commission or consignor price; customer returns stay manual |
| **Customs declarations (МД)** for imported goods: duty and VAT into cost | done | `l10n_ua_customs`: declaration from received goods, duty, excise and fees into each product's cost (native landed costs), VAT into credit; declaration XML exchange with the customs service is out of scope |
| Public procurement (Prozorro), ДК 021 codes on goods | done | `l10n_ua_dk021`: full classifier, code on goods and purchase lines; `procurement` pack; `l10n_ua_procurement_plan`: annual plan with the subject by ДК 021 class, procedure checked against thresholds (split subjects show up), revisions instead of edits, plan against confirmed purchase orders, print and a Prozorro plan file. Tender documents and bids stay on the e-platform |
| **Kinds of goods with characteristics, naming templates** (види номенклатури, характеристики, шаблони найменувань) | done | `l10n_ua_component`: 55 kinds (metal stock, fasteners, tools, measuring instruments, bearings, seals, drone parts, cable) with typed characteristics and units; a name like «болт оцинк. M8*30 кл.8,8 DIN 933» is parsed into kind and values; name and code from the kind's template; one fingerprint per item finds duplicates under different names; mass per metre, square metre and piece from the grade's density, per-product units (metre, bar, sheet; kilogram of bolts from mass per 1000). Reference values carry a "check the current edition" note |
| **Analogs** (аналоги номенклатури) | done | `l10n_ua_component`: candidates by the kind's rules: must match, equal or equivalent (DIN 933 = ISO 4017, ГОСТ 7798; 40Х = 41Cr4), not lower (10.9 for 8.8); full replacement or replacement with a check that says what to check (spanner size M10 17 → 16 mm); saved list; proposal to BOM substitutes approved in production (`l10n_ua_mrp_substitute`) |
| Nomenclature clean-up on a move from 1C | done | `l10n_ua_component`: intake document from a 1C or Excel export or from existing goods: parsed, grouped by fingerprint, applied as goods with kinds; duplicates without movements archived; worked example of 105 lines in `intake_example/` |
| **Supplier nomenclature and price lists** (номенклатура постачальників, завантаження прайсів) | done | `l10n_ua_supplier_catalog`: a price-list profile per supplier (columns, VAT in or out, per unit, pack, 100 or 1000); import from CSV or Excel matched by supplier code, by fingerprint or by name; vendor prices with the supplier's unit (kilogram of bolts converts to pieces); price change against the last list; comparison per base unit; new goods from unmatched lines; where to look for suppliers (Prozorro contracts by ДК 021 code, marketplaces, the register) |

## 4. Production (КУП / ERP)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Bills of materials, routings, work orders | done | native `mrp` |
| Monthly cost calculation by product and cost item | done | `l10n_ua_mrp` (materials, labour, overhead by normal capacity) |
| **Planned calculation (планова калькуляція)** of a product's price by cost item | done | `l10n_ua_defense`: plan and actual by the Resolution 309 items from BOM, routing and contract rates |
| Serial and lot tracking | done | native |
| Quality control (ВТК), inspections | done | check items on routing operations, yes/no answers on work orders (`l10n_ua_mrp`); defense contracts block release and acceptance until every item is "yes" and print the results in the serial passport (`l10n_ua_defense`); incoming and outgoing protocols (`l10n_ua_stock_docs`) |
| Tolling (давальницька сировина) | yes | `l10n_ua_tolling`: customer material in its own owner-tagged location (not valued, off-balance 023), production from it, return of products and leftovers, processing invoice, processor's report with norm vs actual |
| Workwear and low-value items in use (спецодяг, МШП, передача в експлуатацію), personal card | yes | `l10n_ua_workwear`: free-issue norms per job (item, quantity, wear period; a setting), issue sheets that fill what employees lack and post the cost to the sheet's expense account, quantity tracking per employee with wear-until dates, return to stock at issue cost, write-off act, personal card print |
| Limit cards (лімітно-забірна картка, М-8): material issue to a workshop within a monthly limit, over-limit issue | типова форма № М-8 (check the current edition); limits from material norms | done: `l10n_ua_limit_card`: one material, one workshop location, one month; limit by hand or from the material demand of planned manufacturing orders; each issue and return is a posted transfer with a running total; over the limit only a stock manager with a reason; closed card takes nothing; М-8 print |
| Defects in production (брак, рахунок 24): defect act, correctable and final, culprit, supplier claim | done | `l10n_ua_defect`: act from the manufacturing order with the materials cost per unit, serials, cause and culprit; final defects take their cost from work in progress, correctable ones list the correction costs; account 24 is cleared to salvage (209), recovery from the culprit (375), a claim to the supplier (374) and the rest to production cost (23) or other expenses (949); reversal on return to draft; analysis by cause and product, print |
| Engineering changes, BOM versions | done | `l10n_ua_eco`: change notices with was/now lines, approvals (technologist, quality, military representative), BOM revision N+1 on the effective date |
| Component substitutes (аналоги, заміни) | done | `l10n_ua_mrp_substitute`: substitutes per BOM line with a factor and priority, usable only after the production manager approves them with a basis (change notice, customer representative's decision); any change drops the approval. "Замінити відсутні" on the MO covers shortages from free stock of approved substitutes and marks each line "instead of"; the consumption check counts the approved swap as consumption of the original |
| Production planning (MPS/MRP) | done | OCA `mrp_multi_level` over all BOM levels; open defense delivery schedules are demand (`l10n_ua_mrp_plan`) |
| Piece-rate pay from production output (відрядна оплата, виробіток) | done | `l10n_ua_piecework`: rate per routing operation; the "Виробіток" document takes finished work orders of the period, splits the quantity between workers by their logged time, and sends quantity × rate to the payslip as PIECE (basic pay, all taxes); print form of the piece-work order; cancel blocked once the payslip is posted |
| Repairs and warranty returns | done | native `repair`; `l10n_ua_claim`: claims on serial numbers, warranty from the acceptance act, contract deadlines, investigation, decision, history in the passport |
| Vehicles: waybills, fuel norms, fuel write-off (подорожні листи, ПММ) | done | `l10n_ua_fleet` on native `fleet`: each vehicle has its own "tank" location; the waybill takes odometer, tonne-km and engine hours, the norm with seasonal and city adjustments (company settings), refuels from stock or a fuel station, and writes off actual use - within the norm to the vehicle's expense account, over it to a separate account; cancel restores fuel and odometer |

## 5. Retail (Роздріб)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Point of sale | part | native `point_of_sale` |
| **Fiscalisation (ПРРО/РРО)** | done | `l10n_ua_prro`: a receipt for each customer payment in a cash or terminal journal, returns, service cash in and out, shifts with the Z-report checked against the books; the PRRO service sits behind the bridge (`docs/base/spec-prro.md`), a training mode works without it. Receipts from the native point of sale are next |
| Shop catalogue, price labels, cash discipline | done | `small_shop` pack (goods, in-store barcodes, weighed goods); `l10n_ua_price_label` (price with VAT from a pricelist, price per kg or litre for packed goods, barcode, A4 sheet or 58x40 labels); cash in and out through `l10n_ua_prro` |

## 6. Document flow (Документообіг)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Incoming and outgoing correspondence register | done | `l10n_ua_correspondence`: yearly numbering without gaps, executor and deadline with a task, reply closes the incoming, register print, ДСК numbered apart and visible only with clearance |
| Approvals of documents and payments | done | purchase request approvals; `l10n_ua_payment_request`: finance and director steps by limit, payment from the request, payment calendar |
| Cash flow budget (БДДС) with control of payment requests | done | `l10n_ua_budget`: plan by Ф3 cash flow item and month, filled from last year's actuals with a percentage; actuals by the same item rules as Ф3, unplanned items get their own line; committed amounts from open payment requests; an approved budget requires an item on every request and sends a request over the month's remainder to the director or stops it (a setting); the request's item goes into the payment; plan-actual pivot and print |

## 7. Platform and ecosystem

| 1C platform | Here |
| --- | --- |
| Configurator and extensions (розширення) | Odoo modules and inheritance. Per-team changes go into a team pack, never into core: see `docs/customization.md` and `scripts/new_pack.py` |
| External print forms and processing (зовнішні обробки) | QWeb templates in a team pack; scripts against `ua.api` over JSON-RPC |
| Universal report (СКД) | list/pivot/graph views with grouping, `report_xlsx`, `mis_builder` |
| Data exchange (EnterpriseData, Конвертація даних) | `l10n_ua_migrate` imports counterparties, goods and balances from 1C files; continuous two-way exchange during a move is a gap |
| Row-level security (RLS) | record rules |
| Edit lock date (дата заборони редагування) | OCA lock dates + `l10n_ua_changes` |
| Typical configurations for an industry | **packs** in `l10n_ua_catalog`: four defense packs, `procurement`, `small_shop`; a team adds its own as JSON (`docs/customization.md`) |
| Updates of regulated forms (ІТС) | dated parameters (`ua.payroll.param`), versioned XML formats, golden scenarios; a public changelog |

## 8. Defense manufacturers (first vertical)

What a Ukrainian maker of drones, ground stations and their parts needs on top of a standard setup. The
payload in our catalogues is a camera; nothing here covers munitions.

| Need | Source | Plan |
| --- | --- | --- |
| State contract register: customer (МОУ, ДОТ, other), number, items, schedule, advances, penalties | Закон «Про оборонні закупівлі» № 808-IX; постанова КМУ № 363 (2021) | done: `l10n_ua_defense` on top of `l10n_ua_contract`; penalty and fine for late deliveries from the schedule and acceptance acts, rates as contract terms |
| Advances and their security: bank guarantees (tender, performance, advance return, warranty), registers 05 and 06, advance per contract and how much a guarantee covers | Закон «Про публічні закупівлі» (забезпечення); contract terms for advance deadlines | done: `l10n_ua_guarantee`: guarantee register with expiry reminders and auto-expiry; advance received or paid per contract from settlement entries, covered and uncovered amounts, deadline with overdue reminder; a received advance-return guarantee cannot be released while the advance is still open and not covered by another one |
| Grants and targeted financing (Brave1 and donor programmes): budget by items, use of funds, income recognition, report to the grantor | НП(С)БО 15 (income from targeted financing as costs are incurred); the grant agreement | done: `l10n_ua_grant`: grant with its own analytic account, budget items with expense accounts, receipts on 484 tagged from the grantor, use from tagged entries with overspend per item, income recognition Dr 484 Cr 718 up to the amount received, usage report |
| Export control: goods of military purpose and dual use, permits for international transfers, shipments abroad only under a valid permit, use of each permit | Закон «Про державний контроль за міжнародними передачами товарів військового призначення та подвійного використання»; постанови КМУ про порядок і контрольні списки (check the current edition) | done: `l10n_ua_export_control`: product flag with control category and list position, permit (importer, end user, country, products and quantities, term), delivery abroad refused without a matching permit or above its remainder, the permit set on the delivery by itself, expiry reminders, usage report |
| **Separate accounting of actual costs by contract** | постанова № 363: виконавець веде окремий облік фактичних витрат за контрактом | done: analytic account per contract, actual calculation from closed orders and bills, plan vs actual by item |
| **Price calculation by the regulated cost items** (01 сировина ... 10 зворотні відходи, then overhead, admin, selling, financial, other, profit) | постанова КМУ № 309 (2021), пп. 11-13 | done: plan from BOM and routing with the contract's rates, printable with materials breakdown |
| Acceptance by the customer's representative (військове приймання), quality records | contract terms | done: acceptance act per batch with serials; inspection checks on routing steps gate release and acceptance; results in the passport |
| Measuring instruments: periodic verification (повірка) and calibration, certificates, schedule; quality checks only with fit instruments | Закон «Про метрологію та метрологічну діяльність»; intervals for legally regulated instruments set by the authority (a setting per instrument) | done: `l10n_ua_metrology` on native maintenance equipment: verification records with certificate and lab, validity, reminders, yearly schedule print; routing operations name their instruments, a "yes" answer is refused with an overdue, failed or conserved one, and the passport prints which instrument and verification were used |
| Approved suppliers of critical components (перелік погоджених постачальників), suspension after claims | the contract and the company's quality system (AQAP / ДСТУ ISO 9001 requirements as agreed with the customer) | done: `l10n_ua_supplier_approval`: critical flag on a product, approval per supplier for products, categories (with subcategories) or everything, with term, basis and who approved; a purchase order with a critical item is not confirmed and a receipt is not validated without a valid approval; suspend, withdraw, expiry reminders, printed list |
| Product passport / log per serial, spare parts kits (ЗІП) | contract terms | done: passport per serial with components' serials; ЗІП as a kit BOM in the drone pack |
| Precious metals in products (облік дорогоцінних металів): content per component, the passport section, receipts and use for the yearly report | Закон «Про державне регулювання видобутку, виробництва і використання дорогоцінних металів і дорогоцінного каміння та контроль за операціями з ними»; накази Мінфіну про облік (check the current edition) | done: `l10n_ua_precious_metals`: grams per metal on components from datasheets, rolled up through multi-level BOMs plus the product's own (plating), "Відомості про вміст дорогоцінних металів" in the product passport, period statement per metal: received, used in production, in finished products, shipped, written off, on hand |
| Design changes agreed with the customer's representative, revision on every serial | contract terms; ЄСКД change-notice practice | done: `l10n_ua_eco`; the military representative signs when the product was made under a defense contract; the passport shows the revision |
| Periodic and type tests of serial products; acceptance suspended while tests are failed, overdue or pending after a design change | the product's technical conditions and the contract (periodicity and scope); state defense standards on product acceptance as applied by the customer (check the current edition) | done: `l10n_ua_product_tests`: periodicity per product with the first due date, test protocols (periodic, type, qualification) with samples by serial, result, place and representative, validity from the protocol date; the acceptance act is refused while periodic tests failed or expired or type tests are pending; a design change can require type tests; reminders; protocol print |
| Claims (рекламації) from units: deadlines, warranty, root cause, replacement, repeat failures | contract terms | done: `l10n_ua_claim`; the passport prints the claim history; a design cause opens a change notice |
| Imported components: customs declaration, duty and VAT in cost | Митний кодекс, ст. 49-58; ПКУ, ст. 190 | done: `l10n_ua_customs`; duty-free import under defense benefits goes as a 0 % duty rate or a VAT basis on the line |
| Reservation of employees | постанова КМУ № 76 (2023) and its changes | done: status, quota, wage floor, deadlines; reservation request with candidates, missing data, quota, CSV working list for Дія and decisions carried to the cards; the numbers are settings on the status, checked against the current edition |
| Donor-funded deliveries to units | civil and tax rules on charity | done: `l10n_ua_unit_transfer`: a three-party act (maker, donor, unit) or a free transfer from the company, built from the delivery with serials and the order price or book value; the passport shows the unit; a serial cannot be handed over twice. Tax effects of a free transfer stay with the accountant |

Sources checked on 2026-11-07: Resolution 309 cost items and price formula (paragraphs 11-13; profit
formulas are images in the published text, so rates stay contract settings), Resolution 363 separate cost
accounting. Read the current edition before relying on any rule; martial-law resolutions change the
procedure (for example № 335 of 2022, № 1275 of 2022).

## Order of work

Done on 2026-11-07: counterparty contracts and reconciliation acts (`l10n_ua_contract`); defense contracts
with the Resolution 309 calculation, separate cost accounting, acceptance acts and passports
(`l10n_ua_defense`); КСПОВО unit codes in tax invoices; the ДК 021 classifier (`l10n_ua_dk021`); industry
packs and their loader (`l10n_ua_catalog`); `docs/customization.md` and `scripts/new_pack.py`; the import
customs declaration (`l10n_ua_customs`); the 1C bank exchange file (`l10n_ua_bank_1c`);
quality gate on defense production with results in the serial passport; month-end operations
(`l10n_ua_close`) with Form 2 kept intact after closing; tolling (`l10n_ua_tolling`); payment requests with
approval (`l10n_ua_payment_request`); the correspondence register with ДСК access (`l10n_ua_correspondence`);
PRRO fiscal receipts through the bridge (`l10n_ua_prro`); price labels (`l10n_ua_price_label`);
change notices (`l10n_ua_eco`) and claims (`l10n_ua_claim`); electronic document exchange
(`l10n_ua_edo`); the annual procurement plan (`l10n_ua_procurement_plan`); deliveries to military units
(`l10n_ua_unit_transfer`); mutual offset of debts (`l10n_ua_offset`); commission trade
(`l10n_ua_commission`); waybills and fuel (`l10n_ua_fleet`); multi-level production planning
from defense delivery schedules (`l10n_ua_mrp_plan` on OCA `mrp_multi_level`); piece-rate pay
from production output (`l10n_ua_piecework`); approved component substitutes (`l10n_ua_mrp_substitute`); advances and bank guarantees on
contracts (`l10n_ua_guarantee`); measuring instruments and their verification (`l10n_ua_metrology`); workwear and items in use
(`l10n_ua_workwear`); grants and targeted financing (`l10n_ua_grant`); export control permits
(`l10n_ua_export_control`); precious metals in products (`l10n_ua_precious_metals`); approved suppliers of critical
components (`l10n_ua_supplier_approval`); limit cards М-8 (`l10n_ua_limit_card`);
periodic and type tests gating acceptance (`l10n_ua_product_tests`); labour safety briefings and medical exams
(`l10n_ua_safety`); property, land and environmental taxes (`l10n_ua_local_tax`); price types and dated price setting
(`l10n_ua_price_set`); the doubtful debts reserve (`l10n_ua_bad_debt`); the cash flow statement Ф3
(`l10n_ua_cashflow`); the cash flow budget with payment request control (`l10n_ua_budget`); the vacation schedule
(`l10n_ua_vacation_plan`); production defect acts (`l10n_ua_defect`); the statement of changes in equity Ф4
(`l10n_ua_equity`); the notes Ф5, main sections (`l10n_ua_notes`); the average headcount (`l10n_ua_headcount`); the inventory count of non-current assets (`l10n_ua_asset_inventory`); the employment norm for persons with disabilities and the targeted contribution (`l10n_ua_disability_quota`); the cash count act (`l10n_ua_cash_count`); financial statements to DPS in XML with the small-company forms brought to the current rows (`l10n_ua_finrep_dps`); the profit tax return with annex РІ in XML (`l10n_ua_profit_tax`); the monthly VAT return with annex Д2 in XML (`l10n_ua_vat_return`). Done on 2026-11-08: kinds of goods with characteristics, naming templates, duplicates and analogs, the 1C nomenclature intake and component packs (`l10n_ua_component`); supplier price lists, price comparison per base unit and supplier search (`l10n_ua_supplier_catalog`). Parcels with Nova Poshta, Ukrposhta and other carriers: status, history, pickup reminders, stuck and late parcels (`l10n_ua_parcel`). The view from the shop floor and the buyer: [capability-map.md](capability-map.md).

Next, in this order:

1. PRRO receipts from the native point of sale (needs a screen; lives in the UI repository).
2. Continuous exchange with a running 1C during a move (beyond the one-off import in `l10n_ua_migrate`).
3. УКТ ЗЕД classifier from official open data, once a source with a clear licence is found.
