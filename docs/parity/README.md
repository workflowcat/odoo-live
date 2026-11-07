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
| Month-end closing assistant (закриття місяця) | yes | `l10n_ua_close`: depreciation, FX revaluation with reversal, overhead 91, 7/9 to 79, 79 to 44 in order, with undo; period lock and change review in `l10n_ua_changes` |
| Property and land tax, environmental tax | gap | low priority; returns as XML |
| Statistical reports (Держстат) | gap | low priority |
| E-signature (КЕП) and sending reports, ЄРПН registration | gap | XML files are produced; signing and sending stay in M.E.Doc/Вчасно or a bridge route |
| Electronic document exchange with counterparties | gap | bridge route to an EDO service (Вчасно, M.E.Doc, Paperless) |

## 2. Payroll and HR (ЗУП)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Payroll with Ukrainian rules, average earnings, indexation | done | `l10n_ua_payroll_rules`, `l10n_ua_average`, `l10n_ua_index`, 30 golden scenarios |
| Sick leave (employer and PFU parts), vacations, business trips | done | `l10n_ua_average` |
| Unified tax report (ПДФО/ВЗ/ЄСВ) with annexes, XML | done | `l10n_ua_payroll_reports` |
| HR orders, staff list, timesheet П-5, personal card П-2 | done | `l10n_ua_hr_*` |
| Hiring case to filed notice | done | `l10n_ua_hire` |
| Military registration, TCC notices | done | `l10n_ua_military` |
| **Reservation of employees** (бронювання) of critically important companies | part | data on the employee card; the company's quota, list for the Дія request and deadlines tracking are missing |
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
| Commission trade, consignment | gap | later |
| **Customs declarations (МД)** for imported goods: duty and VAT into cost | done | `l10n_ua_customs`: declaration from received goods, duty, excise and fees into each product's cost (native landed costs), VAT into credit; declaration XML exchange with the customs service is out of scope |
| Public procurement (Prozorro), ДК 021 codes on goods | part | `l10n_ua_dk021`: full classifier, code on goods and purchase lines; `procurement` pack. Annual procurement plan report is open |

## 4. Production (КУП / ERP)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Bills of materials, routings, work orders | done | native `mrp` |
| Monthly cost calculation by product and cost item | done | `l10n_ua_mrp` (materials, labour, overhead by normal capacity) |
| **Planned calculation (планова калькуляція)** of a product's price by cost item | done | `l10n_ua_defense`: plan and actual by the Resolution 309 items from BOM, routing and contract rates |
| Serial and lot tracking | done | native |
| Quality control (ВТК), inspections | done | check items on routing operations, yes/no answers on work orders (`l10n_ua_mrp`); defense contracts block release and acceptance until every item is "yes" and print the results in the serial passport (`l10n_ua_defense`); incoming and outgoing protocols (`l10n_ua_stock_docs`) |
| Tolling (давальницька сировина) | gap | stock of customer-owned material, processing act |
| Engineering changes, BOM versions | gap | a simple revision register first |
| Production planning (MPS/MRP) | part | native scheduler; OCA `mrp_multi_level` later |
| Repairs and warranty returns | part | native `repair`; warranty months on goods and serial passports in `l10n_ua_defense`; warranty claims register missing |

## 5. Retail (Роздріб)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Point of sale | part | native `point_of_sale` |
| **Fiscalisation (ПРРО/РРО)** | gap | bridge route to a PRRO service (Checkbox, Вчасно.Каса) or the DPS fiscal server; Z-reports into accounting |
| Shop catalogue, price labels, cash discipline | part | `small_shop` pack (goods, in-store barcodes, weighed goods); price labels missing |

## 6. Document flow (Документообіг)

| 1C/BAS feature | Here | Where / what is missing |
| --- | --- | --- |
| Incoming and outgoing correspondence register | gap | small module; defense companies keep one by law |
| Approvals of documents and payments | part | purchase request approvals; payment requests with approval are missing |

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
| State contract register: customer (МОУ, ДОТ, other), number, items, schedule, advances, penalties | Закон «Про оборонні закупівлі» № 808-IX; постанова КМУ № 363 (2021) | done: `l10n_ua_defense` on top of `l10n_ua_contract`; penalties are open |
| **Separate accounting of actual costs by contract** | постанова № 363: виконавець веде окремий облік фактичних витрат за контрактом | done: analytic account per contract, actual calculation from closed orders and bills, plan vs actual by item |
| **Price calculation by the regulated cost items** (01 сировина ... 10 зворотні відходи, then overhead, admin, selling, financial, other, profit) | постанова КМУ № 309 (2021), пп. 11-13 | done: plan from BOM and routing with the contract's rates, printable with materials breakdown |
| Acceptance by the customer's representative (військове приймання), quality records | contract terms | done: acceptance act per batch with serials; inspection checks on routing steps gate release and acceptance; results in the passport |
| Product passport / log per serial, spare parts kits (ЗІП) | contract terms | done: passport per serial with components' serials; ЗІП as a kit BOM in the drone pack |
| Imported components: customs declaration, duty and VAT in cost | Митний кодекс, ст. 49-58; ПКУ, ст. 190 | done: `l10n_ua_customs`; duty-free import under defense benefits goes as a 0 % duty rate or a VAT basis on the line |
| Reservation of employees | постанова КМУ № 76 (2023) and its changes | quota and list (section 2) |
| Donor-funded deliveries to units | civil and tax rules on charity | transfer act and the tax note, later |

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
(`l10n_ua_close`) with Form 2 kept intact after closing.

Next, in this order:

1. Tolling: customer-owned material and the processing act.
2. Correspondence register and payment approvals.
3. PRRO fiscalisation through a bridge route; price labels for the shop pack.
4. УКТ ЗЕД classifier from official open data, once a source with a clear licence is found.
