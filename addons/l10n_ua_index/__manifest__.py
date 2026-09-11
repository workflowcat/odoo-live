{
    "name": "Україна: індексація зарплати (Постанова 1078)",
    "summary": "Індекси споживчих цін, базовий місяць працівника, автоматична сума індексації в листку",
    "version": "19.0.1.1.1",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_rules"],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_cpi_index_views.xml",
        "views/hr_employee_views.xml",
        "data/rule_index.xml",
    ],
    "installable": True,
}
