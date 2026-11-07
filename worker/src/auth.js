// Who may call the bridge, and which routes.
//
// BRIDGE_TOKENS (a Worker secret) is a JSON list. Each token is stored by its SHA-256, never in clear,
// and carries the routes it may call as "<METHOD or *> <path prefix>":
//
//   [{"name": "prod",    "sha256": "<64 hex>", "allow": ["GET /api/odb/", "* /api/kyc/"]},
//    {"name": "staging", "sha256": "<64 hex>", "allow": ["GET /api/odb/screen/", "GET /api/kyc/"]}]
//
// So staging gets its own token that cannot write to the KYC register or run paid court searches.
// `node scripts/new-token.mjs <name> "<rule>" ...` makes a token and prints its entry.
// Until BRIDGE_TOKENS is set, the old single BRIDGE_TOKEN keeps working with every route.

const enc = new TextEncoder();

export async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Constant-time comparison (Workers have crypto.subtle.timingSafeEqual; Node tests use the loop).
export function sameText(a, b) {
  const x = enc.encode(String(a)), y = enc.encode(String(b));
  if (x.length !== y.length) return false;
  if (typeof crypto.subtle.timingSafeEqual === "function") return crypto.subtle.timingSafeEqual(x, y);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export function parseTokens(env) {
  if (!env.BRIDGE_TOKENS) return null;
  const list = JSON.parse(env.BRIDGE_TOKENS);
  if (!Array.isArray(list)) throw new Error("BRIDGE_TOKENS must be a JSON list");
  return list
    .filter((t) => t && /^[0-9a-f]{64}$/.test(t.sha256 || "") && Array.isArray(t.allow))
    .map((t) => ({ name: String(t.name || "token"), sha256: t.sha256, allow: t.allow.map(String) }));
}

export function allows(token, method, path) {
  return token.allow.some((rule) => {
    const [m, prefix] = rule.trim().split(/\s+/);
    return Boolean(prefix) && (m === "*" || m.toUpperCase() === method) && path.startsWith(prefix);
  });
}

// { name } when the call is allowed, { status, error } otherwise. `path` is the URL's normalised pathname.
export async function authorize(req, env, path) {
  const match = /^Bearer (\S+)$/.exec(req.headers.get("Authorization") || "");
  if (!match) return { status: 401, error: "token required" };
  const presented = match[1];
  const tokens = parseTokens(env);
  if (tokens === null) {
    if (!env.BRIDGE_TOKEN || !sameText(presented, env.BRIDGE_TOKEN)) return { status: 403, error: "forbidden" };
    return { name: "legacy" };
  }
  const hash = await sha256Hex(presented);
  let found = null;
  for (const t of tokens) if (sameText(hash, t.sha256)) found = t; // no early exit
  if (!found) return { status: 403, error: "forbidden" };
  if (!allows(found, req.method, path)) {
    return { status: 403, error: `token "${found.name}" may not call ${req.method} ${path}` };
  }
  return { name: found.name };
}
