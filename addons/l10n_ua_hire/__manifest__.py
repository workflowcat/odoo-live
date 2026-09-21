{
    "name": "Прийняття на роботу (Україна)",
    "summary": "Одна справа від кандидата до поданого повідомлення: дані, документи, перевірки, наказ",
    "version": "19.0.1.3.1",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources",
    # Логіка не залежить від інтерфейсу: місце пункту меню ставить l10n_ua_navigation.
    # Екран hire.js бере службу ua_act із каркаса l10n_ua_shell через спільний бандл
    # web.assets_backend - у продукті каркас стоїть завжди (l10n_ua_home -> l10n_ua_period
    # -> l10n_ua_shell). Свій екран цього модуля чекає на поділ на логіку і UI.
    "depends": ["l10n_ua_hr_card", "l10n_ua_hr_orders", "l10n_ua_payroll_reports", "l10n_ua_reporting", "l10n_ua_military", "web"],
    # pypdf - лише для підрахунку сторінок у "Опис документів особової справи"; за відсутності
    # бібліотеки _pdf_page_count() тихо повертає 1 сторінку (try/except у моделі).
    "external_dependencies": {"python": ["pypdf"]},
    "data": [
        "security/ir.model.access.csv",
        "views/ua_hire_views.xml",
        "report/ua_hire_package_report.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_hire/static/src/hire.scss",
            "l10n_ua_hire/static/src/hire.js",
            "l10n_ua_hire/static/src/hire.xml",
        ],
    },
    "installable": True,
}
