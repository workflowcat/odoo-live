// /api/edo/* - electronic document exchange with counterparties, one contract for every service
// (docs/base/spec-edo.md). Adapters: vchasno. The adapter is chosen by "provider" in the body, or by
// the prefix of the document id ("vchasno:...").
import * as vchasno from "./vchasno.js";

const ADAPTERS = { vchasno };

function adapterFor(name) {
  const adapter = ADAPTERS[String(name || "vchasno")];
  if (!adapter) throw new vchasno.EdoError(`адаптера ЕДО «${name}» у мосту немає`, 501);
  return adapter;
}

async function body(req) {
  try { return await req.json(); } catch { throw new vchasno.EdoError("тіло запиту - не JSON", 400); }
}

// Returns [status, data]; never throws for adapter errors.
export async function edoRoute(env, req, path) {
  try {
    const rest = path.slice("/api/edo".length);
    if (req.method === "POST" && rest === "/documents") {
      const payload = await body(req);
      return [200, await adapterFor(payload.provider).send(env, payload)];
    }
    if (req.method === "POST" && rest === "/inbox") {
      const payload = await body(req);
      return [200, await adapterFor(payload.provider).inbox(env, payload)];
    }
    const m = /^\/documents\/([^/]+)(?:\/(revoke|sign|reject))?$/.exec(rest);
    if (m) {
      const id = decodeURIComponent(m[1]);
      const adapter = adapterFor(id.split(":")[0]);
      if (req.method === "GET" && !m[2]) return [200, await adapter.status(env, id)];
      if (req.method === "POST" && m[2] === "revoke") return [200, await adapter.revoke(env, id)];
      if (req.method === "POST" && m[2] === "sign") return [200, await adapter.sign(env, id)];
      if (req.method === "POST" && m[2] === "reject") return [200, await adapter.reject(env, id, await body(req))];
    }
    return [404, { error: "no such route" }];
  } catch (e) {
    return [e.status || 502, { error: String(e.message || e) }];
  }
}
