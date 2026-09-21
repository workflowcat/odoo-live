"""Українські назви довідників OCA і ядра, зайві додатки лише для адміністратора. Дані, не код: OCA-модулі не змінюються."""
from odoo.addons.l10n_ua_payroll_rules.hooks import ensure_uk_lang

UK = "uk_UA"
RENAMES = {
    "hr.payroll.structure.type": {"Employee": "Працівник", "Worker": "Робітник"},
    "hr.contract.type": {"Intern": "Стажування", "Apprenticeship": "Учнівство", "Thesis": "Дипломна практика", "Statutory": "Статутний",
                         "Permanent": "Безстроковий", "Temporary": "Строковий", "Interim": "Тимчасове заміщення", "Seasonal": "Сезонний",
                         "Full-Time": "Повний робочий день", "Part-Time": "Неповний робочий день", "Employee": "Трудовий договір"},
}
MENU_RENAMES = {
    "account_usability.menu_accounting_bank_and_cash": "Банк і каса",
    "account_reconcile_oca.account_account_reconcile_menu": "Звірка виписок",
    "account_financial_report.menu_oca_reports": "Фінансові звіти (ОСВ, журнали)",
    "account_statement_import_sheet_file.menu_statement_import_sheet_mapping": "Шаблони імпорту виписок",
    "account_reconcile_oca.menu_account_reconcile_model": "Правила звірки",
    "account_statement_import_online.online_bank_statement_provider_menu": "Онлайн-виписки (провайдери)",
    "account.account_reports_taxes_and_fiscal_menu": "Податки",
    "payroll.hr_payslip_menu": "Розрахункові листки", "payroll.hr_payslip_run_menu": "Пакети листків", "payroll.payroll_menu_configuration": "Довідники",
    "payroll.menu_hr_salary_rule_category": "Категорії правил", "payroll.menu_action_hr_salary_rule_form": "Правила розрахунку", "payroll.hr_payroll_structure_menu": "Структури зарплати",
    "payroll.hr_contribution_register_menu": "Реєстри внесків", "payroll.menu_payroll_global_settings": "Налаштування",
    "account_reconcile_oca.menu_account_reconcile": "Звірка", "account_statement_import_sheet_file.menu_account_statement_import_sheet_mapping": "Шаблони імпорту виписок",
    "account_statement_import_online.menu_account_statement_import_online_provider": "Онлайн-виписки (провайдери)",
    "account.menu_finance": "Бухоблік", "account.menu_finance_configuration_reconciliation": "Правила звірки", "account.menu_finance_reports": "Звіти", "account.account_reports_management_menu": "Податки",
}
# друк: власні форми лишаємо, англійські OCA-звіти ховаємо з меню «Друк» (самі звіти лишаються)
HIDE_REPORT_BINDINGS = ["payroll.report_payslipdetails", "payroll.report_payslip"]
REPORT_RENAMES = {
    "hr.print_employee_badge": "Бейдж працівника",
    "account.report_invoice_with_payments": "Рахунок з платежами (PDF)",
    "account.report_original_vendor_bill": "Оригінали рахунків постачальника",
    "account.report_invoice": "Рахунок (PDF)",
}
# види відсутності з демо-даних ядра: українські види свої, ці лише заважають у списку
CORE_LEAVE_TYPES = ["Paid Time Off", "Sick Time Off", "Compensatory Days", "Unpaid",
                    "Extra Hours", "Extra Time Off", "Training Time Off", "Parental Leaves"]
ADMIN_ONLY_MENUS = ["base.menu_management", "mail.menu_root_discuss", "calendar.mail_menu_calendar", "spreadsheet_dashboard.spreadsheet_dashboard_menu_root", "base.menu_tests"]


def post_init_hook(env):
    # На порожній базі uk_UA ще вимкнена, і перший же with_context(lang=UK) падає.
    ensure_uk_lang(env)
    for model, pairs in RENAMES.items():
        Model = env[model].with_context(active_test=False)
        for en, uk in pairs.items():
            recs = Model.with_context(lang="en_US").search([("name", "=", en)])
            recs.with_context(lang=UK).write({"name": uk})
            recs.with_context(lang="en_US").write({"name": uk})   # адміністратор з англійською теж бачить українську назву
    for xmlid, name in MENU_RENAMES.items():
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.with_context(lang=UK).write({"name": name}); menu.with_context(lang="en_US").write({"name": name})
    Report = env["ir.actions.report"]
    for report_name in HIDE_REPORT_BINDINGS:
        report = Report.search([("report_name", "=", report_name)], limit=1)
        if report and report.binding_model_id:
            report.binding_model_id = False
    for report_name, name in REPORT_RENAMES.items():
        report = Report.search([("report_name", "=", report_name)], limit=1)
        if report:
            report.with_context(lang=UK).write({"name": name})
            report.with_context(lang="en_US").write({"name": name})
    LeaveType = env["hr.leave.type"].with_context(active_test=False)
    for name in CORE_LEAVE_TYPES:
        for leave_type in LeaveType.with_context(lang="en_US").search([("name", "=", name), ("active", "=", True)]):
            if not env["hr.leave"].search_count([("holiday_status_id", "=", leave_type.id)]):
                leave_type.active = False
    admin = env.ref("base.group_system")
    for xmlid in ADMIN_ONLY_MENUS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.write({"group_ids": [(6, 0, [admin.id])]})
    # робочі дні: українська назва типу «Normal Working Days paid at 100%»
    for wet in env["hr.work.entry.type"].with_context(lang="en_US").search([("code", "=", "WORK100")]):
        wet.with_context(lang=UK).write({"name": "Відпрацьовані дні"}); wet.with_context(lang="en_US").write({"name": "Відпрацьовані дні"})
