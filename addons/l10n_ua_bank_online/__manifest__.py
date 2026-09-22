{
    "name": "Україна: банк онлайн (ПриватБанк, Monobank) і робоче місце звірки",
    "summary": "Виписки з банку через API замість файлів: провайдери, підтягування, правила звірки, чек-лист підключення",
    "version": "19.0.1.4.0",
    "category": "Accounting",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    # Логіка банку без інтерфейсу: екран «Банк» - окремий l10n_ua_bank_ui.
    "depends": [
        "l10n_ua_screen",
        "account_statement_import_online",
        "account_statement_import_file",
        "account_statement_import_sheet_file",
        "l10n_ua_bank",
        # ua.payments.plan: рядки «що сплачено, що заплановано» (логіка, не панель)
        "l10n_ua_payments",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ua_statement_mappings.xml",
        "views/online_bank_statement_provider_views.xml",
        "views/ua_bank_connect_views.xml",
    ],
    "installable": True,
}
