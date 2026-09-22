"""План рахунків у вигляді, звичному бухгалтеру.

Odoo встановлює український план з англійськими назвами (переклад не застосовано під час
встановлення) і доповнює коди нулями до шести знаків (100000 замість 100). Тут:
1) повертаємо назви з шаблону українською;
2) повертаємо коди шаблону (10, 103, 23, 301, 311, 361, 631, 641, 6411, 651, 661, 92);
3) перекладаємо назви журналів;
4) вирівнюємо валюту типових прайс-листів під валюту компанії.
Дані Odoo і OCA не змінюються, лише записи в базі клієнта.

Два входи, одна робота. `post_init_hook` - для бази, де план уже стоїть; коли модуль
ставлять раніше за план (звичайний порядок: спершу модулі, потім `try_loading`), те саме
робить `_post_load_data` у models/account_chart_template.py. Усе ідемпотентне.
"""
import logging
import re

_logger = logging.getLogger(__name__)

UK = "uk_UA"

JOURNALS = {
    "Sales": "Реалізація", "Purchases": "Придбання", "Miscellaneous Operations": "Інші операції",
    "Cash Basis Taxes": "Податки за касовим методом", "Exchange Difference": "Курсові різниці",
    "Bank": "Банк (поточний рахунок)", "Cash": "Каса", "Customer Invoices": "Рахунки клієнтам",
    "Vendor Bills": "Рахунки постачальників",
}


def _ensure_uk_lang(env):
    """Увімкнути uk_UA разом із перекладами.

    На порожній базі Odoo ставиться англійською, і uk_UA лежить у res.lang вимкненою:
    будь-який with_context(lang="uk_UA") нижче падає з «Invalid language code». Той самий
    запобіжник стоїть у l10n_ua_payroll_rules - це дві різні гілки графа залежностей."""
    Lang = env["res.lang"].with_context(active_test=False)
    lang = Lang.search([("code", "=", UK)], limit=1)
    if not lang or lang.active:
        return lang
    try:
        env["base.language.install"].create({
            "lang_ids": [(6, 0, lang.ids)], "overwrite": False,
        }).lang_install()
    except Exception as e:   # переклади недоступні - достатньо самої мови
        _logger.warning("Не вдалося завантажити переклади uk_UA (%s); вмикаємо мову без них", e)
        env["res.lang"]._activate_lang(UK)
    return Lang.search([("code", "=", UK)], limit=1)


def _chart_companies(env):
    """Компанії, у яких план рахунків уже завантажено.

    Перекладати назви рахунків можна тільки там, де ці рахунки є. Компанія без
    плану (а на встановленні модуля таких зазвичай усі) віддає `chart_template`
    порожнім, і `_load_translations` на ній падає - раніше це валило переклад
    усім компаніям разом, і назви лишалися англійськими.
    """
    Chart = env["account.chart.template"].sudo()
    codes = set(Chart._get_chart_template_mapping(get_all=True))
    return env["res.company"].sudo().search([("chart_template", "!=", False)]).filtered(
        lambda company: company.chart_template in codes)


def _load_uk_names(env):
    """Українські назви рахунків з шаблону - по одній компанії за раз.

    Два входи ведуть сюди: `_post_load_data` (план щойно завантажили) і
    `post_init_hook` (модуль ставлять на базу, де план уже стоїть, - ремонт).
    Компанія без плану просто пропускається, а збій на одній компанії не
    забирає переклад у решти.
    """
    if not _ensure_uk_lang(env):
        return 0
    companies = _chart_companies(env)
    if not companies:
        _logger.info(
            "Плану рахунків ще немає: українські назви рахунків стануть на місце "
            "разом із планом (_post_load_data).")
        return 0
    Chart = env["account.chart.template"].sudo()
    done = 0
    for company in companies:
        try:
            Chart.with_company(company)._load_translations(langs=[UK], companies=company)
            done += 1
        except Exception as e:   # шаблон іншої країни або інша версія Odoo
            _logger.warning(
                "Компанія «%s»: переклади плану рахунків не застосовано (%s)",
                company.display_name, e)
    return done


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
    if not _ensure_uk_lang(env):
        return
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
    if not _ensure_uk_lang(env):
        return
    Account = env["account.account"].sudo()
    for code, uk in CORE_ACCOUNTS.items():
        for account in Account.search([("code", "=", code)]):
            account.with_context(lang="uk_UA").name = uk
            account.with_context(lang="en_US").name = uk


def _repair_lone_pricelist(env):
    """Єдиний прайс-лист компанії - у валюті компанії.

    `product` створює прайс-лист «Default» у валюті компанії на момент створення, а на
    чистій базі це долар: гривня стає валютою компанії лише коли завантажується план
    ua_psbo. Створений раніше прайс-лист так і лишається доларовим, і кожне замовлення
    на продаж мовчки виходить у USD (валюта замовлення - related до прайс-листа).

    Звичайно цей випадок ловить res_company.write (валюта змінилася - типовий прайс-лист
    іде за нею). Це - ремонт для бази, де валюту змінили ще до встановлення модуля: там
    старої валюти вже не дізнатися, тому чіпаємо лише компанію з єдиним прайс-листом без
    жодного правила. Де прайс-листів кілька, котрийсь із них заведено свідомо (експортний
    у євро), і вгадувати за бухгалтера ми не будемо.
    """
    if "product.pricelist" not in env:
        return 0
    Pricelist = env["product.pricelist"].sudo().with_context(active_test=False)
    changed = 0
    for company in env["res.company"].sudo().search([]):
        if not company.currency_id:
            continue
        pricelists = Pricelist.search([("company_id", "=", company.id)])
        if len(pricelists) != 1 or pricelists.item_ids:
            continue
        if pricelists.currency_id != company.currency_id:
            pricelists.currency_id = company.currency_id
            changed += 1
    if changed:
        _logger.info("Прайс-листів переведено у валюту компанії: %s", changed)
    return changed


def apply_chart_shape(env):
    """Усе, що робить план читабельним. Ідемпотентно, у порядку залежностей."""
    _ensure_uk_lang(env)
    _load_uk_names(env)
    _short_codes(env)
    _journal_names(env)
    _core_account_names(env)
    _repair_lone_pricelist(env)


def post_init_hook(env):
    apply_chart_shape(env)
