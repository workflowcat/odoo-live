# Робочі процеси: які виклики робить екран

Протокол, вхід і спільні форми даних - у `README.md`. Тут - що саме викликає екран у
кожному процесі продукту, у порядку, і які відповіді на це приходять. Вісім процесів
бек-офісу (зарплата, кадри, звітність, бухоблік) і десять екранів складу й виробництва.

Відповіді процесів 1-8 зняті з ЖИВОЇ демо-бази (`scripts/demo_server.sh`, порт 8131,
база `demo`, компанія «ТОВ «Ясен Меблі»», вересень 2026) через `POST /jsonrpc`. Вони
обрізані до показових полів - там, де обрізано, стоїть `…`. Числа справжні і
відповідають стану демо на 2026-09-22; якщо демо перезібрати, зміняться числа, але не
форма. Звідки взято відповіді складського розділу - сказано на його початку окремо.

Скорочення нижче: `call(модель, метод, аргументи)` означає

```
POST /jsonrpc
{"jsonrpc":"2.0","method":"call","params":{"service":"object","method":"execute_kw",
 "args":["demo", <uid>, "<ключ>", "<модель>", "<метод>", [<аргументи>], {}]}}
```

---

## 1. Місяць зарплати

Головний екран бухгалтера: де зараз місяць, що заважає його закрити, скільки
нараховано, які документи вже є.

**Читання - один виклик.**

```
call("ua.api", "month_summary", [1, 2026, 9])
```

```json
{
  "company": {"id": 1, "name": "ТОВ «Ясен Меблі»"},
  "period": {
    "year": 2026, "month": 9, "label": "Вересень 2026",
    "closed": false, "hard": false, "closed_by": "", "closed_date": "",
    "periods": [
      {"year": 2026, "month": 4, "label": "Квітень 2026", "current": false, "closed": false},
      {"year": 2026, "month": 7, "label": "Липень 2026", "current": false, "closed": true},
      {"year": 2026, "month": 9, "label": "Вересень 2026", "current": true,  "closed": false}
    ]
  },
  "blockers": [
    {"key": "changes", "text": "непереглянутих змін у журналі: 247",
     "short": "непереглянутих змін: 247",
     "plan": "У журналі змін 247 непереглянутих рядків - спершу прийміть їх.",
     "target": {"model": "ua.change.log",
                "domain": [["company_id","=",1],["year","=",2026],["month","=",9],["state","=","new"]]}},
    {"key": "payslips", "text": "непроведених листків: 20", "short": "непроведених листків: 20",
     "plan": "Непроведених листків: 20.",
     "target": {"model": "hr.payslip", "domain": [["id","in",[59,58,57,"…"]]]}}
  ],
  "plan": [
    {"text": "Дата блокування обліку стане 30.09.2026: проводки й листки з датою до цього дня більше не можна буде створити, провести чи змінити.", "level": "info"},
    {"text": "У журналі змін 247 непереглянутих рядків - спершу прийміть їх.", "level": "crit",
     "target": {"model": "ua.change.log", "domain": ["…"]}},
    {"text": "Непроведених листків: 20.", "level": "crit", "target": {"model": "hr.payslip", "domain": ["…"]}}
  ],
  "payslips": {
    "count": 20, "draft": 20, "done": 0, "cancel": 0,
    "totals": {"GROSS": 654154.19, "PDFO": -109948.72, "VZ": -30707.72,
               "ESV": 129179.57, "NET": 510032.75, "ADV_PAID": 0.0},
    "target": {"model": "hr.payslip",
               "domain": [["company_id","=",1],["date_from",">=","2026-09-01"],["date_from","<=","2026-09-30"]],
               "name": "Вересень 2026"}
  },
  "documents": ["… див. процес 3 …"]
}
```

**Дії місяця** (кожна пише, тому лише у відповідь на натискання):

| Кнопка | Виклик |
| --- | --- |
| Підготувати місяць (табель, листки, розрахунок) | `call("hr.payslip.run", "ua_prepare_month", [1, 2026, 9])` |
| Прийняти всі зміни журналу | `call("ua.change.log", "accept_period", [2026, 9])` |
| Відкрити картку закриття | `call("ua.period.close", "ensure_for", [1, 2026, 9])` -> id запису |
| Закрити місяць | `call("ua.period.close", "close_period", [2026, 9, false])` |

`close_period` із незнятими перешкодами кидає `UserError` із їхнім переліком - той
самий текст, що вже прийшов у `blockers`. Показуйте його як є.

Перемикання місяця у смузі - це просто новий `month_summary` з іншими `year`/`month`.

---

## 2. Листки

Перелік листків місяця, форма одного листка і відповідь на питання «звідки це число».

```
call("hr.payslip", "search_read",
     [[["company_id","=",1],["date_from",">=","2026-09-01"]],
      ["number","employee_id","state","date_from","date_to"]])
```

```json
[{"id": 59, "number": "SLIP/059", "employee_id": [22, "Мельник Ірина Володимирівна"],
  "state": "verify", "date_from": "2026-09-01", "date_to": "2026-09-30"}]
```

Рядки листка - звичайний `search_read` дочірньої моделі:

```
call("hr.payslip.line", "search_read", [[["slip_id","=",59]], ["code","name","total"]])
```

```json
[{"code": "BASIC",  "name": "Оклад",                            "total": 32000.0},
 {"code": "GROSS",  "name": "Усього нараховано",                "total": 32000.0},
 {"code": "PDFO",   "name": "ПДФО 18 %",                        "total": -5760.0},
 {"code": "VZ",     "name": "Військовий збір 5 %",              "total": -1600.0},
 {"code": "NET",    "name": "До виплати",                       "total": 24640.0},
 {"code": "ESV",    "name": "ЄСВ 22 % за рахунок підприємства",  "total": 7040.0}]
```

**«Звідки це число».** Одна точка входу на весь продукт:

```
call("ua.explain", "explain", ["hr.payslip", 59, "PDFO"])
```

