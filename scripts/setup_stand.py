# -*- coding: utf-8 -*-
# odoo shell script: company «Ясен Меблі» (buyer in the fixtures), Ukrainian chart ua_psbo, admin password from ADMIN_PW.
import json, os
exp = json.load(open("/mnt/extra-addons/../scripts/fixtures/expected.json", encoding="utf-8")) if os.path.exists("/mnt/extra-addons/../scripts/fixtures/expected.json") else None
buyer = (exp or {}).get("buyer") or {"name": "ТОВ «Ясен Меблі»", "code": "43715285"}
company = env.company
company.write({"name": buyer["name"], "company_registry": buyer["code"], "country_id": env.ref("base.ua").id,
               "street": "вул. Городоцька, 172", "city": "Львів", "zip": "79018"})
if not env["account.account"].search_count([("company_ids", "in", company.id)]):
    env["account.chart.template"].try_loading("ua_psbo", company, install_demo=False)
pw = os.environ.get("ADMIN_PW")
if pw:
    env.ref("base.user_admin").password = pw
env.ref("base.user_admin").write({"lang": "uk_UA", "tz": "Europe/Kyiv",
                                   "group_ids": [(4, env.ref("account.group_account_manager").id), (4, env.ref("purchase.group_purchase_manager").id)]})
taxes = env["account.tax"].search([("type_tax_use", "=", "purchase"), ("company_id", "=", company.id)])
print("company", company.name, company.company_registry, company.currency_id.name,
      "accounts", env["account.account"].search_count([("company_ids", "in", company.id)]),
      "purchase taxes", [(t.name, t.amount, t.price_include) for t in taxes])
env.cr.commit()
