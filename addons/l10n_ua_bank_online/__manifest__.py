{
    "name": "Україна: банк онлайн (ПриватБанк, Monobank) і робоче місце звірки",
    "summary": "Виписки з банку через API замість файлів; екран «Банк»: рахунки, завантаження, звірка зарплатних платежів",
    "version": "19.0.1.1.1",
    "category": "Accounting",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "account_statement_import_online",
        "account_statement_import_file",
        "account_statement_import_sheet_file",
        "l10n_ua_bank",
        "l10n_ua_dashboard",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ua_statement_mappings.xml",
        "views/online_bank_statement_provider_views.xml",
        "views/ua_bank_connect_views.xml",
        "views/ua_bank_board_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_bank_online/static/src/bank_board.scss",
            "l10n_ua_bank_online/static/src/bank_board.js",
            "l10n_ua_bank_online/static/src/bank_board.xml",
        ],
    },
    "installable": True,
}
