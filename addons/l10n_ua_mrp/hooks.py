# -*- coding: utf-8 -*-
"""Рахунки виробництва для компанії на плані ua_psbo.

Нативний Odoo 19 уміє все, що треба українському виробництву, але з коробки
нічого не проводить: оцінка запасів стоїть «періодична», у виробничої локації
немає рахунку, а всі товари лежать в одній категорії «All» з рахунком 201.
Тоді виробниче замовлення не дає жодної проводки, і бухгалтер бачить порожню
19 колонку там, де мають бути 23 і 26.

Тут один прохід, який ставить усе на місце:

* компанія - постійна оцінка запасів (`inventory_valuation = real_time`),
  журнал оцінки і рахунок оцінки за замовчуванням;
* виробнича локація - рахунок 231 «Основне виробництво»: саме він стає
  кореспондуючим для списання комплектуючих і для випуску продукції;
* локації списання (інвентаризація, брухт) - рахунок 947;
* три категорії товарів під український план: сировина (201/943),
  готова продукція (26/901), товари (281/902), усі з рахунком виробництва 231.

Далі нативна логіка `stock_account` робить проводки сама:
Дт 231 Кт 201 при списанні у виробництво, Дт 26 Кт 231 при випуску,
Дт 901 Кт 26 при продажу (англосаксонська собівартість реалізації, яку план
ua_psbo вмикає сам).

Два входи, одна робота. `post_init_hook` - для компанії, план якої вже
завантажено; коли модуль ставлять раніше за план, те саме робить
`_post_load_data` у models/account_chart_template.py. Ідемпотентно: що вже
стоїть, того не чіпаємо.
"""
import logging

_logger = logging.getLogger(__name__)

# Рахунок виробництва: кореспондуючий для комплектуючих і для випуску.
ACC_WIP = "ua_psbp_231"
# Рахунки оцінки запасів за категоріями.
ACC_RAW = "ua_psbp_201"
ACC_FINISHED = "ua_psbp_26"
ACC_GOODS = "ua_psbp_281"
# Рахунки витрат при вибутті.
ACC_COGS_PRODUCT = "ua_psbp_901"
ACC_COGS_GOODS = "ua_psbp_902"
ACC_COGS_STOCK = "ua_psbp_943"
ACC_SHORTAGE = "ua_psbp_947"
# Дохід від реалізації готової продукції і товарів.
ACC_INCOME_PRODUCT = "ua_psbp_701"
ACC_INCOME_GOODS = "ua_psbp_702"
# Загальновиробничі витрати - база розподілу.
ACC_ZVV = "ua_psbp_91"

# Категорії, які модуль тримає для українського плану. Назви збігаються з тими,
# що вже вживає демо-скрипт, щоб не плодити дублів.
CATEGORIES = [
    {
        "key": "ua_mrp_categ_raw",
        "name": "Сировина і матеріали",
        "valuation": ACC_RAW,
        "expense": ACC_COGS_STOCK,
        "income": ACC_INCOME_PRODUCT,
    },
    {
        "key": "ua_mrp_categ_finished",
        "name": "Готова продукція",
        "valuation": ACC_FINISHED,
        "expense": ACC_COGS_PRODUCT,
        "income": ACC_INCOME_PRODUCT,
    },
    {
        "key": "ua_mrp_categ_goods",
        "name": "Товари",
        "valuation": ACC_GOODS,
        "expense": ACC_COGS_GOODS,
        "income": ACC_INCOME_GOODS,
    },
]


def _chart(env, company):
    return env["account.chart.template"].with_company(company).sudo()


def account_by_xmlid(env, company, xmlid):
    """Рахунок за xmlid шаблону. Код у базі буває і 231000, і 231 (після
    l10n_ua_chart), а xmlid не змінюється ніколи."""
    account = _chart(env, company).ref(xmlid, raise_if_not_found=False)
    if account:
        return account
    # Запасний шлях: план завантажили не шаблоном - шукаємо за кодом.
    code = xmlid.rsplit("_", 1)[-1]
    Account = env["account.account"].sudo().with_company(company)
    for candidate in Account.search(
        [("code", "=like", code + "%"), ("company_ids", "in", company.ids)], order="code"
    ):
        if candidate.code.rstrip("0") == code or candidate.code == code:
            return candidate
    return Account.browse()


