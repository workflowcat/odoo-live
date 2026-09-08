{
    "name": "Кадрові документи (Україна)",
    "summary": "Накази про прийняття, звільнення, відпустку; штатний розпис; табель П-5; Заява-розрахунок до ПФУ",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources",
    "depends": ["l10n_ua_payroll_reports", "l10n_ua_average", "l10n_ua_payroll_account"],
    "data": [
        "security/ir.model.access.csv",
        "wizards/ua_hr_docs_wizards_views.xml",
        "report/ua_orders_report.xml",
        "report/ua_staff_list_report.xml",
        "report/ua_timesheet_report.xml",
        "report/ua_pfu_claim_report.xml",
    ],
    "installable": True,
}
