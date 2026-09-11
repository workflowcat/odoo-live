{
    "name": "Україна: відомість на перерахування зарплати",
    "summary": "Список на виплату з реквізитами працівників, файл для банку і друкована відомість",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_account", "l10n_ua_payroll_rules"],
    "data": [
        "security/ir.model.access.csv",
        "report/ua_payment_batch_report.xml",
        "views/ua_payment_batch_views.xml",
    ],
    "installable": True,
}
