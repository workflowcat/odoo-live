// odoo-assistant: web assistant for employees. Static screens from ./public, API under /api.
import { OdooDown, OdooError, call, reportPdf } from "./odoo.js";
import { REQUESTS, LEAVE_KINDS, employeeByEmail, pickList, profile, payslips, leaves, openRequests, leaveTypes, contextText, kyivToday, fmtDate } from "./data.js";
import { answer, cleanMessages } from "./chat.js";
import { accessEmail } from "./access.js";

const J = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const enc = new TextEncoder();
const isLocal = (url) => ["127.0.0.1", "localhost"].includes(url.hostname);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function b64u(bytes) { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
function unb64u(s) { const b = atob(s.replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(b, (c) => c.charCodeAt(0)); }
function same(a, b) { a = String(a); b = String(b); let d = a.length ^ b.length; for (let i = 0; i < Math.max(a.length, b.length); i++) d |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0); return d === 0; }
async function sign(env, data) {
  const key = await crypto.subtle.importKey("raw", enc.encode(env.SESSION_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(data))));
}
async function cookieFor(env, url, emp) {
  const payload = b64u(enc.encode(JSON.stringify({ e: emp.id, n: emp.name, x: Date.now() + 12 * 3600e3 })));
  const secure = url.protocol === "https:" ? "; Secure" : "";
  return `sid=${payload}.${await sign(env, payload)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200${secure}`;
}
// Two ways in. Real employees: Cloudflare Access proves the work email on every request (access.js);
// no password, no cookie. Test stand: DEMO_PICKER=1, one shared password, then pick anyone - only for
// invented demo data, never for a database with real people.
const demoMode = (env) => env.DEMO_PICKER === "1";
const NO_ACCESS = "Вхід через Cloudflare Access: відкрийте помічника з робочою поштою, яку знає компанія.";

async function who(env, req, url) {
  if (!demoMode(env)) {
    const email = await accessEmail(env, req);
    if (email) { const e = await employeeByEmail(env, email); if (e) return { id: e.id, name: e.name }; }
    if (env.DEV_AUTO_EMAIL && isLocal(url)) { const e = await employeeByEmail(env, env.DEV_AUTO_EMAIL); if (e) return { id: e.id, name: e.name }; }
    return null;
  }
  const m = (req.headers.get("Cookie") || "").match(/(?:^|;\s*)sid=([^;]+)/);
  if (m) {
    const [p, s] = m[1].split(".");
    if (p && s && same(await sign(env, p), s)) {
      try { const o = JSON.parse(new TextDecoder().decode(unb64u(p))); if (o.x > Date.now()) return { id: o.e, name: o.n }; } catch {}
    }
  }
  if (env.DEV_AUTO_EMAIL && isLocal(url)) { const e = await employeeByEmail(env, env.DEV_AUTO_EMAIL); if (e) return { id: e.id, name: e.name }; }
  return null;
}

