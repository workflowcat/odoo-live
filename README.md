# odoo-live

Odoo 19 Community as a product platform for Bot&Partners, wired to the tools we already run:
OpenDataBot (ЄДР, courts), kyc-service (the group KYC register on Cloudflare D1), Gmail.
First product on it: the **KYC process** (`addons/bp_kyc`).

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how it is built and how to build on it.

## Pieces

| Piece | Where | What |
|---|---|---|
| Live database | Supabase project `odoo-live` (Frankfurt, Postgres 17) | the one real database; attachments stored in it too |
| Odoo compute | `docker-compose.live.yml` on any Docker host; `odoo/Dockerfile` for Cloudflare Containers | stateless: nothing of value on its disk |
| Integration bridge | Cloudflare Worker `odoo-live` (`worker/`) at https://odoo-live.botpartners.workers.dev | holds every vendor key; Odoo holds one token |
| KYC product | `addons/bp_kyc` | cases, screening, checklist, decision, register sync, mail |
| Incoming invoices | `addons/bp_purchase_intake` | email PDF → Workers AI → checks → unverified supplier → ЄДР → draft bill; see [docs/purchase-intake.md](docs/purchase-intake.md) |
| Local dev | `docker-compose.yml` (Odoo + local Postgres, port 8100) | fast loop; same addons |

## Run

```bash
cp .env.example .env            # fill in
docker compose up -d            # local dev on http://127.0.0.1:8100
docker compose -f docker-compose.live.yml up -d --build   # Odoo against the live Supabase DB on http://127.0.0.1:8101
cd worker && wrangler deploy    # bridge
```

Install or update the module: `docker compose run --rm odoo odoo -d odoo -u bp_kyc --stop-after-init`.

Secrets live in `.env` (Mac) and as Worker secrets (`wrangler secret put BRIDGE_TOKEN|OPENDATABOT_API_KEY|KYC_API_KEY`). Never in the repo, never in Odoo.
