// odoo-payroll: every request goes to the Odoo container; a weekday cron keeps it awake 08:00-20:00 Kyiv.
import { Container } from "@cloudflare/containers";

export class OdooContainer extends Container {
  defaultPort = 8069;
  sleepAfter = "45m";
  constructor(ctx, env) {
    super(ctx, env);
    this.envVars = {
      HOST: env.PGHOST || "", PORT: env.PGPORT || "5432", USER: env.PGUSER || "", PASSWORD: env.PGPASSWORD || "",
      DB_NAME: env.DB_NAME || "payroll", ODOO_ADMIN_PASSWD: env.ODOO_ADMIN_PASSWD || "",
      MODULE_OPS: env.MODULE_OPS || "", MODULE_OPS_TAG: env.MODULE_OPS_TAG || "",
      BP_BRIDGE_URL: "https://odoo-live.botpartners.workers.dev", BP_BRIDGE_TOKEN: env.BRIDGE_TOKEN || "",
    };
  }
}

const odoo = (env) => env.ODOO.get(env.ODOO.idFromName("main"));

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/_health") return Response.json({ ok: true, db: env.DB_NAME, ts: new Date().toISOString() });
    return odoo(env).fetch(req);
  },
  async scheduled(event, env, ctx) {
    // wake or keep warm; the request also touches Postgres so Supabase does not pause
    ctx.waitUntil(odoo(env).fetch(new Request("https://odoo-payroll.internal/web/login")).catch(() => null));
  },
};
