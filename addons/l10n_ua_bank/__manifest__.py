{
    "name": "Україна: банк (виписки і звірка зарплатних платежів)",
    "summary": "Шаблон імпорту виписки CSV, рахунок 333 у банківському журналі, зведення рядків виписки з платежами, правила звірки",
    "version": "19.0.1.4.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Accounting",
    "depends": ["account_statement_import_sheet_file", "account_statement_import_file_reconcile_oca", "l10n_ua_payroll_account"],
    "data": ["data/sheet_mapping.xml"],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
