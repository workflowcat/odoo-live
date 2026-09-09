# Спека: українські переклади OCA-модулів

Дата: 9 вересня 2026. Автор: Fable. Виконавці: Sonnet-агенти. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`. Не комітити.

## Мета

Бухгалтер бачить англійські меню, поля і назви звітів у модулях OCA. Додати або доповнити файли `i18n/uk.po` у вендорених модулях. Це єдина дозволена зміна в каталогах OCA: лише переклади, жодного коду, XML чи маніфестів. Кожен доданий чи змінений файл записати у `addons/OCA_translations.md` (список «модуль → файл → скільки термінів»), щоб потім віддати upstream.

## Розподіл

- Агент C, база `payroll`: `account_financial_report` (281 термінів, файлу uk.po немає), `account_usability` (26), `report_xlsx` (9), `date_range` (uk.po є, 62 порожні msgstr).
- Агент D, база `payroll_test`: `account_reconcile_oca` (128), `account_statement_base` (23), `account_statement_import_base` (8), `account_statement_import_file` (uk.po є, 17 порожніх), `account_statement_import_sheet_file` (106), `account_statement_import_online` (97), `payroll` (uk.po є, 153 порожні).

## Метод

1. Джерело термінів: `addons/<module>/i18n/<module>.pot`. Новий `uk.po` = копія .pot із заповненим заголовком (`Language: uk_UA`, `Plural-Forms: nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);`, `Content-Type: text/plain; charset=UTF-8`) і перекладеними `msgstr`. Існуючий `uk.po`: заповнити лише порожні `msgstr`, наявні не чіпати.
2. Плейсхолдери лишати як є: `%s`, `%d`, `%(name)s`, `{}`, `{name}`, HTML-теги, `\n`. Не перекладати технічні ідентифікатори (коди, назви полів у фігурних дужках, xml id).
3. Скрипт для генерації писати у `scratchpad` або `/tmp`, не в репозиторій. `polib` і `msgfmt` відсутні: парсити .pot простим парсером (msgid/msgstr, багаторядкові рядки у лапках, `msgid_plural`/`msgstr[n]`).
4. Перевірка синтаксису po: завантаження в Odoo. Команда оновлення для агента C:
   `cd /Users/kit/Codius/odoo-live-payroll && docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll -u account_financial_report,account_usability,report_xlsx,date_range --i18n-overwrite --stop-after-init --log-level=warn 2>&1 | grep -vE 'deprecated|DeprecationWarning|_sql_constraints|http-interface' | tail -20"`.
   Для агента D: `-d payroll_test -u account_reconcile_oca,account_statement_base,account_statement_import_base,account_statement_import_file,account_statement_import_sheet_file,account_statement_import_online,payroll --i18n-overwrite`. Помилки розбору po з'являються у логу як WARNING/ERROR з назвою файлу: виправити всі. Перезапуск Odoo не потрібен і заборонений.
5. Перевірка результату через JSON-RPC (`http://127.0.0.1:8110/jsonrpc`, логін `admin`, пароль `ODOO_ADMIN_USER_PASSWORD` з `.env`, зразок клієнта `scripts/review_guide_table.py`, результат `d.get("result")`), з контекстом `{"lang": "uk_UA"}`: для кожної моделі модуля `fields_get` (attributes string, help, selection) і для меню `ir.ui.menu` `search_read` по `name`; порахувати рядки з латиницею (регулярний вираз `[A-Za-z]{3,}` без кирилиці). Мета: 0 англійських назв полів, меню, кнопок і заголовків звітів у модулях агента. Вивести підсумок «модуль: було N латиницею, стало M».
6. Звіт у відповіді: файли, кількість термінів, підсумок перевірки, що не перекладено і чому.

## Глосарій (обов'язковий, для узгодженості)

Trial Balance = Оборотно-сальдова відомість; General Ledger = Головна книга; Journal Ledger = Журнал проводок; Open Items = Незакриті розрахунки; Aged Partner Balance = Заборгованість за строками; VAT Report = Звіт з ПДВ; Account = Рахунок; Partner = Контрагент; Journal = Журнал; Journal Entry = Проводка; Journal Item = Рядок проводки; Move = Проводка; Debit = Дебет; Credit = Кредит; Balance = Сальдо; Initial Balance = Початкове сальдо; Ending Balance = Кінцеве сальдо; Date Range = Період; Fiscal Year = Фінансовий рік; Report = Звіт; Print = Друк; Export = Експорт; XLSX = XLSX; Hierarchy = Ієрархія; Centralize = Згорнути; Show = Показати; Hide = Сховати; Filter = Фільтр; Analytic = Аналітика; Cost Center = Центр витрат; Bank Statement = Банківська виписка; Statement Line = Рядок виписки; Reconcile = Звірити; Reconciliation = Звірка; Reconciliation Model = Правило звірки; Counterpart = Кореспондуючий рахунок; Write-off = Списання різниці; Manual = Вручну; Suspense Account = Транзитний рахунок; Provider = Провайдер; Online = Онлайн; Import = Імпорт; Mapping = Шаблон імпорту; Delimiter = Роздільник; Encoding = Кодування; Header = Заголовок; Column = Колонка; Amount = Сума; Currency = Валюта; Payslip = Розрахунковий листок; Payslip Batch = Пакет листків; Salary Rule = Правило розрахунку; Salary Rule Category = Категорія правил; Salary Structure = Структура зарплати; Contribution Register = Реєстр внесків; Worked Days = Відпрацьовані дні; Input = Вхід; Other Inputs = Інші входи; Compute Sheet = Розрахувати; Confirm = Підтвердити; Cancel = Скасувати; Refund = Сторнувати; Draft = Чернетка; Waiting = Очікує; Done = Готово; Rejected = Відхилено; Employee = Працівник; Contract = Контракт; Wage = Оклад; Company = Компанія; Sequence = Послідовність; Code = Код; Quantity = Кількість; Rate (%) = Ставка (%); Total = Разом; Note = Примітка.

Стиль: коротко, без дієслівних конструкцій у назвах полів, без крапок у кінці, українська бухгалтерська лексика.
