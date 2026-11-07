// node --test assistant/test/*.test.mjs  (no dependencies)
import { test } from "node:test";
import assert from "node:assert/strict";
import { accessEmail } from "../src/access.js";

const env = { ACCESS_TEAM_DOMAIN: "team.cloudflareaccess.com", ACCESS_AUD: "aud-123" };
const b64u = (bytes) => Buffer.from(bytes).toString("base64url");
const pair = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", pair.publicKey)), kid: "k1", alg: "RS256" };
const keys = async () => [jwk];

async function jwt(claims, { kid = "k1", key = pair.privateKey, alg = "RS256" } = {}) {
  const head = b64u(JSON.stringify({ alg, kid }));
  const body = b64u(JSON.stringify(claims));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64u(new Uint8Array(sig))}`;
}
const req = (token) => new Request("https://assistant.example.com/api/me", { headers: token ? { "Cf-Access-Jwt-Assertion": token } : {} });
const good = () => ({ aud: ["aud-123"], iss: "https://team.cloudflareaccess.com", email: "Olena@Example.com", exp: Date.now() / 1000 + 600 });

test("a valid Access token gives its email", async () => {
  assert.equal(await accessEmail(env, req(await jwt(good())), keys), "olena@example.com");
});

test("anything else gives nobody", async () => {
  assert.equal(await accessEmail(env, req(), keys), null);
  assert.equal(await accessEmail({}, req(await jwt(good())), keys), null, "Access not configured");
  assert.equal(await accessEmail(env, req(await jwt({ ...good(), aud: ["other"] })), keys), null, "other application");
  assert.equal(await accessEmail(env, req(await jwt({ ...good(), exp: Date.now() / 1000 - 5 })), keys), null, "expired");
  assert.equal(await accessEmail(env, req(await jwt({ ...good(), iss: "https://evil.cloudflareaccess.com" })), keys), null);
  assert.equal(await accessEmail(env, req(await jwt(good(), { kid: "unknown" })), keys), null);
  const other = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
  assert.equal(await accessEmail(env, req(await jwt(good(), { key: other.privateKey })), keys), null, "forged signature");
  const [h, , s] = (await jwt(good())).split(".");
  const swapped = `${h}.${b64u(JSON.stringify({ ...good(), email: "boss@example.com" }))}.${s}`;
  assert.equal(await accessEmail(env, req(swapped), keys), null, "claims changed after signing");
  assert.equal(await accessEmail(env, req("not.a.jwt"), keys), null);
});
