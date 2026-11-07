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
| VAT return with annexes in DPS XML | part | the return exists; checking all annexes against the current form is open |
| Profit tax return | done | `l10n_ua_profit_tax` |
| Single tax (FOP group 3) book and return | done | `l10n_ua_fop` |
| Financial statements Ф1/Ф2 (full and small) | done | `l10n_ua_finrep` (mis_builder); DPS XML of the statements is a gap |
| Fixed assets, low-value items, intangibles, tax groups | done | `l10n_ua_assets` + OCA asset management |
| Cash desk: ПКО/ВКО, cash book КО-4, limit | done | `l10n_ua_cash` |
| Bank statements: file, PrivatBank, Monobank | done | `l10n_ua_bank`, `l10n_ua_bank_online` |
| Bank exchange file `1CClientBankExchange` (most Ukrainian banks) | done | `l10n_ua_bank_1c`: statements in through the usual import, payment orders out from payments or payment orders |
| NBU rates, FX differences | done | `l10n_ua_nbu` + native |
| **Counterparty contracts** (settlements by contract, currency, limits) | done | `l10n_ua_contract`: contract on invoices, payments and orders, limits that warn or block, analytic per contract |
| **Reconciliation act** with a counterparty (акт звірки) | done | `l10n_ua_contract`: by partner or contract, two-sided print form, agreed or disputed |
| Mutual offset of debts (взаємозалік) | done | `l10n_ua_offset`: open customer and vendor debts of one counterparty (by contract if chosen), oldest first, one entry 63 to 36 reconciled with the documents it closes, two-sided act under article 601 of the Civil Code, cancel restores the debts; UAH only |
| Month-end closing assistant (закриття місяця) | yes | `l10n_ua_close`: depreciation, FX revaluation with reversal, overhead 91, 7/9 to 79, 79 to 44 in order, with undo; period lock and change review in `l10n_ua_changes` |
| Property and land tax, environmental tax | gap | low priority; returns as XML |
| Statistical reports (Держстат) | gap | low priority |
| E-signature (КЕП) and sending reports, ЄРПН registration | gap | XML files are produced; signing and sending stay in M.E.Doc/Вчасно or a bridge route |
| Electronic document exchange with counterparties | done | `l10n_ua_edo`: invoices, acts, waybills, contracts and reconciliation acts out as PDF through the bridge (one or many at once, no double sends), status and the counterparty's signature back, rejection with a task, paper signature; incoming documents matched to vendor bills, signed or rejected from Odoo. Service adapters in the bridge are separate work |

## 2. Payroll and HR (ЗУП)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Payroll with Ukrainian rules, average earnings, indexation | done | `l10n_ua_payroll_rules`, `l10n_ua_average`, `l10n_ua_index`, 30 golden scenarios |
| Sick leave (employer and PFU parts), vacations, business trips | done | `l10n_ua_average` |
| Unified tax report (ПДФО/ВЗ/ЄСВ) with annexes, XML | done | `l10n_ua_payroll_reports` |
| HR orders, staff list, timesheet П-5, personal card П-2 | done | `l10n_ua_hr_*` |
| Hiring case to filed notice | done | `l10n_ua_hire` |
| Military registration, TCC notices | done | `l10n_ua_military` |
| **Reservation of employees** (бронювання) of critically important companies | part | `l10n_ua_military`: data on the employee card; the critical-company status with its term, quota and wage floor; quota and deadline checks on the reserved list; reminders before the status or a reservation ends; a task when a reserved employee leaves. A ready list for the Дія request is missing |
| Civil contracts (ЦПХ) | done | `l10n_ua_gph` |
| Labour statistics, vacancy reports | gap | low priority |

