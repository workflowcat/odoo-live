{
    "name": "Прийняття на роботу: екран (Україна)",
    "summary": "Клієнтська дія «Прийняття» на OWL над моделями l10n_ua_hire",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources",
    # Екран і нічого більше: моделі, перевірки, звіти і сама дія прийняття - у l10n_ua_hire,
    # який ставиться і працює без цього модуля. hire.js бере службу ua_act із каркаса l10n_ua_shell.
    # hire.js відкриває екран «Звітності» за тегом ua_reporting (чернетка J3001005 прийняття),
    # тому той екран мусить стояти.
    "depends": ["l10n_ua_hire", "l10n_ua_reporting_ui", "l10n_ua_shell", "web"],
    "data": [
        "views/ua_hire_ui_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_hire_ui/static/src/hire.scss",
            "l10n_ua_hire_ui/static/src/hire.js",
            "l10n_ua_hire_ui/static/src/hire.xml",
        ],
    },
    "installable": True,
}
