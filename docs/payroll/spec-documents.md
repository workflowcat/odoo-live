# Спека: документи з прев'ю перед друком

Дата: 9 вересня 2026. Автор спеки: Fable. Виконавці: Sonnet-агенти. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`. Не комітити: перевірку і коміт робить оркестратор.

## Мета

Зараз майстри «Табель (П-5)», «Штатний розпис», «Аванс за місяць» і звіт «Заява-розрахунок до ПФУ» одразу дають PDF або пишуть у листки. Потрібно: майстер створює документ-запис із рядками, бухгалтер переглядає і править рядки, ставить примітки, натискає «Затвердити», далі «Друк». Документи мають історію (chatter), стан, повторний друк.

## Загальний патерн для кожного документа

- Модель документа `ua.<doc>` з `_inherit = ["mail.thread"]`, поля: `name` (обчислене, store), `company_id`, `state` Selection `[("draft", "Чернетка"), ("confirmed", "Затверджено")]` default draft, tracking, `note` Text «Примітка», `line_ids` One2many.
- Кнопки у header форми: «Перерахувати» (`action_refill`, лише draft: видаляє рядки і заповнює знову з джерела), «Затвердити» (`action_confirm`), «Повернути в чернетку» (`action_draft`), «Друк» (звіт). Statusbar по `state`.
- Рядки редагуються лише в draft: у списку рядків `readonly="parent.state != 'draft'"`, у моделі рядка `_check` не потрібен.
- Видалення документа лише в draft (`@api.ondelete(at_uninstall=False)` → UserError).
- Права: `hr.group_hr_user` read/write/create/unlink на документ і рядки (csv у `security/ir.model.access.csv` модуля).
- Звіт QWeb: існуючий шаблон переписати так, щоб він читав рядки документа (`doc.line_ids`), а не рахував заново. `ir.actions.report` перев'язати на модель документа (`binding_model_id`), стару прив'язку на майстер прибрати. `paperformat_id` лишити як був.
- Майстер лишається як точка входу: після «Створити» він створює документ і відкриває його форму (`act_window` form на `res_id`). Якщо документ на той самий період уже є в draft, майстер відкриває його (не дублює).
- Списки документів у меню «Зарплата» (модуль `l10n_ua_payroll_ui`, файли `views/menus_docs.xml` і `views/menus_advance.xml` уже є в маніфесті; пишіть menuitem туди). Батьки: `l10n_ua_payroll_ui.menu_ua_payroll_calc`, `menu_ua_payroll_reporting`, `menu_ua_payroll_docs`.
- Форми стандартні Odoo: `<form>`, `<sheet>`, `<group>`, `<notebook>` з рядками, `<chatter/>`. Без JS, без CSS, без власних віджетів. Написи українською, короткі.
- Назви полів у списках рядків: людські, без кодів.

## Документ 1: Табель обліку робочого часу (модуль `l10n_ua_hr_docs`, агент A)

- Модель `ua.timesheet.sheet`: `year` Integer, `month` Integer, `department_id` M2O hr.department (порожньо = усі), `line_ids`, `name` = «Табель 09.2026» або «Табель 09.2026, Виробництво». Унікальність не потрібна.
- Модель `ua.timesheet.line`: `sheet_id`, `employee_id`, `job_title` Char, `tab_number` Char (id працівника), `hours_day` Float (8 × ставка), 31 поле `d01`..`d31` Char size 3 (код дня: Р, ВХ, В, ТН, НА, ВП, «-» не в штаті, порожньо для днів поза місяцем), обчислені stored: `days_worked` Integer (кількість «Р»), `hours` Float (`days_worked × hours_day`), `days_vac`, `days_sick`, `days_unpaid`, `days_mat` Integer (кількість В / ТН / НА / ВП). `note` Char.
- Заповнення (`action_refill`): перенести логіку `UaTimesheetWizard._rows()` у метод документа; майстер лише створює документ і викликає `action_refill`.
- Форма: заголовок (рік, місяць, підрозділ, стан), вкладка «Рядки» зі списком `editable="bottom"`: працівник, посада, d01..d31 (всі 31, `width="28px"` не потрібен; просто короткі назви колонок «1».. «31»), дні, години, В, ТН, НА, ВП. Вкладка «Примітка».
- Звіт `report_ua_timesheet`: читати `doc.line_ids` і `d01..d31`; години показувати з `hours_day` для днів «Р». Перев'язати на `ua.timesheet.sheet`.
- Меню: «Табелі» (list+form) у `menu_ua_payroll_docs` після майстра.

## Документ 2: Штатний розпис (модуль `l10n_ua_hr_docs`, агент A)

- Модель `ua.staff.list`: `date` Date, `order_ref` Char «Затверджено наказом», `line_ids`, `total_units` Float і `total_fund` Monetary обчислені store, `currency_id` related company. `name` = «Штатний розпис на 31.08.2026».
- Модель `ua.staff.list.line`: `list_id`, `department_id` M2O, `job_title` Char, `kp_code` Char, `units` Float «Штатних одиниць», `wage` Monetary «Оклад», `fund` Monetary обчислене store (`units × wage`), `note` Char. Порядок: підрозділ, посада.
- `action_refill`: логіка `UaStaffListWizard._rows()` → рядки.
- Звіт `report_ua_staff_list` читає рядки документа. Перев'язати на `ua.staff.list`.
- Меню: «Штатні розписи» у `menu_ua_payroll_docs`.

## Документ 3: Заява-розрахунок до ПФУ (модуль `l10n_ua_hr_docs`, агент A)

- Модель `ua.pfu.claim`: `payslip_run_id` M2O hr.payslip.run required, `date` Date default today, `line_ids`, `total` Monetary обчислене store. `name` = «Заява-розрахунок ПФУ, серпень 2026» (місяць з `payslip_run_id.date_start`, назви місяців українською у родовому: січня… грудня → використати «за 08.2026», простіше: «Заява-розрахунок ПФУ 08.2026»).
- Модель `ua.pfu.claim.line`: `claim_id`, `employee_id`, `kind` Selection `[("sick", "Тимчасова непрацездатність"), ("mat", "Вагітність та пологи")]`, `sick_number` Char «№ е-ЛН», `date_from`, `date_to`, `days` Integer «Днів за рахунок ПФУ», `avg_day` Float «Середньоденна», `percent` Float, `amount` Monetary, `note` Char.
- `action_refill`: логіка зі звіту `report_ua_pfu_claim` (пошук рядків SICK_PFU і MAT у листках пакета, відпустки з номером е-ЛН, дні з `slip._ua_leave_calendar_days()`).
- На `hr.payslip.run` кнопка «Заява-розрахунок ПФУ» (`action_ua_pfu_claim`): створює документ (або відкриває існуючий draft для цього пакета) і відкриває форму. Стару прив'язку звіту до `hr.payslip.run` прибрати; звіт перев'язати на `ua.pfu.claim`.
- Меню: «Заяви-розрахунки ПФУ» у `menu_ua_payroll_reporting`.

## Документ 4: Авансова відомість (модуль `l10n_ua_payroll_rules`, агент B)

- Модель `ua.advance.sheet`: `year`, `month`, `percent` Float default 50, `pay_date` Date, `line_ids`, `total` Monetary обчислене store, `name` = «Аванс 09.2026».
- Модель `ua.advance.line`: `sheet_id`, `employee_id`, `payslip_id` M2O hr.payslip, `wage` Monetary, `fte` Float «Ставка», `ratio` Float «Частка відпрацьованих днів 1-15», `amount` Monetary «Сума авансу» (редагується), `note` Char.
- Майстер `ua.payroll.advance.wizard` (є) → створює документ з рядками за логікою `action_fill` і `_first_half_ratio` (перенести у документ як `action_refill`; майстер більше не пише в листки). Рядки лише для чернеток листків місяця з видом відносин «трудовий договір», сума > 0.
- `action_confirm`: для кожного рядка записати вхід `ADVANCE` у листок (створити або оновити `hr.payslip.input`, як зараз), `compute_sheet()`, стан confirmed. `action_draft`: видалити входи `ADVANCE` цих листків, `compute_sheet()`, стан draft. Якщо якийсь листок уже не draft → UserError із назвою працівника.
- Звіт QWeb `report_ua_advance_sheet` (новий, `web.basic_layout`, paperformat `l10n_ua_payroll_reports.paperformat_ua_a4`… модуль rules не залежить від reports: тому paperformat не вказувати, або створити звіт у модулі `l10n_ua_payroll_reports`? Рішення: модель і логіка у `l10n_ua_payroll_rules`; звіт і його `ir.actions.report` у `l10n_ua_payroll_reports` (`report/ua_advance_report.xml`), він уже залежить від rules). Колонки: №, ПІБ, оклад, ставка, частка, сума, підпис. Підсумок. Підписи керівника і головного бухгалтера (`company.ua_director_name`, `ua_accountant_name` є лише з модулем reports: у шаблоні використовувати `getattr`? У QWeb `getattr` недоступний: писати `doc.company_id.ua_director_name` можна, бо шаблон живе в модулі reports).
- Меню: «Авансові відомості» у `menu_ua_payroll_calc` після «Аванс за місяць» (файл `l10n_ua_payroll_ui/views/menus_advance.xml`).
- Старий список входів ADVANCE (view `view_hr_payslip_input_advance_list`) прибрати разом із поверненням act_window з майстра.

## Технічні правила

- Odoo 19: `<list>` замість `<tree>`; `hr.version` замість контракту; безпечно читати `slip.contract_id`.
- Оновлення модулів на локальному стенді без перезапуску Odoo: `docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll -u l10n_ua_hr_docs --stop-after-init --log-level=warn"` (агент A: `-u l10n_ua_hr_docs,l10n_ua_payroll_ui`; агент B: `-u l10n_ua_payroll_rules,l10n_ua_payroll_reports,l10n_ua_payroll_ui`). Сервер підхопить новий реєстр сам. Не робити `docker compose restart`. Не чіпати хмару, wrangler, Supabase.
- Агент A працює на базі `payroll`, агент B на базі `payroll_test` (обидві мають усі модулі; для B команда `-d payroll_test`). Це щоб паралельні оновлення не блокували одна одну.
- Перевірка: JSON-RPC на `http://127.0.0.1:8110/jsonrpc`, логін `admin`, пароль з `.env` (`ODOO_ADMIN_USER_PASSWORD`); зразок клієнта у `scripts/review_guide_table.py` (`rpc(service, method, *args)`, результат `d.get("result")`). PDF перевіряти через HTTP-сесію: `/web/session/authenticate` → `/report/pdf/<report_name>/<id>` (зразок у `scripts/demo_company.py` немає; написати 10 рядків з `http.cookiejar`).
- Кожен агент додає скрипт: A `scripts/docs_check.py` (створює табель за 08.2026, штатний на 2026-08-31, заяву для пакета «Зарплата за серпень 2026»; друкує PDF трьох документів; перевіряє: табель ≥ 15 рядків, штатний total_units > 10, заява total > 0, PDF починається з `%PDF`). B `scripts/advance_check.py` на базі `payroll_test`: створює пакет чернеток за 10.2026 (як `month_batch` у `scripts/demo_company.py`, але простіше: листки для працівників з активним контрактом), авансову відомість за 10.2026, затверджує, перевіряє, що у листках з'явився вхід ADVANCE із сумами відомості, повертає в чернетку, перевіряє, що входи зникли; друкує PDF відомості.
- Не змінювати файли OCA у `addons/payroll`, `addons/account_*`, `addons/date_range`, `addons/report_xlsx`.
- Текст інтерфейсу українською, коротко, без пояснень у формах.
- Після завершення: короткий звіт у відповіді: які файли змінені, як перевірено, що не зроблено.