## 3. Trade and procurement (Управління торгівлею)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Sales and purchase orders, deliveries, returns | done | native |
| Price types, discounts | part | native pricelists; named price types (опт, роздріб, закупівельна) as presets in the packs |
| Purchase requests and approvals | done | OCA `purchase_request`, `l10n_ua_purchase` |
| Supplier risk, invoices from email | done | `l10n_ua_purchase`, `bp_purchase_intake`, `bp_kyc` |
| Debt control by contract, credit limits | done | `l10n_ua_contract`: balance by contract, contract amount as a limit |
| Commission trade, consignment | done | `l10n_ua_commission`: both roles. As commissioner the consignor's goods sit in stock with the consignor as owner (not valued), sell through normal orders, and the report to the consignor fills itself from those deliveries and makes the consignor's bill, the commission invoice and the offset. As consignor own goods move to a "На комісії" location; the commissioner's report writes off what was sold and makes the invoice, the commission bill and the offset. Percent commission or consignor price; customer returns stay manual |
| **Customs declarations (МД)** for imported goods: duty and VAT into cost | done | `l10n_ua_customs`: declaration from received goods, duty, excise and fees into each product's cost (native landed costs), VAT into credit; declaration XML exchange with the customs service is out of scope |
| Public procurement (Prozorro), ДК 021 codes on goods | done | `l10n_ua_dk021`: full classifier, code on goods and purchase lines; `procurement` pack; `l10n_ua_procurement_plan`: annual plan with the subject by ДК 021 class, procedure checked against thresholds (split subjects show up), revisions instead of edits, plan against confirmed purchase orders, print and a Prozorro plan file. Tender documents and bids stay on the e-platform |

## 4. Production (КУП / ERP)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Bills of materials, routings, work orders | done | native `mrp` |
| Monthly cost calculation by product and cost item | done | `l10n_ua_mrp` (materials, labour, overhead by normal capacity) |
| **Planned calculation (планова калькуляція)** of a product's price by cost item | done | `l10n_ua_defense`: plan and actual by the Resolution 309 items from BOM, routing and contract rates |
| Serial and lot tracking | done | native |
| Quality control (ВТК), inspections | done | check items on routing operations, yes/no answers on work orders (`l10n_ua_mrp`); defense contracts block release and acceptance until every item is "yes" and print the results in the serial passport (`l10n_ua_defense`); incoming and outgoing protocols (`l10n_ua_stock_docs`) |
| Tolling (давальницька сировина) | yes | `l10n_ua_tolling`: customer material in its own owner-tagged location (not valued, off-balance 023), production from it, return of products and leftovers, processing invoice, processor's report with norm vs actual |
| Engineering changes, BOM versions | done | `l10n_ua_eco`: change notices with was/now lines, approvals (technologist, quality, military representative), BOM revision N+1 on the effective date |
| Production planning (MPS/MRP) | done | OCA `mrp_multi_level` over all BOM levels; open defense delivery schedules are demand (`l10n_ua_mrp_plan`) |
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
| **Separate accounting of actual costs by contract** | постанова № 363: виконавець веде окремий облік фактичних витрат за контрактом | done: analytic account per contract, actual calculation from closed orders and bills, plan vs actual by item |
| **Price calculation by the regulated cost items** (01 сировина ... 10 зворотні відходи, then overhead, admin, selling, financial, other, profit) | постанова КМУ № 309 (2021), пп. 11-13 | done: plan from BOM and routing with the contract's rates, printable with materials breakdown |
| Acceptance by the customer's representative (військове приймання), quality records | contract terms | done: acceptance act per batch with serials; inspection checks on routing steps gate release and acceptance; results in the passport |
| Product passport / log per serial, spare parts kits (ЗІП) | contract terms | done: passport per serial with components' serials; ЗІП as a kit BOM in the drone pack |
| Design changes agreed with the customer's representative, revision on every serial | contract terms; ЄСКД change-notice practice | done: `l10n_ua_eco`; the military representative signs when the product was made under a defense contract; the passport shows the revision |
| Claims (рекламації) from units: deadlines, warranty, root cause, replacement, repeat failures | contract terms | done: `l10n_ua_claim`; the passport prints the claim history; a design cause opens a change notice |
| Imported components: customs declaration, duty and VAT in cost | Митний кодекс, ст. 49-58; ПКУ, ст. 190 | done: `l10n_ua_customs`; duty-free import under defense benefits goes as a 0 % duty rate or a VAT basis on the line |
| Reservation of employees | постанова КМУ № 76 (2023) and its changes | done except the Дія request list: status, quota, wage floor, deadlines; the numbers are settings on the status, checked against the current edition |
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
from defense delivery schedules (`l10n_ua_mrp_plan` on OCA `mrp_multi_level`).

Next, in this order:

1. PRRO receipts from the native point of sale (needs a screen; lives in the UI repository).
2. Reservation: the list for the Дія request, once the current field set is confirmed.
3. Continuous exchange with a running 1C during a move (beyond the one-off import in `l10n_ua_migrate`).
4. УКТ ЗЕД classifier from official open data, once a source with a clear licence is found.
