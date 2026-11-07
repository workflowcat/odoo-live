// node --test worker/test/*.test.mjs  (no dependencies)
import { test } from "node:test";
import assert from "node:assert/strict";
import { authorize, allows, sha256Hex } from "../src/auth.js";

const req = (method, token) => new Request("https://bridge.example.com/x", {
  method, headers: token ? { Authorization: `Bearer ${token}` } : {},
});

test("legacy single token: right token passes everything, wrong one does not", async () => {
  const env = { BRIDGE_TOKEN: "legacy-secret-value" };
  assert.deepEqual(await authorize(req("POST", "legacy-secret-value"), env, "/api/kyc/subjects"), { name: "legacy" });
  assert.equal((await authorize(req("GET", "legacy-secret-valuX"), env, "/api/odb/court")).status, 403);
  assert.equal((await authorize(req("GET"), env, "/api/odb/court")).status, 401);
  assert.equal((await authorize(req("GET", "anything"), {}, "/api/odb/court")).status, 403);
});

test("scoped tokens: each token reaches only its routes", async () => {
  const env = { BRIDGE_TOKENS: JSON.stringify([
    { name: "prod", sha256: await sha256Hex("prod-token"), allow: ["GET /api/odb/", "* /api/kyc/"] },
    { name: "staging", sha256: await sha256Hex("staging-token"), allow: ["GET /api/odb/screen/", "GET /api/kyc/"] },
  ]), BRIDGE_TOKEN: "old-token-must-stop-working" };
  assert.deepEqual(await authorize(req("PATCH", "prod-token"), env, "/api/kyc/subjects/7"), { name: "prod" });
  assert.deepEqual(await authorize(req("GET", "staging-token"), env, "/api/odb/screen/12345678"), { name: "staging" });
  assert.equal((await authorize(req("GET", "staging-token"), env, "/api/odb/court")).status, 403);
  assert.equal((await authorize(req("POST", "staging-token"), env, "/api/kyc/subjects")).status, 403);
  assert.equal((await authorize(req("GET", "old-token-must-stop-working"), env, "/api/odb/court")).status, 403);
});

test("rules match method and path prefix only", () => {
  const t = { allow: ["GET /api/kyc/", "* /api/odb/screen/"] };
  assert.ok(allows(t, "GET", "/api/kyc/subjects"));
  assert.ok(!allows(t, "POST", "/api/kyc/subjects"));
  assert.ok(allows(t, "POST", "/api/odb/screen/1"));
  assert.ok(!allows(t, "GET", "/api/odb/court"));
  assert.ok(!allows({ allow: ["GET"] }, "GET", "/api/kyc/"));
});

test("URL normalisation keeps dot segments from escaping a prefix", () => {
  const p = new URL("https://b.example.com/api/kyc/%2e%2e/odb/court").pathname;
  assert.equal(p, "/api/odb/court");
  assert.ok(!allows({ allow: ["* /api/kyc/"] }, "GET", p));
});
