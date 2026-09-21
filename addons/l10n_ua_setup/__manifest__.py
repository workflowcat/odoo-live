{
    "name": "Україна: анкета і налаштування компанії",
    "summary": "Анкета бухгалтера як майстер першого запуску: що відомо, що запропоновано, що підтверджено, чого бракує",
    "version": "19.0.1.2.1",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    # l10n_ua_hr_docs - заради hr.payslip.run.ua_prepare_month («пробний місяць» анкети)
    "depends": ["l10n_ua_payroll_reports", "l10n_ua_hr_docs", "web"],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_setup/static/src/setup.scss",
            "l10n_ua_setup/static/src/setup.js",
            "l10n_ua_setup/static/src/setup.xml",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/ua_setup_question_data.xml",
        "views/ua_setup_views.xml",
    ],
    "installable": True,
}
