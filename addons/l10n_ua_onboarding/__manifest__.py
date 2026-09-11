{
    "name": "Україна: перенесення працівників і залишків",
    "summary": "Імпорт працівників з файлу разом із залишком відпустки, середнім заробітком і базовим місяцем індексації",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_rules", "l10n_ua_average", "l10n_ua_hr_card", "l10n_ua_index"],
    "data": [
        "security/ir.model.access.csv",
        "wizards/ua_employee_import_views.xml",
    ],
    "installable": True,
}
