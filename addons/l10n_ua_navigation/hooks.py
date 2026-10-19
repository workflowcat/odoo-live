# -*- coding: utf-8 -*-
"""Українські назви довідників, меню і звітів ядра та OCA.

Дані, не код: жоден OCA-модуль тут не змінюється, перейменовуються самі записи.
Раніше це жило в l10n_ua_payroll_ui разом з його меню; меню пішли, перейменування
лишилися і переїхали сюди, до єдиного власника навігації.

Що НЕ переїхало: приховування стандартних застосунків (Дискусії, Календар,
Контакти, Бухоблік, Співробітники) за base.group_no_one. Продукт іде голим Odoo,
рідні розділи лишаються на місці й видимими.
"""
import html
import json
import os
import re

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
    # розділи верхнього рівня: слова, якими їх називають у бухгалтерії та кадрах
    "purchase.menu_purchase_root": "Закупівлі",
    "hr.menu_hr_root": "Працівники",
    "hr_holidays.menu_hr_holidays_root": "Відпустки",
    "mail.menu_root_discuss": "Обговорення",
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root": "Зведення",
    "account.menu_board_journal_1": "Огляд журналів",
    "account.menu_finance_receivables": "Покупці",
    "account.menu_account_customer": "Покупці",
    "account.menu_action_move_in_refund_type": "Повернення постачальникам",
    "account.menu_action_move_out_refund_type": "Повернення від покупців",
    "account.menu_action_move_journal_line_form": "Проводки",
    "account.menu_action_account_moves_all": "Рядки проводок",
    "account.account_reports_partners_reports_menu": "Звіти за контрагентами",
    "account.account_reports_legal_statements_menu": "Фінансова звітність",
    "account.menu_action_account_journal_group_list": "Групи журналів",
    "account.account_invoicing_menu": "Рахунки і платежі",
    "account_usability.menu_accounting_statement_cash": "Касові звіти",
    "stock.menu_stock_adjustments": "Коригування",
    "stock.menu_stock_scrap": "Списання",
    "mrp.menu_mrp_scrap": "Списання",
    "stock.menu_stock_procurement": "Поповнення запасів",
    "stock.menu_reordering_rules_replenish": "Мінімальні залишки",
    "stock.menu_putaway": "Правила розкладання",
    "stock.menu_action_location_form": "Місця зберігання",
    "stock.menu_valuation": "Залишки",
    "mrp.mrp_operation_picking": "Виробничі замовлення",
    "mrp.menu_mrp_production_action": "Виробничі замовлення",
    "mrp.menu_mrp_workorder_todo": "Наряди",
    "mrp.menu_mrp_work_order_report": "Наряди",
    "purchase.menu_purchase_rfq": "Запити цін",
    "purchase.menu_purchase_form_action": "Замовлення постачальникам",
    "sale.menu_sale_invoicing": "До виставлення рахунку",
    "sale.menu_sale_order_invoice": "Замовлення без рахунку",
    "sale.menu_sale_order_upselling": "Замовлення з допродажем",
    "sale.menu_reporting_salespeople": "Менеджери",
    "sale.menu_reporting_customer": "Покупці",
    "sale.res_partner_menu": "Покупці",
    "sale.menu_sales_config": "Замовлення покупців",
    "crm.res_partner_menu_customer": "Покупці",
    "hr_holidays.menu_hr_holidays_my_leaves": "Мої відпустки",
    "hr_holidays.hr_leave_menu_new_request": "Огляд",
    "contacts.menu_localisation": "Країни та регіони",
    "mail.discuss_gif_favorite_menu": "Улюблені GIF",
    "account.menu_finance_entries": "Облік",
    "account.account_audit_menu": "Контроль",
    "hr.menu_hr_employee": "Довідник працівників",
    "hr.menu_hr_department_kanban": "Підрозділи",
    "hr_holidays.menu_hr_holidays_management": "Керування",
    "hr_holidays.menu_open_allocation": "Мої нарахування днів",
    "hr_holidays.hr_leave_menu_my": "Мої відпустки",
    "hr_holidays.hr_holidays_menu_manager_approve_allocations": "Нарахування днів",
    "hr_holidays.hr_holidays_accrual_menu_configuration": "Плани нарахування днів",
    "purchase.purchase_report": "Закупівлі",
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_dashboard": "Зведення",
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_configuration_dashboards": "Зведення",
    "crm.menu_crm_opportunities": "Моя воронка",
    "crm.crm_opportunity_report_menu": "Воронка",
    "crm.menu_crm_config_lead": "Воронка",
    "mail.discuss_technical": "Технічне",
    "hr.menu_hr_departure_reason_tree": "Причини звільнення",
    "hr.menu_hr_work_location_tree": "Місця роботи",
    "hr.menu_resource_calendar_view": "Графіки роботи",
    "hr.menu_hr_employee_contract_templates": "Шаблони договорів",
    "hr.menu_config_recruitment": "Добір",
    "hr_holidays.menu_open_department_leave_approve": "Відпустки",
    "hr_holidays.hr_holidays_public_time_off_menu_configuration": "Святкові та неробочі дні",
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

