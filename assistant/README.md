# odoo-assistant

Web assistant for employees on top of the payroll Odoo. An employee signs in, asks questions about leave, payslips and insurance record, and sends requests to HR.

Live: https://odoo-assistant.botpartners.workers.dev

## How it works

- `public/` - screens (PixelKit, dark theme): chat, payslips, leave, my requests, request forms.
- `src/index.js` - API: `/api/login`, `/api/me`, `/api/chat`, `/api/payslips`, `/api/payslips/:id/pdf`, `/api/leaves`, `/api/requests`.
- `src/data.js` - Odoo reads. Every query filters by the employee id from the signed session cookie. The model never picks whose data it sees.
- `src/chat.js` - one model call per question with this employee's data in the prompt. Workers AI by default (`AI_MODEL`); Claude when the `ANTHROPIC_API_KEY` secret exists (`CLAUDE_MODEL`, server-side refusal fallback on).
- `src/odoo.js` - JSON-RPC as the Odoo user `assistant` (groups: Employees Officer, Time Off Officer, Payroll Manager). Target: service binding to `odoo-payroll` (Supabase database) or `ODOO_URL` when set.

Requests: leave becomes an `hr.leave` waiting for approval. Other requests become a To-Do activity «Запит: ...» on the employee card, assigned to `HR_USER_LOGIN`.

## Run and deploy

```bash
npm install
npm run dev        # http://127.0.0.1:8787, local Odoo from .dev.vars, auto sign-in as DEV_AUTO_EMAIL
npm run deploy     # Cloudflare
```

`.dev.vars` (gitignored): `ODOO_LOGIN ODOO_PASSWORD APP_PASSWORD SESSION_SECRET ODOO_URL DEV_AUTO_EMAIL`.
Worker secrets: `ODOO_LOGIN ODOO_PASSWORD APP_PASSWORD SESSION_SECRET`, optional `ANTHROPIC_API_KEY`.

## Test mode

`DEMO_PICKER=1`: one shared password, then pick any employee. Before real employees use it: set `DEMO_PICKER` to `0` (sign-in by work email) and put Cloudflare Access in front of the workers.dev address.
