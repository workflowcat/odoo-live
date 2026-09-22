# -*- coding: utf-8 -*-
"""Українські назви довідників, меню і звітів ядра та OCA.

Дані, не код: жоден OCA-модуль тут не змінюється, перейменовуються самі записи.
Раніше це жило в l10n_ua_payroll_ui разом з його меню; меню пішли, перейменування
лишилися і переїхали сюди, до єдиного власника навігації.

Що НЕ переїхало: приховування стандартних застосунків (Дискусії, Календар,
Контакти, Бухоблік, Співробітники) за base.group_no_one. Продукт іде голим Odoo,
рідні розділи лишаються на місці й видимими.
"""
from odoo.addons.l10n_ua_payroll_rules.hooks import ensure_uk_lang

UK = "uk_UA"

RENAMES = {
    "hr.payroll.structure.type": {"Employee": "Працівник", "Worker": "Робітник"},
    "hr.contract.type": {"Intern": "Стажування", "Apprenticeship": "Учнівство",
                         "Thesis": "Дипломна практика", "Statutory": "Статутний",
                         "Permanent": "Безстроковий", "Temporary": "Строковий",
                         "Interim": "Тимчасове заміщення", "Seasonal": "Сезонний",
                         "Full-Time": "Повний робочий день", "Part-Time": "Неповний робочий день",
                         "Employee": "Трудовий договір"},
}

MENU_RENAMES = {
    "account.menu_finance": "Бухоблік",
    "account.menu_finance_configuration_reconciliation": "Правила звірки",
    "account.menu_finance_reports": "Звіти",
    "account.account_reports_management_menu": "Податки",
    "account.account_reports_taxes_and_fiscal_menu": "Податки",
    "account_usability.menu_accounting_bank_and_cash": "Банк і каса",
    "account_financial_report.menu_oca_reports": "Фінансові звіти (ОСВ, журнали)",
    "account_reconcile_oca.menu_account_reconcile_model": "Правила звірки",
    "account_statement_import_sheet_file.menu_statement_import_sheet_mapping": "Шаблони імпорту виписок",
    "account_statement_import_sheet_file.menu_account_statement_import_sheet_mapping": "Шаблони імпорту виписок",
    "account_statement_import_online.online_bank_statement_provider_menu": "Онлайн-виписки (провайдери)",
    "account_statement_import_online.menu_account_statement_import_online_provider": "Онлайн-виписки (провайдери)",
    "payroll.hr_payslip_menu": "Розрахункові листки",
    "payroll.hr_payslip_run_menu": "Пакети листків",
    "payroll.payroll_menu_configuration": "Довідники",
    "payroll.menu_hr_salary_rule_category": "Категорії правил",
    "payroll.menu_action_hr_salary_rule_form": "Правила розрахунку",
    "payroll.hr_payroll_structure_menu": "Структури зарплати",
    "payroll.hr_contribution_register_menu": "Реєстри внесків",
    "payroll.menu_payroll_global_settings": "Налаштування",
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


def _write_both(record, values):
    record.with_context(lang=UK).write(values)
    record.with_context(lang="en_US").write(values)


def post_init_hook(env):
    # На порожній базі uk_UA ще вимкнена, і перший же with_context(lang=UK) падає.
    ensure_uk_lang(env)

    for model, pairs in RENAMES.items():
        Model = env[model].with_context(active_test=False)
        for en, uk in pairs.items():
            recs = Model.with_context(lang="en_US").search([("name", "=", en)])
            if recs:
                _write_both(recs, {"name": uk})

    for xmlid, name in MENU_RENAMES.items():
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            _write_both(menu, {"name": name})

    Report = env["ir.actions.report"]
    for report_name in HIDE_REPORT_BINDINGS:
        report = Report.search([("report_name", "=", report_name)], limit=1)
        if report and report.binding_model_id:
            report.binding_model_id = False
    for report_name, name in REPORT_RENAMES.items():
        report = Report.search([("report_name", "=", report_name)], limit=1)
        if report:
            _write_both(report, {"name": name})

    LeaveType = env["hr.leave.type"].with_context(active_test=False)
    for name in CORE_LEAVE_TYPES:
        for leave_type in LeaveType.with_context(lang="en_US").search(
                [("name", "=", name), ("active", "=", True)]):
            if not env["hr.leave"].search_count([("holiday_status_id", "=", leave_type.id)]):
                leave_type.active = False

    # робочі дні: українська назва типу «Normal Working Days paid at 100%»
    for wet in env["hr.work.entry.type"].with_context(lang="en_US").search([("code", "=", "WORK100")]):
        _write_both(wet, {"name": "Відпрацьовані дні"})

    _default_action(env)


def _default_action(env):
    """Домашня дія бухгалтера і кадровика - «Зарплата > Місяці».

    Раніше домашньою дією був власний екран «Період»; екранів більше немає, тож
    відкривається звичайний список місяців. Тим, хто вже поставив собі щось своє,
    не міняємо."""
    action = env.ref("l10n_ua_changes.action_ua_period_close", raise_if_not_found=False)
    if not action:
        return
    users = env["res.users"]
    for xmlid in ("hr.group_hr_user", "account.group_account_user"):
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            users |= group.all_user_ids
    for user in users:
        if not user.action_id:
            user.action_id = action.id