# Порядок розділів у верхньому меню: спершу щоденна робота бухгалтера і кадровика,
# далі торгівля, склад і виробництво, наприкінці службове.
ROOT_SEQUENCE = [
    "account.menu_finance",
    "l10n_ua_navigation.menu_ua_payroll_root",
    "l10n_ua_navigation.menu_ua_hr_root",
    "l10n_ua_navigation.menu_ua_reporting_root",
    "sale.sale_menu_root",
    "purchase.menu_purchase_root",
    "stock.menu_stock_root",
    "mrp.menu_mrp_root",
    "crm.crm_menu_root",
    "contacts.menu_contacts",
    "bp_kyc.menu_kyc_root",
    "hr.menu_hr_root",
    "hr_holidays.menu_hr_holidays_root",
    "calendar.mail_menu_calendar",
    "mail.menu_root_discuss",
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root",
]

# Розділи, яких на показі не має бути у верхньому меню: порожній рідний корінь payroll
# (його пункти стоять у нашій «Зарплаті»), дубль запитів на закупівлю (ті самі пункти є
# в «Закупівлях»), службові «Тест» і «Відстеження посилань». Не вимикаємо, а лишаємо
# розробникові: група base.group_no_one.
DEVELOPER_ONLY_MENUS = [
    "base.menu_tests",
    "payroll.payroll_menu_root",
    "purchase_request.parent_menu_purchase_request",
    "utm.menu_link_tracker_root",
]

# Пункт меню відкриває сторінку, а не діалог (docs/payroll/words.md). Ці дії OCA і ядра
# оголошені з target="new"; форма майстра та сама, але на всю сторінку і з адресою.
PAGE_ACTIONS = [
    "account_financial_report.action_general_ledger_wizard",
    "account_financial_report.action_journal_ledger_wizard",
    "account_financial_report.action_trial_balance_wizard",
    "account_financial_report.action_open_items_wizard",
    "account_financial_report.action_aged_partner_balance_wizard",
    "account_financial_report.action_vat_report_wizard",
    "account_asset_management.account_asset_compute_action",
    "account_asset_management.wiz_account_asset_report_action",
    "account_statement_import_file.account_statement_import_action",
]

