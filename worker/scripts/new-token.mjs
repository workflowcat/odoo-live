// Make a bridge token for one environment.
//
//   node scripts/new-token.mjs staging "GET /api/odb/screen/" "GET /api/kyc/"
//
// Prints the token once (store it in your secret manager and give it to that Odoo as BP_BRIDGE_TOKEN)
// and the entry to add to the Worker's BRIDGE_TOKENS secret. The Worker keeps only the hash.
import { randomBytes } from "node:crypto";
import { sha256Hex } from "../src/auth.js";

const [name, ...allow] = process.argv.slice(2);
if (!name || !allow.length || allow.some((r) => !/^(\*|GET|POST|PATCH|PUT|DELETE|HEAD) \/api\//.test(r))) {
  console.error('usage: node scripts/new-token.mjs <name> "<METHOD|*> /api/<prefix>" ...');
  process.exit(2);
}
const token = randomBytes(32).toString("base64url");
console.log(`token (shown once): ${token}`);
console.log(`BRIDGE_TOKENS entry: ${JSON.stringify({ name, sha256: await sha256Hex(token), allow })}`);
