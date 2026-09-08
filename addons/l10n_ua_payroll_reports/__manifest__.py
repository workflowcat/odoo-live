{
    "name": "Зарплата: об'єднана звітність (Україна)",
    "summary": "Податковий розрахунок ПДФО/ВЗ/ЄСВ з додатками Д1 і 4ДФ у XML за форматом ДПС; перевірка за схемою XSD; файл для FreeZvit, Електронного кабінету, M.E.Doc",
    "version": "19.0.0.1.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_rules", "l10n_ua_average"],
    "external_dependencies": {"python": ["lxml"]},
    "data": [
        "security/ir.model.access.csv",
        "views/res_company_views.xml",
        "wizards/ua_report_wizard_views.xml",
    ],
    "installable": True,
}