```json
{
  "version": "1",
  "state": "preview",
  "frozen": false,
  "note": "Заморожений слід відсутній: запис або ще не проведено, або його провели до того, як слід почали зберігати. …",
  "subject": {"model": "hr.payslip", "res_id": 59,
              "label": "Розрахунковий листок: Мельник Ірина Володимирівна, вересень 2026",
              "employee": {"id": 22, "name": "Мельник Ірина Володимирівна"}, "period": "2026-09"},
  "params": {
    "esv_rate": {"value": 22.0, "name": "ЄСВ, %", "valid_from": "2026-01-01",
                 "source": "ч. 5 ст. 8 ЗУ про ЄСВ"}
  },
  "steps": [
    {"code": "BASIC", "label": "Оклад", "category": "BASIC",
     "expression": "result = tools.r2(contract.wage * payroll.ua.fte * payroll.ua.time_ratio, 2)",
     "note": "Основна зарплата за оклад. …",
     "reads": ["time_ratio", "fte"], "values": {"time_ratio": 1.0, "fte": 1.0},
     "output": 32000.0, "uses_rules": []},
    {"code": "GROSS", "label": "Усього нараховано",
     "expression": "result = tools.r2(categories.BASIC + categories.ALW + categories.AVG, 2)",
     "output": 32000.0, "uses_rules": ["BASIC"]}
  ]
}
```

`state: "preview"` і `frozen: false` означають «перерахунок за сьогоднішніми
правилами», а не «так було тоді». Показуйте `note` поруч із числами; підміняти
його власним «розрахунок на момент проведення» не можна.

Дії листка: `action_payslip_done`, `action_payslip_cancel`, `action_open_move`,
`compute_sheet` - усе з `inventory.md`, розділ `hr.payslip`.

---

## 3. Документи за місяць

Вісім видів документів місяця з їхніми перевірками. Порядок і склад сталі: вид без
запису теж приходить, із `present: false`.

```
call("ua.api", "documents_for_month", [1, 2026, 9])
```

```json
[
  {"kind": "timesheet", "label": "Табель", "model": "ua.timesheet.sheet", "present": true,
   "records": [{
     "id": 1, "name": "Табель 09.2026", "state": "confirmed", "state_label": "Затверджено",
     "level": "error", "errors": 1, "warns": 1,
     "checks": [
       {"level": "error", "text": "Немає рядка табеля для працівника з активним трудовим договором",
        "fact": "1", "target": {"model": "hr.employee", "domain": [["id","in",[23]]]}},
       {"level": "warn",  "text": "Затверджена відсутність не відображена в днях табеля",
        "fact": "4", "target": {"model": "hr.employee", "domain": [["id","in",[5,8,14,15]]]}},
       {"level": "ok",    "text": "Стан документа", "fact": "Затверджено", "target": false}
     ],
     "target": {"model": "ua.timesheet.sheet", "res_id": 1}}],
   "target": {"model": "ua.timesheet.sheet",
              "domain": [["company_id","=",1],["year","=",2026],["month","=",9]], "name": "Табель"}},

  {"kind": "advance_sheet", "label": "Авансова відомість", "model": "ua.advance.sheet",
   "present": false, "records": [],
   "target": {"model": "ua.advance.sheet", "domain": ["…"], "name": "Авансова відомість"}}
]
```

Стан демо на вересень 2026: є `timesheet`, `staff_list`, `payment_order`,
`military_list` (2 записи), `military_notice` (2), `military_reserved`; немає
`advance_sheet` і `pfu_claim`.

**Створення документа - окрема дія, не читання.** `documents_for_month()` порожній
документ не заводить. Кнопка «створити за місяць» кличе `ua_compose` тієї моделі:

```
call("ua.advance.sheet", "ua_compose", [1, 2026, 9])
call("ua.timesheet.sheet", "ua_compose", [1, 2026, 9])
```

далі `action_refill()`, `action_confirm()`, `action_draft()` на створеному записі.

Ті самі перевірки доступні звичайним читанням поля - коли екрану потрібен лише текст:

```
call("ua.timesheet.sheet", "search_read", [[["year","=",2026]], ["name","state","checks_text"]])
```

```json
[{"id": 1, "name": "Табель 09.2026", "state": "confirmed",
  "checks_text": "ПОМИЛКА: Немає рядка табеля для працівника з активним трудовим договором (1)\nУВАГА: Затверджена відсутність не відображена в днях табеля (4)\nOK: Стан документа (Затверджено)"}]
```

---

## 4. Картка працівника

```
call("ua.api", "employee_card", [12])
```

```json
{
  "employee": {"id": 12, "name": "Бойчук Соломія Андріївна", "active": true,
               "job_title": "Фахівець з маркетингу", "department_id": [4, "Відділ продажу"],
               "company_id": [1, "ТОВ «Ясен Меблі»"], "work_email": "boichuk@yasen-mebli.example",
               "work_phone": "+380 32 245 10 20", "employee_type": "employee"},
  "tabs": {
    "person":  {"ua_rnokpp": "…", "ua_id_doc_type": "id_card", "birthday": "…", "marital": "…",
                "ua_veteran": false, "ua_single_parent": false, "…": "…"},
    "pay":     {"ua_current_wage": 10000.0, "ua_contract_kind": "employment", "ua_main_job": false,
                "ua_fte": "0.5", "ua_esv_category": "standard", "ua_psp": "none",
                "ua_psp_children": 0, "ua_insurance_years": 9.0, "ua_sick_percent": 100.0,
                "ua_index_off": false, "ua_index_base_effective": "2026-07-01"},
    "vacation":{"ua_vacation_days_year": 24, "ua_vacation_accrued": 17.4, "ua_vacation_used": 0.0,
                "ua_vacation_balance": 26.4, "ua_vacation_opening_balance": 9.0,
                "ua_vacation_opening_date": false, "ua_vac_ubd_balance": 0.0,
                "ua_soc_child_balance": 0.0, "ua_special_balance": 0.0},
    "military":{"ua_mil_status": "liable", "ua_mil_women_list": true, "ua_mil_category": "ranks",
                "ua_mil_tcc": "Львівський районний ТЦК та СП", "ua_mil_doc_type": "ticket",
                "ua_mil_reserved": false, "ua_mil_needs_check": true, "…": "…"},
    "overview":{"ua_days_in_company": 1087, "ua_first_hire_date": "2023-10-02",
                "ua_docs_count": 3, "ua_docs_expiring": 0, "ua_overview_alert_count": 1}
  },
  "children": [],
  "version": {"id": 12, "contract_date_start": "2023-10-02", "contract_date_end": false,
              "wage": 10000.0, "job_title": "Фахівець з маркетингу",
              "department_id": [4, "Відділ продажу"], "ua_kp_code": "2419.2",
              "ua_prof_name": "Фахівець з маркетингу", "ua_internal_parttime": false,
              "ua_order_ref": "Наказ № 22-к від 02.10.2023", "ua_pay_type": "monthly",
              "ua_weekly_hours": 40.0, "ua_night_shifts": false},
  "documents": [
    {"id": 67, "name": "Паспорт громадянина України", "type": "passport", "number": "…",
     "date": "2019-07-10", "valid_until": false, "ua_doc_state": "ok", "state": "not_needed",
     "signed_date": false, "attachment_id": false, "note": false},
    {"id": 68, "name": "Диплом, 2013 р.", "type": "diploma", "date": "2013-07-01",
     "ua_doc_state": "ok", "state": "not_needed", "…": "…"}
  ],
  "orders": [],
  "leaves": {
    "allocations": [{"id": 170, "holiday_status_id": [74, "Щорічна відпустка"],
                     "number_of_days": 9.0, "date_from": "2026-01-01", "date_to": false,
                     "state": "validate"}],
    "requests":    [{"id": 10, "holiday_status_id": [76, "Відпустка без збереження зарплати"],
                     "request_date_from": "2026-09-21", "request_date_to": "2026-09-22",
                     "number_of_days": 2.0, "state": "confirm"}]
  },
  "alerts": {"count": 1, "docs_expiring": 0, "military_needs_check": true,
             "items": [{"level": "warn", "text": "Військовий облік: потрібна звірка даних"}]},
  "targets": {"form": {"model": "hr.employee", "res_id": 12},
              "documents": {"model": "ua.employee.document",
                            "domain": [["employee_id","=",12]], "name": "Документи"},
              "orders": {"model": "ua.hr.order",
                         "domain": [["employee_id","=",12]], "name": "Накази"}}
}
```

