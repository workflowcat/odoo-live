{
    "name": "Україна: п'ять розділів меню",
    "summary": "Верхнє меню під роботу бухгалтера: Зарплата, Працівники, Банк, Історія, Налаштування",
    "version": "19.0.1.0.1",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "hr", "hr_holidays",
        "l10n_ua_period", "l10n_ua_changes", "l10n_ua_reporting", "l10n_ua_hub",
        "l10n_ua_dashboard", "l10n_ua_index", "l10n_ua_bank_online",
        "l10n_ua_payroll_account", "l10n_ua_hr_orders", "l10n_ua_hr_docs", "l10n_ua_setup",
    ],
    "data": ["views/menus_areas.xml"],
    "installable": True,
}
