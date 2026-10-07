{
    "name": "Україна: ФОП на єдиному податку (3 група)",
    "summary": "Книга обліку доходів за касовим методом, квартальний розрахунок ЄП, "
               "військового збору і ЄСВ «за себе», контроль річного ліміту групи",
    "description": "Тонкий контур ФОП поверх нативного account. Дохід рахується касовим "
                   "методом: книга доходів наповнюється з проведених платежів у журналах "
                   "банку і каси, валютне надходження переводиться в гривню курсом на дату "
                   "надходження з нативних res.currency.rate (їх наповнює l10n_ua_nbu, але "
                   "залежності від нього немає). Квартальний розрахунок дає ЄП, військовий "
                   "збір і ЄСВ, а також показники декларації платника ЄП наростаючим "
                   "підсумком з початку року. Усі законодавчі числа - мінімальна зарплата, "
                   "ставки ЄП, ВЗ і ЄСВ, множник ліміту - лежать у датованих записах "
                   "ua.fop.param, у коді їх немає. Модуль логічний: жодного OWL, жодної "
                   "залежності від модулів інтерфейсу. Опис у docs/base/spec-fop-migrate-edr.md.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["account", "l10n_ua"],
    "data": [
        "security/ir.model.access.csv",
        "security/ua_fop_security.xml",
        "data/ua_fop_param_data.xml",
        "views/ua_fop_param_views.xml",
        "views/ua_fop_income_views.xml",
        "views/ua_fop_quarter_views.xml",
        "views/res_company_views.xml",
        "views/account_payment_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
