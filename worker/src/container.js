// Odoo container binding. Active only when deployed with wrangler.containers.jsonc (Workers Paid).
// Without the binding, `Container` is a harmless stub so the bridge-only deploy still works.
let ContainerBase = class {};
try { ({ Container: ContainerBase } = await import("@cloudflare/containers")); } catch {}

export class OdooContainer extends ContainerBase {
  defaultPort = 8069;
  sleepAfter = "1h";
  envVars = {
    HOST: this.env?.PGHOST || "", PORT: this.env?.PGPORT || "5432", USER: this.env?.PGUSER || "", PASSWORD: this.env?.PGPASSWORD || "",
    DB_NAME: "odoo", BP_BRIDGE_URL: "https://odoo-live.botpartners.workers.dev", BP_BRIDGE_TOKEN: this.env?.BRIDGE_TOKEN || "",
    ODOO_ADMIN_PASSWD: this.env?.ODOO_ADMIN_PASSWD || "",
  };
}

export async function routeToOdoo(env, req) {
  const id = env.ODOO.idFromName("main");
  return env.ODOO.get(id).fetch(req);
}
