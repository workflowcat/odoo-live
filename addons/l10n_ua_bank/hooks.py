"""Банківський журнал для зарплатного кола: рахунок «гроші в дорозі» і правила звірки.

Дві речі, обидві прив'язані до плану рахунків.

1. **Рахунок 333 «Грошові кошти в дорозі в національній валюті»** стає рахунком
   очікуваних платежів банківського журналу (`account.payment.method.line.payment_account_id`,
   обидва напрями). Проведений платіж відомості тоді робить Дт 661 / Кт 333, а рядок
   виписки - Дт 333 / Кт 311: гроші проходять через 311 один раз, а 333 закривається
   зведенням рядка виписки з платежем. Без цього рахунку Odoo заводить собі англомовні
   «Outstanding Payments / Receipts» під кодом 311xxx, і та сама сума лягала і на платіж,
   і на правило звірки. 333 має бути звірюваним (`reconcile`), бо саме на ньому сходяться
   платіж і виписка; у шаблоні ua_psbo він іде без цієї позначки.

2. **Правила звірки за текстом призначення.** Порядок правил важливий: платіж «ПДФО з
   авансу за серпень» містить слово «аванс», тому широке правило зарплати забрало б його
   на рахунок 661. Спеціальні правила стоять першими, зарплата - останньою. Номер
   послідовності задає цей порядок явно. Правила спрацьовують лише тоді, коли за рядком
   виписки немає проведеного платежу (див. `_ua_payment_blocks_rule` у
   models/account_bank_statement_line.py) - інакше ті самі гроші закрилися б двічі.

Два входи, одна робота. `post_init_hook` - для компанії, план якої вже завантажено; коли
модуль ставлять раніше за план (звичайний порядок на новій базі), те саме робить
`_post_load_data` у models/account_chart_template.py. Обидва шляхи ідемпотентні: без
рахунку 661 правил немає взагалі, тому раніше на чистій базі «Застосувати правила» падало
з «Немає правил звірки».
"""
import logging

_logger = logging.getLogger(__name__)

RULES = [
    # (номер, назва, рахунок, слова)
    (10, "ПДФО (6411)", "6411", ["пдфо", "податок на доходи", "податку на доходи"]),
    (20, "Військовий збір (6415)", "6415", ["військовий збір", "військового збору", "військ. збір"]),
    (30, "ЄСВ (651)", "651", ["єсв", "єдиний внесок", "єдиного внеску", "єдиний соціальний"]),
    (40, "Аліменти (6851)", "6851", ["алімент"]),
    (50, "ФОП-підрядник (6851)", "6851", ["договором підряду", "договір підряду", "фоп ", "послуги фоп"]),
    # Готівка з каси в банк: ВКО робить Дт 333 / Кт 301, виписка закриває Дт 311 / Кт 333.
    (60, "Готівка в дорозі (333)", "333",
     ["здача готівки", "внесення готівки", "зарахування готівки", "готівки на рахунок"]),
    (90, "Зарплата на картки (661)", "661", ["заробітн", "зарплат", "аванс", "винагород"]),
]
# Рахунок очікуваних платежів банківського журналу.
OUTSTANDING_CODE = "333"
OUTSTANDING_XMLID = "ua_psbp_333"


def _account(env, company, code):
    Acc = env["account.account"].with_company(company)
    return Acc.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1) or \
        Acc.search([("code", "=like", f"{code}%"), ("company_ids", "in", company.id)], order="code", limit=1)


def _outstanding_account(env, company):
    """Рахунок 333 шаблону ua_psbo.

    Спершу за xmlid (`account.<компанія>_ua_psbp_333`): це той самий запис і до того, як
    l10n_ua_chart скоротить коди (333000 -> 333), і після. Пошук за кодом лишається
    запасним - на випадок плану, зібраного вручну.
    """
    account = env.ref("account.%s_%s" % (company.id, OUTSTANDING_XMLID), raise_if_not_found=False)
    if account and company.id in account.company_ids.ids:
        return account
    return _account(env, company, OUTSTANDING_CODE)


def set_outstanding_accounts(env, company):
    """Банківським журналам компанії - рахунок 333 як «гроші в дорозі». Ідемпотентно."""
    account = _outstanding_account(env, company)
    if not account:
        return 0
    if not account.reconcile:
        account.sudo().reconcile = True
    journals = env["account.journal"].sudo().search([
        ("type", "=", "bank"), ("company_id", "=", company.id)])
    changed = 0
    for journal in journals:
        lines = journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
        todo = lines.filtered(lambda line: line.payment_account_id != account)
        if todo:
            todo.write({"payment_account_id": account.id})
            changed += len(todo)
    return changed


def create_reconcile_models(env, company):
    """Правила звірки однієї компанії. Нічого не робить без рахунку 661."""
    if not _account(env, company, "661"):
        return 0
    Model = env["account.reconcile.model"].sudo()
    made = 0
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
        made += 1
    bank = env["account.journal"].sudo().search(
        [("type", "=", "bank"), ("company_id", "=", company.id)], limit=1)
    if bank and bank.name in ("Bank", "Банк"):
        bank.name = "Банк (поточний рахунок)"
    return made


def post_init_hook(env):
    total, outstanding = 0, 0
    companies = env["res.company"].sudo().search([])
    for company in companies:
        total += create_reconcile_models(env, company)
        outstanding += set_outstanding_accounts(env, company)
    _logger.info("l10n_ua_bank: створено правил звірки %d, рахунок 333 проставлено %d разів, "
                 "компаній %d", total, outstanding, len(companies))
