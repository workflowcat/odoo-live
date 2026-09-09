{
    "name": "Зведення: головна панель на OWL (Україна)",
    "summary": "Щільний екран головної сторінки: нарахування по підрозділах, платежі і строки, попередження, документи, пульт команд",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "l10n_ua_hub",
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
    "post_init_hook": "post_init_hook",
    "installable": True,
}
