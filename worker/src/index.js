// odoo-live bridge. All external systems are reached through here; Odoo holds one token and no vendor keys.
//   GET  /health
//   GET  /api/odb/screen/:code        registry + risk markers, normalized (OpenDataBot v2, cached 24h in D1)
//   GET  /api/odb/court?text=&offset= court decisions search, passthrough (billable, on demand)
//   ANY  /api/kyc/*                   forward to kyc-service with its key (POST /subjects, PATCH /subjects/:id, ...)
//   *                                 Odoo container when attached (see container.js); otherwise the status page
import { OdooContainer, routeToOdoo } from "./container.js";
export { OdooContainer };

const ODB = "https://opendatabot.ua/api/v2";
const KYC = "https://kyc-service.botpartners.workers.dev";

const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "content-type": "application/json; charset=utf-8" } });
const authed = (req, env) => (req.headers.get("Authorization") || "") === `Bearer ${env.BRIDGE_TOKEN}`;
const first = (x) => (Array.isArray(x) ? x[0] : x);

async function odbGet(env, path, params = {}) {
  const u = new URL(`${ODB}/${path}`);
  u.searchParams.set("apiKey", env.OPENDATABOT_API_KEY); u.searchParams.set("lang", "uk");
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") u.searchParams.set(k, v);
  const r = await fetch(u, { signal: AbortSignal.timeout(40000) });
  const text = await r.text();
  if (!r.ok) throw new Error(`OpenDataBot ${r.status}: ${text.slice(0, 200)}`);
  return JSON.parse(text);
}

const SEV = { danger: "high", warning: "warn", info: "info", success: "info" };
function normalize(code, kind, full, brief) {
  const f = full || {}, b = brief || {};
  const heads = Array.isArray(f.heads) ? f.heads : [];
  const head = heads.find((h) => h.type === "head") || heads[0] || {};
  const acts = Array.isArray(f.activities) ? f.activities : (Array.isArray(f.activity_kinds) ? f.activity_kinds : []);
  const prim = acts.find((a) => a.is_primary) || acts[0] || {};
  const bens = (Array.isArray(f.beneficiaries) ? f.beneficiaries : []).map((x) => ({
    name: x.name || x.beneficiaryName || "", role: x.role || "", amount_percent: x.amount_percent ?? null,
    amount: x.amount ?? null, country: x.country || "", location: x.location || "", code: x.code || "" }));
  const checks = [];
  for (const w of Array.isArray(f.warnings) ? f.warnings : []) {
    for (const [key, v] of Object.entries(w || {})) {
      if (!v || typeof v !== "object") continue;
      const present = v.type === "available";
      checks.push({ key, title: TITLES[key] || key, severity: present ? (SEV[v.indicator] || "warn") : "info",
                    present, detail: String(v.text || (present ? "є" : "немає")).trim() });
    }
  }
  const status = String(f.status || b.status || "");
  if (status && !/зареєстр/i.test(status)) checks.unshift({ key: "status", title: "Стан у ЄДР", severity: "high", present: true, detail: status });
  else checks.unshift({ key: "status", title: "Стан у ЄДР", severity: "info", present: false, detail: status || "невідомо" });
  if (kind === "company" && !bens.length) checks.push({ key: "ubo", title: "Бенефіціари", severity: "warn", present: true, detail: "У ЄДР не розкрито бенефіціарів/засновників" });
  const foreign = bens.filter((x) => x.country && !/укра/i.test(x.country));
  if (foreign.length) checks.push({ key: "foreign_ubo", title: "Іноземні бенефіціари", severity: "info", present: true, detail: foreign.map((x) => `${x.name} (${x.country})`).join("; ") });
  const reg = f.registration_date || f.registration?.date || "";
  if (reg && (Date.now() - Date.parse(reg)) < 365 * 864e5) checks.push({ key: "young", title: "Реєстрація менше року", severity: "warn", present: true, detail: reg });
  return {
    code, kind, fetched_at: new Date().toISOString(),
    registry: {
      full_name: f.full_name || "", short_name: f.short_name || "", status, registration_date: reg,
      kved: prim ? `${prim.code ? prim.code + " " : ""}${prim.name || ""}`.trim() : "",
      head: f.ceo_name || head.name || "", head_role: head.role || "", address: f.location || f.address?.address || "",
      capital: f.capital ?? null, vat_status: b.pdv_status || f.pdv_status || "", vat_code: b.pdv_code || f.pdv_code || "",
      email: f.email || "", phone: Array.isArray(f.phones) ? (f.phones[0] || "") : (f.phones || ""), beneficiaries: bens,
    },
    checks, raw: { full: f, brief: b },
  };
}
const TITLES = { tax_debts: "Податковий борг", sanctions: "Санкції", bankruptcy: "Банкрутство", wanted: "Розшук", court: "Судові справи",
  courts: "Судові справи (маркер ЄДР)", pdv: "ПДВ", enforcements: "Виконавчі провадження", mass_registration: "Масова реєстрація", inactive: "Припинення" };