Особові поля лежать під `groups="hr.group_hr_user"`. Користувач без цієї групи дістає
`AccessError`, а не картку з порожніми значеннями - `ua.api` навмисно не робить
`sudo()`. Порожній `tabs.person` ніколи не означає «немає прав».

Дії картки: `hr.employee.action_view_ua_documents`, `action_ua_print_last_order`,
`ua_mil_register_check`, `ua.employee.document.action_mark_signed` / `action_print`,
`hr.employee.ua_ensure_leave_allocations`.

---

## 5. Накази і прийняття

**Накази** (`ua.hr.order`) - один журнал на всі види: прийняття, переведення,
відпустка, відрядження, звільнення.

```
call("ua.hr.order", "search_read",
     [[["state","=","posted"]],
      ["name","order_type","register","date","state","employee_id","job_title","wage"]])
```

```json
[{"id": 8, "name": "8-в", "order_type": "trip", "register": "v2", "date": "2026-09-25",
  "state": "posted", "employee_id": [5, "Дзюба Ярослав Михайлович"], "job_title": false, "wage": 0.0},
 {"id": 7, "name": "7-в", "order_type": "leave", "register": "v2", "date": "2026-09-22",
  "state": "posted", "employee_id": [14, "Федорів Ірина Василівна"], "job_title": false, "wage": 0.0}]
```

Дії наказу: `action_post` (проводить і створює наслідки - версію контракту, відпустку,
вхід у листок), `action_cancel`, `action_acknowledge`, а також переходи до наслідків:
`action_ua_open_version`, `action_ua_open_leave`, `action_ua_open_slips`,
`action_ua_open_payments`.

**Прийняття** (`ua.hire.case`) - справа кандидата від анкети до наказу.

```
call("ua.hire.case", "search_read", [[], ["name","stage","job_title","department_id","phone"]])
```

```json
[{"id": 4, "name": "Гриценко Павло", "stage": "declined", "job_title": "Водій",
  "department_id": false, "phone": "+380 67 111 22 33"},
 {"id": 3, "name": "Мельник Ірина", "stage": "hired", "job_title": "Менеджерка з персоналу",
  "department_id": [1, "Administration"]}]
```

Порядок дій екрана прийняття:

| Крок | Виклик |
| --- | --- |
| Завести справу | `call("ua.hire.case", "create_case", [{"last_name": "…", "first_name": "…"}])` |
| Додати файл анкети | `call("ua.hire.case", "add_file", [id, "<ім'я>", "<base64>"])` |
| Витягнути поля з файлів | `call("ua.hire.case", "action_extract", [[id]])`, стан - `extract_status` |
| Показати план прийняття | `call("ua.hire.case", "action_hire_plan", [[id]])` |
| Прийняти | `call("ua.hire.case", "action_hire", [[id]])` - створює працівника, версію і наказ |
| Відмовити | `call("ua.hire.case", "action_decline", [[id]])` |

`action_hire_plan` - читання: показує, що станеться, і чого бракує. `action_hire` -
дія, і лише після неї з'являються записи.

---

## 6. Виплати і банк

**Відомість на перерахування** (`account.payment.order` з нашими полями) - місячна
виплата одним документом, зі своїми перевірками.

```
call("account.payment.order", "search_read",
     [[["ua_year","=",2026]],
      ["name","state","ua_label","ua_kind","ua_pay_date","ua_line_count",
       "ua_without_account","checks_text"]])
```

```json
[{"id": 3, "name": "PAY0003", "state": "uploaded", "ua_label": "Заробітна плата 08.2026",
  "ua_kind": "salary", "ua_pay_date": "2026-09-04", "ua_line_count": 21, "ua_without_account": 0,
  "checks_text": "OK: Усі рядки мають IBAN\nOK: Сума відомості збігається з листками місяця (334976.83)\nOK: Платежі проведені (21)\nOK: Стан документа (Оплачено)"},
 {"id": 2, "name": "PAY0002", "state": "draft", "ua_label": "Інша виплата 09.2026",
  "ua_kind": "other", "ua_pay_date": "2026-09-25", "ua_line_count": 0, "ua_without_account": 0,
  "checks_text": "ПОМИЛКА: Немає рядків відомості"}]
```

Клікабельні перевірки того самого документа приходять у `documents_for_month()`
під `kind: "payment_order"` - із `target` на кожен рядок.

