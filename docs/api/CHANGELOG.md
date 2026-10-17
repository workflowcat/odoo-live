# Зміни договору ядра

Один рядок на кожен ПРИБРАНИЙ або ПЕРЕЙМЕНОВАНИЙ публічний метод чи збережене поле
з `docs/api/inventory.md`. Додавання нового нічого сюди не вимагає: від нового методу
жоден інтерфейс не ламається.

`scripts/contract_check.py` порівнює свіжий опис із тим, що лежить у HEAD. Якщо щось
зникло, а цей файл у робочому дереві не зачеплений - перевірка падає. Тому рядок
пишеться в тому ж коміті, що й сама зміна коду.

Формат рядка:

```
## 2026-09-22
- прибрано `ua.period.close.blockers()` - замість нього `blocker_rows()`, той самий
  перелік з ціллю на записи. UI: замінити виклик, поле `text` лишилось те саме.
```

Кожен рядок каже три речі: що саме зникло, що стало натомість і що робити інтерфейсу.
Без «що робити» рядок марний - UI дізнається про поломку від користувача, а не звідси.

## 2026-10-08 (права доступу після аудиту безпеки)

- прибрано `bp.bridge.call()` - замість нього приватний `bp.bridge._call()`: запит у міст
  іде з системним токеном, тому через RPC його більше не викликати. UI: нічого не робити,
  інтерфейс міст напряму не кликав; ЄДР і KYC і далі йдуть діями `res.partner` і `kyc.case`.

Методи й поля нижче не зникли, але відповідають іншим людям - інтерфейс має чекати
`AccessError` там, де раніше приходили дані:

- `ua.explain.explain(model, res_id, ...)` спершу перевіряє право читати сам запис (листок);
  `ua.explain.trace` напряму читає лише керівник зарплати.
- `ua.change.log`: читають кадри (ділянки «Кадри», «Табель»), розрахунок зарплати (ще й
  «Зарплата») і бухгалтер (усі ділянки); `base.group_user` більше ні. Число непереглянутих
  змін у `ua.period.close.blocker_rows()` лишилось для всіх, хто бачить сторінку «Період».
- `ua.vat.period`, `ua.cash.book*`: пише бухгалтер, читає ще й бухгалтер «лише читання».
  Так само лише бухгалтерія читає `ua.vat.compensation*`, `ua.advance.report*`,
  `ua.fop.income`, `ua.fop.quarter`, `ua.profit.declaration*`, `ua.zvv.allocation*`,
  `ua.cost.calculation*` (ще планувальник виробництва), `ua.bank.connect*`.
- `ua.income.certificate*`: група розрахунку зарплати замість кадровика; листки для довідки
  читаються правами користувача.
- `hr.employee.ua_ensure_leave_allocations()`, `ua_ensure_allocations()`,
  `ua_mil_register_check()`: лише кадровик.
- `res.partner.bp_supplier_status`: зняти «не перевірено» прямим записом може лише керівник
  закупівель або бухгалтер-адміністратор, як і кнопкою.
- усі власні моделі з компанією мають правило компанії: запис чужої компанії не знайти й
  не прочитати, а `ua_compose()` з чужою компанією відповідає помилкою доступу.

## 2026-09-22 (меню більше не відкриває діалог)

Рішення Andrii: пункт меню відкриває сторінку, діалог буває лише разовою дією з
кнопки, а річ із періодом і рядками - документ зі своїм списком. Майстри, що були
входом із меню, прибрані; їхня робота живе в `ua_compose()` документа.

- прибрано `ua.staff.list.wizard.action_create()` - замість нього
  `ua.staff.list.ua_compose(company, year, month, date=None)`, той самий документ,
  одразу заповнений. UI: кликати `ua_compose` на `ua.staff.list`; кнопка списку -
  `action_compose_today()`.
- прибрано `ua.timesheet.wizard.action_create()` - замість нього
  `ua.timesheet.sheet.ua_compose(company, year, month)` (ідемпотентний, повертає
  наявний табель місяця). UI: кнопка списку - `action_compose_month()`.
- прибрано `ua.payroll.advance.wizard.action_fill()` - замість нього
  `ua.advance.sheet.ua_compose(company, year, month)`, далі `write()` на
  `percent`/`pay_date` і `action_refill()`. UI: кнопка списку - `action_compose_month()`.
