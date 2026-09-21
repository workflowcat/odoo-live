{
    "name": "Україна: відомість на перерахування зарплати",
    "summary": "Список на виплату з реквізитами працівників, файл для банку і друкована відомість",
    "version": "19.0.1.3.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_screen", "l10n_ua_payroll_account", "l10n_ua_payroll_rules"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "report/ua_payment_batch_report.xml",
        "views/res_company_views.xml",
        "views/ua_payment_batch_views.xml",
    ],
    "installable": True,
}
