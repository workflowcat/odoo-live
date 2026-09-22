{
    "name": "Зарплата: середній заробіток (Україна)",
    "summary": "Постанова 100 (відпускні, компенсація), Постанова 1266 (лікарняні за стажем, частина ПФУ), історія заробітку за 12 місяців",
    "version": "19.0.0.5.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_rules", "hr_holidays", "hr_work_entry_holidays"],
    "data": [
        "views/hr_leave_views.xml",
        "security/ir.model.access.csv",
        "data/leave_types.xml",
        "data/rules.xml",
        "data/leave_allocations_cron.xml",
        "views/ua_earnings_history_views.xml",
        "views/hr_employee_views.xml",
    ],
    "installable": True,
}
