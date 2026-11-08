# Capability map: running a manufacturing company

What a manufacturer needs from one system - a drone or ground-robot maker, an electronics or metal
shop, a defense contractor - what this repository covers today, what is missing, and in what order to
build it. Written 2026-11-08 against `main` plus the `oss/open-source` branch. [README.md](README.md)
looks at the same system from the 1C/BAS side; this page looks at it from the shop floor and the buyer.

Legend: **done** - covered, with tests; **part** - the basics work, named pieces missing; **gap** - not
here. "Odoo" is Odoo 19 Community, "OCA" a community module on the 19.0 branch that we could vendor.

## The chain

```
demand ──> engineering ──> supply ──> production ──> delivery ──> field
contract    BOM, revision   components  plan, work    to the unit   claims, repair,
tender      admission       prices      orders,       documents     feedback
marketplace codification    parcels     tests,        parcels
donor, grant                inspection  acceptance
                 people · money · compliance · the management view run across all of it
```

A buyer of defense goods checks three things before money moves: that the product is admitted for
use, that each delivered unit can be traced to its parts and tests, and that quality problems are
found, recorded and closed. NATO buyers ask for the same through AQAP 2110 on top of ISO 9001
(risk, traceability, configuration control, government quality assurance access, telling the customer
about nonconformities, a certificate of conformity on delivery). The gaps below are ordered by that.

## 1. Demand and contracts

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| State defense contract, delivery schedule, price under Resolution 309, separate accounting | done | `l10n_ua_defense` |
| Acceptance by the military representative per delivery | done | `l10n_ua_defense` (`ua.defense.acceptance`) |
| Counterparty contracts, limits, reconciliation act | done | `l10n_ua_contract` |
| Quotes and sales orders | done | native |
| Bank guarantees (tender, performance, advance) | done | `l10n_ua_guarantee` |
| Grants with a budget by article | done | `l10n_ua_grant` |
| Donor-paid and free transfers to military units | done | `l10n_ua_unit_transfer` |
| Export of military and dual-use goods with permits | done | `l10n_ua_export_control` |
| Counterparty check: EDR data, KYC case | done | `l10n_ua_partner_edr`, `bp_kyc` |
| Marketplace orders (DOT-Chain Defence: framework agreement with the Defense Procurement Agency, the unit orders, the agency pays, delivery deadline) | gap | needs an order source, the unit as consignee, the agency as payer and a deadline on the sales order; the transfer documents already exist |
| Tender participation as a supplier (Prozorro bids, documents, results) | gap | low; guarantees are covered |

