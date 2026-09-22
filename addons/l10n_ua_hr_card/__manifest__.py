{
    "name": "Особова картка (Україна)",
    "summary": "Особова картка П-2, документи працівника зі строками на вкладеннях картки (OCA hr_employee_document), розділи форми працівника за змістом",
    "version": "19.0.1.4.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources",
    "depends": ["l10n_ua_payroll_rules", "l10n_ua_payroll_reports", "l10n_ua_average", "l10n_ua_military",
                "hr_employee_document", "hr_holidays"],
    "data": [
        "security/ir.model.access.csv",
        "report/ua_hr_card_report.xml",
        "views/hr_employee_views.xml",
        "views/ua_employee_document_views.xml",
    ],
    "installable": True,
}
