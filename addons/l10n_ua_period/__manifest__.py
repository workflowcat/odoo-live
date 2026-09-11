{
    "name": "Україна: період (закриття місяця)",
    "summary": "Одна сторінка на місяць: кроки роботи, стан кожного, обороти рахунків і що заважає закрити",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_dashboard", "l10n_ua_hr_docs", "l10n_ua_hr_orders", "l10n_ua_payments", "l10n_ua_reporting", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_period_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_period/static/src/period.scss",
            "l10n_ua_period/static/src/period.js",
            "l10n_ua_period/static/src/period.xml",
        ],
    },
    "installable": True,
}
