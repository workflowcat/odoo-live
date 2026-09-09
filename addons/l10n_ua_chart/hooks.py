"""План рахунків у вигляді, звичному бухгалтеру.

Odoo встановлює український план з англійськими назвами (переклад не застосовано під час
встановлення) і доповнює коди нулями до шести знаків (100000 замість 100). Тут:
1) повертаємо назви з шаблону українською;
2) повертаємо коди шаблону (10, 103, 23, 301, 311, 361, 631, 641, 6411, 651, 661, 92);
3) перекладаємо назви журналів.
Дані Odoo і OCA не змінюються, лише записи в базі клієнта.
"""
import logging
import re

_logger = logging.getLogger(__name__)

JOURNALS = {
    "Sales": "Реалізація", "Purchases": "Придбання", "Miscellaneous Operations": "Інші операції",
    "Cash Basis Taxes": "Податки за касовим методом", "Exchange Difference": "Курсові різниці",
    "Bank": "Банк (поточний рахунок)", "Cash": "Каса", "Customer Invoices": "Рахунки клієнтам",
    "Vendor Bills": "Рахунки постачальників",
}


def _load_uk_names(env):
    lang = env["res.lang"].with_context(active_test=False).search([("code", "=", "uk_UA")])
    if not lang:
        return
    try:
        env["account.chart.template"]._load_translations(langs=["uk_UA"], companies=env["res.company"].search([]))
    except Exception as e:   # шаблон іншої країни або інша версія Odoo
        _logger.warning("Не вдалося застосувати переклади плану рахунків: %s", e)


def _short_codes(env):
    """Код рахунку = код із шаблону (xmlid ...ua_psbp_<код>). Пропускаємо, якщо код уже зайнятий."""
    Data = env["ir.model.data"].sudo()
    Account = env["account.account"].sudo()
    changed = 0
    for d in Data.search([("model", "=", "account.account"), ("name", "like", "ua_psbp_")]):
        m = re.search(r"ua_psbp_(\d+)$", d.name)
        if not m:
            continue
        account = Account.browse(d.res_id).exists()
        target = m.group(1)
        if not account or account.code == target:
            continue
        company = account.company_ids[:1] or env.company
        if Account.with_company(company).search_count([("code", "=", target), ("company_ids", "in", company.ids)]):
            continue
        try:
            account.with_company(company).code = target
            changed += 1
        except Exception as e:
            _logger.warning("Рахунок %s: код не змінено (%s)", account.code, e)
    _logger.info("Скорочено кодів рахунків: %s", changed)
    return changed


def _journal_names(env):
    for journal in env["account.journal"].sudo().search([]):
        uk = JOURNALS.get(journal.name)
        if uk:
            journal.with_context(lang="uk_UA").name = uk
            journal.with_context(lang="en_US").name = uk


CORE_ACCOUNTS = {
    "999001": "Дохід від округлення готівки", "999002": "Витрати від округлення готівки",
    "999997": "Дохід від знижки при оплаті", "999998": "Витрати на знижку при оплаті",
    "999999": "Нерозподілений прибуток (збиток)",
}


def _core_account_names(env):
    Account = env["account.account"].sudo()
    for code, uk in CORE_ACCOUNTS.items():
        for account in Account.search([("code", "=", code)]):
            account.with_context(lang="uk_UA").name = uk
            account.with_context(lang="en_US").name = uk


def post_init_hook(env):
    _load_uk_names(env)
    _short_codes(env)
    _journal_names(env)
    _core_account_names(env)
