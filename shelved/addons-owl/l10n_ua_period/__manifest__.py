{
    "name": "Україна: робоче місце місяця",
    "summary": "Одна сторінка на місяць: головна дія, числа, зміни, черга винятків, кроки і закриття",
    "version": "19.0.1.6.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_screen", "l10n_ua_changes", "l10n_ua_dashboard", "l10n_ua_hr_docs", "l10n_ua_hr_orders", "l10n_ua_payments", "l10n_ua_reporting", "l10n_ua_reporting_ui", "l10n_ua_bank_ui", "l10n_ua_shell", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_period_views.xml",
        "data/ir_cron_timesheet.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_period/static/src/period.scss",
            "l10n_ua_period/static/src/period.js",
            "l10n_ua_period/static/src/period.xml",
        ],
    },
    "installable": True,
    "post_init_hook": "post_init_hook",
}
