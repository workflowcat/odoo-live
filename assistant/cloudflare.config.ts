// odoo-assistant: web assistant for employees on top of the payroll Odoo.
// Odoo target: service binding to the odoo-payroll Worker (Supabase database). Set ODOO_URL to use another Odoo, e.g. the local stand in .dev.vars.
// Secrets: ODOO_LOGIN ODOO_PASSWORD APP_PASSWORD SESSION_SECRET, optional ANTHROPIC_API_KEY (switches the chat to Claude).
// None of them is set on a live Worker yet, so they are not declared below; add bindings.secret() lines once they are.
import { bindings, defineConfig } from "cf/config";

export default defineConfig({
  worker: {
    name: "odoo-assistant",
    compatibilityDate: "2026-08-01",
    compatibilityFlags: ["nodejs_compat"],
    entrypoint: "./src/index.js",
    workersDev: true,
    assets: { runWorkerFirst: ["/api/*"] },
    observability: { enabled: true },
    env: {
      AI: bindings.ai({ dev: { remote: true } }),
      ODOO: bindings.worker({ worker: "odoo-payroll" }),
      ODOO_DB: bindings.text("payroll"),
      HR_USER_LOGIN: bindings.text("lana"),
      AI_MODEL: bindings.text("@cf/deepseek-ai/deepseek-v4-flash-0731"),
      CLAUDE_MODEL: bindings.text("claude-opus-5"),
      DEMO_PICKER: bindings.text("1"),
    },
  },
});
