"""Правила звірки банку для зарплатних платежів: створюються під час встановлення для кожної компанії з планом рахунків."""
RULES = [
    ("Зарплата на картки (661)", "661", ["заробітн", "зарплат", "аванс", "зарплатн"]),
    ("ПДФО (6411)", "6411", ["пдфо", "податок на доходи", "податку на доходи", "101"]),
    ("Військовий збір (6415)", "6415", ["військов", "збір"]),
    ("ЄСВ (651)", "651", ["єсв", "єдиний внесок", "єдиного внеску", "соціальн"]),
    ("Аліменти (6851)", "6851", ["алімент"]),
]


def _account(env, company, code):
    Acc = env["account.account"].with_company(company)
    return Acc.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1) or \
        Acc.search([("code", "=like", f"{code}%"), ("company_ids", "in", company.id)], order="code", limit=1)


def post_init_hook(env):
    Model = env["account.reconcile.model"]
    for company in env["res.company"].search([]):
        if not _account(env, company, "661"):
            continue
        for name, code, words in RULES:
            if Model.search([("name", "=", name), ("company_id", "=", company.id)], limit=1):
                continue
            acc = _account(env, company, code)
            if not acc:
                continue
            Model.create({"name": name, "company_id": company.id, "trigger": "manual", "can_be_proposed": True,
                          "match_label": "match_regex", "match_label_param": "(?i)" + "|".join(words),
                          "line_ids": [(0, 0, {"account_id": acc.id, "amount_type": "percentage", "amount_string": "100", "label": name})]})
        bank = env["account.journal"].search([("type", "=", "bank"), ("company_id", "=", company.id)], limit=1)
        if bank and bank.name in ("Bank", "Банк"):
            bank.name = "Банк (поточний рахунок)"
