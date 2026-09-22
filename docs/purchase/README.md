# Incoming supplier invoices (`addons/bp_purchase_intake`)

An email with a PDF invoice becomes a record in Purchase → Вхідні рахунки. Odoo reads the PDF through
Cloudflare Workers AI, checks the numbers, finds or creates the supplier card marked «Не перевірено»,
pulls ЄДР data through the bridge (OpenDataBot), and creates a draft vendor bill. Nothing is posted:
a bill for an unverified supplier cannot be posted until a purchase manager marks the supplier verified.

## Flow

1. **Mail in.** `mail.thread.message_process("bp.purchase.intake", raw_email)`, the same entry point an
   incoming mail server or `odoo-mailgate.py` uses. `message_new` creates the intake; the first PDF attachment
   becomes the document.
2. **Read.** A PDF with a text layer: `bp.ai.to_markdown` (Workers AI `tomarkdown`, free), then `bp.ai.extract_json`
   on the text. A scan without text, or a JPG/PNG/WebP photo: the page images (embedded JPEGs, via PyPDF2) go to the
   same prompt as images (`BP_AI_VISION_MODEL`, default Llama 4 Scout). Prompt and schema: `data/extract_invoice.json`.
3. **Check.** ЄДРПОУ/РНОКПП and IBAN checksums, line sum (against the total when prices include ПДВ), ПДВ, total,
   buyer = our company, a tax invoice is never billed, duplicate (same supplier code and number, or an existing bill
   with that reference). A supplier the registry does not know is an error.
4. **Supplier.** Found by ЄДРПОУ or ІПН, otherwise created with `bp_supplier_status = unverified`. The IBAN
   from the invoice is added to a new card; a different IBAN on a known card is an error (payment-fraud check).
5. **ЄДР.** `GET /api/odb/screen/<code>` through `bp.bridge`: full name, status, head, КВЕД, ПДВ, markers go
   to the supplier card (tab ЄДР) and become checks (status, name, ІПН, tax debt, sanctions…).
6. **Result.** No errors → draft bill with the PDF attached, state «Чернетка рахунку». Errors → state
   «Потребує перевірки», no bill (a user can still create one, with a confirmation). Duplicate → «Дублікат».

## Run it

```bash
cd /Users/kit/Codius/odoo-live-purchase
./scripts/purchase/cf_token.sh                  # Workers AI token from the wrangler login of this Mac (expires; rerun)
docker compose up -d                   # http://127.0.0.1:8120, database "purchase"
python3 scripts/purchase/intake_check.py        # three test emails end to end: real Workers AI, real bridge
python3 scripts/purchase/mailgate.py some.eml   # deliver any .eml
node scripts/purchase/ui_shots.mjs              # screenshots into demo-out/
docker compose run --rm odoo odoo -d purchase --test-enable --test-tags /bp_purchase_intake --stop-after-init
```

Settings (`.env`, passed by `docker-compose.yml`): `CF_ACCOUNT_ID`, `CF_API_TOKEN` (a Cloudflare API token
with Workers AI permission; when empty, `.cf/token` from `scripts/purchase/cf_token.sh` is used), `BP_AI_MODEL`,
`BP_BRIDGE_TOKEN`. Test documents: `scripts/purchase/fixtures/make_invoices.py` (PDF + .eml + expected values).
Model comparison: `python3 scripts/purchase/ai_probe.py [model ...]`.

## Model and cost

Probe on the fixtures, 13 September 2026, same prompt and schema:

| Model | Fields right | Time | Neurons per invoice |
|---|---|---|---|
| `@cf/meta/llama-4-scout-17b-16e-instruct` (default) | 18/18 | 8 s | 46-56 |
| `@cf/mistralai/mistral-small-3.1-24b-instruct` | 18/18 | 9-13 s | 55-64 |
| `@cf/zai-org/glm-5.3-flash` | 18/18 | 16-19 s | 70-85 |
| `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | 17/18 | 7-11 s | 78-106 |
| `@cf/google/gemma-4-26b-a4b-it`, `@cf/qwen/qwen3.8-27b` | no usable output | 28-55 s | - |

Workers AI bills $0.011 per 1,000 neurons above a free 10,000 neurons a day: about $0.0006 per invoice,
and roughly 190 invoices a day inside the free allowance. The OpenDataBot lookup is the paid part; the bridge
caches it for 24 hours.

## Real mailbox

Use a dedicated mailbox (for example `rahunky@…`). In Odoo: Settings → Technical → Incoming Mail Servers,
IMAP, action «Create a new record» = Вхідний рахунок. A Gmail mailbox needs an app password entered by the
mailbox owner. Do not point the main inbox at this model: every email would become an intake.

## Moving the calls to the bridge

Add `POST /api/ai/tomarkdown` and `POST /api/ai/extract` to `worker/src/index.js` with an `"ai": {"binding": "AI"}`
binding (no API token needed inside a Worker), then make `bp.ai._post` call `bp.bridge` instead of
`api.cloudflare.com`. Nothing else in the module changes.

## Batch test (13 September 2026)

`scripts/purchase/fixtures/make_batch.py` builds 13 documents (4 layouts, real ЄДР suppliers, a ФОП, prices with ПДВ, a tax
invoice, 2 pages, a stamped scan, a phone photo, a fax, a sideways scan); `scripts/purchase/batch_check.py` runs them through
the stand and writes `demo-out/batch_results.json`.

| Documents | Right outcome | Fields right |
|---|---|---|
| 9 text PDFs | 9 of 9 (6 draft bills, 3 held: ФОП missing from ЄДР, wrong buyer, tax invoice) | 54 of 54 |
| 4 scans and photos | 0 of 4 billed: all held for review | 22 of 24 |

Every scan was held because the vision model misread a long digit string (IBAN, ІПН, ЄДРПОУ) or read «ЕК» as the
Latin «EK». The checksums and the ЄДР comparison caught each misread; no wrong bill was created. Total cost of the
batch: about 1,100 neurons, about $0.012.

## Limits today

- Scans and photos are read, but digits are unreliable: expect review, not a bill. Next options: a second pass on a
  crop of the requisites block, a stronger vision model, or taking the ІПН from ЄДР when the ЄДРПОУ is valid.
- The first PDF (or image) in an email is read, up to 3 pages; one invoice per file.
- Bill lines are text lines without products; the expense account is the purchase journal default.
  No purchase-order matching yet.
- Not deployed anywhere but the local stand on port 8120.
