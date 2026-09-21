{
    "name": "Звітність: екран робочого місця (Україна)",
    "summary": "Клієнтська дія «Звітність» на OWL над прогонами l10n_ua_reporting",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    # Екран і нічого більше: перевірки, формування файлів і стани прогону - у l10n_ua_reporting,
    # який ставиться і працює без цього модуля. reporting.js бере службу ua_act із l10n_ua_shell.
    "depends": ["l10n_ua_reporting", "l10n_ua_shell", "web"],
    "data": [
        "views/ua_reporting_ui_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_reporting_ui/static/src/reporting.scss",
            "l10n_ua_reporting_ui/static/src/reporting.js",
            "l10n_ua_reporting_ui/static/src/reporting.xml",
        ],
    },
    "installable": True,
}