Порядок дій: `ua_compose(company, year, month, kind)` -> `action_fill()` ->
`action_confirm()` -> `action_export()` (файл для банку) -> `action_paid()`.
Відкат - `action_draft()`, `action_cancel()`.

**Банк.** Виписка - стандартні моделі Odoo:

```
call("account.bank.statement.line", "search_read",
     [[], ["date","payment_ref","amount","is_reconciled"]])
```

```json
[{"id": 66, "date": "2026-09-18", "payment_ref": "Оплата постачальнику за BILL/2026/09/0002",
  "amount": -57780.0, "is_reconciled": true},
 {"id": 55, "date": "2026-09-18", "payment_ref": "Комісія за еквайринг",
  "amount": -265.86, "is_reconciled": false}]
```

Рядок виписки відкривається лише через `ua.screen.open_target({"model":
"account.bank.statement.line", "res_id": 66})`: ядро саме підставляє подання звірки.
Пряма форма рядка показує порожнечу - звіряти в ній нічим.

Робоче місце банку (`ua.bank.ops`): `action_pull_month`, `action_pull_all`,
`action_apply_rules`, `action_match_payments`, `action_test`, `action_open_providers`.

Календар виплат місяця: `call("ua.payments.plan", "month_rows", [1, 2026, 9])` -
рядки `{date, label, amount, state, state_class, target}`.

---

## 7. Звітність ДПС

```
call("ua.api", "reporting_status", [1, 2026, 9])
```

```json
{
  "company": {"id": 1, "name": "ТОВ «Ясен Меблі»"}, "year": 2026, "month": 9,
  "reports": [
    {"code": "j05", "label": "Об'єднана звітність (J0500111 + Д1 + 4ДФ + Д5)",
     "period_type": "month", "run_id": false, "name": "", "state": "", "state_label": "",
     "doc_kind": "", "submitted_date": false,
     "checks": {"ok": 0, "warn": 0, "error": 0, "rows": []},
     "files": [], "receipts": [],
     "target": {"model": "ua.report.run",
                "domain": [["company_id","=",1],["year","=",2026],["report_code","=","j05"],
                           ["month","in",[9,false]]],
                "name": "Об'єднана звітність (J0500111 + Д1 + 4ДФ + Д5)"}},

    {"code": "j30", "label": "Повідомлення про прийняття (J3001005)", "period_type": "month",
     "run_id": 1, "name": "Повідомлення про прийняття (J3001005), Вересень 2026",
     "state": "draft", "state_label": "Чернетка", "doc_kind": "Звітний", "submitted_date": false,
     "checks": {"ok": 2, "warn": 1, "error": 2, "rows": [
       {"level": "error", "code": "period_closed", "title": "Чернетки листків у періоді",
        "detail": "Проведених листків у періоді немає", "value": "20",
        "target": {"model": "hr.payslip",
                   "domain": [["company_id","=",1],["date_from",">=","2026-09-01"],
                              ["date_from","<=","2026-09-30"],["state","in",["draft","verify"]]]}},
       {"level": "error", "code": "rnokpp", "title": "Усі РНОКПП заповнені і мають 10 цифр",
        "detail": "Без коректного РНОКПП: Administrator", "value": "1",
        "target": {"model": "hr.employee", "domain": [["id","in",[1]]]}},
       {"level": "ok", "code": "company_signers",
        "title": "Компанія має ЄДРПОУ, код ДПІ і підписантів", "detail": "Заповнено",
        "value": "", "target": {"model": "res.company", "res_id": 1}}
     ]},
     "files": [], "receipts": [],
     "target": {"model": "ua.report.run", "res_id": 1}}
  ]
}
```

`run_id: false` означає «прогону ще немає». `reporting_status()` його не заводить -
це читання. Заводить окремий виклик:

```
call("ua.report.run", "ensure_run", ["j05", 2026, false, 9])   -> id прогону
```

Далі дії прогону: `action_refresh()` (перерахувати перевірки), `action_generate()`
(сформувати XML у `attachment_ids`), `action_mark_submitted()`, `action_reset()`,
`action_create_correction()` (звітний новий або уточнюючий).

Готові файли забираються звичайним `ir.attachment.read(["name","datas"])` за
ідентифікаторами з `files`; квитанції ДПС лежать у `receipts`.

---

## 8. ПДВ і бухоблік

**Податкові документи** (`ua.vat.document`) - податкові накладні і розрахунки
коригування над проводками:

```
call("ua.vat.document", "search_read",
     [[], ["name","doc_kind","state","date","move_id","partner_id"]])
```

```json
[{"id": 3, "name": "Податкова накладна INV/2026/00013", "doc_kind": "tax_invoice",
  "state": "draft", "date": "2026-09-21",
  "move_id": [209, "INV/2026/00013 (ЗМ-2026-13)"],
  "partner_id": [33, "ТОВ «Інтер'єр Плюс»"]}]
```

Дії: `account.move.action_ua_create_tax_invoice`, `action_ua_close_first_events`,
`action_ua_post_customs_vat`; на самому документі - `action_export_xml`,
`action_mark_pn_registered`. Розподіл вхідного ПДВ - `ua.vat.compensation`
(`action_compute`, `action_post`, `action_annual_recalc`).

**Первинні документи і проводки** - стандартний Odoo:

```
call("account.move", "search_read",
     [[["move_type","in",["out_invoice","in_invoice"]]],
      ["name","move_type","state","invoice_date","amount_total","amount_tax","partner_id"]])
```

```json
[{"id": 209, "name": "INV/2026/00013", "move_type": "out_invoice", "state": "posted",
  "invoice_date": "2026-09-21", "amount_total": 68400.0, "amount_tax": 11400.0,
  "partner_id": [33, "ТОВ «Інтер'єр Плюс»"]},
 {"id": 153, "name": "BILL/2026/09/0005", "move_type": "in_invoice", "state": "posted",
  "invoice_date": "2026-09-30", "amount_total": 31080.0,
  "partner_id": [51, "ТОВ «Транс Лоджистик»"]}]
```

