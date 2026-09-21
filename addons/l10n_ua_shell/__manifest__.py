{
    "name": "Каркас інтерфейсу: смуга навігації ліворуч і друк пакетом (Україна)",
    "summary": "Навігація ліворуч замість вкладок зверху для всіх застосунків; перегляд документів і друк браузером",
    "version": "19.0.1.3.0",
    "category": "Hidden",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            # спільні правила власних екранів (.o_ua_*): були в l10n_ua_payroll_rules,
            # тобто в логіці; каркас інтерфейсу - їхнє місце
            "l10n_ua_shell/static/src/ua_ui.scss",
            "l10n_ua_shell/static/src/side_rail.scss",
            "l10n_ua_shell/static/src/side_rail.js",
            "l10n_ua_shell/static/src/side_rail.xml",
            "l10n_ua_shell/static/src/act.scss",
            "l10n_ua_shell/static/src/act_service.js",
            "l10n_ua_shell/static/src/act_dialog.xml",
        ],
    },
    "installable": True,
}
