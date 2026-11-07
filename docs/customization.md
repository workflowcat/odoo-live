# Customizing odoo-live for a team

How a company or an integrator adapts odoo-live without forking it. The short version: Odoo and OCA stay
as they are, the Ukrainian core stays shared, an **industry pack** gives a starting catalogue, and
everything specific to one team lives in that team's **own module**. Updating the core then never
overwrites the team's work.

## The layers

| Layer | What lives there | Who changes it | 1C/BAS analogue |
| --- | --- | --- | --- |
| 1. Odoo 19 CE and OCA | generic ERP: accounting engine, stock, manufacturing, purchase, payroll base | nobody here (OCA only `i18n/uk.po`) | the platform |
| 2. Core `l10n_ua_*` | Ukrainian law and practice: chart, VAT, payroll, documents, contracts, defense pricing | maintainers, with tests and golden numbers | typical configuration (типова конфігурація) |
| 3. Industry pack | starting catalogue of an industry: categories, units, goods, work centres, BOMs with routings | maintainers and contributors, as JSON | initial filling (початкове заповнення), industry solutions |
| 4. Team module | your own catalogue, fields, print forms, small rules, integrations | the team or its integrator | extension (розширення), external print forms and processing |
| 5. Configuration | settings, rates, users, rights, sequences | the team's administrator, in the UI | settings in the user mode |

Rule of thumb: if a change would help every Ukrainian company, it belongs in the core with a test. If it
helps one industry, it is a pack. If it helps one company, it is a team module. Settings are never code.

## What to do for a typical request

| The team wants | Do this | Where |
| --- | --- | --- |
| Start with an industry's goods, BOMs, work centres | load a pack: Settings - Галузеві каталоги | layer 3 |
| Its own goods, units, categories, routings | a JSON pack in the team module (`scripts/new_pack.py`) | layer 4 |
| An extra field on a product, order or contract | `_inherit` the model in the team module, add the field to the form view | layer 4 |
| Its own print form (a different act, a label) | a QWeb report in the team module | layer 4 |
| A check before posting ("no invoice over the contract limit without a note") | override the method in the team module, call `super()` | layer 4 |
| Data from another system | `ua.api` over JSON-RPC, or a bridge route (`worker/`) | layer 4 |
| A different VAT, payroll or document rule | open an issue: law changes go into the core for everyone | layer 2 |
| Different rates, sequences, rights | settings | layer 5 |

## Industry packs

A pack is one JSON file in the `catalog/` folder of any installed module. `l10n_ua_catalog` finds packs
in every installed module and loads one into a chosen company: **Settings - Галузеві каталоги**. The
packs that ship with the core:

| Pack | For | Inside |
| --- | --- | --- |
| `defense_uav` | makers of reconnaissance drones | quadcopter with thermal camera, fixed-wing reconnaissance aircraft, ground control station, spare kit; carbon frame made in-house; 6 work centres with wage and energy rates for the Resolution 309 calculation |
| `defense_ugv` | makers of ground robotic platforms | logistics and evacuation platforms, welded hull made in-house, scrap as returnable waste |
| `defense_apparel` | sewing for the armed forces | field uniform, softshell jacket, plate carrier cover, pouch; fabrics by lot, consumption norms |
| `defense_machining` | machining subcontractors | CNC turning and milling, metal by heat lot, chips as returnable waste, anodising as a bought service |
| `procurement` | a purchasing department | typical purchases with ДК 021 codes: paper, IT, fuel, utilities, security, cleaning |
| `small_shop` | a neighbourhood grocery | goods with in-store barcodes, weighed goods, cost and retail prices; POS-ready when `point_of_sale` is installed |

Defense packs carry no weapons: payloads are observation cameras.

### What loading does

- Creates what is missing and remembers each record by its key (`ir.model.data`, module `ua_catalog`).
  Loading again creates nothing.
- Picks up what is already there instead of duplicating: a product with the same internal reference, a
  work centre or category with the same name.
- Goods, work centres and BOMs belong to the chosen company; a second company gets its own copy.
  Categories and units are shared.
- **Update mode** takes names, prices and fields from the pack again for records it loaded before. It
  does not rebuild BOM structure, because orders may already use it.
- Fields from `fields{}` are set only when the model has them. The drone pack sets cost items when
  `l10n_ua_defense` is installed and still loads without it; the result lists the skipped fields.

### Format (schema 1)

