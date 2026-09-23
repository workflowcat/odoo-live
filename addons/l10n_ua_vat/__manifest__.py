{
    "name": "Україна: ПДВ (перша подія, податкові накладні, РК)",
    "summary": "Перша подія за п.187.1 ПКУ, податкові накладні і розрахунки коригування, "
               "XML для ЄРПН, компенсуючі ПЗ, зведення ПДВ за період",
    "description": "Український облік ПДВ поверх нативного account і плану ua_psbo. "
                   "Нативний Odoo дає план рахунків, податки ПДВ і суми податку в рахунках. "
                   "Цей модуль додає те, чого в Odoo немає: правило першої події "
                   "(оплата чи відвантаження, що раніше), податкову накладну і розрахунок "
                   "коригування як окремі документи з XML для ЄРПН, компенсуючі податкові "
                   "зобов'язання за п.198.5 і ст.199 ПКУ, строки реєстрації та оцінку штрафу. "
                   "Модуль логічний: жодного OWL, жодної залежності від модулів інтерфейсу. "
                   "Опис у docs/base/spec-vat.md.",
    "version": "19.0.1.1.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["account", "l10n_ua"],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_vat_relief_views.xml",
        "views/ua_vat_document_views.xml",
        "views/ua_vat_compensation_views.xml",
        "views/ua_vat_period_views.xml",
        "views/account_move_views.xml",
        "views/account_payment_views.xml",
        "views/res_partner_views.xml",
        "views/product_views.xml",
        "views/menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