- прибрано `ua.military.list.wizard.action_create()` і `.action_create_all()` -
  замість них `ua.military.list.ua_compose(company, year, month, date=None, tcc=None,
  variant="all")`; без `tcc` складає по одному списку на кожен ТЦК і повертає всі.
  `ua.military.list.action_create_all_tcc()` лишився без змін. UI: кнопка списку -
  `action_compose_all()`.
- прибрано `ua.military.notice.wizard.action_create()` - замість нього
  `ua.military.notice.ua_compose(company, year, month, date_from=None, date_to=None)`.
  UI: кнопка списку - `action_compose_month()`.
- прибрано `ua.military.reserved.wizard.action_create()` - замість нього наявний
  `ua.military.reserved.ua_compose(company, year, month, date=None)`. UI: кнопка
  списку - `action_compose_today()`.
- прибрано `ua.income.certificate.wizard.action_print()` І модель реєстру
  `ua.income.certificate.register` - замість обох документ `ua.income.certificate`
  (`ua_compose(company, year, month, employee=None, date_from=None, date_to=None)`,
  `action_refill()`, `action_confirm()`, `action_draft()`, `_checks()`, друк
  `l10n_ua_payroll_reports.action_report_ua_income_certificate` тепер на ньому).
  Список довідок і є реєстром. UI: читати `ua.income.certificate`, не `.register`.
- прибрано `ua.hr.doc.pack.wizard.action_print()` - замість нього документ
  `ua.hr.doc.check` (`ua_compose(company, year, month, date=None)`, `action_refill()`,
  `action_confirm()`, `action_draft()`, `matrix()`, `_checks()`); звіт
  `l10n_ua_hr_orders.action_report_ua_hr_doc_pack` тепер на ньому. UI: читати
  `ua.hr.doc.check`, дія меню - `action_ua_hr_doc_check`.
- прибрано `ua.hr.order.register.wizard.action_print()` - журнал реєстрації не став
  окремим документом: це той самий перелік наказів. Замість майстра
  `ua.hr.order.action_print_register()` (друкує вибрані накази, а без вибору - усе,
  що показує список) і звіт `l10n_ua_hr_orders.action_report_ua_hr_order_register`
  на моделі `ua.hr.order`. UI: дія меню - `action_ua_hr_order_register` над
  `ua.hr.order`.
- прибрано `ua.bank.ops.wizard.action_run()` - замість нього прямі виклики
  `ua.bank.ops` (без змін) з кнопок: `account.bank.statement.action_ua_pull()`,
  `.action_ua_pull_all()`, `.action_ua_match_payments()`, `.action_ua_apply_rules()`,
  `account.journal.action_ua_bank_test()`, `.action_ua_bank_provider()`. Єдиний
  параметр (рахунок і місяць) - діалог `ua.bank.pull.action_pull()`. UI: пункту меню
  «Операції банку» більше немає.
- перейменовано `ua.vat.cabinet` -> `ua.vat.period`: модель стала постійною (запис на
  період зі своїм списком), `action_compute()` лишився, додано
  `ua_compose(company, year, month)`, `action_compose_month()` і поле `name`.
  `_ua_cabinet_vals()` -> `_ua_period_vals()`. UI: читати `ua.vat.period`, дія меню -
  `l10n_ua_vat.action_ua_vat_period`.

Регістри `ua.osv.report`, `ua.account.card`, `ua.account.analysis`, `ua.cash.book` і
`ua.depreciation.sheet` теж стали постійними моделями (ті самі поля і `action_compute`,
додано `name`, `action_ask()` і `action_compose()`). Нічого не прибрано: методи і поля
лишилися ті самі, змінилося лише те, що запис тепер переживає сеанс.

## 2026-09-22

- договір заведено. `docs/api/inventory.md` і `docs/api/inventory.json` описують те,
  що є зараз; нічого не прибрано і не перейменовано.

- додано пʼять читань складу і виробництва: `ua.api.warehouse_map()`,
  `stock_glance()`, `floor_packages()`, `product_assembly()`, `inventory_plan()`.
  Нічого не прибрано і не перейменовано - рядок тут лише щоб знайти, коли саме склад
  зайшов у договір; опис у `screens.md`, розділ «Склад і виробництво».