## 2. Engineering and product data

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Component catalog with characteristics, units, analogs, intake from 1C | done | `l10n_ua_component` |
| BOM revisions and change notices with approvals | done | `l10n_ua_eco` |
| Substitutes on BOM lines and in manufacturing orders | done | `l10n_ua_mrp_substitute` |
| Precious metals in components and products | done | `l10n_ua_precious_metals` |
| Codification (NSN) and admission for operation per product and variant (Resolution 763 and the ministry's procedure) | gap | status, decision document and date per product, which variants and firmware are admitted, a block on delivery of a non-admitted variant |
| Design documents (drawings, specifications, technical conditions) with letter and revision | gap | attachments only; OCA `dms` exists on 19.0 |
| As-built record of one serial number: component lots, firmware version, tests passed, acceptance, where it went | part | native lot and serial traceability; the serial passport with acceptance act and work order checks (`l10n_ua_defense`); firmware version, measured values and the transfer and claim history on one page are missing |

## 3. Supply

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Purchase requests with approval, department, expense account | done | OCA `purchase_request` + `l10n_ua_purchase` |
| Approved suppliers for critical components | done | `l10n_ua_supplier_approval` |
| Supplier price lists, comparison by real unit, where to look for suppliers | done | `l10n_ua_supplier_catalog` |
| Vendor bills from mail | done | `bp_purchase_intake` |
| Payment requests with approval | done | `l10n_ua_payment_request` |
| Customs declaration into cost and VAT | done | `l10n_ua_customs` |
| Parcels in and out: tracking numbers, carrier status, events, late and stuck parcels, cash on delivery | done | `l10n_ua_parcel`: Nova Poshta and Ukrposhta connectors, a bridge and a demo connector, attention and reminders |
| Expediting: late purchase lines, promised against confirmed dates | part | native dates; a view of what is late is missing |
| Incoming inspection: sample size, hold in quarantine, release or reject | part | an inspection protocol with norms and measured values on a receipt (`l10n_ua_stock_docs`), on paper only: no sampling, no hold; OCA `quality_control_oca` exists on 19.0 |

## 4. Warehouse

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Stock by lot, serial and location with valuation | done | native |
| Count sheets, limit cards, tolling, consignment | done | `l10n_ua_stock_docs`, `l10n_ua_limit_card`, `l10n_ua_tolling`, `l10n_ua_commission` |
| Shelf life (batteries, sealants, adhesives) | part | native `product_expiry`; not switched on in the catalog packs |
| Scanning on a phone | part | the warehouse client in `odoo-ui`; nothing in the core needs to change |
| Storage rules for lithium batteries | gap | low |

## 5. Production

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Manufacturing orders, routings, work centers, cost with overhead | done | native + `l10n_ua_mrp` |
| Multi-level planning from contract schedules | done | OCA `mrp_multi_level` + `l10n_ua_mrp_plan` |
| Piecework pay from operations | done | `l10n_ua_piecework` |
| Defect acts | done | `l10n_ua_defect` |
| Periodic, type and qualification tests | done | `l10n_ua_product_tests` |
| Acceptance test of each unit (ПЗВ) | part | yes/no check items on routing operations, release blocked until all are yes (`l10n_ua_mrp`, `l10n_ua_defense`); measured values with limits per serial are missing |
| Load per work center by week | gap | Odoo has no Gantt in Community; a dashboard is enough |
| Shop floor screen for operators | gap | belongs in `odoo-ui`, over native work orders |

## 6. Quality

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Measuring instruments and calibration | done | `l10n_ua_metrology` |
| Customer claims on a serial number | done | `l10n_ua_claim` |
| Change notices | done | `l10n_ua_eco` |
| One nonconformity register for incoming, production, claims and audits, with cause, correction and corrective action | gap | OCA `mgmtsystem_nonconformity` and `mgmtsystem_action` exist on 19.0 |
| Telling the customer about a nonconformity, certificate of conformity on delivery | gap | follows from the register |
| Internal audits, quality plan, risk register | gap | low; OCA `mgmtsystem_audit` exists |

## 7. Maintenance and repair

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Equipment and preventive maintenance | part | native `maintenance` (used by metrology); OCA `maintenance_plan` exists |
| Repair of returned products with spare parts | gap | native `repair` is not linked to claims |
| Spare kits per product for the field | gap | low |

## 8. Delivery and logistics

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Delivery note, simplified waybill, power of attorney | done | `l10n_ua_docs_stock` |
| Transfer act to a military unit | done | `l10n_ua_unit_transfer` |
| Trip sheets and fuel | done | `l10n_ua_fleet` |
| Parcels to customers and units with tracking | done | `l10n_ua_parcel`, same module as in section 3 |

## 9. People

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Personnel card, hiring, orders, timesheets, vacations | done | `l10n_ua_hr_card`, `l10n_ua_hire`, `l10n_ua_hr_orders`, `l10n_ua_hr_docs`, `l10n_ua_vacation_plan` |
| Military registration, reservation of workers, critical enterprise status | done | `l10n_ua_military` |
| Payroll with taxes and filings | done | OCA `payroll` + `l10n_ua_payroll_*` |
| Safety briefings, medical checks, workwear | done | `l10n_ua_safety`, `l10n_ua_workwear` |
| Skills and work permits: who may solder, assemble or test which product, with expiry | gap | native `hr_skills` is the base |
| The person card is easy to read | part | the wording pass starts now |

## 10. Money

Covered in [README.md](README.md): accounting, VAT, profit tax, payroll, cash, bank, budgets, cost per
product and contract. One gap that matters to a manufacturer: a cash forecast built from sales schedules,
purchase orders and payment requests (**part**: `l10n_ua_budget` has the plan and the commitments).

## 11. Compliance and records

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Export control | done | `l10n_ua_export_control` |
| Restricted correspondence (ДСК) | done | `l10n_ua_correspondence` |
| Who changed what, period lock | done | `l10n_ua_changes`, OCA `auditlog` |
| Register of licences, permits and certificates (production licence, ISO 9001, AQAP 2110, admissions) with scope and expiry reminders | gap | one register for everything with a number, a scope and an end date |

State secrets never go into this system; at most a clearance register with form and end date.

## 12. The management view

| Capability | Here | Where / what is missing |
| --- | --- | --- |
| Ukrainian menus over standard screens | done | `l10n_ua_navigation` |
| Composite read API for screens | done | `l10n_ua_api` |
| System map: every area, what exists, live counts, a link into each screen | done | `l10n_ua_map`: `ua.api.system_map()`; the screen lives in `odoo-ui` |
| Dashboards: contracts against schedule, shortages for planned orders, late purchases, parcels in transit, open quality items, cash | part | the "needs attention" strip comes from the map; charts in `odoo-ui` |

## Order of work

Now, in this round:

1. Parcels and carrier connectors (`l10n_ua_parcel`).
2. System map and dashboards: the data in `l10n_ua_api`, the screen in `odoo-ui`.
3. Wording and structure of the core forms, starting with the person card.

Next, each a module with tests, in this order:

1. **Quality loop**: incoming inspection that holds goods until released, and one nonconformity register
   with corrective actions, fed by receipts, inspection protocols, defect acts and claims. Vendor OCA `quality_control_oca` and `mgmtsystem_*` if they fit,
   ours thin on top.
2. **Serial record**: one page per serial number - component lots, firmware, acceptance test values,
   military acceptance, transfer to the unit, claims. Printable as the product passport.
3. **Admission and permits**: codification and admission status per product and variant, and one
   register of licences and certificates with expiry. Delivery of a variant that is not admitted is
   blocked.
4. **Marketplace orders**: DOT-Chain orders as a sales source with the unit, the payer and the deadline.
5. **Skills and work permits** on `hr_skills`, checked when a work order is assigned.

Later: claim to repair order, work center load, tender register, storage rules for batteries, shop floor
screen in `odoo-ui`.

Why this order: 1-3 are what a buyer audits and what stops a delivery; 4 is how a growing share of
drones is ordered (about one in five by October 2026, by public reports); 5 protects people and quality.

## Sources

- Codification and admission: Resolution of the Cabinet of Ministers No. 763 of 2023-07-21 as amended;
  the ministry's procedure page https://mod.gov.ua/kodifikacziya-novih-zrazkiv-ovt (check the current
  edition).
- DOT-Chain Defence: https://mod.gov.ua/en/news/dot-chain-defence-how-fast-do-military-units-get-drones
- AQAP 2110 scope: https://www.kiwa.com/en/services/certification/aqap-2110-certification/
- OCA modules checked on the 19.0 branches of OCA/manufacture, OCA/management-system,
  OCA/delivery-carrier, OCA/maintenance and OCA/dms on 2026-11-08.
