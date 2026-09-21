# How odoo-live is built, how it works, how to build on it

## The shape

Three layers. Each one can be replaced without touching the others.

```
   people ──▶ Odoo 19 (compute, stateless)  ──▶ Postgres on Supabase (the live data)
                    │
                    │ one token, one URL
                    ▼
            Cloudflare Worker "odoo-live" (the bridge)
              ├── /api/odb/*   OpenDataBot  (ЄДР, courts)         key: OPENDATABOT_API_KEY
              ├── /api/kyc/*   kyc-service  (group KYC register)   key: KYC_API_KEY, service binding
              └── /health      + call log and a 24h cache in D1
```

**Odoo is compute, not storage.** The live database is on Supabase. Attachments are stored inside Postgres
(`ir_attachment.location = db`), so an Odoo container has nothing of value on its disk and can be killed,
moved, or started on another host. Today the container runs on a Mac (`docker-compose.live.yml`).
The same image (`odoo/Dockerfile`, `odoo/entrypoint.sh`) is ready for Cloudflare Containers
(`worker/wrangler.containers.jsonc`); that needs the Workers Paid plan.

**The bridge is the only door to the outside.** Odoo never holds a vendor key. It holds one URL and one
token (`BP_BRIDGE_URL`, `BP_BRIDGE_TOKEN`; the fallback config parameters are `bp_bridge.url` and
`bp_bridge.token`, with the older `bp_kyc.bridge_url` / `bp_kyc.bridge_token` still read). The Odoo side is
one module, `addons/bp_bridge`: the abstract model `bp.bridge`, no screens, `base` its only dependency.
Every module that needs an outside call depends on it - `bp_kyc`, `l10n_ua_partner_edr`,
`bp_purchase_intake`. The Worker holds the OpenDataBot key and the kyc-service key,
normalizes vendor answers into one shape, caches paid lookups for 24 hours, and logs every call
(route, status, milliseconds) in D1. Any future product on Odoo, or any non-Odoo tool, reuses the same
bridge routes. A new vendor is a new route in `worker/src/index.js`, not a change in Odoo.

**kyc-service stays the source of truth for KYC subjects.** Odoo runs the process; the decision is written
into the register through the bridge (`POST /subjects`, `PATCH /subjects/:id`, `POST /subjects/:id/risks`).
The register keeps its append-only log; Odoo keeps the case file.

## The KYC process (addons/bp_kyc)

Models: `kyc.case` (the file), `kyc.screening` (one finding per row), `res.partner` extension
(ЄДРПОУ, latest decision and risk, smart button).

Stages: Нова → Збір даних → Скринінг → Оцінка → Рішення. Buttons on the case:

1. **Скринінг ЄДР** — `GET /api/odb/screen/{code}`. Fills the ЄДР tab (name, status, date, КВЕД, head,
   address, capital, ПДВ, beneficiaries) and creates one screening row per marker: tax debt, sanctions,
   bankruptcy, status, undisclosed beneficiaries, foreign beneficiaries, registration under one year.
   Severity: info / warn / high. Suggests a risk level if none is set.
2. **Судові рішення** — `GET /api/odb/court?text=` (billable, on demand). One row with the count and the
   first ten decisions; high when ten or more.
3. **Запит документів** — sends the Ukrainian document-request template to the partner email, queues it
   in the Odoo mail queue, moves the case to Збір даних.
4. **Погодити / Погодити з умовами / Відхилити** — needs a risk level. Sets the decision, stamps who and
   when, and syncs the register: creates or updates subject `edrpou-<code>` with recommendation, risk,
   group, role, who introduced the partner, and the summary; pushes every high marker as a named risk.
   Sends the decision template unless rejected.
5. **Чек-лист** — five booleans the analyst confirms (ЄДР, ownership, sanctions, courts, documents).

Groups: Аналітик (read, write, create) and Менеджер (delete too). Sequence `KYC/2026/0001`.

## Mail

Outgoing: an `ir.mail_server` record for `smtp.gmail.com:587` (STARTTLS, `au@bot-partners.com`) exists but is
inactive until a Gmail app password is pasted in. Incoming: a `fetchmail.server` record for
`imap.gmail.com:993` exists, inactive, same credential. Activate both and the two KYC templates go out and
replies thread into the case. Alternative: Odoo's Google OAuth module (`google_gmail`) with an OAuth client;
it needs a consent click by the mailbox owner. `bot-partners.com` DNS is not on Cloudflare, so Cloudflare
Email Routing is not an option today.

## Where things live

| What | Where |
|---|---|
| Odoo admin login and master password, Supabase DB password, bridge token | `.env` on the Mac (gitignored) |
| Worker secrets | Cloudflare (`wrangler secret put`) |
| Bridge call log, OpenDataBot cache | D1 `odoo-demo-link`, tables `calls`, `odb_cache` |
| Live database | Supabase `odoo-live`, database `odoo`, role `odoo` through the session pooler (port 5432, SSL) |
| Backups | `pg_dump` through the pooler; Supabase keeps daily backups on paid plans only |

## How to build the next product on it

1. New Odoo module in `addons/<name>/` with `"version": "19.0.x.y.z"`. Odoo 19 rules that bit us:
   groups need a `res.groups.privilege` (`privilege_id`, not `category_id`); search-view `<group>` takes no
   `expand`/`string`; kanban cards use `<t t-name="card">`; a search filter needs a stored field.
2. New outside system: add a route under `/api/<vendor>/` in `worker/src/index.js`, put its key in a Worker
   secret, keep the response shape flat and stable. If the vendor is another Worker in this account, call it
   through a service binding (a plain fetch to `*.workers.dev` from a Worker is refused, error 1042).
3. Odoo calls the bridge through `env["bp.bridge"].call(method, path, payload)`. Reuse it: depend on
   `bp_bridge`, not on `bp_kyc`.
4. Test locally (`docker compose up -d`, port 8100), then update the live instance
   (`docker compose -f docker-compose.live.yml run --rm odoo-live odoo -d odoo -u <module> --stop-after-init`).
5. Deploy order: Worker first (`wrangler deploy`), then the module, so Odoo never calls a route that does
   not exist yet.

## Moving compute off the Mac

Cloudflare Containers: upgrade to Workers Paid, then `cd worker && wrangler deploy -c wrangler.containers.jsonc`.
Set the container secrets `PGHOST`, `PGUSER`, `PGPASSWORD`, `ODOO_ADMIN_PASSWD` (same values as `.env`).
The Worker then routes everything that is not `/api/*` to the container; the bridge routes stay as they are.
Any VPS works the same way: `docker compose -f docker-compose.live.yml up -d` with the `.env` values.

## Known limits

- Free-tier ceilings hit while building: Cloudflare KV daily writes, the D1 database count, Containers and
  R2 locked behind Workers Paid. The bridge therefore shares the D1 of the old demo link.
- The session pooler adds one round trip per query between the Mac and Frankfurt; a Container in Western
  Europe cuts that to a few milliseconds.
- Supabase free projects pause after a week without traffic; the Odoo cron keeps it awake while the
  compute runs.