Облікові звіти рахуються своїми моделями і віддають файл:
`ua.osv.report`, `ua.account.card`, `ua.account.analysis` - у кожної
`action_compute()` і `action_print_xlsx()`. Каса - `ua.cash.book.action_compute` /
`action_print`, авансовий звіт - `ua.advance.report` (`action_confirm`,
`action_settle_balance`, `action_print`). Фінзвітність - `mis.report.instance`
(`action_ua_finrep_xml_draft` - стара чернетка, не для подання); файл для ДПС -
`ua.finrep.filing` (`action_compute`, `action_check`, `action_xml`, `action_done`).

---

## Склад і виробництво

Десять екранів складського клієнта поза Odoo. Шість читань `ua.api` складають те, що
клієнт раніше збирав із пʼяти-восьми викликів `search_read` і власної таблички
місткостей у файлі поруч із кодом; решта - нативні моделі `stock` і `mrp`, бо свого
там нічого й не треба.

**Звідки тут числа.** Відповіді цього розділу зняті ЖИВИМИ зі стенду (порт 8130, база
`payroll`, компанія «ТОВ «Ясен Меблі»») 2026-09-22 через `POST /jsonrpc`. На стенді
склад порожній: жодного товару, залишку, специфікації, приймання й опису
інвентаризації, а склад - одна локація `WH/Запаси` без заданої місткості. Тому живий
приклад показує справжню форму відповіді з порожніми переліками, а склад заповненого
рядка йде поруч під підписом **форма рядка** - це договір, а не жива відповідь. Коли
склад наповнять, зміняться числа, форма не зміниться. Перевірено на демо-даних у
тестах з тегом `ua_api` (`addons/l10n_ua_payroll_tests/tests/test_api.py`,
`TestUaApiStock`): там ті самі поля рахуються на справжніх полицях і специфікаціях.

**Вхід.** Складський клієнт ходить `/json/2` з `Authorization: Bearer <ключ>`
службового користувача `sklad_api` (`python3 scripts/api_key.py --db payroll`). Ключ
успадковує групи `stock.group_stock_user` і `mrp.group_mrp_user`; бухгалтерських у
нього немає. Сеансова кука лишається потрібною лише для PDF (`/report/pdf/...`).

---

### Карта

Коробка на зону і полицю: скільки місць є, скільки зайнято, де переповнення.

```
call("ua.api", "warehouse_map", [1])
```

```json
{
  "company": {"id": 1, "name": "ТОВ «Ясен Меблі»"},
  "sizes": {"s": 1, "m": 4, "l": 16, "default": "s"},
  "roots": [5],
  "locations": [
    {"id": 5, "name": "Запаси", "path": "WH/Запаси", "parent_id": [4, "WH"], "level": 0,
     "capacity": 0, "used": 0, "own": 0, "free": false, "overflow": false, "fill": false,
     "floor": false, "purpose": false, "purpose_label": "", "plan": false, "items": [],
     "target": {"model": "stock.quant",
                "domain": [["location_id","=",5],["quantity",">",0]], "name": "WH/Запаси"}}
  ]
}
```

Форма рядка полиці з вмістом:

```json
{"id": 14, "name": "Полиця М2", "path": "WH/Запаси/Полиця М2", "parent_id": [5, "WH/Запаси"],
 "level": 1, "capacity": 2, "used": 48, "own": 48, "free": 0, "overflow": true, "fill": 999.0,
 "floor": false, "purpose": "storage", "purpose_label": "Зберігання",
 "plan": {"x": 8, "y": 1, "w": 5, "h": 3},
 "items": [{"product": [7, "Рама карбон"], "code": "RM-7", "category": [4, "Комплектуючі"],
            "quantity": 3.0, "reserved": 0.0, "uom": "Units",
            "size": "l", "size_label": "L - велике", "slots": 48.0}],
 "target": {"model": "stock.quant", "domain": ["…"], "name": "WH/Запаси/Полиця М2"}}
```

- `used` - `stock.location.ua_capacity_used`: зайнято місць РАЗОМ З ДОЧІРНІМИ;
  `own` - те саме без дочірніх. Полиця з підлогою покаже `used` більший за `own`.
- `capacity` 0 означає «місткості не задано»: тоді `free` і `fill` - `false`, а
  `overflow` ніколи не `true`.
- Переповнення нічого не блокує. Обмеження розкладання вміє нативна
  `stock.storage.category`, і вона лишилась на місці.
- Дерево будується з `roots` і `parent_id`; `level` - глибина від найвищої локації
  переліку, з нуля.
- `purpose` - призначення зони, `stock.location.ua_purpose`: `receiving` (приймання),
  `storage` (зберігання), `hazard` (небезпечні вантажі, шафа АКБ), `quality` (ВТК),
  `production`, `finished` (готова продукція), `shipping`, `reject` (брак), або
  `false`; `purpose_label` - підпис українською.
- `plan` - прямокутник зони на плані складу в клітинках від лівого верхнього кута,
  поля `ua_plan_x`, `ua_plan_y`, `ua_plan_w`, `ua_plan_h`. Ширина або висота нуль -
  `plan: false`, зона на плані не намальована. Розмір сітки ядро не задає: клієнт
  бере найбільші `x + w` і `y + h`. У демо «АероСіч» сітка 24 × 14, девʼять зон.

**Місткість, призначення і місце на плані ставить людина** - це єдиний запис
цього екрана:

```
call("stock.location", "write", [[14], {"ua_capacity": 24}])
call("stock.location", "write", [[14], {"ua_purpose": "hazard",
     "ua_plan_x": 8, "ua_plan_y": 10, "ua_plan_w": 4, "ua_plan_h": 3}])
```

---

### Залишки

Скільки лежить, скільки треба тримати, на скільки виробів вистачить.

```
call("ua.api", "stock_glance", [1])
call("ua.api", "stock_glance", [1], {"location_ids": [5], "category_ids": [4]})
call("ua.api", "stock_glance", [1], {"query": "2207", "offset": 0, "limit": 100})
```

```json
{"company": {"id": 1, "name": "ТОВ «Ясен Меблі»"}, "total": 0, "offset": 0, "limit": 500,
 "count": 0, "truncated": false, "rows": []}
```

Форма рядка:

