{
    "name": "Зарплата: український інтерфейс і меню",
    "summary": "Одне меню «Зарплата» для всього циклу, українські назви довідників OCA, приховані технічні коди і зайві додатки для бухгалтера",
    "version": "19.0.1.0.5",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources/Payroll",
    "depends": ["l10n_ua_payroll_rules", "l10n_ua_average", "l10n_ua_payroll_account", "l10n_ua_payroll_reports", "l10n_ua_hr_docs", "l10n_ua_bank", "l10n_ua_hr_card", "l10n_ua_military", "account_usability", "account_financial_report"],
    "data": ["views/menus.xml", "views/menus_docs.xml", "views/menus_advance.xml", "views/menus_military.xml", "views/hr_payslip_views.xml", "views/hr_employee_views.xml"],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
