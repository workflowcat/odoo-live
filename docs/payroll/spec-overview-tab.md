# Спека: вкладка «Огляд» у картці працівника і початковий залишок відпустки

Дата: 9 вересня 2026. Автор: Fable. Виконавці: Sonnet-агенти G і H. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`. Не комітити, не пушити, не чіпати хмару, не перезапускати контейнери стенду (для нового Python-коду використовуйте `odoo shell` або тимчасовий `docker run --rm` з тим самим образом і томом addons).

Мета: одна вкладка відповідає на питання «хто ця людина і що з нею зараз» без переходів. Лише стандартні засоби Odoo: стат-кнопки, `widget="badge"`, групи полів, вбудовані списки. Жодного власного CSS, JS чи OWL. Макет узгоджений з Kit 9 вересня 2026.

## Агент G: вкладка «Огляд» (модуль `l10n_ua_hr_card`, база `payroll`)

1. Залежності модуля: додати `l10n_ua_military` до `depends` (щоб показувати службу в огляді; циклу немає, `l10n_ua_payroll_ui` залежить від обох).
2. Нові обчислені поля на `hr.employee` (усі `groups="hr.group_hr_user"`, `compute`, без store, крім позначених):
   - `ua_days_in_company` Integer «Днів у компанії» (сума днів усіх періодів контракту, дублікати дат не рахувати двічі; активний період рахувати до сьогодні).
   - `ua_first_hire_date` Date «Прийнято вперше» (найраніша `contract_date_start`), store=True.
   - `ua_current_wage` Monetary «Поточний оклад» (з поточної версії, `currency_id` компанії).
   - `ua_docs_count` Integer «Документів» (кількість `ua_document_ids`).
   - `ua_overview_alert_count` Integer «Потребує уваги»: рахує ознаки: документ спливає за 30 днів або прострочений; немає РНОКПП; немає документа особи; військовозобов'язаний без звірки понад 12 місяців або без дати; залишок відпустки > 60 днів.
3. Стат-кнопки у `button_box` (стандартний вигляд `o_stat_info`, великі числа): «Оклад» (`ua_current_wage`), «Стаж, років» (`ua_insurance_years`), «Залишок відпустки» (`ua_vacation_balance`), «Документи» (`ua_docs_count`, відкриває список документів, дія вже є), «У компанії, днів» (`ua_days_in_company`). Кнопка «Потребує уваги» показується лише коли `ua_overview_alert_count > 0`, клас `oe_stat_button`, іконка `fa-exclamation-triangle`, відкриває вкладку огляду (дія не обов'язкова, можна без `name`).
4. Нова перша вкладка `name="ua_overview"` string «Огляд» (перед «Робота»):
   - Група «Стан» у два стовпці: `ua_contract_kind`, `ua_main_job`, `ua_fte`, `ua_esv_category`, `ua_psp`, `ua_disability_group`; військова частина: `ua_mil_status`, `ua_mil_rank`, `ua_mil_fitness`, `ua_mil_reserved`, `ua_mil_last_check`. Для полів вибору використати `widget="badge"` там, де це читабельно (`ua_contract_kind`, `ua_mil_status`, `ua_mil_fitness`), решта звичайні, усі `readonly="1"`.
   - Група «Ідентифікація»: `ua_rnokpp`, `birthday`, `ua_id_doc_type`, `ua_id_doc_number`, `ua_id_doc_unzr`, `private_city`, `ua_actual_address`, `private_phone` (readonly, значення редагуються у своїх вкладках).
   - Група «Документи» на всю ширину: `ua_document_ids` списком (readonly, `create="false"`), колонки: тип, назва, номер, дата, «дійсний до»; `decoration-danger="valid_until and valid_until &lt; current_date"`, `decoration-warning="valid_until and valid_until &lt; (current_date + relativedelta(days=30))"`. Якщо `decoration` з `relativedelta` не працює у списку, додати обчислене поле рядка `ua_doc_state` Selection (діє / спливає / прострочений) і фарбувати за ним.
   - Група «Хроніка» на всю ширину: `version_ids` списком (readonly, `create="false"`), колонки: `contract_date_start`, `contract_date_end`, `job_title`, `wage`, `ua_order_ref`; сортування за датою початку. Поруч список `ua_mil_event_ids` (дата, вид, примітка), readonly.
   - Група «Дії»: кнопки-звіти в заголовку сторінки не потрібні; друк лишається у стандартному меню «Друк».
5. Вкладку «Персональний» (`personal_information`) і «Сертифікації», якщо вони не потрібні бухгалтеру, лишити як є: не ховати додатково (Kit не просив).
6. Демо-дані не змінювати. Перевірка: розширити `scripts/card_check.py`: форма містить сторінку `ua_overview` першою; для 3 працівників `ua_days_in_company > 0`, `ua_docs_count >= 1`; у Ткачука `ua_overview_alert_count >= 1`; `get_views` без помилок; П-2 PDF далі працює.

## Агент H: початковий залишок відпустки (модуль `l10n_ua_payroll_rules`, база `payroll_test`)

Проблема: `ua_vacation_accrued` рахується від дати прийняття і не знає про відпустки, використані до впровадження системи. У Ткачука виходить 127,7 дня.

1. Нові поля на `hr.employee` (`groups="hr.group_hr_user"`): `ua_vacation_opening_balance` Float «Залишок на дату впровадження» (default 0), `ua_vacation_opening_date` Date «Дата впровадження обліку відпусток» (help: «Накопичення рахується з цієї дати; до неї береться залишок вручну»).
2. `_compute_ua_vacation_balance` переписати: якщо `ua_vacation_opening_date` заповнена, накопичення рахувати з максимуму (дата впровадження, дата початку періоду контракту), а використані дні брати лише з відпусток і компенсацій після дати впровадження; `ua_vacation_balance = ua_vacation_opening_balance + accrued - used`. Якщо дата не заповнена, поведінка як зараз.
3. Компанія: поле `ua_vacation_opening_date` на `res.company` «Дата впровадження обліку відпусток» і використання його як типового значення для працівників, у яких своя дата порожня (через `_compute` або `default`, на ваш вибір; простіше читати з компанії в обчисленні).
4. Вид: у вкладці «Зарплата» група «Відпустка» доповнюється двома новими полями; на формі компанії поле поруч із наявними полями зарплати (`l10n_ua_payroll_account` має сторінку «Зарплата (проводки)»; додайте своє поле у власному наслідуванні виду компанії в модулі rules).
5. Скрипт `scripts/vacation_check.py` (база з `PAYROLL_DB`, типово `payroll`): встановлює компанії дату впровадження 2026-01-01, кільком працівникам початкові залишки, перевіряє: у працівника з датою прийняття 2021 накопичення рахується лише з 2026-01-01; залишок = початковий + накопичене − використане; без дати впровадження поведінка стара.
6. Демо: у `scripts/demo_company.py` не чіпати нічого, крім додавання дати впровадження компанії 2026-01-01 і початкових залишків для працівників, прийнятих до 2026 (правдоподібно 3-12 днів). Робіть це окремою функцією в кінці скрипта, ідемпотентно.

## Спільні правила

- Odoo 19: `<list>`, `hr.version`, `widget="badge"`, `decoration-*`; `position="move"` лише для прямого нащадка вузла-специфікації; `@string` в xpath заборонено.
- Оновлення модуля: `docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d <база> -u <модуль> --stop-after-init --log-level=warn 2>&1 | grep -vE 'deprecated|DeprecationWarning|_sql_constraints|http-interface' | tail -20"`.
- JSON-RPC: зразок `scripts/card_check.py`; PDF по HTTP лише для бази `payroll`.
- Українська мова, короткі назви, без пояснень у формах.
- Звіт: файли, вивід перевірок, що не зроблено.
