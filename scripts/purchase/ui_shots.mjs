// Screenshots of the intake screens on the local stand (Playwright from StoryKit). Usage: node scripts/purchase/ui_shots.mjs
import { chromium } from "/Users/kit/Codius/StoryKit/node_modules/playwright/index.mjs";
import fs from "node:fs";
const env = Object.fromEntries(fs.readFileSync(process.env.ODOO_ENV_FILE || new URL("../.env", import.meta.url), "utf8").split("\n")
  .map((l) => l.split("#")[0].trim()).filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
const base = process.env.ODOO_URL || `http://127.0.0.1:${env.ODOO_PORT || 8120}`;
const db = process.env.ODOO_DB || "purchase";
const prefix = process.env.SHOT_PREFIX || "";
const out = new URL("../demo-out/", import.meta.url).pathname;
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 }, locale: "uk-UA" });
const r = await ctx.request.post(`${base}/web/session/authenticate`, { data: { jsonrpc: "2.0", params: { db, login: env.ODOO_ADMIN_USER_LOGIN || "admin", password: env.ODOO_ADMIN_USER_PASSWORD } } });
if (!(await r.json()).result) throw new Error("login failed");
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
const rpc = async (model, method, args, kwargs = {}) => (await (await ctx.request.post(`${base}/web/dataset/call_kw`, { data: { jsonrpc: "2.0", params: { model, method, args, kwargs } } })).json()).result;
const [first] = await rpc("bp.purchase.intake", "search_read", [[["state", "=", "bill"]]], { fields: ["id", "partner_id", "move_id"], limit: 1 });
const [bad] = await rpc("bp.purchase.intake", "search_read", [[["state", "=", "review"]]], { fields: ["id"], limit: 1 });
const shots = [
  ["1-inbox", `${base}/odoo/action-bp_purchase_intake.action_purchase_intake`],
  ["2-intake-bill", `${base}/odoo/action-bp_purchase_intake.action_purchase_intake/${first.id}`],
  ["3-intake-review", `${base}/odoo/action-bp_purchase_intake.action_purchase_intake/${bad.id}`],
  ["4-supplier", `${base}/odoo/contacts/${first.partner_id[0]}`],
  ["5-bill", `${base}/odoo/action-account.action_move_in_invoice_type/${first.move_id[0]}`],
];
for (const [name, url] of shots) {
  await page.goto(url, { waitUntil: "load" });
  await page.waitForSelector(".o_action_manager .o_view_controller", { timeout: 30000 });
  await page.waitForTimeout(2000);
  if (name === "4-supplier") {
    const tab = page.getByRole("tab", { name: "ЄДР" });
    if (await tab.count()) { await tab.click(); await page.waitForTimeout(600); } else errors.push("no ЄДР tab on supplier");
  }
  await page.screenshot({ path: `${out}${prefix}${name}.png` });
  const blocking = await page.locator(".o_error_dialog, .o_dialog .modal-title:has-text('Error')").count();
  console.log(name, "ok", blocking ? "ERROR DIALOG" : "");
}
console.log("console errors:", errors.length ? errors.slice(0, 8) : "none");
await browser.close();