```json
{"product": [5, "Гвинт М3"], "code": "GV-3", "category": [4, "Комплектуючі"],
 "location": [13, "WH/Запаси/Полиця М1"], "uom": "Units",
 "qty": 10.0, "reserved": 0.0, "free": 10.0, "free_total": 15.0, "value": 20.0,
 "min": 100.0, "month": 0.0, "need": 100.0, "level": "warn",
 "enough_for": [{"product": [9, "Дрон Шершень"], "per_unit": 4.0, "units": 3}],
 "size": "s", "size_label": "S - дрібне", "slots": 10.0,
 "last_move": "2026-09-20 11:02:14",
 "target": {"model": "stock.quant", "res_id": 41}}
```

- `min` - `stock.warehouse.orderpoint.product_min_qty`; правила немає - `min` 0.
- `month` - витрата за 60 днів, поділена навпіл. Витратою рахуються лише проведені
  рядки руху з внутрішньої локації у виробництво або до клієнта: переміщення між
  полицями потребу не підіймає.
- `need` - `max(min, month)`.
- `enough_for` рахується від `free_total` (вільне по всіх локаціях вибірки), а не від
  `free` цієї полиці; `per_unit` - потреба на ОДНУ одиницю виробу, тому специфікація
  на партію 2 з 8 гвинтами дає 4.
- `level`: `bad` (вільного мінус), `warn` (мінімум задано і вільного менше),
  інакше `ok`.
- `query` - частина назви або внутрішнього коду товару (`default_code`), без
  регістру. Пошук іде в ядрі, тому знаходить товар і за межами першої сторінки.
- Сторінки: `offset` (з нуля) і `limit` (1..500, типово 500; більше ядро обріже до
  500 і скаже це в `limit`). `total` - скільки рядків усього під звуженнями й
  пошуком; `truncated` - чи є рядки після цієї сторінки (`offset + count < total`).
  Наступна сторінка - `offset + count`. Порядок сталий: товар, локація, id залишку.

---

### Рухи

Журнал рухів - нативний `stock.move.line`, свого читання тут немає.

```
call("stock.move.line", "search_read",
     [[["state","=","done"]],
      ["date","reference","product_id","quantity","location_id","location_dest_id",
       "location_usage","location_dest_usage","picking_id","picking_code",
       "production_id","is_inventory"]],
     {"order": "date desc, id desc", "limit": 100})
```

Вид руху інтерфейс розкладає сам, полями того самого рядка - саме для цього вони в
переліку:

| Що це | Як пізнати |
| --- | --- |
| Приймання | `picking_code` = `incoming` |
| Відвантаження | `picking_code` = `outgoing` |
| Переміщення по складу | `location_usage` = `location_dest_usage` = `internal` |
| Списання у виробництво | `location_dest_usage` = `production`, `production_id` заповнене |
| Випуск із виробництва | `location_usage` = `production` |
| Коригування інвентаризації | `is_inventory` = `true` |

`stock.move` поля `name` не має (`_rec_name = "reference"`); опис позиції -
`description_picking`.

---

### Приймання

Нативний `stock.picking` виду `incoming`, у трьох рухах.

**1. Що приймати.**

```
call("stock.picking", "search_read",
     [[["picking_type_code","=","incoming"],
       ["state","in",["assigned","confirmed","waiting"]]],
      ["name","partner_id","scheduled_date","state","origin","location_dest_id"]])

call("stock.move", "search_read",
     [[["picking_id","=",7]],
      ["product_id","product_uom_qty","quantity","picked","product_uom","description_picking"]])
```

**2. Скільки насправді приїхало** - кількість пишеться на `stock.move`, не на
`stock.move.line`:

```
call("stock.move", "write", [[31], {"quantity": 48.0, "picked": true}])
```

**3. Провести.** `button_validate()` без контексту повертає ОПИС ВІКНА майстра
дозамовлення, а не `true`. Щоб провести без дозамовлення, обидва ключі контексту
обовʼязкові:

```
call("stock.picking", "button_validate", [[7]],
     {"context": {"skip_backorder": true, "picking_ids_not_to_backorder": [7]}})
```

**4. Папір** - акт приймання-передачі ТМЦ, сеансом, не ключем:

```
GET /report/pdf/l10n_ua_stock_docs.report_ua_acceptance_act/7
```

---

### Інвентаризація

Три дієслова контракту цілком: створити, показати план, провести.

**1. Документ за міткою клієнта.** Повторний виклик із тією самою міткою віддає ТОЙ
САМИЙ документ і не чіпає його вміст - захист від подвійного запису після обриву
звʼязку більше не треба тримати в памʼяті воркера:

```
call("ua.stock.inventory", "ua_get_or_create",
     ["sklad-2026-09-22-1", {"location_id": 5, "date": "2026-09-22", "basis": "Наказ 14"}])
-> 3
```

**2. Аркуш підрахунку.** Або залити залишками ядром, за потреби звузивши:

```
call("ua.stock.inventory", "action_fill", [[3]], {"category_ids": [4], "location_ids": [13]})
```

або принести свої рядки і перевести документ у підрахунок, не пишучи `state` ззовні:

```
call("ua.stock.inventory", "write", [[3], {"line_ids": [[0,0,{"product_id":5,"qty_book":10,"qty_fact":9,"cost":2.0}]]}])
call("ua.stock.inventory", "action_start_count", [[3]])
```

**3. План перед проведенням.**

```
call("ua.api", "inventory_plan", [3])
```

```json
{"inventory": {"id": 3, "name": "ІНВ/2026/0003", "date": "2026-09-22",
               "state": "counting", "state_label": "Підрахунок",
               "location": [5, "WH/Запаси"], "client_ref": "sklad-2026-09-22-1",
               "lines": 12, "diff_lines": 1,
               "amount_surplus": 0.0, "amount_shortage": 2.0,
               "target": {"model": "ua.stock.inventory", "res_id": 3}},
 "plan": [
   {"text": "Розбіжностей: 1 рядків із 12.", "level": "info",
    "target": {"model": "ua.stock.inventory.line", "domain": [["inventory_id","=",3]]}},
   {"text": "Гвинт М3: за обліком 10, фактично 9, різниця -1 на -2.00 ₴.", "level": "info"},
   {"text": "Нестача 2.00: Дт 947 Кт 201. Норми природного убутку не рахуються, уся сума йде на 947 - розподіл «у межах норм / понад норми» робить бухгалтер.", "level": "warn"},
   {"text": "Обидві проводки - нативна оцінка запасів і наша 947 -> 719 - лягають датою опису 22.09.2026.", "level": "info"}
 ],
 "crit": 0, "can_apply": true}
```

