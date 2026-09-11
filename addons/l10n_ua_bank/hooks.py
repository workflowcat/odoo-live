"""Правила звірки банку для зарплатних платежів.

Порядок правил важливий. Платіж «ПДФО з авансу за серпень» містить слово «аванс», тому
широке правило зарплати забрало б його на рахунок 661. Спеціальні правила стоять першими,
зарплата - останньою. Номер послідовності задає цей порядок явно.
"""
RULES = [
    # (номер, назва, рахунок, слова)
    (10, "ПДФО (6411)", "6411", ["пдфо", "податок на доходи", "податку на доходи"]),
    (20, "Військовий збір (6415)", "6415", ["військовий збір", "військового збору", "військ. збір"]),
    (30, "ЄСВ (651)", "651", ["єсв", "єдиний внесок", "єдиного внеску", "єдиний соціальний"]),
    (40, "Аліменти (6851)", "6851", ["алімент"]),
    (50, "ФОП-підрядник (6851)", "6851", ["договором підряду", "договір підряду", "фоп ", "послуги фоп"]),
    (90, "Зарплата на картки (661)", "661", ["заробітн", "зарплат", "аванс", "винагород"]),
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
        for sequence, name, code, words in RULES:
            pattern = "(?i)" + "|".join(words)
            existing = Model.search([("name", "=", name), ("company_id", "=", company.id)], limit=1)
            if existing:
                existing.write({"match_label_param": pattern, "sequence": sequence})
                continue
            acc = _account(env, company, code)
            if not acc:
                continue
            Model.create({"name": name, "company_id": company.id, "sequence": sequence,
                          "trigger": "manual", "can_be_proposed": True,
                          "match_label": "match_regex", "match_label_param": pattern,
                          "line_ids": [(0, 0, {"account_id": acc.id, "amount_type": "percentage", "amount_string": "100", "label": name})]})
        bank = env["account.journal"].search([("type", "=", "bank"), ("company_id", "=", company.id)], limit=1)
        if bank and bank.name in ("Bank", "Банк"):
            bank.name = "Банк (поточний рахунок)"
