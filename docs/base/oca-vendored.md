# Модулі OCA у репозиторії

Модулі OCA лежать у `addons/<модуль>` без жодних змін. Комміт вихідного репозиторію
записаний у `addons/OCA_<репозиторій>.commit` - один файл на репозиторій, усі модулі
з нього взяті з того самого комміту. Оновлення = перекопіювати теку з нового комміту
і переписати файл `.commit`. Українські переклади, дописані для upstream, перелічені
в `addons/OCA_translations.md`.

## Таблиця

| Репозиторій | Модуль | Комміт | Для чого | Чи розширюємо |
| --- | --- | --- | --- | --- |
| OCA/payroll | `payroll` | не записано (файл `.commit` відсутній) | рушій розрахунку зарплати: структури, правила, листки | так: `l10n_ua_payroll_rules`, `l10n_ua_changes`, `l10n_ua_home`, `l10n_ua_papers` |
| OCA/account-financial-reporting | `account_financial_report` | 6a7c307a529d47534a68335e39f2730eeff63ab0 | оборотно-сальдова відомість і головна книга | так: `l10n_ua_payroll_ui` |
| OCA/account-financial-tools | `account_usability` | f553f7642ab8ab8b73917bcb5a7361f8a560e0e6 | зручніші меню і фільтри бухгалтерії | так: `l10n_ua_payroll_ui` |
| OCA/account-financial-tools | `account_asset_management` | f553f7642ab8ab8b73917bcb5a7361f8a560e0e6 | основні засоби: картка, амортизація, вибуття | ні |
| OCA/account-financial-tools | `account_lock_date_update` | f553f7642ab8ab8b73917bcb5a7361f8a560e0e6 | зміна дат блокування періоду окремим правом | ні |
| OCA/account-reconcile | `account_reconcile_oca` | 3b98edd114b334e00df1c75df6e4ca91af7b6a2c | екран звірки банку | ні |
| OCA/account-reconcile | `account_statement_base` | 3b98edd114b334e00df1c75df6e4ca91af7b6a2c | база для виписок | ні |
| OCA/bank-statement-import | `account_statement_import_base` | 65316c38d7a5586456bc751d8939b84f1cf0bc2e | база імпорту виписок | ні |
| OCA/bank-statement-import | `account_statement_import_file` | 65316c38d7a5586456bc751d8939b84f1cf0bc2e | імпорт виписки з файлу | так: `l10n_ua_bank_online` |
| OCA/bank-statement-import | `account_statement_import_file_reconcile_oca` | 65316c38d7a5586456bc751d8939b84f1cf0bc2e | звʼязка імпорту зі звіркою | так: `l10n_ua_bank` |
| OCA/bank-statement-import | `account_statement_import_online` | 65316c38d7a5586456bc751d8939b84f1cf0bc2e | тягнути виписку через провайдера | так: `l10n_ua_bank_online` |
| OCA/bank-statement-import | `account_statement_import_sheet_file` | 65316c38d7a5586456bc751d8939b84f1cf0bc2e | імпорт CSV і XLSX виписок | так: `l10n_ua_bank`, `l10n_ua_bank_online` |
| OCA/bank-payment | `account_payment_mode` | 7063666deffc7b92ad17b715479b102b71d1a335 | способи оплати і банківські реквізити для них | так: `l10n_ua_payments` (формат файлу для банку) |
| OCA/bank-payment | `account_payment_order` | 7063666deffc7b92ad17b715479b102b71d1a335 | платіжні доручення пакетом: збір рахунків, підтвердження, вивантаження | так: `l10n_ua_payments` (відомість на перерахування), `l10n_ua_changes` |
| OCA/currency | `currency_rate_update` | 2e53026930455187b7acbe1961ab0b524f29dbd6 | автоматичне підтягування курсів валют за розкладом | ні |
| OCA/mis-builder | `mis_builder` | 7d519f31e1a553d7a5499571a9146f7e3ea49ea4 | конструктор управлінських звітів з рахунків | ні |
| OCA/mis-builder | `mis_builder_budget` | 7d519f31e1a553d7a5499571a9146f7e3ea49ea4 | бюджет як колонка у звіті mis_builder | ні |
| OCA/server-tools | `auditlog` | 8e9ae3a408802c70813d49385af90931787c9d6e | журнал змін по обраних моделях і полях | ні |
| OCA/server-ux | `date_range` | e2f17815d3b872c7b836900159b62028d600e52e | іменовані періоди для звітів | ні |
| OCA/hr | `hr_employee_document` | 37cc00ed8aa56ce492c078463ac221a86afdfc19 | кнопка «Документи» над вкладеннями картки працівника і права доступу до них; своєї моделі документа не має | так: `l10n_ua_hr_card` кладе скани документів саме цими вкладеннями |
| OCA/reporting-engine | `report_xlsx` | b730d603317691d9608a8a3c5710286d9dbc81f1 | друк звітів у XLSX | ні |
| OCA/reporting-engine | `report_xlsx_helper` | b730d603317691d9608a8a3c5710286d9dbc81f1 | допоміжний шар XLSX; потрібен для `account_asset_management` | ні |
| OCA/purchase-workflow | `purchase_request` | fa109e9e58f1bcca94384db8662c1a2f899c4baa | внутрішній запит на закупівлю: стани і погодження, права користувача і керівника запитів, чарівник «запит -> замовлення» | так: `l10n_ua_purchase` (підрозділ, рахунок витрат, ліміт погодження) |
| OCA/multi-company | `account_invoice_inter_company` | 3b39c33f0c62c9ef208d30414a638adc08b54695 | дзеркала рахунків між компаніями однієї бази: продаж у А створює чернетку вхідного рахунку в Б і навпаки | ні: `l10n_ua_group` лише залежить від нього і перевіряє тестами |

## Що свідомо не беремо

- SEPA і pain-модулі з OCA/bank-payment (`account_banking_pain_base`,
  `account_banking_sepa_*`) - українські платежі йдуть не через SEPA.
- `account_payment_partner` - на гілці 19.0 цього модуля немає.
- `account_fiscal_year` з OCA/account-financial-tools - жоден із наших модулів
  його не вимагає.
- `web_responsive` з OCA/web - ставиться без помилок, але переписує ті самі
  шаблони меню застосунків і розділів (`web.NavBar.AppsMenu`,
  `web.NavBar.SectionsMenu`, `web.SectionMenu`), які `l10n_ua_shell` ховає і
  замінює власною лівою смугою, та ще й перевизначає SCSS-змінні форм і списків
  поверх `l10n_ua_card_ui`, `l10n_ua_home`, `l10n_ua_dashboard`. Дві оболонки на
  один екран - беремо нашу.
