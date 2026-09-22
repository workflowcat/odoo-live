# Вісім робочих процесів: які виклики робить екран

Протокол, вхід і спільні форми даних - у `README.md`. Тут - що саме викликає екран у
кожному з восьми процесів продукту, у порядку, і які відповіді на це приходять.

Усі відповіді на цій сторінці зняті з ЖИВОЇ демо-бази (`scripts/demo_server.sh`,
порт 8131, база `demo`, компанія «ТОВ «Ясен Меблі»», вересень 2026) через
`POST /jsonrpc`. Вони обрізані до показових полів - там, де обрізано, стоїть `…`.
Числа справжні і відповідають стану демо на 2026-09-22; якщо демо перезібрати,
зміняться числа, але не форма.

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
  "alerts": {"count": 1, "docs_expiring": 0, "military_needs_check": true},
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
(`action_ua_finrep_xml_draft`).

---

## Чого на цій сторінці немає

- Списків полів кожної моделі: їх дає `fields_get()` і `inventory.md`.
- Прав доступу по групах: інтерфейс їх не вирішує. Якщо прийшов `AccessError` -
  показуйте його, а не порожній екран.
- Власних розрахунків: жодного числа з цієї сторінки не можна порахувати на боці
  інтерфейсу. Бракує числа - `python3 scripts/agent_note.py new request --from ui
  --to core "…"`.
