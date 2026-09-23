{
    "name": "Україна: основні засоби, МНМА і нематеріальні активи",
    "summary": "Профілі 16 податкових груп ОЗ і 6 груп НМА на плані ua_psbo, "
               "амортизація з наступного місяця, ОЗ-1, ОЗ-3, ОЗ-6 і відомість амортизації",
    "description": "Тонка надбудова над OCA account_asset_management. Рушій амортизації, "
                   "картки активів, проводки, крон і списання - усе з OCA, ми його не чіпаємо. "
                   "Наше тут три речі. Перша: готовий набір профілів під 16 груп основних "
                   "засобів (п. 138.3.3 ПКУ) і 6 груп нематеріальних активів (п. 138.3.4) з "
                   "мінімальними строками і рахунками плану ua_psbo; рахунок шукається за "
                   "xmlid шаблону, тож працює і з повними кодами Odoo (104000), і зі "
                   "скороченими з l10n_ua_chart (104). Друга: амортизація починається з місяця, "
                   "наступного за введенням в експлуатацію (п. 29 П(С)БО 7, п. 138.3.1 ПКУ) - "
                   "цього в OCA немає. Третя: друковані форми наказу Мінстату 352 - ОЗ-1, ОЗ-3, "
                   "ОЗ-6 - і відомість нарахування амортизації за місяць. "
                   "Модуль логічний: жодного OWL, жодної залежності від модулів інтерфейсу. "
                   "Опис у docs/base/spec-assets-nbu.md.",
    "version": "19.0.1.1.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["account_asset_management", "l10n_ua"],
    "data": [
        "security/ir.model.access.csv",
        "report/ua_asset_reports.xml",
        "report/ua_depreciation_sheet_report.xml",
        "views/account_asset_profile_views.xml",
        "views/account_asset_views.xml",
        "views/ua_depreciation_sheet_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