async function body(req) { try { return await req.json(); } catch { return {}; } }
function plusDays(iso, n) { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
let HR_UID = null;
async function hrUser(env) {
  if (!HR_UID) { const r = await call(env, "res.users", "search_read", [[["login", "=", env.HR_USER_LOGIN || "lana"]]], { fields: ["id"], limit: 1 }); HR_UID = r[0]?.id || false; }
  return HR_UID;
}

async function api(req, env, url) {
  const path = url.pathname;
  const method = req.method;

  if (path === "/api/login" && method === "POST") {
    if (!demoMode(env)) {
      const me = await who(env, req, url);
      return me ? J({ ok: true }) : J({ error: NO_ACCESS, access: true }, 401);
    }
    const b = await body(req);
    if (!env.APP_PASSWORD || !env.SESSION_SECRET || !same(b.password || "", env.APP_PASSWORD)) { await sleep(700); return J({ error: "Пароль неправильний." }, 401); }
    if (!b.employee_id) return J({ pick: await pickList(env) });
    const r = await call(env, "hr.employee", "search_read", [[["id", "=", Number(b.employee_id)], ["work_email", "!=", false]]], { fields: ["name"], limit: 1 });
    const emp = r[0] || null;
    if (!emp) return J({ error: "Працівника не знайдено." }, 404);
    return J({ ok: true }, 200, { "Set-Cookie": await cookieFor(env, url, emp) });
  }
  if (path === "/api/logout" && method === "POST") return J({ ok: true }, 200, { "Set-Cookie": "sid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" });

  const me = await who(env, req, url);
  if (!me) return demoMode(env) ? J({ error: "Потрібно увійти." }, 401) : J({ error: NO_ACCESS, access: true }, 401);

  if (path === "/api/me" && method === "GET") {
    const [p, slips, types] = await Promise.all([profile(env, me.id), payslips(env, me.id, 1), leaveTypes(env)]);
    if (!p) return J({ error: "Картку працівника не знайдено." }, 404);
    const requests = Object.fromEntries(Object.entries(REQUESTS).map(([k, v]) => [k, { ...v, fields: k === "leave" ? undefined : v.fields }]));
    return J({ profile: p, lastSlip: slips[0] || null, leaveTypes: types, requests, model: env.ANTHROPIC_API_KEY ? (env.CLAUDE_MODEL || "claude-opus-5") : env.AI_MODEL, today: kyivToday(),
      dev: !!(env.DEV_AUTO_EMAIL && isLocal(url)) });
  }
  if (path === "/api/payslips" && method === "GET") return J({ payslips: await payslips(env, me.id, 12) });
  const pdf = path.match(/^\/api\/payslips\/(\d+)\/pdf$/);
  if (pdf && method === "GET") {
    const id = Number(pdf[1]);
    const own = await call(env, "hr.payslip", "search_count", [[["id", "=", id], ["employee_id", "=", me.id]]]);
    if (!own) return J({ error: "Листок не знайдено." }, 404);
    const res = await reportPdf(env, "l10n_ua_payroll_reports.report_ua_payslip", id);
    return new Response(res.body, { headers: { "Content-Type": "application/pdf", "Content-Disposition": `inline; filename="rozrakhunkovyi-lystok-${id}.pdf"`, "Cache-Control": "no-store" } });
  }
  if (path === "/api/leaves" && method === "GET") {
    const [p, list] = await Promise.all([profile(env, me.id), leaves(env, me.id)]);
    return J({ vacation: p?.vacation, leaves: list });
  }
  if (path === "/api/requests" && method === "GET") {
    const [reqs, list] = await Promise.all([openRequests(env, me.id), leaves(env, me.id)]);
    return J({ requests: reqs, leaves: list.filter((l) => ["confirm", "validate1"].includes(l.state) || l.from >= kyivToday()) });
  }
  if (path === "/api/requests" && method === "POST") return J(await createRequest(env, me, await body(req)));
  if (path === "/api/chat" && method === "POST") {
    const b = await body(req);
    const messages = cleanMessages(b.messages);
    if (!messages.length) return J({ error: "Напишіть питання." }, 400);
    const [p, slips, lvs, reqs] = await Promise.all([profile(env, me.id), payslips(env, me.id, 6), leaves(env, me.id), openRequests(env, me.id)]);
    const t0 = Date.now();
    const out = await answer(env, p, contextText(p, slips, lvs, reqs), messages, isLocal(url) && typeof b.model === "string" ? b.model : null);
    return J({ ...out, ms: Date.now() - t0 });
  }
  return J({ error: "Not found" }, 404);
}

async function createRequest(env, me, b) {
  const kind = b.kind;
  const def = REQUESTS[kind];
  if (!def) throw new OdooError("Невідомий вид запиту.");
  const v = b.values || {};
  if (kind === "leave") {
    if (!LEAVE_KINDS.includes(v.type)) throw new OdooError("Оберіть вид відпустки.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v.date_from || "") || !/^\d{4}-\d{2}-\d{2}$/.test(v.date_to || "")) throw new OdooError("Вкажіть дати відпустки.");
    if (v.date_to < v.date_from) throw new OdooError("Останній день раніше за перший.");
    const t = await call(env, "hr.leave.type", "search_read", [[["name", "=", v.type]]], { fields: ["id"], limit: 1 });
    const id = await call(env, "hr.leave", "create", [{ employee_id: me.id, holiday_status_id: t[0].id, request_date_from: v.date_from, request_date_to: v.date_to,
      private_name: String(v.note || "Заява через помічника").slice(0, 500) }]);
    const r = await call(env, "hr.leave", "read", [[id]], { fields: ["number_of_days", "state"] });
    return { ok: true, message: `Заяву подано: ${v.type}, ${fmtDate(v.date_from)} - ${fmtDate(v.date_to)}, ${r[0].number_of_days} дн. Вона чекає погодження.` };
  }
  for (const f of def.fields) if (f.required && !String(v[f.name] || "").trim()) throw new OdooError(`Заповніть поле «${f.label}».`);
  const rows = def.fields.filter((f) => String(v[f.name] || "").trim())
    .map((f) => `<li>${esc(f.label)}: ${esc(f.type === "date" ? fmtDate(v[f.name]) : String(v[f.name]).slice(0, 2000))}</li>`).join("");
  const hr = await hrUser(env);
  await call(env, "hr.employee", "activity_schedule", [[me.id]], {
    act_type_xmlid: "mail.mail_activity_data_todo", summary: `Запит: ${def.label}`, date_deadline: plusDays(kyivToday(), 3),
    note: `<p>Запит від працівника через помічника.</p><ul>${rows}</ul>`, ...(hr ? { user_id: hr } : {}),
  });
  return { ok: true, message: `Запит «${def.label}» надіслано HR. Строк виконання: ${fmtDate(plusDays(kyivToday(), 3))}.` };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return new Response("Not found", { status: 404 });
    try {
      return await api(req, env, url);
    } catch (e) {
      if (e instanceof OdooDown) return J({ error: "Odoo не відповідає. Спробуйте ще раз за хвилину." }, 503);
      if (e instanceof OdooError) return J({ error: e.message }, 400);
      console.error(e);
      return J({ error: "Помилка сервера." }, 500);
    }
  },
};
