// Who is signing in, proven by Cloudflare Access in front of this Worker.
//
// Access checks the person (one-time code to the work email, or the company's identity provider) and adds a
// signed JWT to every request (Cf-Access-Jwt-Assertion). We verify it against the team's public keys and
// take the email from it. Settings: ACCESS_TEAM_DOMAIN ("<team>.cloudflareaccess.com") and ACCESS_AUD
// (the Access application's audience tag). Without them nobody signs in outside demo mode.

const enc = new TextEncoder();
const dec = new TextDecoder();

function unb64u(s) {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

let cache = { at: 0, keys: [] };
export async function teamKeys(env, fetcher = fetch) {
  if (Date.now() - cache.at < 3600e3 && cache.keys.length) return cache.keys;
  const r = await fetcher(`https://${env.ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error(`Access keys: HTTP ${r.status}`);
  cache = { at: Date.now(), keys: (await r.json()).keys || [] };
  return cache.keys;
}

// The verified, lower-cased email, or null.
export async function accessEmail(env, req, keysFor = teamKeys) {
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) return null;
  const token = req.headers.get("Cf-Access-Jwt-Assertion") || "";
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const header = JSON.parse(dec.decode(unb64u(parts[0])));
    const claims = JSON.parse(dec.decode(unb64u(parts[1])));
    if (header.alg !== "RS256") return null;
    const jwk = (await keysFor(env)).find((k) => k.kid === header.kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, unb64u(parts[2]), enc.encode(`${parts[0]}.${parts[1]}`));
    if (!ok) return null;
    const now = Date.now() / 1000;
    const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (!aud.includes(env.ACCESS_AUD) || !(claims.exp > now) || (claims.nbf && claims.nbf > now + 60)) return null;
    if (claims.iss !== `https://${env.ACCESS_TEAM_DOMAIN}`) return null;
    const email = String(claims.email || "").trim().toLowerCase();
    return email.includes("@") ? email : null;
  } catch {
    return null;
  }
}
