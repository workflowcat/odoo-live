{
    "name": "Анкета компанії: екран (Україна)",
    "summary": "Клієнтська дія «Анкета компанії» на OWL над моделями l10n_ua_setup",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    # Екран і нічого більше: питання, відповіді і запис у налаштування - у l10n_ua_setup,
    # який ставиться і працює без цього модуля.
    "depends": ["l10n_ua_setup", "l10n_ua_shell", "web"],
    "data": [
        "views/ua_setup_ui_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_setup_ui/static/src/setup.scss",
            "l10n_ua_setup_ui/static/src/setup.js",
            "l10n_ua_setup_ui/static/src/setup.xml",
        ],
    },
    "installable": True,
}
