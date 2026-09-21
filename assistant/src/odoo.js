// Odoo access for the assistant: JSON-RPC as one service user.
// Target: ODOO_URL when set (local stand or tunnel), otherwise the odoo-payroll Worker through a service binding.
export class OdooDown extends Error {}
export class OdooError extends Error {}

const UA = "Mozilla/5.0 (compatible; odoo-assistant/0.1)";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let UID = null;
let SESSION = null;

async function http(env, path, init) {
  let last;
  for (let i = 0; i < 6; i++) {
    try {
      const res = env.ODOO_URL
        ? await fetch(env.ODOO_URL.replace(/\/$/, "") + path, init)
        : await env.ODOO.fetch(new Request("https://odoo-payroll.internal" + path, init));
      if (res.status >= 500 || res.status === 429) { last = new Error(`Odoo HTTP ${res.status}`); await sleep(2500 * (i + 1)); continue; }
      return res;
    } catch (e) {
      last = e;
      await sleep(2500 * (i + 1));
    }
  }
  throw new OdooDown(String(last));
}

async function rpc(env, service, method, args) {
  const init = {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": UA },
    body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { service, method, args }, id: Date.now() }),
  };
  const res = await http(env, "/jsonrpc", init);
  let j;
  try { j = await res.json(); } catch { throw new OdooDown("Odoo returned a non-JSON answer"); }
  if (j.error) throw new OdooError(j.error.data?.message || j.error.message || "Odoo error");
  return j.result;
}

async function uid(env) {
  if (!UID) {
    UID = await rpc(env, "common", "login", [env.ODOO_DB, env.ODOO_LOGIN, env.ODOO_PASSWORD]);
    if (!UID) throw new OdooError("The assistant cannot sign in to Odoo.");
  }
  return UID;
}

export async function call(env, model, method, args = [], kwargs = {}) {
  const u = await uid(env);
  return rpc(env, "object", "execute_kw", [env.ODOO_DB, u, env.ODOO_PASSWORD, model, method, args, kwargs]);
}

async function session(env, force) {
  if (SESSION && !force) return SESSION;
  const res = await http(env, "/web/session/authenticate", {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": UA },
    body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { db: env.ODOO_DB, login: env.ODOO_LOGIN, password: env.ODOO_PASSWORD } }),
  });
  const m = (res.headers.get("Set-Cookie") || "").match(/session_id=([^;]+)/);
  if (!m) throw new OdooError("Odoo did not open a session.");
  SESSION = m[1];
  return SESSION;
}

// PDF of a QWeb report. Retries once with a fresh session when Odoo answers with the login page.
export async function reportPdf(env, reportName, id) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const sid = await session(env, attempt > 0);
    const res = await http(env, `/report/pdf/${reportName}/${id}`, { headers: { Cookie: `session_id=${sid}`, "User-Agent": UA } });
    if ((res.headers.get("Content-Type") || "").includes("pdf")) return res;
  }
  throw new OdooError("Odoo did not return the PDF.");
}