`can_apply` - не окрема перевірка, а підсумок тих самих рядків: ядро не дасть провести
рівно тоді, коли в плані є `crit`. Перешкоди рівно дві: стан не «Підрахунок» і дата в
майбутньому. Неіснуючий id - `UserError` із людським текстом.

**4. Провести і надрукувати.**

```
call("ua.stock.inventory", "action_apply", [[3]])
GET /report/pdf/l10n_ua_stock_docs.report_ua_inventory_list/3     # інвентаризаційний опис
GET /report/pdf/l10n_ua_stock_docs.report_ua_inventory_sheet/3    # звіряльна відомість
```

Лишок ядро перекидає з 947 на 719 окремою проводкою - це не помилка оцінки запасів, а
українське правило: лишок це дохід, а не менша нестача.

---

### Розкласти

Що стоїть нерозкладеним: приймання, підлоги полиць і свіжий випуск із виробництва.

```
call("ua.api", "floor_packages", [1])
```

```json
{"company": {"id": 1, "name": "ТОВ «Ясен Меблі»"}, "count": 0, "rows": []}
```

Форма рядка:

```json
{"source": "floor", "product": [6, "Мотор 2207"], "code": "MT-2207",
 "category": [4, "Комплектуючі"], "lot": [12, "АКБ-2607"], "uom": "Units",
 "location": [15, "WH/Запаси/Полиця М1/Підлога"],
 "quantity": 1.0, "reserved": 0.0, "free": 1.0,
 "size": "m", "size_label": "M - середнє", "per_unit": 4, "slots": 4.0,
 "order": false, "done_date": false,
 "suggest": {"location": [13, "WH/Запаси/Полиця М1"], "why": "правило розкладання"},
 "target": {"model": "stock.quant", "res_id": 44}}
```

- `source`: `input` (локація приймання складу, `wh_input_stock_loc_id`), `floor`
  (локація з назвою «Підлога» - підлога полиці), `production` (готова продукція
  замовлень, закритих за останні 3 дні і ДОСІ у виробничій локації; такий рядок несе
  `order` і `done_date`).
- `suggest` - нативне правило розкладання (`_get_putaway_strategy`), або `false`.
- `category` - категорія товару `[id, назва]` або `false`; `lot` - партія або серійний
  номер САМЕ ЦЬОГО залишку (`stock.quant.lot_id`) або `false`. Один товар із двома
  партіями на підлозі - два рядки.
- Габарит один на все ядро: `size` - це `product.template.ua_size` (той самий, що
  читає `product.product`), `per_unit` - місць на одну штуку, `slots` = `quantity ×
  per_unit`. Тим самим числом рахують `warehouse_map` і `stock.location.ua_capacity_used`,
  тому «влізе / не влізе» на полицю рахується з `slots` рядка і `free` полиці з карти,
  без власної таблиці габаритів. Коди габариту - малими літерами (`s`/`m`/`l`), як у
  `sizes` карти; порівнювати з великими `S`/`M`/`L` не можна.
- Сам рух - окрема дія, див. «Переміщення».

---

### Переміщення

Розкладання і перекидання між полицями - нативний `stock.picking` внутрішнього виду.
Цей вид у складі з одноступеневим прийманням буває вимкнений, тому спершу його треба
знайти і за потреби ввімкнути.

```
call("stock.picking.type", "search_read", [[["code","=","internal"]], ["name","active"]],
     {"context": {"active_test": false}})
```

Далі чотири кроки, усі нативні:

```
call("stock.picking", "create",
     [{"picking_type_id": 5, "location_id": 15, "location_dest_id": 13,
       "origin": "sklad-2026-09-22-розкласти",
       "move_ids": [[0,0,{"product_id": 6, "product_uom_qty": 1.0,
                          "location_id": 15, "location_dest_id": 13,
                          "description_picking": "Мотор 2207"}]]}])
call("stock.picking", "action_confirm", [[9]])
call("stock.picking", "action_assign", [[9]])
call("stock.move", "write", [[33], {"quantity": 1.0, "picked": true}])
call("stock.picking", "button_validate", [[9]],
     {"context": {"skip_backorder": true, "picking_ids_not_to_backorder": [9]}})
```

`origin` - зручне місце для мітки операції клієнта: перед створенням пошук за
`[["origin","=","…"]]` показує, чи документ уже є. У рухах поля `name` немає, опис
позиції - `description_picking`.

---

### Збирання

Складальна карта виробу: креслення, операції, позиції і полиці, де комплектуючі
лежать ЗАРАЗ.

```
call("ua.api", "product_assembly", [9])
```

`product_id` тут - id `product.template`, картки товару. З `product.product`
передавайте `product_tmpl_id[0]`: два переліки мають свої лічильники id, і вгадувати,
який із них прийшов, метод не буде - неіснуючий id дає `UserError`.

Форма відповіді:

```json
{"product": [9, "Дрон Шершень"], "code": "SH-7",
 "drawing_svg": "<svg viewBox=\"0 0 800 600\"…</svg>", "drawing_name": "shershen-7.svg",
 "total_minutes": 20.0,
 "operations": [
   {"name": "Збирання рами", "workcenter": "Стіл складання", "time_minutes": 20.0,
    "steps": ["Розпакувати раму", "Поставити мотори"],
    "checks": ["Люфтів немає"],
    "parts": [{"pos": 1, "product": "Рама карбон", "product_id": 7, "qty": 1.0,
               "bin_location": "WH/Запаси/Полиця М2", "bin_source": "stock"}]},
   {"name": "Без операції", "workcenter": "", "time_minutes": 0.0,
    "steps": [], "checks": [],
    "parts": [{"pos": 2, "product": "Гвинт М3", "product_id": 5, "qty": 4.0,
               "bin_location": "WH/Запаси/Полиця М1", "bin_source": "stock"}]}
 ]}
```

- `drawing_svg` приходить РОЗКОДОВАНИМ текстом SVG, не base64: вставляйте як є.
  Домовленість про вміст файла одна і обовʼязкова: елемент позиції має id `bom-N`,
  де N - `pos`. Інших id договір не знає - `pos-N` з першої ітерації UI прибрано і з
  демо-креслення «Шершень» (`scripts/demo_aerosich.py` знімає його при записі), тому
  підсвічуйте лише `#bom-N`. Позиції без елемента на кресленні просто не світяться.