def _setup_company(env, company, accounts):
    """Постійна оцінка запасів і середньозважена собівартість.

    Без постійної оцінки (`real_time`) жодна виробнича проводка не зʼявиться:
    Odoo просто нічого не проводить до закриття періоду. Метод собівартості з
    коробки - «нормативна ціна», і тоді випуск продукції оцінюється плановою
    ціною з картки товару, а не тим, що справді пішло у виробництво. Для
    українського обліку беремо середньозважену (п. 16 П(С)БО 9): випуск
    оцінюється фактичними витратами, 231 закривається в нуль.
    """
    values = {}
    if company.inventory_valuation != "real_time":
        values["inventory_valuation"] = "real_time"
    if company.cost_method == "standard":
        values["cost_method"] = "average"
    if not company.account_stock_valuation_id and accounts["raw"]:
        values["account_stock_valuation_id"] = accounts["raw"].id
    if not company.account_stock_journal_id:
        journal = env["account.journal"].sudo().search(
            [("code", "=", "STJ"), ("company_id", "=", company.id)], limit=1)
        if journal:
            values["account_stock_journal_id"] = journal.id
    if accounts["wip"] and not company.account_production_wip_account_id:
        values["account_production_wip_account_id"] = accounts["wip"].id
    if accounts["zvv"] and not company.account_production_wip_overhead_account_id:
        values["account_production_wip_overhead_account_id"] = accounts["zvv"].id
    if values:
        company.sudo().write(values)
    return bool(values)


def _setup_locations(env, company, accounts):
    """Виробнича локація - 231, локації списання - 947.

    Саме рахунок локації вирішує кореспонденцію: `stock_account` бере його з
    тієї сторони переміщення, що не є складом. Комплектуючі йдуть на виробничу
    локацію - Кт 201 Дт 231; продукція йде з неї - Кт 231 Дт 26.
    """
    Location = env["stock.location"].sudo()
    touched = 0
    if accounts["wip"]:
        production = Location.search(
            [("usage", "=", "production"), ("company_id", "=", company.id)])
        for location in production:
            if not location.valuation_account_id:
                location.valuation_account_id = accounts["wip"]
                touched += 1
    if accounts["shortage"]:
        losses = Location.search(
            [("usage", "=", "inventory"), ("company_id", "=", company.id)])
        for location in losses:
            if not location.valuation_account_id:
                location.valuation_account_id = accounts["shortage"]
                touched += 1
    return touched


def _setup_categories(env, company, accounts):
    """Три категорії під український план плюс значення за замовчуванням.

    `ir.default` на категорії - це те, що Odoo називає «company dependent
    fallback»: категорія «All», у якій лежать товари з демо і з імпорту,
    успадковує рахунок оцінки і рахунок виробництва звідти.
    """
    Category = env["product.category"].sudo().with_company(company)
    Default = env["ir.default"].sudo()
    made = 0
    if accounts["wip"]:
        Default.set("product.category", "property_stock_account_production_cost_id",
                    accounts["wip"].id, company_id=company.id)
    Default.set("product.category", "property_valuation", "real_time", company_id=company.id)
    Default.set("product.category", "property_cost_method", "average", company_id=company.id)
    for spec in CATEGORIES:
        valuation = account_by_xmlid(env, company, spec["valuation"])
        if not valuation:
            continue
        category = Category.search([("name", "=", spec["name"])], limit=1)
        values = {
            "property_valuation": "real_time",
            "property_cost_method": "average",
            "property_stock_valuation_account_id": valuation.id,
        }
        if accounts["wip"]:
            values["property_stock_account_production_cost_id"] = accounts["wip"].id
        expense = account_by_xmlid(env, company, spec["expense"])
        income = account_by_xmlid(env, company, spec["income"])
        if expense:
            values["property_account_expense_categ_id"] = expense.id
        if income:
            values["property_account_income_categ_id"] = income.id
        if category:
            category.write(values)
        else:
            values["name"] = spec["name"]
            category = Category.create(values)
            made += 1
        env["ir.model.data"].sudo()._update_xmlids([{
            "xml_id": "l10n_ua_mrp.%s_%s" % (company.id, spec["key"]),
            "record": category,
            "noupdate": True,
        }])
    return made


def setup_costing(env, company):
    """Усе налаштування однією дією. Повертає True, якщо рахунки знайшлися."""
    accounts = {
        "wip": account_by_xmlid(env, company, ACC_WIP),
        "raw": account_by_xmlid(env, company, ACC_RAW),
        "shortage": account_by_xmlid(env, company, ACC_SHORTAGE),
        "zvv": account_by_xmlid(env, company, ACC_ZVV),
    }
    if not accounts["wip"]:
        _logger.warning(
            "l10n_ua_mrp: у компанії %s немає рахунку 231, налаштування пропущено",
            company.name)
        return False
    _setup_company(env, company, accounts)
    _setup_locations(env, company, accounts)
    _setup_categories(env, company, accounts)
    _logger.info("l10n_ua_mrp: рахунки виробництва налаштовано для компанії %s", company.name)
    return True


def post_init_hook(env):
    companies = env["res.company"].sudo().search([("chart_template", "=", "ua_psbo")])
    done = sum(1 for company in companies if setup_costing(env, company))
    _logger.info("l10n_ua_mrp: налаштовано компаній - %d з %d", done, len(companies))
