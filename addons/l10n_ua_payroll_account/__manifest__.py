{
    "name": "Зарплата: проводки (Україна)",
    "summary": "Проводки за розрахунковим листком: витрати за підрозділом, 661, 6411, 6415, 651, 378, 6851; журнал «Зарплата»",
    "version": "19.0.0.2.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_rules", "l10n_ua_average", "account"],
    "data": [
        "views/hr_employee_views.xml",
        "security/ir.model.access.csv",
        "security/ua_payroll_account_security.xml",
        "data/account_map_data.xml",
        "views/ua_payroll_account_map_views.xml",
        "views/hr_department_views.xml",
        "views/hr_payslip_views.xml",
    ],
    "installable": True,
}