```json
{
  "schema": 1,
  "pack": "acme_parts",
  "name": "Acme: склад запчастин",
  "summary": "For whom and what is inside.",
  "industry": "trade",
  "requires": ["stock", "mrp"],
  "sources": [{"title": "Where the data comes from", "url": "https://..."}],
  "notes": ["What the user should check after loading."],
  "groups": ["stock.group_production_lot"],
  "uoms": [{"key": "u_kit", "name": "Комплект", "short": "компл", "kspovo": "2938"}],
  "categories": [{"key": "c_root", "name": "Запчастини"},
                 {"key": "c_motor", "name": "Двигуни", "parent": "@c_root"}],
  "workcenters": [{"key": "wc_asm", "name": "Складання", "code": "СКЛ", "costs_hour": 120,
                   "fields": {"ua_wage_hour": 240, "ua_energy_hour": 8}}],
  "products": [{"key": "motor", "code": "M-001", "name": "Двигун 2807", "category": "@c_motor",
                "uom": "шт", "cost": 1150, "price": 1600, "tracking": "serial",
                "uktzed": "8501310000", "dk021": "31110000-0", "fields": {"ua_cost_item": "02"}}],
  "boms": [{"key": "b_kit", "product": "@kit", "qty": 1, "type": "normal",
            "lines": [{"product": "@motor", "qty": 4}],
            "operations": [{"name": "Складання", "workcenter": "@wc_asm", "minutes": 30,
                            "ua_checks": "What the inspector checks."}],
            "byproducts": [{"product": "@scrap", "qty": 0.05}]}],
  "records": [{"key": "tag_vip", "model": "res.partner.category", "values": {"name": "VIP"}}]
}
```

- `@key` points to a record of the same pack declared earlier; `ref:module.xmlid` to any Odoo record.
- Units: the Ukrainian short name from КСПОВО (`шт`, `кг`, `м`, `м2`, `м3`, `л`, `год`, `доб`, `кВт·год`),
  an Odoo xmlid (`uom.product_uom_kgm`) or a key from `uoms`. The unit's КСПОВО code goes into tax invoices.
- `type`: `consu` (goods, storable unless `"storable": false`), `service`, `combo`. A phantom BOM
  (`"type": "phantom"`) is a kit.
- Barcodes in a public pack start with `20` (in-store range), so they never clash with a manufacturer's.
- `records` covers any other model; `match` (`[["name", "=", "VIP"]]`) picks up an existing record.

`python3 scripts/catalog_check.py` validates every pack without a database: references, units, ДК 021
codes against the full classifier, УКТ ЗЕД format, barcode check digits, BOM cycles, required modules,
no real e-mail addresses. It runs in `scripts/check_static.sh` and in CI.

## A team module

```bash
python3 scripts/new_pack.py acme_pack --title "Acme: склад запчастин" --industry trade --requires stock,mrp
```

creates `addons/acme_pack/` with a manifest, an empty pack, a test that loads the pack twice and a README.
Add to it, in this order of preference:

1. **Data** in `catalog/*.json`: goods, units, categories, work centres, BOMs.
2. **Fields and views**: `models/*.py` with `_inherit`, `views/*.xml` inheriting the core's views by
   xpath. Prefix your fields with the team's prefix (`acme_`), never `ua_`.
3. **Print forms**: `report/*.xml` QWeb templates; reuse the core's helpers
   (`l10n_ua_docs.models.tools.amount_in_words`).
4. **Rules**: override a method and call `super()`. Raise `UserError` with a sentence the user can act on.
5. **Integrations**: through `ua.api` or a bridge route, keys from the environment, never in the module.

Keep a private team module in a private repository. Mount its folder into the container next to
`./addons:/mnt/extra-addons` in `docker-compose.yml` (for example `../acme-addons:/mnt/team-addons`) and
add that path to `addons_path` in `odoo/odoo.local.conf` (`addons_path = /mnt/extra-addons,/mnt/team-addons`).
A module useful to others can come to this repository by pull request: a pack is reviewed like code.

### Rules for team modules

- Never edit the core, OCA or Odoo. If the core lacks a hook you need, ask for one
  (`python3 scripts/agent_note.py new request --to core "..."`) or send a pull request with a test.
- Every module installs on an empty database and has tests tagged with its name.
- No secrets and no real people's data in the repository; demo data is invented, e-mails use `.example`.
- Keys in a pack (`key`) are permanent: the loader finds its records by them. Rename the name, not the key.
- Updating the core: `git pull`, then `-u` the core modules and yours. Your data stays; your overrides
  keep working as long as they call `super()`.

## Mapping from 1C habits

| In 1C you would | Here |
| --- | --- |
| Create an extension (розширення) in the configurator | create a team module with `scripts/new_pack.py` |
| Add a requisite (реквізит) to a catalogue | add a field with `_inherit` |
| Make an external print form | add a QWeb report to the team module |
| Make an external processing (обробка) | a server action, a wizard in the team module, or a script against `ua.api` |
| Fill catalogues from a typical configuration's initial filling | load an industry pack |
| Load catalogues from another base | `l10n_ua_migrate` for 1C files; a pack for a curated starting set |
| Restrict rights by organisation | companies and record rules; one database, several companies |
| Use a universal report (СКД) | list, pivot and graph views with grouping; `report_xlsx`; `mis_builder` |
