# Опис ядра для інтерфейсу

Згенеровано `scripts/api_inventory.py`. Руками не правити: зміни в коді, потім
`python3 scripts/api_inventory.py`. Що саме сюди потрапляє - у шапці скрипта.
Як цим користуватися - `docs/api/README.md`, приклади викликів - `docs/api/screens.md`,
прибрані й перейменовані методи - `docs/api/CHANGELOG.md`.

Модулів: 97. Моделей: 205. Методів: 788. Збережених полів на чужих моделях: 433.

## Зарплата

### `ua.advance.sheet`

наша модель · `l10n_ua_payroll_rules`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_month()` | Кнопка списку «Створити за місяць»: відомість поточного місяця, одразу порахована. | `l10n_ua_payroll_rules` |
| `action_confirm()` | - | `l10n_ua_payroll_rules` |
| `action_draft()` | - | `l10n_ua_payroll_rules` |
| `action_refill()` | Видалити рядки і заповнити знову з чернеток листків місяця. Лише для чернетки документа. | `l10n_ua_payroll_rules` |
| `ua_compose(company, year=None, month=None, **params)` | Нова авансова відомість місяця, одразу порахована. | `l10n_ua_payroll_rules` |

### `ua.cpi.index`

наша модель · `l10n_ua_index`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `get_map(date_from, date_to)` | {(рік, місяць): індекс} за період включно. | `l10n_ua_index` |

### `ua.diia.city.month`

наша модель · `l10n_ua_payroll_rules`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_fill()` | Порахувати кількість людей і середню винагороду з проведених листків місяця. | `l10n_ua_payroll_rules` |

### `ua.dps.xml`

