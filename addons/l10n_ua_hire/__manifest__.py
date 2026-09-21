{
    "name": "Прийняття на роботу (Україна)",
    "summary": "Одна справа від кандидата до поданого повідомлення: дані, документи, перевірки, наказ",
    "version": "19.0.1.4.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources",
    # Логіка не залежить від інтерфейсу: екран «Прийняття» живе в окремому l10n_ua_hire_ui,
    # місце пункту меню ставить l10n_ua_navigation.
    "depends": ["l10n_ua_hr_card", "l10n_ua_hr_orders", "l10n_ua_payroll_reports", "l10n_ua_reporting", "l10n_ua_military", "web"],
    # pypdf - лише для підрахунку сторінок у "Опис документів особової справи"; за відсутності
    # бібліотеки _pdf_page_count() тихо повертає 1 сторінку (try/except у моделі).
    "external_dependencies": {"python": ["pypdf"]},
    "data": [
        "security/ir.model.access.csv",
        "views/ua_hire_views.xml",
        "report/ua_hire_package_report.xml",
    ],
    "installable": True,
}
