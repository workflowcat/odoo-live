{
    "name": "Банк: екран рахунків і звірки (Україна)",
    "summary": "Клієнтська дія «Банк» на OWL над операціями l10n_ua_bank_online",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    # Екран і нічого більше: підтягування виписок, правила звірки, провайдери і чек-лист
    # підключення - у l10n_ua_bank_online (ua.bank.ops, ua.bank.connect), який ставиться
    # і працює без цього модуля. Кроки «Періоду» кличуть ua.bank.ops напряму.
    "depends": [
        "l10n_ua_screen",
        "l10n_ua_bank_online",
        "l10n_ua_shell",
        "account_reconcile_oca",
        "account_statement_import_file",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_bank_board_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_bank_ui/static/src/bank_board.scss",
            "l10n_ua_bank_ui/static/src/bank_board.js",
            "l10n_ua_bank_ui/static/src/bank_board.xml",
        ],
    },
    "installable": True,
}