наша модель · `l10n_ua_payroll_reports`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `build(company, c_doc, c_doc_sub, c_doc_ver, period_type, month, year, body_fields, linked=None, c_doc_cnt=1, c_doc_type=0, c_doc_stan=1, fill_date=None)` | body_fields: список (тег, значення) у порядку схеми; порожні значення пропускаються. Повертає (ім'я файлу, bytes). | `l10n_ua_payroll_reports` |
| `file_name(tin, sti, c_doc, c_doc_sub, c_doc_ver, c_doc_stan, c_doc_type, c_doc_cnt, period_type, month, year, sti_orig)` | Ім'я файлу за форматом ДПС, звірено з прикладом M.E.Doc 26550008012019J0500111100000000110720262655.XML: | `l10n_ua_payroll_reports` |
| `validate(data, schema_code)` | Перевірка за XSD зі schemas/ (файли збережені в UTF-8). Повертає список помилок; порожній = валідний. | `l10n_ua_payroll_reports` |

### `ua.explain`

наша модель · `l10n_ua_explain`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `explain(model, res_id, field=None, when='auto')` | when: "auto" - заморожений слід, якщо є, інакше живий перерахунок (preview); | `l10n_ua_explain` |

### `ua.explain.trace`

наша модель · `l10n_ua_explain`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `freeze(record, payload_dict)` | Створити новий рядок сліду для запису. Завжди create, ніколи write | `l10n_ua_explain` |

### `ua.hire.notice.wizard`

наша модель · `l10n_ua_payroll_reports`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_generate()` | - | `l10n_ua_payroll_reports` |

### `ua.income.certificate`

наша модель · `l10n_ua_payroll_reports`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_confirm()` | Видати довідку: присвоїти номер із послідовності і дату видачі. | `l10n_ua_payroll_reports` |
| `action_draft()` | - | `l10n_ua_payroll_reports` |
| `action_refill()` | Видалити рядки і заповнити знову з проведених листків періоду. | `l10n_ua_payroll_reports` |
| `ua_compose(company, year=None, month=None, employee=None, date_from=None, date_to=None, **params)` | Нова довідка про доходи, одразу заповнена листками періоду. | `l10n_ua_payroll_reports` |

### `ua.payments.plan`

наша модель · `l10n_ua_payments`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `month_rows(company, year, month)` | Рядки календаря виплат місяця: минулий місяць - факт, поточний - план. | `l10n_ua_payments` |

### `ua.payroll.param`

наша модель · `l10n_ua_payroll_rules`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `get(key, date=None, company=None)` | - | `l10n_ua_payroll_rules` |
| `get_all(date=None, company=None)` | - | `l10n_ua_payroll_rules` |

### `ua.payroll.report.wizard`

наша модель · `l10n_ua_payroll_reports`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_collect()` | Зібрати рядки Д1 і 4ДФ у таблиці: бухгалтер править їх, потім «Сформувати» бере рядки як є. | `l10n_ua_payroll_reports` |
| `action_drop_lines()` | Прибрати зібрані рядки: файли знову рахуються прямо з листків. | `l10n_ua_payroll_reports` |
| `action_generate()` | - | `l10n_ua_payroll_reports` |

### `ua.payroll.statement`

наша модель · `l10n_ua_payroll_account`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_payroll_account` |
| `action_print()` | - | `l10n_ua_payroll_account` |
| `money(amount)` | - | `l10n_ua_payroll_account` |
| `period_text()` | - | `l10n_ua_payroll_account` |
| `signers()` | Підписи: керівник і головний бухгалтер із картки компанії, якщо модуль документів їх веде. | `l10n_ua_payroll_account` |
| `totals()` | - | `l10n_ua_payroll_account` |

### `account.payment.line`

доповнена модель · `l10n_ua_payments`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_account_id` | Many2one | account.account | `l10n_ua_payments` |
| `ua_employee_id` | Many2one | hr.employee | `l10n_ua_payments` |
| `ua_label` | Char | Рядок | `l10n_ua_payments` |

### `account.payment.mode`

доповнена модель · `l10n_ua_payments`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_file_format` | Selection | - | `l10n_ua_payments` |

### `account.payment.order`

доповнена модель · `l10n_ua_bank_1c`, `l10n_ua_payments`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | Скасувати відомість. Odoo 19 лишає платіж у стані «в обробці» (in_process), а | `l10n_ua_payments` |
| `action_confirm()` | Затвердити: OCA складає платежі (ще чернетки) з рядків відомості. | `l10n_ua_payments` |
| `action_draft()` | - | `l10n_ua_payments` |
| `action_export()` | Кнопка «Файл для банку»: формує файл, чіпляє його до відомості і віддає посилання. | `l10n_ua_payments` |
| `action_fill()` | - | `l10n_ua_payments` |
| `action_paid()` | Позначити оплаченою: платежі проводяться і закривають 661 / 6411 / 6415 / 651. | `l10n_ua_payments` |
| `ua_compose(company, year=None, month=None, kind=None, **params)` | Нова відомість на перерахування за місяць, одразу заповнена. | `l10n_ua_payments` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `state` | Selection | Стан | `l10n_ua_payments` |
| `ua_kind` | Selection | - | `l10n_ua_payments` |
| `ua_label` | Char | Назва | `l10n_ua_payments` |
| `ua_legacy` | Boolean | Перенесена історія | `l10n_ua_payments` |
| `ua_month` | Integer | Місяць | `l10n_ua_payments` |
| `ua_note` | Text | Примітка | `l10n_ua_payments` |
| `ua_pay_date` | Date | Дата виплати | `l10n_ua_payments` |
| `ua_year` | Integer | Рік | `l10n_ua_payments` |

### `hr.department`

доповнена модель · `l10n_ua_payroll_account`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_expense_account_id` | Many2one | account.account | `l10n_ua_payroll_account` |

### `hr.employee`

доповнена модель · `l10n_ua_average`, `l10n_ua_diia_city`, `l10n_ua_gph`, `l10n_ua_hr_card`, `l10n_ua_hr_orders`, `l10n_ua_index`, `l10n_ua_military`, `l10n_ua_payments`, `l10n_ua_payroll_account`, `l10n_ua_payroll_reports`, `l10n_ua_payroll_rules`, `l10n_ua_safety`, `l10n_ua_workwear`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_mil_register_check()` | Кнопка форми працівника: та сама звірка, що й для списку персонального обліку - | `l10n_ua_military` |
| `action_ua_print_last_order()` | Друк останнього проведеного наказу працівника (будь-якого виду). Якщо наказу в реєстрі | `l10n_ua_hr_orders` |
| `action_ua_print_workwear_card()` | - | `l10n_ua_workwear` |
| `action_ua_workwear()` | - | `l10n_ua_workwear` |
| `action_view_ua_documents()` | - | `l10n_ua_hr_card` |
| `get_ua_doc_package()` | Пакет документів картки (docs/payroll/spec-intake.md) - той самий package_for, яким | `l10n_ua_hr_card` |
| `ua_ensure_allocations(year=None)` | - | `l10n_ua_average` |
| `ua_ensure_leave_allocations(on_date=None)` | Публічна обгортка: Odoo не дає викликати методи з підкресленням через execute_kw. | `l10n_ua_average` |
| `ua_mil_register_check(note=None)` | Записати звірку з ТЦК: подія обліку плюс дата останньої звірки. | `l10n_ua_military` |
| `ua_safety_problems(day=None)` | Що заважає допустити працівника до роботи в цей день. | `l10n_ua_safety` |
| `ua_tab_number()` | Табельний номер для картки: поле є не в кожній збірці Odoo, і воно закрите групою. | `l10n_ua_workwear` |
| `ua_workwear_due(day=None)` | Чого бракує за нормами посади на дату: [{product, norm, in_use, due, months, reference}]. | `l10n_ua_workwear` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `marital` | Selection | - | `l10n_ua_hr_card` |
| `ua_actual_address` | Char | Фактична адреса | `l10n_ua_hr_card` |
| `ua_alimony_partner_id` | Many2one | res.partner | `l10n_ua_payroll_account` |
| `ua_briefing_due` | Date | Повторний інструктаж до | `l10n_ua_safety` |
| `ua_briefing_last` | Date | Останній інструктаж на робочому місці | `l10n_ua_safety` |
| `ua_briefing_line_ids` | One2many | ua.safety.briefing.line | `l10n_ua_safety` |
| `ua_chernobyl_category` | Selection | - | `l10n_ua_hr_card` |
| `ua_child_ids` | One2many | ua.employee.child | `l10n_ua_hr_card` |
| `ua_contract_kind` | Selection | - | `l10n_ua_payroll_rules` |
| `ua_diploma_number` | Char | Номер диплома | `l10n_ua_hr_card` |
| `ua_disability_group` | Selection | - | `l10n_ua_payroll_rules` |
| `ua_dismissal_date` | Date | Дата звільнення | `l10n_ua_payroll_reports` |
| `ua_document_ids` | One2many | ua.employee.document | `l10n_ua_hr_card` |
| `ua_education_year` | Integer | Рік закінчення | `l10n_ua_hr_card` |
| `ua_electronic_labor_book` | Boolean | Електронна трудова | `l10n_ua_hr_card` |
| `ua_esv_category` | Selection | - | `l10n_ua_payroll_rules` |
| `ua_expense_account_id` | Many2one | account.account | `l10n_ua_payroll_account` |
| `ua_first_hire_date` | Date | Прийнято вперше | `l10n_ua_hr_card` |
| `ua_first_name` | Char | Ім'я | `l10n_ua_payroll_reports` |
| `ua_fte` | Selection | - | `l10n_ua_payroll_rules` |
| `ua_full_time` | Boolean | Повна зайнятість | `l10n_ua_payroll_reports` |
| `ua_gig_currency_id` | Many2one | res.currency | `l10n_ua_diia_city` |
| `ua_gig_fee` | Monetary | Винагорода за місяць у валюті договору | `l10n_ua_diia_city` |
| `ua_gph_contract_date` | Date | Дата договору ЦПХ | `l10n_ua_payroll_rules` |
| `ua_gph_contract_end` | Date | Договір діє до | `l10n_ua_payroll_rules` |
| `ua_gph_contract_ref` | Char | Договір ЦПХ № | `l10n_ua_payroll_rules` |
| `ua_hire_date` | Date | Дата прийняття | `l10n_ua_payroll_reports` |
| `ua_id_doc_date` | Date | Дата видачі | `l10n_ua_hr_card` |
| `ua_id_doc_issued_by` | Char | Ким виданий | `l10n_ua_hr_card` |
| `ua_id_doc_number` | Char | Номер документа | `l10n_ua_hr_card` |
| `ua_id_doc_series` | Char | Серія | `l10n_ua_hr_card` |
| `ua_id_doc_type` | Selection | - | `l10n_ua_hr_card` |
| `ua_id_doc_unzr` | Char | УНЗР | `l10n_ua_hr_card` |
| `ua_index_base` | Date | Базовий місяць індексації | `l10n_ua_index` |
| `ua_index_off` | Boolean | Не індексувати | `l10n_ua_index` |
| `ua_index_paid_month` | Date | Місяць останньої виплаченої індексації | `l10n_ua_index` |
| `ua_insurance_years` | Float | Страховий стаж, років | `l10n_ua_average` |
| `ua_labor_book_date` | Date | Дата заведення | `l10n_ua_hr_card` |
| `ua_labor_book_number` | Char | Номер трудової книжки | `l10n_ua_hr_card` |
| `ua_languages` | Char | Мови | `l10n_ua_hr_card` |
| `ua_large_family` | Boolean | Багатодітна сім'я | `l10n_ua_hr_card` |
| `ua_last_name` | Char | Прізвище | `l10n_ua_payroll_reports` |
| `ua_main_job` | Boolean | Основне місце роботи | `l10n_ua_payroll_rules` |
| `ua_medical_exam_ids` | One2many | ua.medical.exam | `l10n_ua_safety` |
| `ua_medical_result` | Selection | - | `l10n_ua_safety` |
| `ua_medical_valid_until` | Date | Медогляд дійсний до | `l10n_ua_safety` |
| `ua_middle_name` | Char | По батькові | `l10n_ua_payroll_reports` |
| `ua_mil_category` | Selection | Категорія обліку | `l10n_ua_military` |
| `ua_mil_deferment` | Char | Відстрочка (підстава) | `l10n_ua_military` |
| `ua_mil_deferment_until` | Date | Відстрочка до | `l10n_ua_military` |
| `ua_mil_doc_date` | Date | Дата видачі документа | `l10n_ua_military` |
| `ua_mil_doc_number` | Char | Номер військового документа | `l10n_ua_military` |
| `ua_mil_doc_series` | Char | Серія документа | `l10n_ua_military` |
| `ua_mil_doc_type` | Selection | Вид документа | `l10n_ua_military` |
| `ua_mil_event_ids` | One2many | ua.military.event | `l10n_ua_military` |
| `ua_mil_fitness` | Selection | Придатність | `l10n_ua_military` |
| `ua_mil_group` | Selection | Група обліку | `l10n_ua_military` |
| `ua_mil_last_check` | Date | Дата звірки даних | `l10n_ua_military` |
| `ua_mil_needs_check` | Boolean | Потребує звірки | `l10n_ua_military` |
| `ua_mil_note` | Text | Примітка | `l10n_ua_military` |
| `ua_mil_rank` | Char | Військове звання | `l10n_ua_military` |
| `ua_mil_reserve_order` | Char | Підстава бронювання (наказ, рішення) | `l10n_ua_military` |
| `ua_mil_reserve_until` | Date | Бронювання до | `l10n_ua_military` |
| `ua_mil_reserved` | Boolean | Заброньований | `l10n_ua_military` |
| `ua_mil_status` | Selection | Стан обліку | `l10n_ua_military` |
| `ua_mil_tcc` | Char | ТЦК та СП, де перебуває на обліку | `l10n_ua_military` |
| `ua_mil_vlk_date` | Date | Дата ВЛК | `l10n_ua_military` |
| `ua_mil_vos` | Char | ВОС | `l10n_ua_military` |
| `ua_mil_women_list` | Boolean | У списку жінок | `l10n_ua_military` |
| `ua_payable_account_id` | Many2one | account.account | `l10n_ua_payroll_account` |
| `ua_previous_employee_id` | Many2one | hr.employee | `l10n_ua_hr_card` |
| `ua_prior_job_ids` | One2many | ua.employee.prior.job | `l10n_ua_hr_card` |
| `ua_psp` | Selection | - | `l10n_ua_payroll_rules` |
| `ua_psp_children` | Integer | Дітей до 18 років | `l10n_ua_payroll_rules` |
| `ua_reserve_date` | Date | Дата витягу Резерв+ | `l10n_ua_military` |
| `ua_reserve_file` | Binary | Файл витягу Резерв+ | `l10n_ua_military` |
| `ua_reserve_filename` | Char | Файл витягу (назва) | `l10n_ua_military` |
| `ua_reserve_number` | Char | Номер витягу Резерв+ | `l10n_ua_military` |
| `ua_rnokpp` | Char | РНОКПП | `l10n_ua_payroll_rules` |
| `ua_science_degree` | Char | Науковий ступінь | `l10n_ua_hr_card` |
| `ua_sick_full` | Boolean | Лікарняні 100 % незалежно від стажу | `l10n_ua_average` |
| `ua_single_parent` | Boolean | Одинокий батько/мати | `l10n_ua_hr_card` |
| `ua_soc_child_disabled_child` | Boolean | Є дитина з інвалідністю | `l10n_ua_average` |
| `ua_special_leave_days` | Integer | Днів додаткової відпустки за особливий характер праці | `l10n_ua_average` |
| `ua_vacation_days_year` | Integer | Днів щорічної відпустки на рік | `l10n_ua_payroll_rules` |
| `ua_vacation_opening_balance` | Float | Залишок на дату впровадження | `l10n_ua_payroll_rules` |
| `ua_vacation_opening_date` | Date | Дата впровадження обліку відпусток | `l10n_ua_payroll_rules` |
| `ua_veteran` | Boolean | УБД / ветеран | `l10n_ua_hr_card` |
| `ua_war_disability` | Boolean | Особа з інвалідністю внаслідок війни | `l10n_ua_average` |
| `ua_workwear_line_ids` | One2many | ua.workwear.line | `l10n_ua_workwear` |

### `hr.leave`

доповнена модель · `l10n_ua_average`, `l10n_ua_hr_orders`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_refuse()` | - | `l10n_ua_hr_orders` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_order_id` | Many2one | ua.hr.order | `l10n_ua_hr_orders` |
| `ua_order_ref` | Char | Наказ (№ і дата) | `l10n_ua_average` |
| `ua_sick_number` | Char | Номер е-лікарняного | `l10n_ua_average` |

### `hr.leave.allocation`

доповнена модель · `l10n_ua_average`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_period_start` | Date | Початок періоду нарахування | `l10n_ua_average` |
| `ua_source` | Selection | - | `l10n_ua_average` |

### `hr.leave.type`

доповнена модель · `l10n_ua_average`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_alloc_basis` | Selection | - | `l10n_ua_average` |
| `ua_calendar_days` | Boolean | Рахувати календарні дні | `l10n_ua_average` |

### `hr.payslip`

доповнена модель · `l10n_ua_average`, `l10n_ua_diia_city`, `l10n_ua_explain`, `l10n_ua_hr_docs`, `l10n_ua_index`, `l10n_ua_payroll_account`, `l10n_ua_payroll_reports`, `l10n_ua_payroll_rules`, `l10n_ua_piecework`, `l10n_ua_project_cost`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_open_move()` | - | `l10n_ua_payroll_account` |
| `action_payslip_cancel()` | - | `l10n_ua_payroll_account` |
| `action_payslip_done()` | - | `l10n_ua_average` |
| `action_payslip_done()` | - | `l10n_ua_explain` |
| `action_payslip_done()` | Виплачена індексація починає новий цикл: базовим стає місяць листка. | `l10n_ua_index` |
| `action_payslip_done()` | - | `l10n_ua_payroll_account` |
| `get_payroll_dict(contracts)` | - | `l10n_ua_explain` |
| `get_payroll_dict(contracts)` | - | `l10n_ua_payroll_rules` |
| `get_worked_day_lines(contracts, date_from, date_to)` | Дні і години WORK100 з табеля. Дні відсутності лишаються окремими рядками, | `l10n_ua_hr_docs` |
| `ua_index_amount()` | - | `l10n_ua_index` |
| `ua_index_detail()` | (сума, наростаючий відсоток, місяці без індексу) для правила і перевірок. | `l10n_ua_index` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `move_id` | Many2one | account.move | `l10n_ua_payroll_account` |
| `ua_diia_city` | Boolean | Ставки Дія Сіті | `l10n_ua_payroll_rules` |
| `ua_report_month` | Date | Місяць звітності | `l10n_ua_payroll_reports` |

### `hr.version`

доповнена модель · `l10n_ua_average`, `l10n_ua_payroll_reports`, `l10n_ua_payroll_rules`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_dismissal_basis` | Char | Підстава припинення | `l10n_ua_payroll_reports` |
| `ua_end_order_ref` | Char | Наказ про звільнення (№ і дата) | `l10n_ua_payroll_reports` |
| `ua_hour_rate` | Monetary | Ставка, грн/год | `l10n_ua_payroll_rules` |
| `ua_internal_parttime` | Boolean | Внутрішній сумісник | `l10n_ua_payroll_reports` |
| `ua_kp_code` | Char | Код КП | `l10n_ua_payroll_reports` |
| `ua_new_workplace` | Boolean | Нове робоче місце | `l10n_ua_payroll_reports` |
| `ua_new_workplace_until` | Date | Нове робоче місце до | `l10n_ua_payroll_reports` |
| `ua_night_shifts` | Boolean | Працює в нічну зміну | `l10n_ua_payroll_rules` |
| `ua_order_ref` | Char | Наказ про прийняття (№ і дата) | `l10n_ua_payroll_reports` |
| `ua_pay_type` | Selection | - | `l10n_ua_payroll_rules` |
| `ua_prof_name` | Char | Професійна назва роботи | `l10n_ua_payroll_reports` |
| `ua_special_seniority` | Boolean | Спецстаж (пільгова пенсія) | `l10n_ua_payroll_reports` |
| `ua_special_seniority_code` | Char | Підстава спецстажу | `l10n_ua_payroll_reports` |
| `ua_unfixed_hours` | Boolean | Нефіксований робочий час | `l10n_ua_payroll_reports` |
| `ua_weekly_hours` | Float | Норма годин на тиждень | `l10n_ua_payroll_rules` |

### `res.company`

доповнена модель · `l10n_ua_average`, `l10n_ua_cash`, `l10n_ua_chart`, `l10n_ua_docs`, `l10n_ua_edo`, `l10n_ua_fop`, `l10n_ua_hr_orders`, `l10n_ua_payment_request`, `l10n_ua_payments`, `l10n_ua_payroll_account`, `l10n_ua_payroll_reports`, `l10n_ua_payroll_rules`, `l10n_ua_purchase`, `l10n_ua_safety`, `l10n_ua_setup`, `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_payment_setup()` | Довідники зарплатних виплат одним викликом: способи оплати і банк. | `l10n_ua_payments` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_accountant_name` | Char | Головний бухгалтер (ПІБ) | `l10n_ua_docs` |
| `ua_accountant_name` | Char | Головний бухгалтер (ПІБ) | `l10n_ua_payroll_reports` |
| `ua_accountant_rnokpp` | Char | РНОКПП головного бухгалтера | `l10n_ua_payroll_reports` |
| `ua_acts_on_basis` | Char | Діє на підставі | `l10n_ua_docs` |
| `ua_below_min_wage` | Boolean | Є оклади нижче мінімальної зарплати | `l10n_ua_setup` |
| `ua_booking_planned` | Boolean | Бронюємо або плануємо бронювати | `l10n_ua_setup` |
| `ua_briefing_months_hazard` | Integer | Повторний інструктаж на роботах з підвищеною небезпекою, раз на (міс.) | `l10n_ua_safety` |
| `ua_briefing_months_other` | Integer | Повторний інструктаж на інших роботах, раз на (міс.) | `l10n_ua_safety` |
| `ua_cash_limit` | Monetary | Ліміт каси | `l10n_ua_cash` |
| `ua_dc_resident` | Boolean | Резидент Дія Сіті | `l10n_ua_payroll_rules` |
| `ua_dc_since` | Date | Статус резидента з | `l10n_ua_payroll_rules` |
| `ua_dc_until` | Date | Статус припинено | `l10n_ua_payroll_rules` |
| `ua_director_name` | Char | Керівник (ПІБ) | `l10n_ua_docs` |
| `ua_director_name` | Char | Керівник (ПІБ) | `l10n_ua_payroll_reports` |
| `ua_director_rnokpp` | Char | РНОКПП керівника | `l10n_ua_payroll_reports` |
| `ua_dps_partner_id` | Many2one | res.partner | `l10n_ua_payroll_account` |
| `ua_dps_raj` | Char | Код району ДПІ | `l10n_ua_vat` |
| `ua_dps_reg` | Char | Код області ДПІ | `l10n_ua_vat` |
| `ua_dps_sti` | Char | Код ДПІ отримувача | `l10n_ua_vat` |
| `ua_edo_mode` | Selection | - | `l10n_ua_edo` |
| `ua_edo_provider` | Char | Сервіс ЕДО | `l10n_ua_edo` |
| `ua_engagement_forms` | Char | Форми залучення людей | `l10n_ua_setup` |
| `ua_fop` | Boolean | ФОП на єдиному податку | `l10n_ua_fop` |
| `ua_fop_group` | Selection | - | `l10n_ua_fop` |
| `ua_fop_vat_payer` | Boolean | Платник ПДВ | `l10n_ua_fop` |
| `ua_has_disabled` | Boolean | Є працівники з інвалідністю (ЄСВ 8,41 %) | `l10n_ua_setup` |
| `ua_iban_esv` | Char | Рахунок бюджету: ЄСВ | `l10n_ua_payments` |
| `ua_iban_pdfo` | Char | Рахунок бюджету: ПДФО | `l10n_ua_payments` |
| `ua_iban_vz` | Char | Рахунок бюджету: військовий збір | `l10n_ua_payments` |
| `ua_index_default_off` | Boolean | Індексацію не ведемо | `l10n_ua_setup` |
| `ua_katottg` | Char | Код КАТОТТГ | `l10n_ua_payroll_reports` |
| `ua_kved` | Char | Основний КВЕД | `l10n_ua_payroll_reports` |
| `ua_military_officer` | Char | Відповідальний за військовий облік | `l10n_ua_setup` |
| `ua_opening_balances` | Boolean | Будуть вхідні залишки | `l10n_ua_setup` |
| `ua_pay_advance_day` | Integer | Аванс до числа | `l10n_ua_hr_orders` |
| `ua_pay_advance_percent` | Float | Аванс, % окладу | `l10n_ua_hr_orders` |
| `ua_pay_final_day` | Integer | Остаточний розрахунок до числа | `l10n_ua_hr_orders` |
| `ua_payment_mode_salary_id` | Many2one | account.payment.mode | `l10n_ua_payments` |
| `ua_payment_mode_tax_id` | Many2one | account.payment.mode | `l10n_ua_payments` |
| `ua_payment_request_limit` | Monetary | Ліміт заявки без директора | `l10n_ua_payment_request` |
| `ua_payroll_bank_mode` | Selection | - | `l10n_ua_setup` |
| `ua_pfu_partner_id` | Many2one | res.partner | `l10n_ua_payroll_account` |
| `ua_purchase_approval_limit` | Monetary | Ліміт погодження запиту | `l10n_ua_purchase` |
| `ua_raj` | Char | Код району (C_RAJ) | `l10n_ua_payroll_reports` |
| `ua_reg` | Char | Код області (C_REG) | `l10n_ua_payroll_reports` |
| `ua_safety_notify_days` | Integer | Нагадувати про охорону праці за, днів | `l10n_ua_safety` |
| `ua_settlement_currency` | Char | Валюта розрахунків з клієнтами | `l10n_ua_setup` |
| `ua_sti_code` | Char | Код ДПІ (C_STI_ORIG) | `l10n_ua_payroll_reports` |
| `ua_sti_name` | Char | Назва ДПІ | `l10n_ua_payroll_reports` |
| `ua_tax_system` | Selection | - | `l10n_ua_setup` |
| `ua_vacation_opening_date` | Date | Дата впровадження обліку відпусток | `l10n_ua_payroll_rules` |
| `ua_vat_payer` | Boolean | Платник ПДВ | `l10n_ua_setup` |

## Кадри

### `ua.employee.document`

наша модель · `l10n_ua_hr_card`, `l10n_ua_hr_orders`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_mark_signed()` | - | `l10n_ua_hr_card` |
| `action_print()` | - | `l10n_ua_hr_card` |
| `action_unmark_signed()` | Чесний зворотний бік action_mark_signed - для вікна скасування «узгодження» | `l10n_ua_hr_card` |

### `ua.employee.import`

наша модель · `l10n_ua_onboarding`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_import()` | - | `l10n_ua_onboarding` |
| `action_template()` | Порожній файл із заголовками, двома прикладами і аркушем заробітку. | `l10n_ua_onboarding` |

### `ua.hire.case`

наша модель · `l10n_ua_hire`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_decline(reason='')` | - | `l10n_ua_hire` |
| `action_extract()` | Надіслати файли локальному помічнику Claude і записати пропозиції. Значення в поля не пишемо. | `l10n_ua_hire` |
| `action_hire()` | - | `l10n_ua_hire` |
| `action_hire_plan()` | План перед «Прийняти на роботу»: перелік того, що action_hire нижче справді зробить | `l10n_ua_hire` |
| `action_reopen()` | - | `l10n_ua_hire` |
| `action_start_onboarding()` | - | `l10n_ua_hire` |
| `add_file(name, data, doc_type='other')` | - | `l10n_ua_hire` |
| `clear_reserve_file()` | - | `l10n_ua_hire` |
| `create_case(last_name='', first_name='', job_title='')` | - | `l10n_ua_hire` |
| `extract_status()` | - | `l10n_ua_hire` |
| `set_package_doc(key, on)` | - | `l10n_ua_hire` |
| `set_reserve_file(filename, data)` | Файл витягу Резерв+: необов'язковий, не редагується через set_value (не в SECTIONS). | `l10n_ua_hire` |
| `set_value(field_name, value)` | - | `l10n_ua_hire` |

### `ua.hire.file`

наша модель · `l10n_ua_hire`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `set_doc_type(doc_type)` | - | `l10n_ua_hire` |

### `ua.hire.proposal`

наша модель · `l10n_ua_hire`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_accept()` | - | `l10n_ua_hire` |
| `action_reject()` | - | `l10n_ua_hire` |

### `ua.hr.doc.check`

наша модель · `l10n_ua_hr_orders`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_today()` | Кнопка списку «Створити на сьогодні». | `l10n_ua_hr_orders` |
| `action_confirm()` | - | `l10n_ua_hr_orders` |
| `action_draft()` | - | `l10n_ua_hr_orders` |
| `action_refill()` | Видалити рядки і заповнити знову: кожен працівник компанії x кожна вимога. | `l10n_ua_hr_orders` |
| `matrix()` | Матриця для друку: (працівники, вимоги, {(employee_id, requirement_id): мітка}). | `l10n_ua_hr_orders` |
| `ua_compose(company, year=None, month=None, date=None, **params)` | Нова перевірка документів на дату, одразу заповнена. | `l10n_ua_hr_orders` |

### `ua.hr.doc.requirement`

наша модель · `l10n_ua_hr_orders`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `package_for(employee=None, case=None)` | Пакет документів за формою зі спеки: employee-блок (що приносить людина) і | `l10n_ua_hr_orders` |
| `package_used_file_ids(case)` | Файли справи, що підпадають під якусь employee-вимогу пакета (docs/payroll/ | `l10n_ua_hr_orders` |

### `ua.hr.order`

наша модель · `l10n_ua_hr_orders`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_acknowledge()` | - | `l10n_ua_hr_orders` |
| `action_acknowledge()` | - | `l10n_ua_hr_orders` |
| `action_cancel()` | - | `l10n_ua_hr_orders` |
| `action_post()` | - | `l10n_ua_hr_orders` |
| `action_post()` | - | `l10n_ua_hr_orders` |
| `action_print_register()` | Друк журналу реєстрації: вибрані накази, а без вибору - усе, що показує список. | `l10n_ua_hr_orders` |
| `action_ua_open_leave()` | - | `l10n_ua_hr_orders` |
| `action_ua_open_payments()` | - | `l10n_ua_hr_orders` |
| `action_ua_open_slips()` | - | `l10n_ua_hr_orders` |
| `action_ua_open_version()` | - | `l10n_ua_hr_orders` |
| `content_line()` | Короткий однорядковий зміст наказу - для журналу реєстрації. | `l10n_ua_hr_orders` |

### `ua.kp.code`

наша модель · `l10n_ua_kp`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `audit_staff_lists(include_posted=False)` | Що не так із кодами в штатних розписах: кожен рядок - факт і ціль. | `l10n_ua_kp` |
| `audit_versions()` | Версії, де посада змінилася, а код професії лишився від попередньої. | `l10n_ua_kp` |
| `ensure(code, group=None, source=None)` | Запис довідника для коду; створює, якщо ще немає. | `l10n_ua_kp` |
| `official(code)` | Офіційна назва і група за кодом. Немає служби - None. | `l10n_ua_kp` |
| `suggest(query, limit=10)` | Підказки за назвою посади. Розуміє англійські назви і фемінітиви. | `l10n_ua_kp` |
| `sync_from_documents()` | Наповнити довідник кодами, які вже стоять у штатних розписах. | `l10n_ua_kp` |
| `verify()` | Звірити офіційні назви зі службою. Недоступна - лишаємо як є. | `l10n_ua_kp` |

### `ua.military.critical`

наша модель · `l10n_ua_military`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_reserved_list()` | Список заброньованих на сьогодні з квотою цього статусу. | `l10n_ua_military` |
| `quota_counts(date=None)` | {liable, reserved, quota, free} для компанії статусу на дату. | `l10n_ua_military` |
| `wage_floor(date=None)` | Нижня межа окладу заброньованого на дату; 0 - межі немає або невідома МЗП. | `l10n_ua_military` |

### `ua.military.list`

наша модель · `l10n_ua_military`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_all()` | Кнопка списку «Створити за всіма ТЦК»: по одному документу на кожен ТЦК. | `l10n_ua_military` |
| `action_confirm()` | - | `l10n_ua_military` |
| `action_create_all_tcc(company_id=None, doc_date=None, variant='all')` | Створити по одному чернетковому списку на кожен ТЦК, де є хоча б один військовозобов'язаний. | `l10n_ua_military` |
| `action_draft()` | - | `l10n_ua_military` |
| `action_reconcile()` | Звірка з ТЦК: записує дату звірки всім працівникам у списку і подію в їхню хроніку. | `l10n_ua_military` |
| `action_refill()` | Видалити рядки і заповнити знову з hr.employee: працівники цього ТЦК, що підлягають обліку | `l10n_ua_military` |
| `ua_compose(company, year=None, month=None, date=None, tcc=None, variant='all', **params)` | Новий список персонального обліку, одразу заповнений. | `l10n_ua_military` |

### `ua.military.notice`

наша модель · `l10n_ua_military`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_month()` | Кнопка списку «Створити за місяць»: повідомлення за поточний місяць. | `l10n_ua_military` |
| `action_confirm()` | - | `l10n_ua_military` |
| `action_draft()` | - | `l10n_ua_military` |
| `action_refill()` | - | `l10n_ua_military` |
| `ua_compose(company, year=None, month=None, date_from=None, date_to=None, **params)` | Нове повідомлення ТЦК за період, одразу заповнене. | `l10n_ua_military` |

### `ua.military.reserve.request`

наша модель · `l10n_ua_military`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply()` | Рішення з заявки - на картки працівників і в події обліку. | `l10n_ua_military` |
| `action_draft()` | - | `l10n_ua_military` |
| `action_export_csv()` | - | `l10n_ua_military` |
| `action_fill()` | - | `l10n_ua_military` |
| `action_print()` | - | `l10n_ua_military` |
| `action_submit()` | - | `l10n_ua_military` |
| `ua_csv()` | CSV для заповнення заявки: лише включені рядки, у порядку переліку. | `l10n_ua_military` |
| `ua_date(day)` | - | `l10n_ua_military` |
| `ua_doc_label(line)` | - | `l10n_ua_military` |
| `ua_purpose_label(line)` | - | `l10n_ua_military` |

### `ua.military.reserved`

наша модель · `l10n_ua_military`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_today()` | Кнопка списку «Створити на сьогодні»: список заброньованих на поточну дату. | `l10n_ua_military` |
| `action_confirm()` | - | `l10n_ua_military` |
| `action_draft()` | - | `l10n_ua_military` |
| `action_refill()` | - | `l10n_ua_military` |
| `ua_compose(company, year=None, month=None, date=None, **params)` | Новий список заброньованих на дату, одразу заповнений. | `l10n_ua_military` |

### `ua.pfu.claim`

наша модель · `l10n_ua_hr_docs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_accept()` | ПФУ прийняв заяву. | `l10n_ua_hr_docs` |
| `action_compose_month()` | Кнопка списку «Створити за місяць»: заява-розрахунок за поточний місяць. | `l10n_ua_hr_docs` |
| `action_confirm()` | - | `l10n_ua_hr_docs` |
| `action_done()` | - | `l10n_ua_hr_docs` |
| `action_draft()` | - | `l10n_ua_hr_docs` |
| `action_notice_sent()` | Повідомлення про виплату подано до ПФУ. | `l10n_ua_hr_docs` |
| `action_refill()` | Видалити рядки і заповнити знову: рядки SICK_PFU і MAT листків пакета, відпустка з номером е-ЛН, дні з _ua_leave_calendar_days(). | `l10n_ua_hr_docs` |
| `action_register_funding(amount=None)` | Гроші від ПФУ надійшли. Часткове фінансування лишає залишок. | `l10n_ua_hr_docs` |
| `action_register_payment(amount=None)` | Допомогу виплачено працівникам. Виплатити можна лише профінансоване. | `l10n_ua_hr_docs` |
| `action_reject()` | ПФУ відмовив. Причина обов'язкова. | `l10n_ua_hr_docs` |
| `action_submit()` | Заяву подано до ПФУ. | `l10n_ua_hr_docs` |
| `ua_compose(company, year=None, month=None, **params)` | Нова заява-розрахунок за місяць: пакет листків місяця і його суми. | `l10n_ua_hr_docs` |

### `ua.staff.list`

наша модель · `l10n_ua_hr_docs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_today()` | Кнопка списку «Створити на сьогодні»: розпис на поточну дату, одразу заповнений. | `l10n_ua_hr_docs` |
| `action_confirm()` | - | `l10n_ua_hr_docs` |
| `action_draft()` | - | `l10n_ua_hr_docs` |
| `action_refill()` | Видалити рядки і заповнити знову: підрозділ / посада / код КП / оклад -> сума ставок і фонд. | `l10n_ua_hr_docs` |
| `ua_compose(company, year=None, month=None, date=None, **params)` | Новий штатний розпис на дату, одразу заповнений поточним складом. | `l10n_ua_hr_docs` |

### `ua.timesheet.sheet`

наша модель · `l10n_ua_hr_docs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_month()` | Кнопка списку «Створити за місяць»: табель поточного місяця, одразу заповнений. | `l10n_ua_hr_docs` |
| `action_confirm()` | - | `l10n_ua_hr_docs` |
| `action_draft()` | - | `l10n_ua_hr_docs` |
| `action_recompute_payslips()` | Перерахувати чернетки листків періоду за виправленим табелем. | `l10n_ua_hr_docs` |
| `action_refill()` | Видалити рядки і заповнити знову: працівник за день - код (Р, ВХ, В, ТН, НА, ВП, «-»). | `l10n_ua_hr_docs` |
| `ua_compose(company, year=None, month=None, **params)` | Табель місяця для «Паперів»: той самий ідемпотентний _ua_ensure_for(). | `l10n_ua_hr_docs` |

### `hr.payslip.run`

доповнена модель · `l10n_ua_hr_docs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_pfu_claim()` | - | `l10n_ua_hr_docs` |
| `ua_compose(company, year=None, month=None, **params)` | Новий пакет листків на місяць: назва, межі місяця, компанія. | `l10n_ua_hr_docs` |
| `ua_prepare_month(company, year, month)` | Підготувати місяць: табель, чернетки листків, перерахунок. | `l10n_ua_hr_docs` |

## Звітність і контроль

### `ua.change.log`

наша модель · `l10n_ua_changes`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `accept_period(year, month)` | Прийняти всі нові зміни місяця однією дією. | `l10n_ua_changes` |
| `action_accept()` | - | `l10n_ua_changes` |
| `action_open_record()` | - | `l10n_ua_changes` |
| `action_reset()` | - | `l10n_ua_changes` |
| `count_new(company, year, month)` | - | `l10n_ua_changes` |
| `undo_accept_period(year, month, seconds=25)` | Відкат «Прийняти всі зміни»: щойно прийняті рядки знову стають новими. | `l10n_ua_changes` |

### `ua.period.close`

наша модель · `l10n_ua_changes`, `l10n_ua_close`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_accept_changes()` | Прийняти всі непереглянуті зміни місяця. | `l10n_ua_changes` |
| `action_close()` | - | `l10n_ua_changes` |
| `action_close_quarter()` | - | `l10n_ua_changes` |
| `action_close_year()` | - | `l10n_ua_changes` |
| `action_open_changes()` | - | `l10n_ua_changes` |
| `action_open_draft_moves()` | - | `l10n_ua_changes` |
| `action_open_payslips()` | - | `l10n_ua_changes` |
| `action_prepare_month()` | Підготувати місяць: табель, пакет листків, розрахунок. | `l10n_ua_changes` |
| `action_reopen()` | - | `l10n_ua_changes` |
| `action_ua_run_operations()` | - | `l10n_ua_close` |
| `action_ua_undo_operations()` | - | `l10n_ua_close` |
| `blocker_rows(company, year, month)` | Кожна перешкода закриття місяця - одним записом, з усіма трьома її словами. | `l10n_ua_changes` |
| `blockers(company, year, month)` | Список причин, чому місяць закрити не можна. Порожній список = можна. | `l10n_ua_changes` |
| `close_period(year, month, hard=False)` | - | `l10n_ua_changes` |
| `close_quarter(year, quarter)` | Закрити квартал: дата податкового блокування на кінець кварталу. | `l10n_ua_changes` |
| `close_year(year)` | Закрити рік остаточно: жорстка дата блокування, яку не знімає ніхто. | `l10n_ua_changes` |
| `ensure_for(company, year, month)` | Картка закриття місяця: наявна або нова чернетка. | `l10n_ua_changes` |
| `operation_rows(company, year, month)` | Регламентні операції місяця по порядку: що проведено і що ще треба провести. | `l10n_ua_close` |
| `plan(company, year, month)` | План перед закриттям місяця: що станеться, що заважає, що лишиться потім. | `l10n_ua_changes` |
| `plan(company, year, month)` | План закриття ще й нагадує про непроведені регламентні операції: після дати | `l10n_ua_close` |
| `quarter_blockers(company, year, quarter)` | Чому не можна закрити квартал: незакриті місяці або неподана звітність. | `l10n_ua_changes` |
| `run_operations()` | Провести регламентні операції місяця, які ще не проведені, по порядку. | `l10n_ua_close` |
| `state_of(company, year, month)` | - | `l10n_ua_changes` |
| `undo_operations()` | Скасувати регламентні операції місяця: проводки видаляються, рядки амортизації | `l10n_ua_close` |
| `year_blockers(company, year)` | Чому не можна закрити рік: незакриті квартали. | `l10n_ua_changes` |

### `ua.report.run`

наша модель · `l10n_ua_reporting`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_create_correction(kind='HZU')` | Новий прогін-коригування на основі поданого: рядки на вилучення беруться з його файлів. | `l10n_ua_reporting` |
| `action_generate()` | - | `l10n_ua_reporting` |
| `action_mark_submitted()` | - | `l10n_ua_reporting` |
| `action_refresh()` | - | `l10n_ua_reporting` |
| `action_reset()` | - | `l10n_ua_reporting` |
| `create_correction(run_id, kind='HZU')` | Виклик з екрана: зробити коригування і повернути id нового прогону. | `l10n_ua_reporting` |
| `ensure_run(report_code=None, year=None, quarter=None, month=None, date=None, run_id=None)` | Створити прогін періоду, якщо його ще немає, і повернути його id. | `l10n_ua_reporting` |

### `ua.setup.answer`

наша модель · `l10n_ua_setup`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_confirm()` | - | `l10n_ua_setup` |
| `action_reset()` | - | `l10n_ua_setup` |

### `ua.setup.profile`

наша модель · `l10n_ua_setup`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_activate()` | Дозволити реальний розрахунок. Обов'язкові питання мають бути закриті. | `l10n_ua_setup` |
| `action_apply()` | Записати підтверджені відповіді в налаштування компанії. | `l10n_ua_setup` |
| `action_draft()` | - | `l10n_ua_setup` |
| `action_fill()` | Створити рядки на всі питання каталогу і підставити те, що вже відоме системі. | `l10n_ua_setup` |
| `action_propose()` | Підставити перше наближення з опису компанії. Усе - зі станом «запропоновано». | `l10n_ua_setup` |
| `action_ready()` | - | `l10n_ua_setup` |
| `action_test_month()` | Пробний місяць: система готує табель і чернетки листків за поточний місяць. | `l10n_ua_setup` |
| `preview_apply()` | Що саме зміниться в налаштуваннях. Показуємо до запису. | `l10n_ua_setup` |
| `profile_for(company=None)` | - | `l10n_ua_setup` |

### `auditlog.rule`

доповнена модель · `l10n_ua_changes`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `get_auditlog_fields(model)` | Білий список замість усіх збережених полів - тут і відсікається тріска. | `l10n_ua_changes` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_area` | Selection | - | `l10n_ua_changes` |
| `ua_company` | Char | Компанія | `l10n_ua_changes` |
| `ua_field_ids` | One2many | ua.change.field | `l10n_ua_changes` |
| `ua_label` | Char | Назва запису | `l10n_ua_changes` |
| `ua_period_date` | Char | Період: дата документа | `l10n_ua_changes` |
| `ua_period_ym` | Char | Період: рік і місяць | `l10n_ua_changes` |

## Бухоблік

### `ua.account.analysis`

наша модель · `l10n_ua_ledger`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_ledger` |
| `action_print_xlsx()` | - | `l10n_ua_ledger` |

### `ua.account.card`

наша модель · `l10n_ua_ledger`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_ledger` |
| `action_print_xlsx()` | - | `l10n_ua_ledger` |

### `ua.advance.report`

наша модель · `l10n_ua_cash`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_confirm()` | Затвердити звіт: Дт рахунки витрат / Кт 372 на суму звіту. | `l10n_ua_cash` |
| `action_draft()` | - | `l10n_ua_cash` |
| `action_print()` | - | `l10n_ua_cash` |
| `action_settle_balance()` | Закрити залишок підзвіту касовим ордером. | `l10n_ua_cash` |

### `ua.bank.connect`

наша модель · `l10n_ua_bank_online`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_create_provider()` | Зробити з'єднання, коли ключ уже є. Ключ вписує людина, не система. | `l10n_ua_bank_online` |
| `action_fill_steps()` | Наповнити чек-лист кроками для обраної служби. | `l10n_ua_bank_online` |
| `for_journal(journal)` | Картка підключення журналу. Створюємо порожню, якщо її ще немає. | `l10n_ua_bank_online` |

### `ua.bank.ops`

наша модель · `l10n_ua_bank_online`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply_rules(journal_id=None, line_id=None)` | Закрити незвірені рядки виписки: спершу платежами, потім правилами. | `l10n_ua_bank_online` |
| `action_create_provider(journal_id, service)` | Створити з'єднання для журналу і відкрити його форму. | `l10n_ua_bank_online` |
| `action_match_payments(journal_id=None, line_id=None)` | Звести незвірені рядки виписки з уже проведеними платежами. | `l10n_ua_bank_online` |
| `action_open_providers(journal_id=None)` | Форма з'єднання рахунку (або перелік усіх, якщо рахунок не вибрано). | `l10n_ua_bank_online` |
| `action_pull(journal_id, date_from=None, date_to=None)` | Завантажити виписку за період. Без дат - за поточний місяць до сьогодні. | `l10n_ua_bank_online` |
| `action_pull_all(year=None, month=None)` | Завантажити виписку за місяць для всіх рахунків із з'єднанням. | `l10n_ua_bank_online` |
| `action_pull_month(journal_id, year, month)` | - | `l10n_ua_bank_online` |
| `action_test(journal_id)` | - | `l10n_ua_bank_online` |

### `ua.bank.pull`

наша модель · `l10n_ua_bank_online`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_pull()` | Одна дія: завантажити виписку рахунку за місяць. | `l10n_ua_bank_online` |

### `ua.cash.book`

наша модель · `l10n_ua_cash`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ask()` | Кнопка «Сформувати» в шапці списку: діалог параметрів нової книги. | `l10n_ua_cash` |
| `action_compose()` | Кнопка «Скласти» в діалозі: порахувати і відкрити книгу сторінкою. | `l10n_ua_cash` |
| `action_compute()` | Перерахувати книгу. Ідемпотентно: попередні аркуші стираються. | `l10n_ua_cash` |
| `action_print()` | - | `l10n_ua_cash` |

### `ua.cost.calculation`

наша модель · `l10n_ua_mrp`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | Перезібрати рядки. Ідемпотентно: старі рядки замінюються новими. | `l10n_ua_mrp` |

### `ua.depreciation.sheet`

наша модель · `l10n_ua_assets`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ask()` | Кнопка «Сформувати» в шапці списку: діалог параметрів нової відомості. | `l10n_ua_assets` |
| `action_compose()` | Кнопка «Скласти» в діалозі: відкрити складену відомість сторінкою. | `l10n_ua_assets` |
| `action_compute()` | «Перерахувати»: рядки читаються з таблиці амортизації щоразу, тому тут | `l10n_ua_assets` |
| `action_print()` | - | `l10n_ua_assets` |
| `month_name()` | - | `l10n_ua_assets` |
| `sheet_rows()` | Готові рядки відомості для друку. | `l10n_ua_assets` |
| `total()` | - | `l10n_ua_assets` |

### `ua.fop.income`

наша модель · `l10n_ua_fop`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_sync()` | Кнопка «Оновити з платежів». | `l10n_ua_fop` |

### `ua.fop.param`

наша модель · `l10n_ua_fop`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `get(key, on_date=None, company=None)` | Значення параметра, чинне на дату. Значення компанії б'є загальне. | `l10n_ua_fop` |

### `ua.fop.quarter`

наша модель · `l10n_ua_fop`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_fop` |
| `declaration_rows()` | Числа декларації платника ЄП за квартал - наростаючим підсумком. | `l10n_ua_fop` |

### `ua.group.consolidation`

наша модель · `l10n_ua_group`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_build()` | Зібрати звіт і відкрити його. Повертає дію на mis.report.instance. | `l10n_ua_group` |

### `ua.ledger.base`

наша модель · `l10n_ua_ledger`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ask()` | Кнопка «Сформувати» в шапці списку: діалог параметрів нового регістра. | `l10n_ua_ledger` |
| `action_compose()` | Кнопка «Скласти» в діалозі параметрів: порахувати і відкрити результат сторінкою. | `l10n_ua_ledger` |

### `ua.migrate`

наша модель · `l10n_ua_migrate`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_import()` | - | `l10n_ua_migrate` |

### `ua.osv.line`

наша модель · `l10n_ua_ledger`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_open_card()` | З рядка відомості - у картку цього рахунку за той самий період. | `l10n_ua_ledger` |

### `ua.osv.report`

наша модель · `l10n_ua_ledger`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_ledger` |
| `action_print_xlsx()` | - | `l10n_ua_ledger` |

### `ua.profit.declaration`

наша модель · `l10n_ua_profit_tax`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | Заповнити числа і рядки декларації. Дозволено лише в чернетці. | `l10n_ua_profit_tax` |
| `action_confirm()` | - | `l10n_ua_profit_tax` |
| `action_draft()` | - | `l10n_ua_profit_tax` |
| `action_xml()` | Зберегти XML декларації і додатка РІ в документі. | `l10n_ua_profit_tax` |

### `ua.profit.param`

наша модель · `l10n_ua_profit_tax`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `get(key, on_date=None, company=None)` | Значення параметра, чинне на дату. Значення компанії б'є загальне. | `l10n_ua_profit_tax` |

### `ua.quality.protocol`

наша модель · `l10n_ua_stock_docs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_fail()` | - | `l10n_ua_stock_docs` |
| `action_fill_checklist()` | Типовий перелік параметрів. Уже заповнений протокол не чіпаємо. | `l10n_ua_stock_docs` |
| `action_pass()` | - | `l10n_ua_stock_docs` |

### `ua.stock.inventory`

наша модель · `l10n_ua_stock_docs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply()` | Провести: коригування складу плюс проводка лишків 947 -> 719. | `l10n_ua_stock_docs` |
| `action_fill(category_ids=None, location_ids=None)` | Заповнити опис залишками складу. Старі рядки замінюються свіжими. | `l10n_ua_stock_docs` |
| `action_open_moves()` | - | `l10n_ua_stock_docs` |
| `action_start_count()` | Перевести опис із чернетки в підрахунок, не пишучи `state` ззовні. | `l10n_ua_stock_docs` |
| `plan()` | Що зробить проведення: розбіжності, суми на 947 і 719, дата, перешкоди. | `l10n_ua_stock_docs` |
| `ua_get_or_create(client_ref, vals=None)` | Документ за міткою клієнта: є - віддаємо, немає - створюємо. | `l10n_ua_stock_docs` |

### `ua.vat.compensation`

наша модель · `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_annual_recalc()` | Річний перерахунок ЧВ за ст.199.4 і 199.5 ПКУ. | `l10n_ua_vat` |
| `action_compute()` | ЧВ періоду і перегляд рядків компенсації. Лише в чернетці. | `l10n_ua_vat` |
| `action_post()` | Провести компенсацію: бухгалтерська проводка плюс зведена ПН. | `l10n_ua_vat` |

### `ua.vat.document`

наша модель · `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_export_xml()` | «XML для ЄРПН»: перевірка, складання, вкладення, завантаження. | `l10n_ua_vat` |
| `action_export_xml()` | Диспетчер: РК будуємо за J1201216, решту віддаємо конвеєру ПН. | `l10n_ua_vat` |
| `action_mark_pn_registered()` | «Позначити зареєстрованою»: ставить сьогоднішню дату реєстрації, | `l10n_ua_vat` |

### `ua.vat.period`

наша модель · `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compose_month()` | Кнопка списку «Створити за місяць»: зведення поточного місяця. | `l10n_ua_vat` |
| `action_compute()` | Кнопка «Порахувати»: перерахувати зведення за період. | `l10n_ua_vat` |
| `ua_compose(company, year=None, month=None, **params)` | Нове зведення ПДВ за місяць, одразу пораховане. | `l10n_ua_vat` |

### `ua.zvv.allocation`

наша модель · `l10n_ua_mrp`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | Зібрати базу, години і коефіцієнт. Рядки перезаписуються. | `l10n_ua_mrp` |
| `action_open_move()` | - | `l10n_ua_mrp` |
| `action_post()` | Одна проводка: Дт 231 розподілене, Дт 901 нерозподілене, Кт 91 усе. | `l10n_ua_mrp` |

### `account.asset`

доповнена модель · `l10n_ua_assets`, `l10n_ua_project_cost`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_commission` | Text | Склад комісії | `l10n_ua_assets` |
| `ua_disposal_reason` | Text | Причина списання | `l10n_ua_assets` |
| `ua_factory_number` | Char | Заводський номер | `l10n_ua_assets` |
| `ua_license_product_ids` | Many2many | product.product | `l10n_ua_project_cost` |
| `ua_location` | Char | Місцезнаходження об'єкта | `l10n_ua_assets` |
| `ua_manufacturer` | Char | Виробник | `l10n_ua_assets` |
| `ua_passport_number` | Char | Номер паспорта (документа) | `l10n_ua_assets` |
| `ua_responsible` | Char | Матеріально відповідальна особа | `l10n_ua_assets` |
| `ua_start_next_month` | Boolean | Амортизація з наступного місяця | `l10n_ua_assets` |
| `ua_year_built` | Char | Рік випуску (побудови) | `l10n_ua_assets` |

### `account.asset.profile`

доповнена модель · `l10n_ua_assets`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_min_months` | Integer | Мінімальний строк за ПКУ, міс. | `l10n_ua_assets` |
| `ua_rule` | Selection | Українське правило | `l10n_ua_assets` |
| `ua_start_next_month` | Boolean | Амортизація з наступного місяця | `l10n_ua_assets` |
| `ua_tax_group` | Selection | Податкова група | `l10n_ua_assets` |

### `account.bank.statement`

доповнена модель · `l10n_ua_bank_online`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_apply_rules()` | «Застосувати правила звірки»: усі незвірені рядки компанії. | `l10n_ua_bank_online` |
| `action_ua_match_payments()` | «Звести з платежами»: усі незвірені рядки компанії. | `l10n_ua_bank_online` |
| `action_ua_pull()` | «Завантажити виписку»: діалог з трьох полів - рахунок, рік, місяць. | `l10n_ua_bank_online` |
| `action_ua_pull_all()` | «Завантажити за всі рахунки»: поточний місяць, усі підключені рахунки. | `l10n_ua_bank_online` |

### `account.tax.group`

доповнена модель · `l10n_ua_vat`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_vat_zero_kind` | Selection | Вид нульової ставки (ПДВ, Україна) | `l10n_ua_vat` |

### `mis.report`

доповнена модель · `l10n_ua_finrep`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_finrep_form` | Selection | Українська форма | `l10n_ua_finrep` |

### `mis.report.instance`

доповнена модель · `l10n_ua_finrep`, `l10n_ua_group`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_finrep_xml_draft()` | Кнопка «XML (чернетка формату)»: вкладення і посилання на завантаження. | `l10n_ua_finrep` |
| `action_ua_group_consolidation()` | Кнопка «Сформувати» в шапці списку: діалог параметрів консолідації. | `l10n_ua_group` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_finrep_form` | Selection | Українська форма | `l10n_ua_finrep` |
| `ua_group_consolidation` | Boolean | Консолідація групи | `l10n_ua_group` |

### `online.bank.statement.provider`

доповнена модель · `l10n_ua_bank_online`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_test()` | Легкий запит до банку, щоб побачити, чи приймають токен. | `l10n_ua_bank_online` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_account` | Char | Рахунок у банку | `l10n_ua_bank_online` |
| `ua_demo` | Boolean | Демо-дані замість банку | `l10n_ua_bank_online` |

### `res.bank`

доповнена модель · `l10n_ua_docs`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_mfo` | Char | - | `l10n_ua_docs` |

### `res.currency.rate.provider`

доповнена модель · `l10n_ua_nbu`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `service` | Selection | - | `l10n_ua_nbu` |

### `sale.order`

доповнена модель · `l10n_ua_contract`, `l10n_ua_docs_sale`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_confirm()` | - | `l10n_ua_contract` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_contract_date` | Date | Дата договору | `l10n_ua_docs_sale` |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |
| `ua_contract_number` | Char | Договір № | `l10n_ua_docs_sale` |

### `uom.uom`

доповнена модель · `l10n_ua_vat`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_kspovo_code` | Char | Код КСПОВО | `l10n_ua_vat` |
| `ua_kspovo_short` | Char | Позначення КСПОВО | `l10n_ua_vat` |

## Контрагенти і закупівлі

### `bp.ai`

наша модель · `bp_purchase_intake`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `extract_json(spec, text=None, images=None)` | Run the extraction prompt with JSON mode, on document text or on page images. Returns (dict, usage, model). | `bp_purchase_intake` |
| `load_spec(name)` | - | `bp_purchase_intake` |
| `model_name()` | - | `bp_purchase_intake` |
| `to_markdown(filename, content, mimetype='application/pdf')` | PDF or image to text. Free for PDFs with a text layer. Returns (text, tokens). | `bp_purchase_intake` |
| `vision_model_name()` | - | `bp_purchase_intake` |

### `bp.purchase.intake`

наша модель · `bp_purchase_intake`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_create_bill()` | - | `bp_purchase_intake` |
| `action_open_bill()` | - | `bp_purchase_intake` |
| `action_open_partner()` | - | `bp_purchase_intake` |
| `action_refresh_registry()` | - | `bp_purchase_intake` |
| `action_reprocess()` | - | `bp_purchase_intake` |
| `message_new(msg_dict, custom_values=None)` | - | `bp_purchase_intake` |

### `kyc.case`

наша модель · `bp_kyc`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_decide_cleared()` | - | `bp_kyc` |
| `action_decide_flagged()` | - | `bp_kyc` |
| `action_decide_rejected()` | - | `bp_kyc` |
| `action_open_register()` | The register (kyc-service) is an API without a public page; show where the subject lives. | `bp_kyc` |
| `action_request_documents()` | - | `bp_kyc` |
| `action_screen_odb()` | - | `bp_kyc` |
| `action_search_courts()` | - | `bp_kyc` |
| `action_stage()` | - | `bp_kyc` |
| `action_sync_register()` | - | `bp_kyc` |

### `ua.partner.edr.wizard`

наша модель · `l10n_ua_partner_edr`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_create()` | - | `l10n_ua_partner_edr` |

### `ua.purchase.pad`

наша модель · `l10n_ua_purchase`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_create_request()` | Зробити запит на закупівлю з розпізнаних рядків. | `l10n_ua_purchase` |

### `purchase.request`

доповнена модель · `l10n_ua_purchase`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_pad()` | Кнопка «Пад» у шапці списку: разовий діалог, з якого виходить запит. | `l10n_ua_purchase` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_department_id` | Many2one | Підрозділ | `l10n_ua_purchase` |
| `ua_expense_account_id` | Many2one | Рахунок витрат | `l10n_ua_purchase` |

### `res.partner`

доповнена модель · `bp_kyc`, `bp_purchase_intake`, `l10n_ua_docs`, `l10n_ua_partner_edr`, `l10n_ua_purchase`, `l10n_ua_unit_transfer`, `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_bp_mark_unverified()` | - | `bp_purchase_intake` |
| `action_bp_mark_verified()` | - | `bp_purchase_intake` |
| `action_bp_open_intakes()` | - | `bp_purchase_intake` |
| `action_bp_refresh_registry()` | - | `bp_purchase_intake` |
| `action_fill_from_edr()` | - | `l10n_ua_partner_edr` |
| `action_new_kyc_case()` | - | `bp_kyc` |
| `action_open_kyc_cases()` | - | `bp_kyc` |
| `action_ua_new_from_edr()` | Кнопка «Контрагент з ЄДР» у шапці списку: разовий діалог на одне поле - код. | `l10n_ua_partner_edr` |
| `action_ua_supplier_bills()` | Кнопка-лічильник: вхідні рахунки цього контрагента. | `l10n_ua_purchase` |
| `action_ua_supplier_sync()` | «Оновити сигнали»: перечитати ЄДР, ПДВ і KYC та перерахувати ризик. | `l10n_ua_purchase` |
| `action_ua_unit_transfers()` | - | `l10n_ua_unit_transfer` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `bp_intake_id` | Many2one | bp.purchase.intake | `bp_purchase_intake` |
| `bp_registry_address` | Char | Адреса (ЄДР) | `bp_purchase_intake` |
| `bp_registry_checked_at` | Datetime | Дані ЄДР отримано | `bp_purchase_intake` |
| `bp_registry_date` | Date | Дата реєстрації (ЄДР) | `bp_purchase_intake` |
| `bp_registry_head` | Char | Керівник (ЄДР) | `bp_purchase_intake` |
| `bp_registry_kved` | Char | Основний КВЕД | `bp_purchase_intake` |
| `bp_registry_markers` | Text | Маркери (ЄДР) | `bp_purchase_intake` |
| `bp_registry_name` | Char | Повна назва (ЄДР) | `bp_purchase_intake` |
| `bp_registry_status` | Char | Стан (ЄДР) | `bp_purchase_intake` |
| `bp_registry_vat` | Char | ПДВ (ЄДР) | `bp_purchase_intake` |
| `bp_supplier_status` | Selection | - | `bp_purchase_intake` |
| `bp_verified_at` | Datetime | Перевірено | `bp_purchase_intake` |
| `bp_verified_by` | Many2one | res.users | `bp_purchase_intake` |
| `kyc_case_ids` | One2many | kyc.case | `bp_kyc` |
| `ua_actual_address` | Char | Фактична адреса | `l10n_ua_docs` |
| `ua_edr_capital` | Float | Статутний капітал, грн | `l10n_ua_partner_edr` |
| `ua_edr_checks` | Text | Маркери ризику | `l10n_ua_partner_edr` |
| `ua_edr_full_name` | Char | Повна назва (ЄДР) | `l10n_ua_partner_edr` |
| `ua_edr_head` | Char | Керівник | `l10n_ua_partner_edr` |
| `ua_edr_kind` | Selection | - | `l10n_ua_partner_edr` |
| `ua_edr_registration_date` | Date | Дата реєстрації | `l10n_ua_partner_edr` |
| `ua_edr_status` | Char | Стан у ЄДР | `l10n_ua_partner_edr` |
| `ua_edr_synced_at` | Datetime | Оновлено з ЄДР | `l10n_ua_partner_edr` |
| `ua_kved` | Char | Основний КВЕД | `l10n_ua_partner_edr` |
| `ua_purchase_avg_delay_days` | Integer | Середнє запізнення оплат, днів | `l10n_ua_purchase` |
| `ua_purchase_bill_count` | Integer | Рахунків | `l10n_ua_purchase` |
| `ua_purchase_bill_ids` | One2many | Рахунки постачальника | `l10n_ua_purchase` |
| `ua_purchase_bill_total` | Monetary | Сума рахунків | `l10n_ua_purchase` |
| `ua_purchase_open_balance` | Monetary | Заборгованість | `l10n_ua_purchase` |
| `ua_purchase_overprice_count` | Integer | Рахунків дорожчих за замовлення | `l10n_ua_purchase` |
| `ua_purchase_paid_total` | Monetary | Сплачено | `l10n_ua_purchase` |
| `ua_signatory_basis` | Char | Діє на підставі | `l10n_ua_docs` |
| `ua_signatory_name` | Char | Підписант (ПІБ) | `l10n_ua_docs` |
| `ua_supplier_edr_terminated` | Boolean | У ЄДР припинено | `l10n_ua_purchase` |
| `ua_supplier_kyc_block` | Boolean | KYC: відхилено | `l10n_ua_purchase` |
| `ua_supplier_risk_level` | Selection | Ризик постачальника | `l10n_ua_purchase` |
| `ua_supplier_risk_note` | Text | Через що бали | `l10n_ua_purchase` |
| `ua_supplier_risk_score` | Integer | Бали ризику | `l10n_ua_purchase` |
| `ua_supplier_signals_date` | Datetime | Сигнали оновлено | `l10n_ua_purchase` |
| `ua_supplier_vat_non_payer` | Boolean | Неплатник ПДВ | `l10n_ua_purchase` |
| `ua_unit` | Boolean | Військова частина | `l10n_ua_unit_transfer` |
| `ua_unit_number` | Char | Умовне найменування частини | `l10n_ua_unit_transfer` |
| `ua_vat_payer_status` | Selection | Статус ПДВ | `l10n_ua_vat` |
| `ua_vat_status` | Char | ПДВ | `l10n_ua_partner_edr` |

## Спільне

### `ua.api`

наша модель · `l10n_ua_api`, `l10n_ua_map`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `documents_for_month(company_id, year, month)` | Документи місяця з їхніми перевірками, по одному рядку на ВИД документа. | `l10n_ua_api` |
| `employee_card(employee_id)` | Картка працівника: те саме, що показує стандартна форма hr.employee. | `l10n_ua_api` |
| `floor_packages(company_id)` | Що стоїть нерозкладеним: приймання, підлоги полиць і свіжий випуск. | `l10n_ua_api` |
| `inventory_plan(inventory_id)` | Що зробить проведення інвентаризації - третє дієслово екрана складу. | `l10n_ua_api` |
| `month_summary(company_id, year, month)` | Усе, що показує екран місяця зарплати, одним читанням. | `l10n_ua_api` |
| `product_assembly(product_id)` | Складальна карта виробу з полицями, де комплектуючі лежать ЗАРАЗ. | `l10n_ua_api` |
| `record_checks(model, res_id)` | Перевірки одного запису: публічний вхід до `_checks()` будь-якої моделі. | `l10n_ua_api` |
| `reporting_status(company_id, year, month=None)` | Стан звітності за період: по рядку на кожен звіт робочого місця. | `l10n_ua_api` |
| `stock_glance(company_id, location_ids=None, category_ids=None, query=None, offset=0, limit=500)` | Залишки з першого погляду: скільки лежить, скільки треба, на скільки вистачить. | `l10n_ua_api` |
| `system_map(company_id=None)` | Карта системи з живими лічильниками. | `l10n_ua_map` |
| `warehouse_map(company_id)` | Карта складу: дерево локацій із місткістю, заповненням і вмістом. | `l10n_ua_api` |
| `workorder_card(workorder_id)` | Картка наряду для кіоску цеху: що робити, чим, і що вже перевірено. | `l10n_ua_api` |

### `ua.asset.inventory`

наша модель · `l10n_ua_asset_inventory`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_fill()` | Заповнити опис з реєстру: рядки за обліком перестворюються, лишки лишаються. | `l10n_ua_asset_inventory` |
| `action_post()` | Відобразити результати в обліку: нестачі, суми з винних, лишки, нові місця і МВО. | `l10n_ua_asset_inventory` |
| `action_print()` | - | `l10n_ua_asset_inventory` |
| `ua_condition(line)` | - | `l10n_ua_asset_inventory` |
| `ua_money(value)` | Сума для друку: пробіл між тисячами, кома, нуль - прочерк. | `l10n_ua_asset_inventory` |

### `ua.bad.debt.reserve`

наша модель · `l10n_ua_bad_debt`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_draft()` | - | `l10n_ua_bad_debt` |
| `action_fill()` | - | `l10n_ua_bad_debt` |
| `action_post()` | - | `l10n_ua_bad_debt` |
| `action_print()` | - | `l10n_ua_bad_debt` |
| `ua_buckets()` | [(назва групи, борг, відсоток, резерв)] для друку. | `l10n_ua_bad_debt` |
| `ua_date(day)` | - | `l10n_ua_bad_debt` |
| `ua_percent(bucket)` | - | `l10n_ua_bad_debt` |
| `ua_residual_at(line)` | Залишок дебетового рядка на дату: мінус зарахування, зроблені не пізніше дати. | `l10n_ua_bad_debt` |

### `ua.bom.substitute`

наша модель · `l10n_ua_mrp_substitute`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_approve()` | - | `l10n_ua_mrp_substitute` |
| `action_revoke()` | - | `l10n_ua_mrp_substitute` |

### `ua.cash.count`

наша модель · `l10n_ua_cash_count`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_done()` | - | `l10n_ua_cash_count` |
| `action_nominals()` | Поставити звичайний набір номіналів (наявні рядки лишаються). | `l10n_ua_cash_count` |
| `action_print()` | - | `l10n_ua_cash_count` |
| `action_refresh()` | Перечитати залишок за обліком на дату акта (після нових проводок по касі). | `l10n_ua_cash_count` |
| `ua_money(value)` | - | `l10n_ua_cash_count` |
| `ua_nominal(line)` | Номінал для друку: гривні цілим числом, монети - у копійках. | `l10n_ua_cash_count` |

### `ua.cashflow.budget`

наша модель · `l10n_ua_budget`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_approve()` | - | `l10n_ua_budget` |
| `action_close()` | - | `l10n_ua_budget` |
| `action_draft()` | - | `l10n_ua_budget` |
| `action_fill_from_fact()` | План = факт року «Рік факту» по місяцях, змінений на «Зміна, %». Лише чернетка. | `l10n_ua_budget` |
| `action_open_analysis()` | - | `l10n_ua_budget` |
| `action_print()` | - | `l10n_ua_budget` |
| `action_refresh_fact()` | Факт і зобов'язання в усі рядки; стаття з фактом без плану отримує рядок з нулем плану. | `l10n_ua_budget` |
| `ua_active(company, day)` | Затверджений бюджет компанії на рік дня, або порожньо. | `l10n_ua_budget` |
| `ua_rows(upto_month=12)` | Рядки виконання за статтями до місяця включно: стаття, план, факт, відхилення, %. | `l10n_ua_budget` |

### `ua.cashflow.rule`

наша модель · `l10n_ua_cashflow`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_match(company, code)` | Правило з найдовшим префіксом коду рахунку; правило компанії перед спільним. | `l10n_ua_cashflow` |

### `ua.cashflow.statement`

наша модель · `l10n_ua_cashflow`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_cashflow` |
| `action_done()` | - | `l10n_ua_cashflow` |
| `action_draft()` | - | `l10n_ua_cashflow` |
| `action_open_unassigned()` | - | `l10n_ua_cashflow` |
| `action_print()` | - | `l10n_ua_cashflow` |
| `ua_flow_totals(company, date_from, date_to, cash_prefixes='30,31,33')` | Рух коштів за статтями за період: {id статті: сума}, надходження плюс, витрачання мінус. | `l10n_ua_cashflow` |
| `ua_money(value)` | Сума для форми в гривнях з копійками: витрачання в дужках, нуль - прочерк. | `l10n_ua_cashflow` |
| `ua_rows()` | Рядки для друку: назва, код, звітний, попередній, вид рядка. | `l10n_ua_cashflow` |

### `ua.cashflow.statement.entry`

наша модель · `l10n_ua_cashflow`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_set_item(item)` | Записати статтю на рядок проводки: наступний розрахунок візьме її першою. | `l10n_ua_cashflow` |

### `ua.cashflow.statement.line`

наша модель · `l10n_ua_cashflow`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_open_entries()` | - | `l10n_ua_cashflow` |

### `ua.catalog.load`

наша модель · `l10n_ua_catalog`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_load()` | - | `l10n_ua_catalog` |

### `ua.claim`

наша модель · `l10n_ua_claim`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_claim` |
| `action_close()` | - | `l10n_ua_claim` |
| `action_create_eco()` | Конструкторська причина: чернетка повідомлення про зміну на виріб. | `l10n_ua_claim` |
| `action_decide()` | - | `l10n_ua_claim` |
| `action_print()` | - | `l10n_ua_claim` |
| `action_reopen()` | - | `l10n_ua_claim` |
| `action_respond()` | Відповідь замовнику надіслано (рекламацію прийнято до розгляду). | `l10n_ua_claim` |
| `action_start()` | - | `l10n_ua_claim` |

### `ua.commission.agreement`

наша модель · `l10n_ua_commission`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_close()` | - | `l10n_ua_commission` |
| `action_new_report()` | - | `l10n_ua_commission` |
| `action_open()` | - | `l10n_ua_commission` |
| `action_open_pickings()` | - | `l10n_ua_commission` |
| `action_open_reports()` | - | `l10n_ua_commission` |
| `action_return()` | Повернути все непродане: комітенту (in) або від комісіонера на склад (out). | `l10n_ua_commission` |
| `action_transfer()` | Прийняти товар від комітента (in) або передати комісіонеру (out): кількості з | `l10n_ua_commission` |
| `balance_rows()` | Що зараз лежить за договором: [{product, quantity, price}]. | `l10n_ua_commission` |

### `ua.commission.report`

наша модель · `l10n_ua_commission`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_commission` |
| `action_done()` | - | `l10n_ua_commission` |
| `action_fill()` | - | `l10n_ua_commission` |
| `action_open_invoices()` | - | `l10n_ua_commission` |
| `action_print()` | - | `l10n_ua_commission` |
| `action_reset_draft()` | - | `l10n_ua_commission` |
| `amount_words(amount)` | - | `l10n_ua_commission` |
| `money(amount)` | 1 240,50 - сума для друку. | `l10n_ua_commission` |
| `parties()` | (комісіонер, комітент) для друку. | `l10n_ua_commission` |

### `ua.component.analog.finder`

наша модель · `l10n_ua_component`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_search()` | - | `l10n_ua_component` |

### `ua.component.analog.finder.line`

наша модель · `l10n_ua_component`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_propose_bom()` | Запропонувати аналог на рядки специфікацій з цим товаром (без погодження). | `l10n_ua_component` |
| `action_save()` | Записати в перелік аналогів товару (і зворотний запис для повної заміни). | `l10n_ua_component` |

### `ua.component.class`

наша модель · `l10n_ua_component`, `l10n_ua_supplier_catalog`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_find_suppliers()` | - | `l10n_ua_supplier_catalog` |
| `action_ua_products()` | - | `l10n_ua_component` |
| `action_ua_suppliers()` | - | `l10n_ua_supplier_catalog` |

### `ua.component.intake`

наша модель · `l10n_ua_component`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply()` | - | `l10n_ua_component` |
| `action_lines()` | - | `l10n_ua_component` |
| `action_parse()` | - | `l10n_ua_component` |

### `ua.contract`

наша модель · `l10n_ua_claim`, `l10n_ua_contract`, `l10n_ua_defense`, `l10n_ua_edo`, `l10n_ua_guarantee`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_activate()` | - | `l10n_ua_contract` |
| `action_close()` | - | `l10n_ua_contract` |
| `action_new_plan_calculation()` | Планова калькуляція на перший виріб графіка без калькуляції. | `l10n_ua_defense` |
| `action_new_reconciliation_act()` | Акт звірки за договором з початку року по сьогодні. | `l10n_ua_contract` |
| `action_print_penalty()` | - | `l10n_ua_defense` |
| `action_ua_guarantees()` | - | `l10n_ua_guarantee` |
| `action_view_moves()` | - | `l10n_ua_contract` |
| `action_view_productions()` | - | `l10n_ua_defense` |
| `ua_penalty_rows(date=None)` | Рядки розрахунку: одна частина рядка графіка, поставлена (чи ні) з простроченням. | `l10n_ua_defense` |
| `ua_penalty_totals(date=None)` | - | `l10n_ua_defense` |

### `ua.correspondence`

наша модель · `l10n_ua_correspondence`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_correspondence` |
| `action_done()` | - | `l10n_ua_correspondence` |
| `action_print_register()` | - | `l10n_ua_correspondence` |
| `action_reopen()` | - | `l10n_ua_correspondence` |
| `action_reply()` | Форма нового вихідного у відповідь на цей документ. | `l10n_ua_correspondence` |
| `action_start()` | - | `l10n_ua_correspondence` |
| `register_rows(direction, date_from, date_to, restricted=False, company=None)` | Журнал реєстрації за період: рядки по порядку номерів. | `l10n_ua_correspondence` |

### `ua.customs.declaration`

наша модель · `l10n_ua_customs`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_customs` |
| `action_compute()` | Перераховує митну вартість, мито, базу і суму ПДВ, розносить збори. | `l10n_ua_customs` |
| `action_fill_from_pickings()` | Рядки з отриманих надходжень: кількість, фактурна вартість із замовлення. | `l10n_ua_customs` |
| `action_post()` | - | `l10n_ua_customs` |
| `action_print()` | - | `l10n_ua_customs` |
| `action_reset_draft()` | - | `l10n_ua_customs` |
| `action_view_landed_cost()` | - | `l10n_ua_customs` |
| `action_view_vat_move()` | - | `l10n_ua_customs` |

### `ua.debt.offset`

наша модель · `l10n_ua_offset`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_offset` |
| `action_fill()` | Заповнити документ відкритими сумами обох сторін. | `l10n_ua_offset` |
| `action_open_move()` | - | `l10n_ua_offset` |
| `action_post()` | - | `l10n_ua_offset` |
| `action_print()` | - | `l10n_ua_offset` |
| `action_reset_draft()` | - | `l10n_ua_offset` |
| `amount_words()` | - | `l10n_ua_offset` |
| `document_label(move)` | - | `l10n_ua_offset` |
| `money(amount)` | 1 240,50 - сума для друку. | `l10n_ua_offset` |
| `open_amounts()` | Скільки зараз відкрито з кожного боку: (борг контрагента, борг компанії). | `l10n_ua_offset` |
| `side_lines(side)` | - | `l10n_ua_offset` |

### `ua.defect.act`

наша модель · `l10n_ua_defect`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_defect` |
| `action_draft()` | - | `l10n_ua_defect` |
| `action_post()` | - | `l10n_ua_defect` |
| `action_print()` | - | `l10n_ua_defect` |
| `ua_cause_label()` | - | `l10n_ua_defect` |
| `ua_kind_label()` | - | `l10n_ua_defect` |
| `ua_loss_label()` | - | `l10n_ua_defect` |

### `ua.defense.acceptance`

наша модель · `l10n_ua_defense`, `l10n_ua_product_tests`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_defense` |
| `action_done()` | - | `l10n_ua_defense` |
| `action_done()` | - | `l10n_ua_defense` |
| `action_done()` | - | `l10n_ua_product_tests` |
| `action_fill_from_picking()` | Рядки з відвантаження: виріб, кількість і серійні номери. | `l10n_ua_defense` |
| `action_print()` | - | `l10n_ua_defense` |
| `action_reset_draft()` | - | `l10n_ua_defense` |

### `ua.defense.calculation`

наша модель · `l10n_ua_defense`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_approve()` | - | `l10n_ua_defense` |
| `action_compute()` | - | `l10n_ua_defense` |
| `action_print()` | - | `l10n_ua_defense` |
| `action_reset_draft()` | - | `l10n_ua_defense` |

### `ua.defense.schedule`

наша модель · `l10n_ua_defense`, `l10n_ua_mrp_plan`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_open_demand(product, company)` | Непокрита частина графіків: [(дата, кількість, контракт)], від найранішого. | `l10n_ua_mrp_plan` |

### `ua.disability.quota`

наша модель · `l10n_ua_disability_quota`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_disability_quota` |
| `action_done()` | - | `l10n_ua_disability_quota` |
| `action_draft()` | - | `l10n_ua_disability_quota` |
| `action_print()` | - | `l10n_ua_disability_quota` |
| `ua_group(line)` | - | `l10n_ua_disability_quota` |
| `ua_money(value)` | - | `l10n_ua_disability_quota` |
| `ua_norm(headcount_int)` | Кількість місць за нормативом для цілої середньооблікової кількості. | `l10n_ua_disability_quota` |

### `ua.eco`

наша модель · `l10n_ua_eco`, `l10n_ua_product_tests`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply()` | - | `l10n_ua_eco` |
| `action_approve()` | - | `l10n_ua_eco` |
| `action_cancel()` | - | `l10n_ua_eco` |
| `action_draft()` | - | `l10n_ua_eco` |
| `action_print()` | - | `l10n_ua_eco` |
| `action_reject()` | - | `l10n_ua_eco` |
| `action_submit()` | - | `l10n_ua_eco` |
| `diff_rows()` | [{action, product, new_product, old_qty, new_qty, uom, note}] по рядках ПЗ. | `l10n_ua_eco` |

### `ua.edo.document`

наша модель · `l10n_ua_edo`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_edo` |
| `action_mark_signed()` | Підписано поза ЕДО: контрагент підписав папір, скан прикладено. | `l10n_ua_edo` |
| `action_match_bill()` | - | `l10n_ua_edo` |
| `action_open_source()` | - | `l10n_ua_edo` |
| `action_open_url()` | - | `l10n_ua_edo` |
| `action_refresh()` | - | `l10n_ua_edo` |
| `action_reject()` | - | `l10n_ua_edo` |
| `action_revoke()` | Відкликати вихідний документ, поки контрагент його не підписав. | `l10n_ua_edo` |
| `action_send()` | - | `l10n_ua_edo` |
| `action_sign()` | Погодити вхідний документ: сервіс ставить підпис відповідальної особи. | `l10n_ua_edo` |

### `ua.edo.send.wizard`

наша модель · `l10n_ua_edo`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_open(records)` | - | `l10n_ua_edo` |
| `action_send()` | - | `l10n_ua_edo` |

### `ua.edo.source.mixin`

наша модель · `l10n_ua_edo`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_edo_documents()` | - | `l10n_ua_edo` |
| `action_ua_edo_send()` | - | `l10n_ua_edo` |

### `ua.equity.rule`

наша модель · `l10n_ua_equity`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_pick(rules, company, code, side, counter_codes)` | Найточніше правило: найдовші коди, далі з боком, далі правило компанії. | `l10n_ua_equity` |

### `ua.equity.statement`

наша модель · `l10n_ua_equity`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_equity` |
| `action_done()` | - | `l10n_ua_equity` |
| `action_draft()` | - | `l10n_ua_equity` |
| `action_open_fallback()` | - | `l10n_ua_equity` |
| `action_print()` | - | `l10n_ua_equity` |
| `ua_columns()` | - | `l10n_ua_equity` |
| `ua_money(value)` | Сума для форми: від'ємна в дужках, нуль - прочерк. | `l10n_ua_equity` |
| `ua_rows(period='current')` | Рядки для друку: назва, код, вид, суми граф 3-9, разом. | `l10n_ua_equity` |

### `ua.equity.statement.entry`

наша модель · `l10n_ua_equity`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_set_row(row)` | Записати рядок форми на рядок проводки: наступний розрахунок візьме його першим. | `l10n_ua_equity` |

### `ua.equity.statement.line`

наша модель · `l10n_ua_equity`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_open_entries()` | - | `l10n_ua_equity` |

### `ua.export.permit`

наша модель · `l10n_ua_export_control`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_activate()` | - | `l10n_ua_export_control` |
| `action_close()` | - | `l10n_ua_export_control` |
| `action_draft()` | - | `l10n_ua_export_control` |
| `action_print()` | - | `l10n_ua_export_control` |
| `ua_date(day)` | - | `l10n_ua_export_control` |
| `ua_kind_label()` | - | `l10n_ua_export_control` |
| `ua_shipments()` | Рядки звіту: проведені відвантаження з дозволом, за датою. | `l10n_ua_export_control` |
| `ua_used()` | {виріб: відвантажено} - проведені вихідні переміщення з цим дозволом. | `l10n_ua_export_control` |

### `ua.finrep.filing`

наша модель · `l10n_ua_finrep_dps`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_check()` | - | `l10n_ua_finrep_dps` |
| `action_compute()` | - | `l10n_ua_finrep_dps` |
| `action_done()` | - | `l10n_ua_finrep_dps` |
| `action_draft()` | - | `l10n_ua_finrep_dps` |
| `action_xml()` | - | `l10n_ua_finrep_dps` |

### `ua.fuel.norm.adjustment`

наша модель · `l10n_ua_fleet`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `for_date(date, company)` | - | `l10n_ua_fleet` |

### `ua.gig.act`

наша модель · `l10n_ua_diia_city`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_diia_city` |
| `action_confirm()` | - | `l10n_ua_diia_city` |
| `action_draft()` | - | `l10n_ua_diia_city` |
| `action_print()` | - | `l10n_ua_diia_city` |
| `action_refresh_rate()` | Взяти курс НБУ на дату акта ще раз (після оновлення курсів). | `l10n_ua_diia_city` |
| `money(amount)` | 1 240,50 - сума для друку. | `l10n_ua_diia_city` |
| `rate_text(rate)` | - | `l10n_ua_diia_city` |

### `ua.grant`

наша модель · `l10n_ua_grant`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_activate()` | - | `l10n_ua_grant` |
| `action_close()` | - | `l10n_ua_grant` |
| `action_draft()` | - | `l10n_ua_grant` |
| `action_find_receipts()` | Позначити грантом кредитові рядки 484 від грантодавця, що ще без аналітики. | `l10n_ua_grant` |
| `action_print()` | - | `l10n_ua_grant` |
| `action_recognize(date=None)` | Визнати доходом використане, але не більше отриманого. | `l10n_ua_grant` |
| `action_view_moves()` | - | `l10n_ua_grant` |
| `money(value)` | - | `l10n_ua_grant` |
| `ua_analytic_distribution()` | Розподіл для рядків документів, що йдуть у грант. | `l10n_ua_grant` |
| `ua_fresh()` | Суми з проводок, а не з кешу: проводки не є залежністю полів. | `l10n_ua_grant` |

### `ua.guarantee`

наша модель · `l10n_ua_guarantee`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_activate()` | - | `l10n_ua_guarantee` |
| `action_claim()` | - | `l10n_ua_guarantee` |
| `action_draft()` | - | `l10n_ua_guarantee` |
| `action_release()` | - | `l10n_ua_guarantee` |

### `ua.headcount.report`

наша модель · `l10n_ua_headcount`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_headcount` |
| `action_done()` | - | `l10n_ua_headcount` |
| `action_draft()` | - | `l10n_ua_headcount` |
| `action_print()` | - | `l10n_ua_headcount` |
| `ua_number(value, digits=2)` | Число для друку: дві цифри після коми, кома як роздільник. | `l10n_ua_headcount` |

### `ua.ia.capitalization`

наша модель · `l10n_ua_project_cost`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_project_cost` |
| `action_compute()` | - | `l10n_ua_project_cost` |
| `action_draft()` | - | `l10n_ua_project_cost` |
| `action_post()` | - | `l10n_ua_project_cost` |

### `ua.ia.license.split`

наша модель · `l10n_ua_project_cost`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_project_cost` |
| `action_draft()` | - | `l10n_ua_project_cost` |
| `action_fill_from_sales()` | Кількість ліцензій з проведених рахунків покупцям за місяць, мінус повернення. | `l10n_ua_project_cost` |
| `action_post()` | - | `l10n_ua_project_cost` |

### `ua.labour.report`

наша модель · `l10n_ua_labour_stat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_labour_stat` |
| `action_done()` | - | `l10n_ua_labour_stat` |
| `action_draft()` | - | `l10n_ua_labour_stat` |
| `action_print()` | - | `l10n_ua_labour_stat` |
| `ua_number(value, digits=1)` | - | `l10n_ua_labour_stat` |

### `ua.limit.card`

наша модель · `l10n_ua_limit_card`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_close()` | - | `l10n_ua_limit_card` |
| `action_fill_from_productions()` | Ліміт = потреба в матеріалі за обраними виробничими замовленнями. | `l10n_ua_limit_card` |
| `action_issue(quantity, reason=None, receiver=None, day=None)` | Відпустити в цех. Понад ліміт - лише керівник складу з причиною. | `l10n_ua_limit_card` |
| `action_open()` | - | `l10n_ua_limit_card` |
| `action_print()` | - | `l10n_ua_limit_card` |
| `action_reopen()` | - | `l10n_ua_limit_card` |
| `action_return(quantity, day=None)` | Повернути невикористаний матеріал з цеху на склад. | `l10n_ua_limit_card` |
| `ua_month()` | - | `l10n_ua_limit_card` |
| `ua_rows()` | Рядки друку: дата, відпущено, повернуто, наростаючим підсумком, залишок ліміту. | `l10n_ua_limit_card` |

### `ua.local.tax.line`

наша модель · `l10n_ua_local_tax`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_env_kind_label()` | - | `l10n_ua_local_tax` |
| `ua_split()` | [(кінець періоду, сума)]: нерухомість - квартали, земля - місяці, екологія - квартал. | `l10n_ua_local_tax` |

### `ua.local.tax.object`

наша модель · `l10n_ua_local_tax`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_annual(min_wage=0.0)` | Сума за повний рік. | `l10n_ua_local_tax` |
| `ua_months(year)` | Місяці року, за які платить власник: з місяця набуття до місяця перед втратою права. | `l10n_ua_local_tax` |

### `ua.local.tax.return`

наша модель · `l10n_ua_local_tax`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_copy_previous()` | Склад речовин і ставки з попереднього кварталу, кількості - нулі. | `l10n_ua_local_tax` |
| `action_draft()` | Повернути в чернетку: проводки сторнуються. | `l10n_ua_local_tax` |
| `action_fill()` | - | `l10n_ua_local_tax` |
| `action_post()` | - | `l10n_ua_local_tax` |
| `action_print()` | - | `l10n_ua_local_tax` |
| `ua_date(day)` | - | `l10n_ua_local_tax` |
| `ua_kind_label()` | - | `l10n_ua_local_tax` |
| `ua_schedule()` | [(дата кінця періоду, сума)] за всіма рядками. | `l10n_ua_local_tax` |

### `ua.navigation`

наша модель · `l10n_ua_navigation`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `apply()` | - | `l10n_ua_navigation` |

### `ua.notes.statement`

наша модель · `l10n_ua_notes`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_notes` |
| `action_done()` | - | `l10n_ua_notes` |
| `action_draft()` | - | `l10n_ua_notes` |
| `action_print()` | - | `l10n_ua_notes` |
| `ua_money(value)` | Сума для форми: від'ємна в дужках, нуль - прочерк. | `l10n_ua_notes` |
| `ua_sections()` | Для друку: (назва розділу, [(графа, заголовок)], [(назва, код, вид, [суми])]). | `l10n_ua_notes` |

### `ua.parcel`

наша модель · `l10n_ua_parcel`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_close()` | - | `l10n_ua_parcel` |
| `action_ua_open_carrier()` | - | `l10n_ua_parcel` |
| `action_ua_reopen()` | - | `l10n_ua_parcel` |
| `action_ua_track()` | Спитати перевізника зараз. Помилка одного перевізника не зупиняє інших. | `l10n_ua_parcel` |

### `ua.parcel.add`

наша модель · `l10n_ua_parcel`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_add()` | - | `l10n_ua_parcel` |

### `ua.parcel.carrier`

наша модель · `l10n_ua_parcel`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_parcels()` | - | `l10n_ua_parcel` |

### `ua.parcel.links`

наша модель · `l10n_ua_parcel`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_parcel_add()` | - | `l10n_ua_parcel` |
| `action_ua_parcels()` | - | `l10n_ua_parcel` |

### `ua.payment.request`

наша модель · `l10n_ua_budget`, `l10n_ua_payment_request`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_approve()` | - | `l10n_ua_payment_request` |
| `action_cancel()` | - | `l10n_ua_payment_request` |
| `action_create_payment()` | - | `l10n_ua_budget` |
| `action_create_payment()` | Платіж за погодженою заявкою: за рахунками - майстром оплати, інакше аванс. | `l10n_ua_payment_request` |
| `action_draft()` | - | `l10n_ua_payment_request` |
| `action_print()` | - | `l10n_ua_payment_request` |
| `action_reject()` | - | `l10n_ua_payment_request` |
| `action_submit()` | - | `l10n_ua_budget` |
| `action_submit()` | - | `l10n_ua_payment_request` |
| `calendar_rows(date_from, date_to, company=None)` | Платіжний календар: заявки на погодженні й погоджені за датами оплати. | `l10n_ua_payment_request` |

### `ua.payroll.allocation`

наша модель · `l10n_ua_project_cost`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_confirm()` | - | `l10n_ua_project_cost` |
| `action_copy_previous()` | Взяти рядки попереднього місяця: ті самі люди, проєкти, рахунки і години. | `l10n_ua_project_cost` |
| `action_draft()` | - | `l10n_ua_project_cost` |
| `action_fill_timesheets()` | Години з обліку часу за проєктами (hr_timesheet), якщо він встановлений. | `l10n_ua_project_cost` |

### `ua.piecework`

наша модель · `l10n_ua_piecework`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_piecework` |
| `action_confirm()` | - | `l10n_ua_piecework` |
| `action_draft()` | - | `l10n_ua_piecework` |
| `action_fill()` | - | `l10n_ua_piecework` |
| `action_print()` | - | `l10n_ua_piecework` |
| `by_employee()` | [(працівник, рядки, сума)] за абеткою. | `l10n_ua_piecework` |
| `money(amount)` | 1 240,50 - сума для друку. | `l10n_ua_piecework` |
| `qty(amount)` | - | `l10n_ua_piecework` |

### `ua.precious.report`

наша модель · `l10n_ua_precious_metals`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_print()` | - | `l10n_ua_precious_metals` |
| `ua_date(day)` | - | `l10n_ua_precious_metals` |
| `ua_rows()` | Рядок на кожен метал, що трапився: {"metal", "code", колонка: текст грамів}. | `l10n_ua_precious_metals` |

### `ua.price.label.wizard`

наша модель · `l10n_ua_price_label`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_print()` | - | `l10n_ua_price_label` |
| `label_rows()` | Рядки цінників по порядку, з копіями: [{name, code, price, unit, unit_price, | `l10n_ua_price_label` |

### `ua.price.order`

наша модель · `l10n_ua_price_set`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | Скасувати: прибрати ціни документа і повернути попереднім їхній кінець. | `l10n_ua_price_set` |
| `action_compute()` | Нова ціна = собівартість x (1 + націнка типу) з округленням типу. | `l10n_ua_price_set` |
| `action_done()` | - | `l10n_ua_price_set` |
| `action_draft()` | - | `l10n_ua_price_set` |
| `action_fill_category()` | - | `l10n_ua_price_set` |
| `action_fill_picking()` | - | `l10n_ua_price_set` |
| `action_fill_pricelist()` | Товари, які вже мають ціну в обраних типах цін. | `l10n_ua_price_set` |
| `action_labels()` | - | `l10n_ua_price_set` |
| `action_print()` | - | `l10n_ua_price_set` |
| `ua_date(day)` | - | `l10n_ua_price_set` |

### `ua.price.order.line`

наша модель · `l10n_ua_price_set`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_changed()` | - | `l10n_ua_price_set` |

### `ua.procurement.plan`

наша модель · `l10n_ua_procurement_plan`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_amend()` | Зміни до затвердженого плану: нова редакція-чернетка з тими самими рядками. | `l10n_ua_procurement_plan` |
| `action_approve()` | - | `l10n_ua_procurement_plan` |
| `action_export_json()` | Файл для майданчика: предмети плану в структурі планів API Prozorro. | `l10n_ua_procurement_plan` |
| `action_print()` | - | `l10n_ua_procurement_plan` |
| `actual_rows()` | План проти замовлень за класами ДК 021: [{code, name, planned, ordered, left, level}]. | `l10n_ua_procurement_plan` |
| `prozorro_plans()` | Предмети плану у вигляді планів API Prozorro (без процедури і звіту - не йдуть). | `l10n_ua_procurement_plan` |
| `subject_rows()` | Предмети закупівлі: [{key, dk021, name, kind, total, threshold, lines}]. | `l10n_ua_procurement_plan` |

### `ua.product.test`

наша модель · `l10n_ua_product_tests`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_done()` | - | `l10n_ua_product_tests` |
| `action_draft()` | - | `l10n_ua_product_tests` |
| `action_print()` | - | `l10n_ua_product_tests` |
| `ua_date(day)` | - | `l10n_ua_product_tests` |
| `ua_kind_label()` | - | `l10n_ua_product_tests` |

### `ua.prro.receipt`

наша модель · `l10n_ua_prro`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_prro` |
| `action_open_url()` | - | `l10n_ua_prro` |
| `action_send()` | - | `l10n_ua_prro` |

### `ua.prro.register`

наша модель · `l10n_ua_prro`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_close_shift()` | - | `l10n_ua_prro` |
| `action_service_in()` | - | `l10n_ua_prro` |
| `action_service_out()` | - | `l10n_ua_prro` |
| `service_operation(kind, amount)` | Службове внесення чи видача готівки: чек без товарів, лише сума. | `l10n_ua_prro` |

### `ua.prro.shift`

наша модель · `l10n_ua_prro`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_close()` | - | `l10n_ua_prro` |
| `local_totals()` | Підсумки зміни за чеками в обліку - те, з чим звіряється Z-звіт. | `l10n_ua_prro` |

### `ua.reconciliation.act`

наша модель · `l10n_ua_contract`, `l10n_ua_edo`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_fill()` | Заповнити акт проводками періоду; дані контрагента не чіпає. | `l10n_ua_contract` |
| `action_mark_agreed()` | - | `l10n_ua_contract` |
| `action_mark_disputed()` | - | `l10n_ua_contract` |
| `action_mark_sent()` | - | `l10n_ua_contract` |
| `action_print()` | - | `l10n_ua_contract` |
| `action_reset_draft()` | - | `l10n_ua_contract` |

### `ua.safety.briefing`

наша модель · `l10n_ua_safety`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_done()` | - | `l10n_ua_safety` |
| `action_draft()` | - | `l10n_ua_safety` |
| `action_fill_job()` | - | `l10n_ua_safety` |
| `action_print()` | - | `l10n_ua_safety` |
| `ua_date(day)` | - | `l10n_ua_safety` |
| `ua_journal_rows()` | Рядки журналу за датою: № з/п, дата, працівник, посада, вид, інструкції, інструктор. | `l10n_ua_safety` |
| `ua_kind_label()` | - | `l10n_ua_safety` |

### `ua.screen`

наша модель · `l10n_ua_screen`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `open_target(target)` | Відкрити ціль будь-якого блоку будь-якого екрана. | `l10n_ua_screen` |

### `ua.supplier.approval`

наша модель · `l10n_ua_supplier_approval`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_approve()` | - | `l10n_ua_supplier_approval` |
| `action_draft()` | - | `l10n_ua_supplier_approval` |
| `action_print()` | - | `l10n_ua_supplier_approval` |
| `action_suspend(reason=None)` | - | `l10n_ua_supplier_approval` |
| `action_withdraw(reason=None)` | - | `l10n_ua_supplier_approval` |
| `ua_check(partner, products, company, day, what)` | UserError, якщо хоч один критичний товар не має чинного погодження в постачальника. | `l10n_ua_supplier_approval` |
| `ua_covers(product, day)` | Чи діє погодження на товар у цей день. | `l10n_ua_supplier_approval` |
| `ua_date(day)` | - | `l10n_ua_supplier_approval` |
| `ua_find(partner, product, company, day)` | Чинне погодження постачальника на товар або порожньо. | `l10n_ua_supplier_approval` |
| `ua_scope_text()` | - | `l10n_ua_supplier_approval` |
| `ua_state_label()` | - | `l10n_ua_supplier_approval` |

### `ua.supplier.price.import`

наша модель · `l10n_ua_supplier_catalog`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply()` | - | `l10n_ua_supplier_catalog` |
| `action_lines()` | - | `l10n_ua_supplier_catalog` |
| `action_parse()` | - | `l10n_ua_supplier_catalog` |

### `ua.supplier.price.profile`

наша модель · `l10n_ua_supplier_catalog`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_imports()` | - | `l10n_ua_supplier_catalog` |
| `action_new_import()` | - | `l10n_ua_supplier_catalog` |

### `ua.tolling.order`

наша модель · `l10n_ua_tolling`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_tolling` |
| `action_confirm()` | - | `l10n_ua_tolling` |
| `action_deliver()` | Відвантаження готової продукції давальцю. | `l10n_ua_tolling` |
| `action_done()` | - | `l10n_ua_tolling` |
| `action_draft()` | - | `l10n_ua_tolling` |
| `action_fill_from_bom()` | Сировина давальця за специфікацією на всю кількість. Власні матеріали з переліку | `l10n_ua_tolling` |
| `action_invoice()` | Рахунок за переробку на виготовлену, ще не виставлену кількість. | `l10n_ua_tolling` |
| `action_open_invoices()` | - | `l10n_ua_tolling` |
| `action_open_pickings()` | - | `l10n_ua_tolling` |
| `action_open_productions()` | - | `l10n_ua_tolling` |
| `action_print()` | - | `l10n_ua_tolling` |
| `action_produce()` | Виробниче замовлення на ще не виготовлену кількість: давальницькі компоненти - з | `l10n_ua_tolling` |
| `action_receive()` | Прийом сировини: на місце давальця, з давальцем як власником. | `l10n_ua_tolling` |
| `action_return_materials()` | Повернення невикористаної сировини давальцю. | `l10n_ua_tolling` |
| `material_rows()` | Рядки звіту переробника по кожному матеріалу давальця. | `l10n_ua_tolling` |

### `ua.unit.transfer`

наша модель · `l10n_ua_unit_transfer`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_unit_transfer` |
| `action_done()` | - | `l10n_ua_unit_transfer` |
| `action_fill_from_picking()` | Рядки з відвантаження: виріб, кількість, серійні номери, ціна. | `l10n_ua_unit_transfer` |
| `action_print()` | - | `l10n_ua_unit_transfer` |
| `action_reset_draft()` | - | `l10n_ua_unit_transfer` |
| `amount_words()` | - | `l10n_ua_unit_transfer` |
| `money(amount)` | 1 240,50 - сума для друку. | `l10n_ua_unit_transfer` |

### `ua.unit.transfer.line`

наша модель · `l10n_ua_unit_transfer`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `lot_names()` | - | `l10n_ua_unit_transfer` |

### `ua.vacation.move.wizard`

наша модель · `l10n_ua_vacation_plan`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_apply()` | - | `l10n_ua_vacation_plan` |

### `ua.vacation.plan`

наша модель · `l10n_ua_vacation_plan`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_approve()` | - | `l10n_ua_vacation_plan` |
| `action_draft()` | - | `l10n_ua_vacation_plan` |
| `action_fill()` | Рядок без дат кожному працівнику, якого ще немає в графіку. | `l10n_ua_vacation_plan` |
| `action_print()` | - | `l10n_ua_vacation_plan` |
| `ua_balance(employee)` | Невикористані дні виду відпустки за затвердженими нарахуваннями на 1 січня року. | `l10n_ua_vacation_plan` |
| `ua_date_text(day)` | Дата для друку: 01.07.2026; порожньо - підкреслення. | `l10n_ua_vacation_plan` |

### `ua.vacation.plan.line`

наша модель · `l10n_ua_vacation_plan`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_create_leave()` | Заявка на відпустку за датами графіка; погоджують її звичайним порядком. | `l10n_ua_vacation_plan` |
| `action_move(date_from, date_to, reason)` | Перенести відпустку: старі дати лишаються в рядку, нові - з підставою. | `l10n_ua_vacation_plan` |
| `action_notified()` | - | `l10n_ua_vacation_plan` |
| `action_open_move()` | - | `l10n_ua_vacation_plan` |
| `action_print_notice()` | - | `l10n_ua_vacation_plan` |

### `ua.vat.return`

наша модель · `l10n_ua_vat_return`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_compute()` | - | `l10n_ua_vat_return` |
| `action_done()` | - | `l10n_ua_vat_return` |
| `action_draft()` | - | `l10n_ua_vat_return` |
| `action_xml()` | - | `l10n_ua_vat_return` |

### `ua.waybill`

наша модель · `l10n_ua_fleet`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | Скасувати: рух палива сторнується, запис спідометра зникає. | `l10n_ua_fleet` |
| `action_done()` | Закрити лист: заправки - у бак, фактична витрата - зі списанням за нормою. | `l10n_ua_fleet` |
| `action_open()` | Видати лист водію: фіксуємо спідометр і залишок у баку. | `l10n_ua_fleet` |
| `action_print()` | - | `l10n_ua_fleet` |
| `action_reset_draft()` | - | `l10n_ua_fleet` |
| `adjustments_text()` | «Зима 10%, Місто 5%» - коригування норми для друку. | `l10n_ua_fleet` |
| `litres(value)` | 27,50 - літри для друку. | `l10n_ua_fleet` |

### `ua.workwear.issue`

наша модель · `l10n_ua_workwear`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_cancel()` | - | `l10n_ua_workwear` |
| `action_done()` | - | `l10n_ua_workwear` |
| `action_draft()` | - | `l10n_ua_workwear` |
| `action_fill()` | Додати рядки з того, чого працівникам бракує за нормами посад. | `l10n_ua_workwear` |
| `action_print()` | - | `l10n_ua_workwear` |

### `ua.workwear.line`

наша модель · `l10n_ua_workwear`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_print_write_off()` | - | `l10n_ua_workwear` |
| `action_return(location=None)` | Повернути з експлуатації на склад відомості за ціною видачі. | `l10n_ua_workwear` |
| `action_write_off(reason=None)` | Списати з експлуатації: вартість уже у витратах, лишається акт. | `l10n_ua_workwear` |
| `money(value)` | 10 000,00 - гроші для друку. | `l10n_ua_workwear` |
| `ua_date(value)` | - | `l10n_ua_workwear` |
| `ua_period()` | «12 міс.» або «до зносу» - для друку. | `l10n_ua_workwear` |

### `account.account`

доповнена модель · `l10n_ua_notes`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_investment_basis` | Selection | Оцінка інвестиції у формі № 5 | `l10n_ua_notes` |
| `ua_investment_row` | Selection | Рядок розділу IV форми № 5 | `l10n_ua_notes` |

### `account.journal`

доповнена модель · `l10n_ua_bank_1c`, `l10n_ua_bank_online`, `l10n_ua_prro`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_bank_provider()` | «З'єднання з банком»: наявне відкриваємо, відсутнє - показуємо перелік. | `l10n_ua_bank_online` |
| `action_ua_bank_test()` | «Перевірити з'єднання» на формі банківського журналу. | `l10n_ua_bank_online` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_prro_payment_type` | Selection | - | `l10n_ua_prro` |
| `ua_prro_register_id` | Many2one | ua.prro.register | `l10n_ua_prro` |

### `account.move`

доповнена модель · `bp_purchase_intake`, `l10n_ua_cashflow`, `l10n_ua_close`, `l10n_ua_commission`, `l10n_ua_contract`, `l10n_ua_docs`, `l10n_ua_edo`, `l10n_ua_equity`, `l10n_ua_grant`, `l10n_ua_prro`, `l10n_ua_tolling`, `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_post()` | - | `bp_purchase_intake` |
| `action_ua_close_first_events()` | Кнопка «Закрити першу подію» - страховка, коли автоматика не | `l10n_ua_vat` |
| `action_ua_create_tax_invoice()` | Кнопка «Скласти податкову накладну». | `l10n_ua_vat` |
| `action_ua_post_customs_vat()` | «Взяти в кредит»: проводка Дт 6412 / Кт 3771 на суму ПДВ із митної | `l10n_ua_vat` |
| `action_ua_prro_receipts()` | - | `l10n_ua_prro` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `bp_intake_id` | Many2one | bp.purchase.intake | `bp_purchase_intake` |
| `ua_cashflow_item_id` | Many2one | ua.cashflow.item | `l10n_ua_cashflow` |
| `ua_close_id` | Many2one | ua.period.close | `l10n_ua_close` |
| `ua_close_kind` | Selection | - | `l10n_ua_close` |
| `ua_commission_report_id` | Many2one | ua.commission.report | `l10n_ua_commission` |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |
| `ua_customs_decl_number` | Char | Номер митної декларації | `l10n_ua_vat` |
| `ua_customs_entry` | Boolean | Позначка проводки митного ПДВ | `l10n_ua_vat` |
| `ua_customs_move_id` | Many2one | account.move | `l10n_ua_vat` |
| `ua_customs_vat` | Monetary | Митний ПДВ | `l10n_ua_vat` |
| `ua_equity_row` | Selection | Рядок звіту про власний капітал | `l10n_ua_equity` |
| `ua_fe_kind` | Selection | Проводка першої події | `l10n_ua_vat` |
| `ua_grant_id` | Many2one | ua.grant | `l10n_ua_grant` |
| `ua_in_pn_registered` | Boolean | ПН постачальника зареєстрована | `l10n_ua_vat` |
| `ua_pn_deadline` | Date | Граничний строк реєстрації ПН | `l10n_ua_vat` |
| `ua_prro_receipt_ids` | Many2many | ua.prro.receipt | `l10n_ua_prro` |
| `ua_tolling_id` | Many2one | ua.tolling.order | `l10n_ua_tolling` |
| `ua_vat_comp` | Boolean | Проводка компенсуючих ПЗ | `l10n_ua_vat` |
| `ua_vat_document_ids` | One2many | ua.vat.document | `l10n_ua_vat` |

### `account.move.line`

доповнена модель · `l10n_ua_cashflow`, `l10n_ua_contract`, `l10n_ua_equity`, `l10n_ua_tolling`, `l10n_ua_vat`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_cashflow_item_id` | Many2one | ua.cashflow.item | `l10n_ua_cashflow` |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |
| `ua_equity_row` | Selection | Рядок форми № 4 | `l10n_ua_equity` |
| `ua_tolling_qty` | Boolean | Кількість переробки | `l10n_ua_tolling` |

### `account.payment`

доповнена модель · `l10n_ua_bank_1c`, `l10n_ua_cash`, `l10n_ua_cashflow`, `l10n_ua_contract`, `l10n_ua_fop`, `l10n_ua_prro`, `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_post()` | - | `l10n_ua_cash` |
| `action_post()` | Спершу стандартне проведення, потім спроба створити проводку першої | `l10n_ua_vat` |
| `action_ua_bank1c_export()` | - | `l10n_ua_bank_1c` |
| `action_ua_print_cash_order()` | Друк КО-1 (ПКО) або КО-2 (ВКО). | `l10n_ua_cash` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_cashflow_item_id` | Many2one | ua.cashflow.item | `l10n_ua_cashflow` |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |
| `ua_document` | Char | Документ одержувача | `l10n_ua_cash` |
| `ua_fe_closed_amount` | Float | Закрито ПДВ першої події | `l10n_ua_vat` |
| `ua_fe_move_id` | Many2one | account.move | `l10n_ua_vat` |
| `ua_fe_reversed` | Boolean | Першу подію закрито | `l10n_ua_vat` |
| `ua_fop_not_income` | Boolean | Не дохід ФОП | `l10n_ua_fop` |
| `ua_order_kind` | Selection | Вид касового ордера | `l10n_ua_cash` |
| `ua_order_number` | Char | Номер ордера | `l10n_ua_cash` |
| `ua_person` | Char | Прийнято від / Видати | `l10n_ua_cash` |
| `ua_prro_receipt_ids` | One2many | ua.prro.receipt | `l10n_ua_prro` |

### `account.payment.register`

доповнена модель · `l10n_ua_contract`, `l10n_ua_prro`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |

### `account.tax`

доповнена модель · `l10n_ua_prro`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_prro_letter` | Char | Літера в чеку ПРРО | `l10n_ua_prro` |

### `fleet.vehicle`

доповнена модель · `l10n_ua_fleet`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_waybills()` | - | `l10n_ua_fleet` |
| `ua_fuel_balance()` | Скільки палива зараз у баку. | `l10n_ua_fleet` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_expense_account_id` | Many2one | account.account | `l10n_ua_fleet` |
| `ua_expense_location_id` | Many2one | stock.location | `l10n_ua_fleet` |
| `ua_fuel_product_id` | Many2one | product.product | `l10n_ua_fleet` |
| `ua_norm_base` | Float | Базова норма, л/100 км | `l10n_ua_fleet` |
| `ua_norm_cargo` | Float | На транспортну роботу, л/100 т·км | `l10n_ua_fleet` |
| `ua_norm_hour` | Float | Робота на місці, л/год | `l10n_ua_fleet` |
| `ua_overnorm_account_id` | Many2one | account.account | `l10n_ua_fleet` |
| `ua_overnorm_location_id` | Many2one | stock.location | `l10n_ua_fleet` |
| `ua_tank_location_id` | Many2one | stock.location | `l10n_ua_fleet` |
| `ua_warehouse_id` | Many2one | stock.warehouse | `l10n_ua_fleet` |
| `ua_waybill_ids` | One2many | ua.waybill | `l10n_ua_fleet` |

### `hr.job`

доповнена модель · `l10n_ua_safety`, `l10n_ua_workwear`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_briefing_months` | Integer | Повторний інструктаж, раз на (міс.) | `l10n_ua_safety` |
| `ua_hazardous` | Boolean | Роботи з підвищеною небезпекою | `l10n_ua_safety` |
| `ua_medical_months` | Integer | Медогляд, раз на (міс.) | `l10n_ua_safety` |
| `ua_safety_instructions` | Char | Інструкції з охорони праці | `l10n_ua_safety` |
| `ua_workwear_norm_ids` | One2many | ua.workwear.norm | `l10n_ua_workwear` |

### `hr.payslip.input`

доповнена модель · `l10n_ua_diia_city`, `l10n_ua_piecework`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_gig_auto` | Boolean | З акта гіг-спеціаліста | `l10n_ua_diia_city` |
| `ua_piecework_auto` | Boolean | З виробітку | `l10n_ua_piecework` |

### `hr.salary.rule`

доповнена модель · `l10n_ua_labour_stat`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_pv_class` | Selection | - | `l10n_ua_labour_stat` |
| `ua_pv_unworked` | Boolean | Оплата за невідпрацьований час (5090) | `l10n_ua_labour_stat` |

### `maintenance.equipment`

доповнена модель · `l10n_ua_metrology`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_print_schedule()` | - | `l10n_ua_metrology` |
| `action_ua_verifications()` | - | `l10n_ua_metrology` |
| `ua_label()` | «Штангенциркуль ШЦ-I-150 № 1234, повірка до 10.01.2027» - для відповіді ВТК і паспорта. | `l10n_ua_metrology` |
| `ua_unfit_reason(day=None)` | Чому засобом не можна міряти на дату; порожньо - можна. | `l10n_ua_metrology` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_accuracy` | Char | Клас точності, похибка | `l10n_ua_metrology` |
| `ua_conserved` | Boolean | Законсервовано | `l10n_ua_metrology` |
| `ua_interval_months` | Integer | Інтервал, міс. | `l10n_ua_metrology` |
| `ua_last_date` | Date | Остання повірка | `l10n_ua_metrology` |
| `ua_last_result` | Selection | - | `l10n_ua_metrology` |
| `ua_measure_range` | Char | Діапазон вимірювань | `l10n_ua_metrology` |
| `ua_measuring` | Boolean | Засіб вимірювальної техніки | `l10n_ua_metrology` |
| `ua_notify_days` | Integer | Нагадати за, днів | `l10n_ua_metrology` |
| `ua_regulated` | Boolean | Законодавчо регульований | `l10n_ua_metrology` |
| `ua_valid_until` | Date | Придатний до | `l10n_ua_metrology` |
| `ua_verification_ids` | One2many | ua.metrology.verification | `l10n_ua_metrology` |

### `mrp.area`

доповнена модель · `l10n_ua_mrp_plan`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_defense_area(company)` | - | `l10n_ua_mrp_plan` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_defense_demand` | Boolean | Попит з оборонних контрактів | `l10n_ua_mrp_plan` |

### `mrp.bom`

доповнена модель · `l10n_ua_eco`, `l10n_ua_mrp`, `l10n_ua_mrp_substitute`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_substitutes()` | - | `l10n_ua_mrp_substitute` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_eco_id` | Many2one | ua.eco | `l10n_ua_eco` |
| `ua_previous_bom_id` | Many2one | mrp.bom | `l10n_ua_eco` |
| `ua_revision` | Integer | Зміна № | `l10n_ua_eco` |
| `ua_successor_eco_id` | Many2one | ua.eco | `l10n_ua_eco` |

### `mrp.bom.line`

доповнена модель · `l10n_ua_mrp_substitute`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_substitute_ids` | One2many | ua.bom.substitute | `l10n_ua_mrp_substitute` |

### `mrp.production`

доповнена модель · `l10n_ua_defect`, `l10n_ua_defense`, `l10n_ua_eco`, `l10n_ua_mrp`, `l10n_ua_mrp_substitute`, `l10n_ua_tolling`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_defect_act()` | - | `l10n_ua_defect` |
| `action_ua_open_defects()` | - | `l10n_ua_defect` |
| `action_ua_substitute()` | Покрити нестачу компонентів вільним залишком погоджених аналогів. | `l10n_ua_mrp_substitute` |
| `ua_defect_unit_cost()` | Матеріали замовлення на одиницю виробу за обліковою ціною компонентів. | `l10n_ua_defect` |
| `ua_get_or_create(client_ref, vals=None)` | Замовлення за міткою клієнта: є - віддаємо, немає - створюємо. | `l10n_ua_mrp` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_bom_revision` | Integer | Зміна специфікації | `l10n_ua_eco` |
| `ua_client_ref` | Char | Мітка операції | `l10n_ua_mrp` |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_defense` |
| `ua_defect_act_ids` | One2many | ua.defect.act | `l10n_ua_defect` |
| `ua_tolling_id` | Many2one | ua.tolling.order | `l10n_ua_tolling` |

### `mrp.routing.workcenter`

доповнена модель · `l10n_ua_metrology`, `l10n_ua_mrp`, `l10n_ua_piecework`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_checks` | Text | Перевірка | `l10n_ua_mrp` |
| `ua_instrument_ids` | Many2many | maintenance.equipment | `l10n_ua_metrology` |
| `ua_piece_rate` | Float | Розцінка, грн за одиницю | `l10n_ua_piecework` |
| `ua_steps` | Text | Кроки | `l10n_ua_mrp` |

### `mrp.workcenter`

доповнена модель · `l10n_ua_defense`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_energy_hour` | Float | Енергія за годину | `l10n_ua_defense` |
| `ua_wage_hour` | Float | Основна зарплата за годину | `l10n_ua_defense` |

### `mrp.workorder`

доповнена модель · `l10n_ua_metrology`, `l10n_ua_mrp`, `l10n_ua_piecework`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_answer_check(index, result, note=None)` | Як у l10n_ua_mrp, але «так» - лише придатними засобами вимірювання операції. | `l10n_ua_metrology` |
| `ua_answer_check(index, result, note=None)` | Записати відповідь на пункт перевірки. Повторна відповідь оновлює першу. | `l10n_ua_mrp` |
| `ua_check_rows()` | - | `l10n_ua_metrology` |
| `ua_check_rows()` | Пункти перевірки наряду з відповідями. | `l10n_ua_mrp` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_check_ids` | One2many | ua.workorder.check | `l10n_ua_mrp` |
| `ua_piecework_line_ids` | One2many | ua.piecework.line | `l10n_ua_piecework` |

### `product.pricelist`

доповнена модель · `l10n_ua_price_set`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_markup` | Float | Націнка від собівартості, % | `l10n_ua_price_set` |
| `ua_price_kind` | Selection | - | `l10n_ua_price_set` |
| `ua_rounding` | Selection | - | `l10n_ua_price_set` |

### `product.pricelist.item`

доповнена модель · `l10n_ua_price_set`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_price_order_id` | Many2one | ua.price.order | `l10n_ua_price_set` |

### `product.product`

доповнена модель · `l10n_ua_precious_metals`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `ua_precious_content(quantity=1.0, _path=())` | {метал: грами} у quantity одиниць товару, разом зі складовими специфікації. | `l10n_ua_precious_metals` |
| `ua_precious_rows()` | Рядки розділу паспорта: метал, символ, грами на один виріб. | `l10n_ua_precious_metals` |

### `product.supplierinfo`

доповнена модель · `l10n_ua_supplier_catalog`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_component_class_id` | Many2one | Вид комплектуючих | `l10n_ua_supplier_catalog` |
| `ua_import_id` | Many2one | ua.supplier.price.import | `l10n_ua_supplier_catalog` |
| `ua_price_base` | Float | Ціна за одиницю обліку | `l10n_ua_supplier_catalog` |
| `ua_stock` | Float | Залишок у постачальника | `l10n_ua_supplier_catalog` |

### `product.template`

доповнена модель · `l10n_ua_component`, `l10n_ua_customs`, `l10n_ua_defense`, `l10n_ua_dk021`, `l10n_ua_export_control`, `l10n_ua_mrp`, `l10n_ua_precious_metals`, `l10n_ua_price_label`, `l10n_ua_product_tests`, `l10n_ua_stock_docs`, `l10n_ua_supplier_approval`, `l10n_ua_supplier_catalog`, `l10n_ua_vat`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_analogs()` | - | `l10n_ua_component` |
| `action_ua_apply_template()` | Назву й артикул - за шаблоном виду (артикул лише якщо порожній). | `l10n_ua_component` |
| `action_ua_compare_suppliers()` | - | `l10n_ua_supplier_catalog` |
| `action_ua_duplicates()` | - | `l10n_ua_component` |
| `action_ua_find_suppliers()` | - | `l10n_ua_supplier_catalog` |
| `action_ua_parse_name()` | Розібрати назву товару в характеристики (порожні не перезаписує). | `l10n_ua_component` |
| `action_ua_units()` | Одиниці конкретного товару з маси: метр, пруток, м², лист; кг для кріплення. | `l10n_ua_component` |
| `ua_acceptance_block(day)` | Чому виріб зараз не можна приймати, або порожній рядок. | `l10n_ua_product_tests` |
| `ua_assembly()` | Креслення і операції з позиціями - усе, що треба екрану збирання. | `l10n_ua_mrp` |
| `ua_test_status(day=None)` | Коротко для списку і картки виробу. | `l10n_ua_product_tests` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_analog_ids` | One2many | ua.component.analog | `l10n_ua_component` |
| `ua_approved_only` | Boolean | Лише від погоджених постачальників | `l10n_ua_supplier_approval` |
| `ua_component_class_id` | Many2one | ua.component.class | `l10n_ua_component` |
| `ua_component_code` | Char | Артикул за шаблоном | `l10n_ua_component` |
| `ua_component_key` | Char | Відбиток | `l10n_ua_component` |
| `ua_component_missing` | Char | Бракує | `l10n_ua_component` |
| `ua_component_name` | Char | Назва за шаблоном | `l10n_ua_component` |
| `ua_component_value_ids` | One2many | ua.component.value | `l10n_ua_component` |
| `ua_control_kind` | Selection | - | `l10n_ua_export_control` |
| `ua_control_ref` | Char | Позиція контрольного списку | `l10n_ua_export_control` |
| `ua_cost_item` | Selection | - | `l10n_ua_defense` |
| `ua_customs_duty_rate` | Float | Ставка ввізного мита, % | `l10n_ua_customs` |
| `ua_dk021_id` | Many2one | ua.dk021 | `l10n_ua_dk021` |
| `ua_drawing_name` | Char | Файл креслення | `l10n_ua_mrp` |
| `ua_drawing_svg` | Binary | Складальне креслення | `l10n_ua_mrp` |
| `ua_export_controlled` | Boolean | Під експортним контролем | `l10n_ua_export_control` |
| `ua_label_content` | Float | Вміст упаковки | `l10n_ua_price_label` |
| `ua_label_unit` | Selection | - | `l10n_ua_price_label` |
| `ua_mass_per_m` | Float | Маса 1 м, кг | `l10n_ua_component` |
| `ua_mass_per_m2` | Float | Маса 1 м², кг | `l10n_ua_component` |
| `ua_periodic_first_due` | Date | Перші періодичні - до | `l10n_ua_product_tests` |
| `ua_periodic_last_id` | Many2one | ua.product.test | `l10n_ua_product_tests` |
| `ua_periodic_months` | Integer | Періодичні випробування, раз на (міс.) | `l10n_ua_product_tests` |
| `ua_periodic_valid_until` | Date | Періодичні діють до | `l10n_ua_product_tests` |
| `ua_piece_mass` | Float | Маса штуки, кг | `l10n_ua_component` |
| `ua_precious_ids` | One2many | ua.precious.content | `l10n_ua_precious_metals` |
| `ua_size` | Selection | Габарит | `l10n_ua_stock_docs` |
| `ua_test_ids` | One2many | ua.product.test | `l10n_ua_product_tests` |
| `ua_test_notify_days` | Integer | Нагадати про випробування за, днів | `l10n_ua_product_tests` |
| `ua_test_program` | Char | Програма і методика випробувань | `l10n_ua_product_tests` |
| `ua_type_test_reason` | Char | Чому потрібні типові | `l10n_ua_product_tests` |
| `ua_type_test_required` | Boolean | Потрібні типові випробування | `l10n_ua_product_tests` |
| `ua_uktzed` | Char | Код УКТ ЗЕД | `l10n_ua_vat` |
| `ua_vat_relief_id` | Many2one | ua.vat.relief | `l10n_ua_vat` |
| `ua_vat_treatment` | Selection | Режим ПДВ товару | `l10n_ua_vat` |
| `ua_warranty_months` | Integer | Гарантія, місяців | `l10n_ua_defense` |

### `purchase.order`

доповнена модель · `l10n_ua_contract`, `l10n_ua_parcel`, `l10n_ua_purchase`, `l10n_ua_supplier_approval`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |
| `ua_department_id` | Many2one | Підрозділ | `l10n_ua_purchase` |
| `ua_expense_account_id` | Many2one | Рахунок витрат | `l10n_ua_purchase` |
| `ua_parcel_ids` | One2many | ua.parcel | `l10n_ua_parcel` |
| `ua_request_id` | Many2one | Запит на закупівлю | `l10n_ua_purchase` |
| `ua_sale_contract_id` | Many2one | ua.contract | `l10n_ua_contract` |

### `purchase.order.line`

доповнена модель · `l10n_ua_dk021`, `l10n_ua_purchase`, `l10n_ua_supplier_approval`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_dk021_id` | Many2one | ua.dk021 | `l10n_ua_dk021` |

### `stock.landed.cost`

доповнена модель · `l10n_ua_customs`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_customs_declaration_id` | Many2one | ua.customs.declaration | `l10n_ua_customs` |

### `stock.location`

доповнена модель · `l10n_ua_commission`, `l10n_ua_stock_docs`, `l10n_ua_tolling`, `l10n_ua_workwear`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_capacity` | Integer | Місць | `l10n_ua_stock_docs` |
| `ua_commission_partner_id` | Many2one | res.partner | `l10n_ua_commission` |
| `ua_in_use` | Boolean | Предмети в експлуатації | `l10n_ua_workwear` |
| `ua_plan_h` | Integer | План: висота | `l10n_ua_stock_docs` |
| `ua_plan_w` | Integer | План: ширина | `l10n_ua_stock_docs` |
| `ua_plan_x` | Integer | План: X | `l10n_ua_stock_docs` |
| `ua_plan_y` | Integer | План: Y | `l10n_ua_stock_docs` |
| `ua_purpose` | Selection | Призначення зони | `l10n_ua_stock_docs` |
| `ua_tolling_partner_id` | Many2one | res.partner | `l10n_ua_tolling` |

### `stock.lot`

доповнена модель · `l10n_ua_claim`, `l10n_ua_defense`, `l10n_ua_eco`, `l10n_ua_precious_metals`, `l10n_ua_unit_transfer`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_print_passport()` | - | `l10n_ua_defense` |
| `action_ua_claims()` | - | `l10n_ua_claim` |
| `ua_precious_rows()` | - | `l10n_ua_precious_metals` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_acceptance_id` | Many2one | ua.defense.acceptance | `l10n_ua_defense` |
| `ua_contract_id` | Many2one | ua.contract | `l10n_ua_defense` |
| `ua_passport_number` | Char | Номер паспорта | `l10n_ua_defense` |
| `ua_unit_transfer_id` | Many2one | ua.unit.transfer | `l10n_ua_unit_transfer` |

### `stock.move`

доповнена модель · `l10n_ua_fleet`, `l10n_ua_limit_card`, `l10n_ua_mrp_substitute`, `l10n_ua_workwear`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_limit_card_id` | Many2one | ua.limit.card | `l10n_ua_limit_card` |
| `ua_substitute_id` | Many2one | ua.bom.substitute | `l10n_ua_mrp_substitute` |
| `ua_substitute_of_id` | Many2one | product.product | `l10n_ua_mrp_substitute` |
| `ua_waybill_id` | Many2one | ua.waybill | `l10n_ua_fleet` |
| `ua_waybill_reversed` | Boolean | Сторновано скасуванням листа | `l10n_ua_fleet` |
| `ua_workwear_line_id` | Many2one | ua.workwear.line | `l10n_ua_workwear` |

### `stock.move.line`

доповнена модель · `l10n_ua_commission`

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_commission_report_id` | Many2one | ua.commission.report | `l10n_ua_commission` |

### `stock.picking`

доповнена модель · `l10n_ua_commission`, `l10n_ua_docs_stock`, `l10n_ua_export_control`, `l10n_ua_parcel`, `l10n_ua_stock_docs`, `l10n_ua_supplier_approval`, `l10n_ua_tolling`, `l10n_ua_unit_transfer`

| Метод | Що робить | Модуль |
| --- | --- | --- |
| `action_ua_unit_transfer()` | Акт передачі з цього відвантаження: існуючий або новий, заповнений. | `l10n_ua_unit_transfer` |
| `ua_get_or_create(client_ref, vals=None)` | Доставка за міткою клієнта: є - віддаємо, немає - створюємо. | `l10n_ua_stock_docs` |

| Поле | Тип | Підпис | Модуль |
| --- | --- | --- | --- |
| `ua_act_condition` | Char | Стан цінностей | `l10n_ua_stock_docs` |
| `ua_act_handover` | Char | Передав (ПІБ, посада) | `l10n_ua_stock_docs` |
| `ua_act_receiver` | Char | Прийняв (ПІБ, посада) | `l10n_ua_stock_docs` |
| `ua_client_ref` | Char | Мітка операції | `l10n_ua_stock_docs` |
| `ua_commission_id` | Many2one | ua.commission.agreement | `l10n_ua_commission` |
| `ua_export_permit_id` | Many2one | ua.export.permit | `l10n_ua_export_control` |
| `ua_parcel_ids` | One2many | ua.parcel | `l10n_ua_parcel` |
| `ua_proxy_date` | Date | Дата довіреності | `l10n_ua_docs_stock` |
| `ua_proxy_number` | Char | Довіреність № | `l10n_ua_docs_stock` |
| `ua_proxy_person` | Char | Видана на (ПІБ) | `l10n_ua_docs_stock` |
| `ua_tolling_id` | Many2one | ua.tolling.order | `l10n_ua_tolling` |
| `ua_unit_transfer_ids` | One2many | ua.unit.transfer | `l10n_ua_unit_transfer` |
