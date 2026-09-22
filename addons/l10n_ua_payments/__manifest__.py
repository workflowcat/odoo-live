{
    "name": "Україна: відомість на перерахування зарплати",
    "summary": "Платіжне доручення пакетом на зарплату, аванс і податки: файл для банку, друкована відомість, проведені платежі",
    "version": "19.0.2.1.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_screen", "l10n_ua_payroll_account", "l10n_ua_payroll_rules",
                "account_payment_order"],
    "data": [
        "report/ua_payment_order_report.xml",
        "views/res_company_views.xml",
        "views/account_payment_order_views.xml",
    ],
    "installable": True,
}
