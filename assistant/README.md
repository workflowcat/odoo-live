# odoo-assistant

Web assistant for employees on top of the payroll Odoo. An employee signs in, asks questions about leave, payslips and insurance record, and sends requests to HR.


## How it works

- `public/` - screens (PixelKit, dark theme): chat, payslips, leave, my requests, request forms.
- `src/index.js` - API: `/api/login`, `/api/me`, `/api/chat`, `/api/payslips`, `/api/payslips/:id/pdf`, `/api/leaves`, `/api/requests`.
- `src/data.js` - Odoo reads. Every query filters by the employee id from the signed session cookie. The model never picks whose data it sees.
- `src/chat.js` - one model call per question with this employee's data in the prompt. Workers AI by default (`AI_MODEL`); Claude when the `ANTHROPIC_API_KEY` secret exists (`CLAUDE_MODEL`, server-side refusal fallback on).
- `src/odoo.js` - JSON-RPC as the Odoo user `assistant` (groups: Employees Officer, Time Off Officer, Payroll Manager). Target: service binding to `odoo-payroll` or `ODOO_URL` when set.

Requests: leave becomes an `hr.leave` waiting for approval. Other requests become a To-Do activity «Запит: ...» on the employee card, assigned to `HR_USER_LOGIN`.

## Run and deploy

```bash
npm install
npm run dev        # http://127.0.0.1:8787, local Odoo from .dev.vars, auto sign-in as DEV_AUTO_EMAIL
npm run deploy     # Cloudflare
```

`.dev.vars` (gitignored): `ODOO_LOGIN ODOO_PASSWORD APP_PASSWORD SESSION_SECRET ODOO_URL DEV_AUTO_EMAIL`.
Worker secrets: `ODOO_LOGIN ODOO_PASSWORD`, `ACCESS_TEAM_DOMAIN ACCESS_AUD` for employees, `APP_PASSWORD SESSION_SECRET` for the test stand, optional `ANTHROPIC_API_KEY`.

## Who signs in

- **Employees (default, `DEMO_PICKER=0`).** Put a Cloudflare Access application in front of the Worker
  (one-time code to the work email, or your identity provider). Set `ACCESS_TEAM_DOMAIN`
  (`<team>.cloudflareaccess.com`) and `ACCESS_AUD` (the application's audience tag). Every request carries
  Access's signed token; `src/access.js` verifies it and the employee is the one whose work email matches
  exactly. Nobody types an email or a password here. Without the two settings nobody gets in.
- **Test stand (`DEMO_PICKER=1`).** One shared password (`APP_PASSWORD`), then pick any employee. Only for
  a database with invented people: anyone with the password can read everyone's pay.

Tests: `node --test assistant/test/*.test.mjs` (also run by `scripts/check_static.sh`).
