{
    "name": "Звітність: робоче місце з перевірками (Україна)",
    "summary": "Один екран: обрати звіт і період, перевірити дані, сформувати XML/PDF, позначити поданим",
    "version": "19.0.1.0.4",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "l10n_ua_screen",
        "l10n_ua_payroll_reports",
        "l10n_ua_hr_docs",
        "l10n_ua_hr_orders",
        "l10n_ua_dashboard",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_report_run_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_reporting/static/src/reporting.scss",
            "l10n_ua_reporting/static/src/reporting.js",
            "l10n_ua_reporting/static/src/reporting.xml",
        ],
    },
    "installable": True,
}
