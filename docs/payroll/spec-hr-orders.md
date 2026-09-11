# Спека: кадрові накази як документи, журнал реєстрації, пакет документів

Дата: 9 вересня 2026. Автор: Fable. Виконавець: Sonnet-агент P. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`, база `payroll_test`. Не комітити, не пушити, не чіпати хмару, не перезапускати контейнер стенду (для нового Python-коду `odoo shell` або тимчасовий `docker run --rm`). Паралельно інший агент робить `addons/l10n_ua_card_ui` на базі `payroll`: не редагувати той модуль і ту базу.

## Рішення замовника

Наказ стає документом, який проводить зміну, а не друком після зміни. Макет узгоджений: бланк наказу зі станами чернетка → проведено → ознайомлено, журнал реєстрації з окремою нумерацією за реєстрами і роками, матриця обов'язкового пакета документів.

Форми звичайні (Odoo form, list, звіт QWeb). OWL тут не потрібен.

## Модуль `l10n_ua_hr_orders`

Залежності: `l10n_ua_hr_docs`, `l10n_ua_payroll_rules`, `l10n_ua_average`, `l10n_ua_military`, `l10n_ua_hr_card`.

### Модель `ua.hr.order`

Поля: `name` (номер, обчислений при проведенні, readonly), `order_type` Selection (`hire` прийняття, `wage` зміна окладу, `transfer` переведення, `leave` відпустка, `dismissal` звільнення, `trip` відрядження), `register` Selection (`k1` «К-1, кадрові, 75 років», `v2` «В-2, відпустки і відрядження, 5 років»; обчислюється з виду: leave і trip → v2, решта → k1, можна змінити вручну), `date` (дата наказу, default today), `employee_id` (required), `state` Selection (`draft`, `posted`, `acknowledged`, `cancelled`), `company_id`, `note`, `basis` Char («Підстава»), `signed_file` Binary + `signed_filename`, `ack_date` Date, `ack_user_id`, `version_id` (hr.version, створена наказом, readonly), `leave_id` (hr.leave, створена наказом, readonly), `_inherit = ["mail.thread"]`.

Поля за видами (усі невидимі, коли не той вид):
- hire: `date_from` (перший день роботи), `job_title`, `department_id`, `wage`, `fte` (Selection як у працівника), `kp_code`, `prof_name`, `contract_type_id`, `trial_date_end`, `main_job` Boolean, `contract_kind` Selection (трудовий, ЦПХ).
- wage: `date_from`, `wage_old` (readonly, обчислене), `wage`.
- transfer: `date_from`, `department_id`, `job_title`, `wage` (може не змінюватися), `kp_code`, `prof_name`.
- leave: `leave_type_id` (hr.leave.type), `date_from`, `date_to`, `days` (обчислене, календарні), `sick_number` (для декретної).
- dismissal: `date_to` (останній день роботи), `dismissal_basis` Char, `comp_days` Float («Днів компенсації», необов'язково).
- trip: `date_from`, `date_to`, `destination` Char, `purpose` Char, `days` обчислене.

### Нумерація

`ir.sequence` окремо на реєстр, з річними діапазонами (`use_date_range=True`), суфікс з реєстру: `-к` для K-1, `-в` для V-2. Номер присвоюється при проведенні (`action_post`), не при створенні. Формат: число без нулів попереду плюс суфікс, наприклад `51-к`.

### Проведення (`action_post`)

Загальне: перевірити обов'язкові поля виду, присвоїти номер, поставити `state = posted`, записати в чаттер, повернути повідомлення.

За видами:
- `hire`: створити `hr.version` (працівник, `date_version = date_from`, `contract_date_start = date_from`, оклад, посада, підрозділ, `struct_id` структури `UA_SALARY`, `resource_calendar_id` компанії, `contract_type_id`, `trial_date_end`, `ua_order_ref = «Наказ № <номер> від <дата>»`, `ua_kp_code`, `ua_prof_name`), записати на працівника `ua_main_job`, `ua_fte`, `ua_contract_kind`, `ua_hire_date`. Дати писати з контекстом `sync_contract_dates=True` (інакше Odoo синхронізує дати всіх версій).
- `wage`: створити нову `hr.version` копією поточної з `date_version = date_from` і новим окладом; `ua_order_ref`.
- `transfer`: нова версія з новим підрозділом, посадою, кодом КП, при потребі окладом.
- `leave`: створити `hr.leave` (працівник, тип, `request_date_from`, `request_date_to`, `ua_order_ref`, `ua_sick_number`), затвердити (`action_approve`), у контексті компанії працівника (`with_company` і `allowed_company_ids`, інакше Odoo 19 кидає «на відпустці не вказано співробітника»).
- `dismissal`: у поточній версії поставити `contract_date_end = date_to`, `ua_end_order_ref`, `ua_dismissal_basis`; працівнику `ua_dismissal_date`; якщо задано `comp_days`, додати вхід `COMP_DAYS` у чернетковий листок місяця звільнення, якщо такий є.
- `trip`: даних не змінює, лише реєструється і друкується.

### Скасування (`action_cancel`)

Якщо створений об'єкт не змінювався після проведення (порівняти `write_date` з датою проведення), видалити його і повернути стан `draft` без номера; інакше `UserError` з поясненням, що робити вручну. Скасований наказ отримує `state = cancelled` і лишається в журналі.

### Ознайомлення (`action_acknowledge`)

Ставить `ack_date = today`, `ack_user_id = env.user`, `state = acknowledged`. Доступно лише з `posted`.

### Звіти

- По одному QWeb на вид (`web.basic_layout`, paperformat `l10n_ua_payroll_reports.paperformat_ua_a4`), шапка з назвою компанії, ЄДРПОУ, номером і датою, текст наказу за видом, підстава, підписи керівника і працівника. Стиль узяти з `addons/l10n_ua_hr_docs/report/ua_orders_report.xml`.
- «Журнал реєстрації наказів» (майстер `ua.hr.order.register.wizard`: рік, реєстр) → таблиця: номер, дата, вид, працівник, зміст одним рядком, стан, дата ознайомлення. Альбомна орієнтація.

### Обов'язковий пакет документів

- Модель `ua.hr.doc.requirement`: `name`, `code`, `applies_to` Selection (`employment`, `gph`, `fop`, `all`), `active`, `sequence`. Дані: заява про прийняття, наказ про прийняття, трудовий договір, копія паспорта і РНОКПП, військово-обліковий документ (лише для військовозобов'язаних), згода на обробку персональних даних, інструктаж з охорони праці, договір ЦПХ (для gph і fop), медичний огляд (для виробництва, необов'язково).
- На `hr.employee`: `ua_doc_missing_ids` (обчислене, `ua.hr.doc.requirement`, які не покриті наявними `ua.employee.document` за кодом типу або наказами), `ua_doc_missing_count` (обчислене, store=False), поле показати у вкладці «Документи».
- Майстер `ua.hr.doc.pack.wizard` → звіт «Пакет документів» матрицею: рядки документи, колонки працівники, значення «є», «немає», «н/п». Альбомна.

### Перенесення наявних даних (`post_init_hook`)

Створити проведені накази з наявних записів, щоб журнал не був порожній:
- з кожної `hr.version` із `ua_order_ref` → наказ `hire` (або `wage`, якщо це не перша версія працівника) зі станом `posted`, номером з тексту (розібрати «Наказ № 9-к від 17.08.2026»), датою з тексту, `version_id` = ця версія;
- з `ua_end_order_ref` → наказ `dismissal`;
- з кожної `hr.leave` із `ua_order_ref` → наказ `leave`, `leave_id` = ця відпустка.
Номери не переприсвоювати, послідовності виставити так, щоб наступний номер був більший за максимальний перенесений.

### Меню

У модулі `l10n_ua_payroll_ui` є розділ «Кадрові документи» (`menu_ua_payroll_docs`). Додати пункти власним файлом у своєму модулі: «Накази» (список), «Журнал реєстрації», «Пакет документів». Пункти пульта в `l10n_ua_hub` не чіпати, їх додасть оркестратор.

## Перевірка

`scripts/orders_check.py` (база з `PAYROLL_DB`, типово `payroll`):
- перенесення дало щонайменше 15 наказів, усі з номерами, стан `posted`;
- новий наказ `wage` на Ткачука: проведення створює нову версію з новим окладом і датою, `ua_order_ref` заповнено, номер має суфікс `-к` і на одиницю більший за максимальний;
- новий наказ `leave` на Мельничука: проведення створює затверджену відпустку з `ua_order_ref`, суфікс `-в`;
- скасування наказу `wage` видаляє створену версію і повертає стан `draft`;
- ознайомлення ставить дату;
- три PDF (наказ про зміну окладу, журнал реєстрації, пакет документів) починаються з `%PDF`;
- `ua_doc_missing_count` більший за нуль хоча б у одного працівника.

## Технічні правила

- Odoo 19: `<list>`, `hr.version`, `sync_contract_dates=True` при записі дат контракту, `with_company` для `hr.leave`.
- Оновлення: `docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll_test -i l10n_ua_hr_orders --stop-after-init --log-level=warn 2>&1 | tail -20"`.
- Українська мова, короткі підписи, без пояснень у формах.
- Звіт: файли, вивід перевірки, що не зроблено.


## Наслідки наказу

Після проведення наказ показує, що з нього вийшло. У шапці - рядок «Наслідки»: версія
договору, відсутність, введення в листок, листок місяця, рядок виплати. Поруч кнопки, які
ведуть до самих документів.

Так бухгалтер вводить подію один раз і бачить усі її наслідки в одному місці, замість того
щоб шукати їх списками. Перевірка: `scripts/orders_check.py`, три останні пункти.
