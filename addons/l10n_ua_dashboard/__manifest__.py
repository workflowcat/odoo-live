{
    "name": "Зведення: головна панель на OWL (Україна)",
    "summary": "Аналітика періоду: нарахування по підрозділах, обороти, документи",
    "version": "19.0.1.1.1",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "l10n_ua_screen",
        "l10n_ua_payroll_account",
        "l10n_ua_hr_docs",
        "l10n_ua_military",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_dashboard/static/src/dashboard.scss",
            "l10n_ua_dashboard/static/src/dashboard.js",
            "l10n_ua_dashboard/static/src/dashboard.xml",
        ],
    },
    "installable": True,
}
