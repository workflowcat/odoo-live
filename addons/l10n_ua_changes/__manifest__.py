{
    "name": "Україна: журнал змін і закриття періоду",
    "summary": "Хто, коли і що змінив у зарплаті, кадрах, обліку і банку; перевірка змін бухгалтером; закриття місяця датою блокування",
    "version": "19.0.1.1.1",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "account", "hr_holidays", "payroll",
        "l10n_ua_payroll_rules", "l10n_ua_hr_docs", "l10n_ua_hr_orders",
        "l10n_ua_payments", "l10n_ua_reporting", "l10n_ua_index",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_change_log_views.xml",
        "views/ua_period_close_views.xml",
    ],
    "installable": True,
}
