{
    "name": "Зарплата: правила України",
    "summary": "Параметри з датами (МЗП, ПМ, ПСП, ставки), поля працівника, структура «Україна: оклад», правила ПДФО, ВЗ, ЄСВ",
    "version": "19.0.0.7.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["payroll", "hr"],
    "data": [
        "security/ir.model.access.csv",
        "data/ua_payroll_param_data.xml",
        "data/ua_salary_structure.xml",
        "data/ua_extra_rules.xml",
        "data/ua_salary_rules_pay.xml",
        "views/ua_payroll_param_views.xml",
        "views/hr_employee_views.xml",
        "views/ua_advance_sheet_views.xml",
    ],
    # вмикає uk_UA: без неї гачки інших модулів падають на порожній базі
    "post_init_hook": "post_init_hook",
    "installable": True,
}
