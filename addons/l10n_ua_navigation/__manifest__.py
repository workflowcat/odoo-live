{
    "name": "Україна: меню продукту",
    "summary": "Три власні розділи - Зарплата, Кадри, Звітність - над стандартними поданнями Odoo; "
               "єдиний власник меню і українських назв довідників",
    "version": "19.0.2.3.7",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    # Верхній модуль продукту: `-i l10n_ua_navigation` ставить усе.
    "depends": [
        # рідні застосунки, чиї дії стоять у наших розділах
        "hr", "hr_holidays", "hr_org_chart", "contacts", "calendar",
        # зарплата
        "l10n_ua_payroll_rules", "l10n_ua_average", "l10n_ua_index", "l10n_ua_gph",
        "l10n_ua_payroll_account", "l10n_ua_payments", "l10n_ua_explain",
        # кадри
        "l10n_ua_hr_card", "l10n_ua_hr_orders", "l10n_ua_hr_docs", "l10n_ua_military",
        "l10n_ua_kp", "l10n_ua_onboarding", "l10n_ua_hire",
        # договір читання для інтерфейсу (без подань і меню)
        "l10n_ua_api",
        # бухоблік, склад, виробництво, група (хвиля C, DataCore 2026-09-22)
        "l10n_ua_purchase",
        "l10n_ua_mrp",
        "l10n_ua_stock_docs",
        "l10n_ua_group",
        "l10n_ua_profit_tax",
        # звітність і контроль
        "l10n_ua_payroll_reports", "l10n_ua_reporting", "l10n_ua_changes", "l10n_ua_setup",
        # бухоблік
        "l10n_ua_chart", "l10n_ua_vat", "l10n_ua_ledger", "l10n_ua_finrep", "l10n_ua_assets",
        "l10n_ua_nbu", "l10n_ua_cash", "l10n_ua_bank", "l10n_ua_bank_online",
        "l10n_ua_docs", "l10n_ua_docs_sale", "l10n_ua_docs_stock", "l10n_ua_fop",
        "l10n_ua_migrate",
        # контрагенти і закупівлі
        "l10n_ua_partner_edr", "l10n_ua_contract", "l10n_ua_defense", "l10n_ua_dk021", "l10n_ua_catalog",
        "l10n_ua_customs",
        "l10n_ua_bank_1c", "l10n_ua_close", "l10n_ua_tolling",
        "l10n_ua_payment_request", "l10n_ua_correspondence", "l10n_ua_prro", "l10n_ua_price_label",
        "l10n_ua_eco", "l10n_ua_claim", "l10n_ua_edo", "l10n_ua_procurement_plan", "l10n_ua_unit_transfer", "l10n_ua_offset", "bp_kyc", "bp_purchase_intake",
        # OCA, чиї пункти меню перейменовуються і переставляються тут
        "account_usability", "account_financial_report", "account_reconcile_oca",
        "account_statement_import_online",
    ],
    "data": [
        "views/menus_areas.xml",
        "views/hr_leave_views.xml",
        "views/hr_payslip_views.xml",
        "data/res_lang_data.xml",
        "data/apply.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
}
