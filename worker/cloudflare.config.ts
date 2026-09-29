// odoo-live: integration bridge (OpenDataBot, kyc-service) + future front door for the Odoo container.
import { bindings, defineConfig } from "cf/config";

export default defineConfig({
  worker: {
    name: "odoo-live",
    compatibilityDate: "2026-08-01",
    entrypoint: "./src/index.js",
    workersDev: true,
    env: {
      KYC: bindings.worker({ worker: "kyc-service" }),
      DB: bindings.d1({ name: "odoo-demo-link", id: "cb71de82-5ced-4717-8163-16cd2ea9cbe3" }),
      BRIDGE_TOKEN: bindings.secret(),
      KYC_API_KEY: bindings.secret(),
      OPENDATABOT_API_KEY: bindings.secret(),
    },
  },
});