- `pos` - порядок рядків специфікації (`sequence`, далі `id`), з одиниці. Окремого
  поля «номер позиції» немає свідомо: два джерела правди про порядок розійшлися б
  після першого ж перетягування рядка.
- `qty` - на ОДНУ одиницю виробу, в одиниці виміру компонента.
- `bin_location` - спершу полиця, де комплектуюча ЛЕЖИТЬ зараз (найбільший залишок),
  і лише якщо її ніде немає - полиця за правилом розкладання; `bin_source` каже, що
  саме віддали: `stock`, `rule` або `false`. Це єдина навмисна різниця з
  `product.template.ua_assembly()`, де першим іде правило: збирач іде по деталі, а не
  по налаштуванню.
- Рядки без операції - остання група «Без операції». Виріб без специфікації віддає
  `operations: []`.

Креслення і тексти операцій заводить людина у формах Odoo:
`product.template.ua_drawing_svg` / `ua_drawing_name`,
`mrp.routing.workcenter.ua_steps` / `ua_checks` (по пункту в рядок). Замовлення на
виробництво - нативна `mrp.production`; `ua.api` його не створює.

Підводні камені нативного складу зібрані в `README.md`, розділ «Підводні камені».

---

### Журнали

Журнали «Надходження» і «Інвентаризація» (зокрема у вигляді 1С) - звичайний
`search_read`; свого читання тут немає. Колонки «Сума» і «Відповідальний»:

```
call("stock.picking", "search_read",
     [[["picking_type_code","=","incoming"]],
      ["name","date_done","scheduled_date","partner_id","state","origin",
       "user_id","ua_amount"]],
     {"order": "scheduled_date desc, id desc", "limit": 100})

call("ua.stock.inventory", "search_read",
     [[], ["name","date","location_id","state","user_id",
           "amount_fact","amount_surplus","amount_shortage"]],
     {"limit": 100})
```

- `stock.picking.user_id` - нативний «Відповідальний»; порожній буває, його ставлять
  руками.
- `stock.picking.ua_amount` - сума документа за собівартістю: проведений рядок дає
  свою оцінку (`stock.move.value`), непроведений - кількість × облікова ціна товару в
  компанії документа; скасовані рядки не рахуються. Поле НЕ зберігається (облікова
  ціна змінюється), тому його немає в `inventory.md`, фільтрувати й сортувати за ним
  не можна - лише читати. Ціни закупівлі тут немає: вона живе в `purchase.order.line`.
- `ua.stock.inventory.user_id` - хто веде опис (типово той, хто завів);
  `amount_fact` - Σ фактична кількість × облікова ціна рядка.
- Ціна і сума по рядку форми приймання: `stock.move` поле `value` (проведений) або
  `product_id` → `standard_price` × `quantity`.

---

### Кіоск цеху

Наряди пишуться НАТИВНО - `mrp.workorder` у CE 19 має всі кнопки. Своє тут лише
відповіді на пункти перевірки операції і одне читання.

**1. Що робити на наряді.**

```
call("mrp.workorder", "search_read",
     [[["workcenter_id","=",3],["state","in",["ready","progress","waiting"]]],
      ["name","production_id","product_id","state","duration_expected"]])
call("ua.api", "workorder_card", [21])
```

Форма відповіді:

```json
{"workorder": {"id": 21, "name": "Пайка силової частини",
               "production": [7, "АС/MO/00007"], "product": [40, "FPV-дрон «Шершень» 7\""],
               "workcenter": [3, "Пайка"], "state": "ready", "state_label": "Готово",
               "qty_production": 1.0, "qty_producing": 0.0,
               "duration_expected": 40.0, "duration": 0.0,
               "date_start": false, "date_finished": false,
               "target": {"model": "mrp.workorder", "res_id": 21}},
 "steps": ["Залудити майданчики ESC", "Припаяти три фази кожного мотора за схемою"],
 "checks": [{"index": 1, "text": "Опір між фазами однаковий", "result": false,
             "note": "", "user": false, "date": false}],
 "open": 1, "failed": 0,
 "parts": [{"product": [12, "Мотор безколекторний 2207 1950KV"], "code": "D02",
            "qty": 4.0, "uom": "Units", "picked": false}]}
```

- `steps` і `checks` - з операції маршруту (`ua_steps`, `ua_checks`, по пункту в
  рядок); `index` пункту - з одиниці.
- `parts` - рядки списання замовлення, що споживаються в ЦІЙ операції (нативне
  `operation_id` рядка специфікації); `qty` - на все замовлення.
- `duration*` - хвилини.

**2. Писати.**

```
call("mrp.workorder", "button_start", [[21]])      # таймер і стан «В роботі»
call("mrp.workorder", "button_pending", [[21]])    # пауза
call("mrp.workorder", "ua_answer_check", [[21], 1, "fail"], {"note": "КЗ на раму"})
call("mrp.workorder", "button_finish", [[21]])     # закрити наряд
```

- `ua_answer_check(index, result, note=None)`: `result` - `ok` або `fail`; повторна
  відповідь на той самий пункт оновлює першу; повертає `checks` у тій самій формі.
  Текст пункту зберігається знімком - якщо технолог потім переписав перевірку,
  відповідь лишається з тим текстом, на який відповідали.
- Закритий або скасований наряд відповідей не приймає (`UserError`); пункту поза
  переліком - теж `UserError`.
- `button_finish()` відповіді НЕ перевіряє: закриття лишається нативним. Чи пускати
  людину далі з `open > 0` або `failed > 0` - рішення кіоску.
- Замовлення на виробництво за міткою клієнта:
  `mrp.production.ua_get_or_create(client_ref, vals)` - той самий захист від дубля, що
  на приймання і описі.

---

## Чого на цій сторінці немає

- Списків полів кожної моделі: їх дає `fields_get()` і `inventory.md`.
- Прав доступу по групах: інтерфейс їх не вирішує. Якщо прийшов `AccessError` -
  показуйте його, а не порожній екран.
- Власних розрахунків: жодного числа з цієї сторінки не можна порахувати на боці
  інтерфейсу. Бракує числа - `python3 scripts/agent_note.py new request --from ui
  --to core "…"`.