async function screen(env, code) {
  const cached = await env.DB.prepare("SELECT json, fetched_at FROM odb_cache WHERE code = ?1").bind(code).first();
  if (cached && Date.now() - Date.parse(cached.fetched_at) < 864e5) return { ...JSON.parse(cached.json), cached: true };
  let out;
  if (code.length === 8) {
    const [full, brief] = await Promise.all([odbGet(env, `fullcompany/${code}`), odbGet(env, `company/${code}`).catch(() => null)]);
    const f = first(full); if (!f || !f.full_name) throw new Error("ЄДР не знайшов юрособу з таким кодом");
    out = normalize(code, "company", f, first(brief));
  } else if (code.length === 10) {
    const f = first(await odbGet(env, `fop/${code}`)); if (!f || !f.full_name) throw new Error("ЄДР не знайшов ФОП з таким кодом");
    out = normalize(code, "fop", f, null);
  } else throw new Error("Код: 8 цифр (ЄДРПОУ) або 10 цифр (РНОКПП)");
  await env.DB.prepare("INSERT INTO odb_cache (code, json, fetched_at) VALUES (?1, ?2, ?3) ON CONFLICT(code) DO UPDATE SET json = ?2, fetched_at = ?3")
    .bind(code, JSON.stringify(out), out.fetched_at).run();
  return { ...out, cached: false };
}

async function kycForward(env, req, subpath) {
  const init = { method: req.method, headers: { "Authorization": `Bearer ${env.KYC_API_KEY}`, "X-KYC-Client": "odoo",
                 "content-type": req.headers.get("content-type") || "application/json" } };
  const author = req.headers.get("X-Author"); if (author) init.headers["X-Author"] = author;
  if (!["GET", "HEAD"].includes(req.method)) init.body = await req.arrayBuffer();
  const url = new URL(req.url);
  // same-account Worker: go through the service binding (a plain fetch to *.workers.dev is refused with error 1042)
  const r = await env.KYC.fetch(new Request(`${KYC}${subpath}${url.search}`, init));
  return new Response(await r.text(), { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/json" } });
}

function statusPage(env) {
  return new Response(`<!doctype html><html lang="uk"><meta charset="utf-8"><title>odoo-live</title>
<style>body{font:15px/1.5 ui-monospace,Menlo,monospace;background:#f6f1e7;color:#1d1b18;max-width:640px;margin:8vh auto;padding:0 20px}h1{font:600 24px Georgia,serif}code{background:#eee6d6;padding:1px 6px}p{margin:8px 0}</style>
<h1>odoo-live</h1>
<p>Міст інтеграцій працює: <code>/api/odb/*</code> (OpenDataBot), <code>/api/kyc/*</code> (kyc-service).</p>
<p>Odoo на цьому домені ще не підключено: контейнер чекає на план Workers Paid. База даних живе на Supabase.</p>
<p><code>GET /health</code></p></html>`, { headers: { "content-type": "text/html; charset=utf-8" } });
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url); const p = url.pathname; const t0 = Date.now();
    const log = (status) => ctx.waitUntil(env.DB.prepare("INSERT INTO calls (ts, route, status, ms) VALUES (?1, ?2, ?3, ?4)")
      .bind(new Date().toISOString(), p.replace(/\/\d{8,10}(\/|$)/, "/:code$1"), status, Date.now() - t0).run().catch(() => {}));
    if (p === "/health") return json({ ok: true, odoo_attached: !!env.ODOO, ts: new Date().toISOString() });
    if (p.startsWith("/api/")) {
      if (!authed(req, env)) return json({ error: "forbidden" }, 403);
      try {
        let res;
        if (p.startsWith("/api/odb/screen/")) { const code = p.split("/")[4].replace(/\D/g, ""); res = json(await screen(env, code)); }
        else if (p === "/api/odb/court") { res = json(await odbGet(env, "court", { text: url.searchParams.get("text"), offset: url.searchParams.get("offset") || 0 })); }
        else if (p.startsWith("/api/kyc/")) { res = await kycForward(env, req, p.slice("/api/kyc".length)); }
        else res = json({ error: "no such route" }, 404);
        log(res.status); return res;
      } catch (e) { log(502); return json({ error: String(e.message || e) }, 502); }
    }
    if (env.ODOO) return routeToOdoo(env, req);
    return statusPage(env);
  },
};
