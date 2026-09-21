{
    "name": "Україна: п'ять розділів меню",
    "summary": "Верхнє меню під роботу бухгалтера: Зарплата, Працівники, Банк, Історія, Налаштування",
    "version": "19.0.1.1.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "hr", "hr_holidays", "hr_org_chart", "contacts", "calendar",
        "l10n_ua_period", "l10n_ua_changes", "l10n_ua_reporting",
        "l10n_ua_dashboard", "l10n_ua_index", "l10n_ua_bank_online",
        "l10n_ua_payroll_account", "l10n_ua_hr_orders", "l10n_ua_hr_docs", "l10n_ua_setup", "l10n_ua_average", "l10n_ua_onboarding", "l10n_ua_payroll_ui", "l10n_ua_military",
        "l10n_ua_people",
        # логічні модулі, чиї пункти меню розставляє саме ця навігація
        "l10n_ua_gph", "l10n_ua_kp", "l10n_ua_hire",
        # екрани: їхні дії і пункти меню розставляє ця навігація, тому вони мусять стояти раніше
        "l10n_ua_hire_ui", "l10n_ua_reporting_ui", "l10n_ua_setup_ui", "l10n_ua_bank_ui",
    ],
    "data": ["views/menus_areas.xml", "views/hr_leave_views.xml", "data/res_lang_data.xml"],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_navigation/static/src/navigation.scss",
        ],
    },
    "installable": True,
}