PAGE_TITLES = {
    "general.ledger.report.wizard": "Головна книга",
    "journal.ledger.report.wizard": "Журнал проводок",
    "trial.balance.report.wizard": "Оборотно-сальдова відомість",
    "open.items.report.wizard": "Незакриті розрахунки",
    "aged.partner.balance.report.wizard": "Заборгованість за строками",
    "vat.report.wizard": "Звіт з ПДВ",
    "account.asset.compute": "Нарахування амортизації",
    "wiz.account.asset.report": "Звіт про основні засоби",
    "account.statement.import": "Імпорт виписки",
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
    apply_navigation(env)
    _default_action(env)


# Таблиці з назвою-перекладом (jsonb), де слово шукаємо за англійським джерелом.
TERM_TABLES = [
    ("ir_ui_menu", "name"),
    ("ir_act_window", "name"),
    ("ir_act_server", "name"),
    ("ir_act_client", "name"),
    ("ir_act_report_xml", "name"),
    ("ir_model_fields", "field_description"),
    ("ir_model_fields", "help"),
    ("ir_model_fields_selection", "name"),
    ("ir_model", "name"),
    ("ir_ui_view", "name"),
]


def _load_terms():
    path = os.path.join(os.path.dirname(__file__), "data", "terms_uk.json")
    if not os.path.exists(path):
        return {}, {}, [], {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("fill", {}), data.get("force", {}), data.get("replace", []), data.get("by_model", {})


# Текст до, між і після тегів, а також підказки title і aria-label.
MARKUP_TEXT = re.compile(r"(^|>)([^<>]+)(?=<|$)")
MARKUP_ATTR = re.compile(r'((?:title|aria-label)=")([^"]+)(?=")')


def _norm(words):
    """Ключі словника без зайвих пробілів і переносів: так вони збігаються з текстом у розмітці."""
    return {" ".join(k.split()): v for k, v in words.items()}


def _lookup(text, dicts):
    key = " ".join(html.unescape(text).split())
    for words in dicts:
        if key in words:
            return words[key]
    return None


def _swap_markup(src, dicts):
    """Міняє в терміні з розміткою лише людський текст, теги й атрибути лишаються як були."""
    def text(match):
        word = _lookup(match.group(2), dicts)
        if word is None:
            return match.group(0)
        raw = match.group(2)
        return match.group(1) + raw.replace(raw.strip(), html.escape(word, quote=False))

    def attr(match):
        word = _lookup(match.group(2), dicts)
        return match.group(0) if word is None else match.group(1) + html.escape(word, quote=True)

    return MARKUP_ATTR.sub(attr, MARKUP_TEXT.sub(text, src))


def apply_terms(env):
    """Українські слова поверх ядра й OCA: data/terms_uk.json.

    by_model - слово лише в поданнях однієї моделі (вкладка «Payroll» у картці працівника);
    fill  - англійський рядок, для якого українського перекладу немає взагалі
            (нові рядки Odoo 19, модулі OCA без uk.po): ставимо, лише якщо порожньо;
    force - рядок, який ядро перекладає не так, як кажуть у бухгалтерії та кадрах
            («Співробітник» -> «Працівник»): ставимо завжди.
    Джерело - англійський текст, тому один запис закриває всі поля і подання з цим
    рядком. Повторний запуск нічого не псує."""
    fill, force, replace, by_model = _load_terms()
    if not fill and not force and not replace and not by_model:
        return
    cr = env.cr
    for table, column in TERM_TABLES:
        cr.execute("SELECT data_type FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                   (table, column))
        row = cr.fetchone()
        if not row or row[0] != "jsonb":
            continue
        for terms, only_empty in ((fill, True), (force, False)):
            for src, dst in terms.items():
                query = ("UPDATE {t} SET {c} = {c} || jsonb_build_object('uk_UA', %s::text) "
                         "WHERE {c}->>'en_US' = %s").format(t=table, c=column)
                if only_empty:
                    query += " AND COALESCE({c}->>'uk_UA', {c}->>'en_US') = {c}->>'en_US'".format(c=column)
                cr.execute(query, (dst, src))
    # Подання: переклад живе по термінах усередині arch_db.
    norm_force, norm_fill = _norm(force), _norm(fill)
    View = env["ir.ui.view"].with_context(active_test=False)
    arch_field = View._fields["arch_db"]
    cr.execute("SELECT id, arch_db->>'en_US', COALESCE(arch_db->>'uk_UA', arch_db->>'en_US'), model FROM ir_ui_view")
    for view_id, arch_en, arch_uk, view_model in cr.fetchall():
        if not arch_en:
            continue
        # Перекладати можна лише цілий термін подання, а не будь-який підрядок.
        try:
            view_terms = set(arch_field.get_trans_terms(arch_en))
        except Exception:
            continue
        uk_terms = arch_field.get_trans_terms(arch_uk) if arch_uk else []
        todo = {}
        own = by_model.get(view_model) or {}
        for src in view_terms:
            if src in own:
                todo[src] = own[src]
            elif src in force:
                todo[src] = force[src]
            elif src in fill and src in uk_terms:
                todo[src] = fill[src]
            elif src in uk_terms and " ".join(src.split()) in norm_fill:
                todo[src] = norm_fill[" ".join(src.split())]
        # Термін з розміткою (<span>Forecasted</span>), де ядро лишило англійські шматки:
        # у чинному українському варіанті міняємо лише текст між тегами і підказки,
        # якщо шматок цілком є серед слів.
        try:
            pairs = arch_field.get_translation_dictionary(arch_en, {UK: arch_uk or arch_en})
        except Exception:
            pairs = {}
        for src, tr in pairs.items():
            current = tr.get(UK) or src
            if src in todo or "<" not in src:
                continue
            new = _swap_markup(current, (_norm(own), norm_force, norm_fill))
            if new != current:
                todo[src] = new
        if todo:
            try:
                with cr.savepoint():
                    View.browse(view_id).update_field_translations("arch_db", {UK: todo})
            except Exception:  # термін може бути підрядком іншого - тоді його просто немає серед термінів
                continue
    # replace - заміна слова в уже перекладеному українському тексті (регулярний вираз
    # Postgres): там, де ядро перекладає слово скрізь однаково не так, як кажуть в обліку.
    for table, column in TERM_TABLES + [("ir_ui_view", "arch_db")]:
        cr.execute("SELECT data_type FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
                   (table, column))
        row = cr.fetchone()
        if not row or row[0] != "jsonb":
            continue
        for pattern, replacement in replace:
            cr.execute(
                ("UPDATE {t} SET {c} = jsonb_set({c}, '{{uk_UA}}', "
                 "to_jsonb(regexp_replace({c}->>'uk_UA', %s, %s, 'g'))) "
                 "WHERE {c} ? 'uk_UA' AND {c}->>'uk_UA' ~ %s").format(t=table, c=column),
                (pattern, replacement, pattern))
    env.invalidate_all()
    env.registry.clear_cache()


def apply_navigation(env):
    """Усе, що модуль навішує на чужі записи. Викликається на встановлення (хук) і на
    кожне оновлення (data/apply.xml), тому мусить бути безпечним на повторі."""
    # На порожній базі uk_UA ще вимкнена, і перший же with_context(lang=UK) падає.
    ensure_uk_lang(env)

    no_one = env.ref("base.group_no_one")
    for xmlid in DEVELOPER_ONLY_MENUS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.group_ids = [(6, 0, [no_one.id])]
    # «Склад > Переміщення > Виробничі замовлення» ядро показує кожному комірнику, а
    # список читає наряди, на які в нього прав немає, - сторінка падає. Лишаємо пункт
    # тим, хто має права виробництва.
    menu = env.ref("mrp.mrp_operation_picking", raise_if_not_found=False)
    mrp_user = env.ref("mrp.group_mrp_user", raise_if_not_found=False)
    if menu and mrp_user:
        menu.group_ids = [(6, 0, [mrp_user.id])]
    for index, xmlid in enumerate(ROOT_SEQUENCE):
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.sequence = 10 + index
    for xmlid in PAGE_ACTIONS:
        action = env.ref(xmlid, raise_if_not_found=False)
        if action and action.target == "new":
            action.target = "current"
    # Майстри, які лишаються діалогом з кнопки, а з меню були б діалогом без сторінки
    # під ним: повертаємо, якщо попередня версія модуля встигла їх перемкнути.
    for xmlid in ("account.action_view_account_secure_entries_wizard",
                  "date_range.date_range_generator_action"):
        action = env.ref(xmlid, raise_if_not_found=False)
        if action and action.target == "current":
            action.target = "new"
    # Заголовок сторінки-майстра береться з назви моделі.
    for model, title in PAGE_TITLES.items():
        record = env["ir.model"]._get(model)
        if record:
            _write_both(record, {"name": title})

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

    apply_terms(env)


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
