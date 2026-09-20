# Спека: екран «Папери»

Дата: 20 вересня 2026. Макет: https://claude.ai/artifact/La67gyVPmm2wsDMQ834GnY
Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`. Модуль `l10n_ua_papers`.
Не комітити: перевірку і коміт робить оркестратор.

## Мета

Сьогодні папери розкидані: дванадцять майстрів, двадцять чотири звіти, кожен у своєму меню,
кожен зі своїм вибором місяця. Бухгалтер натискає кнопку і лише тоді дізнається, що вийшло
або чого бракує.

Потрібен один екран. Період задається один раз угорі і діє на всі папери. Ліворуч - які
папери бувають. Посередині - поля цього паперу, під ними одразу видно, що вийде. Праворуч -
що в папір входить і звідки.

Правило екрана: папір показується раніше, ніж його просять зробити.

## Три колонки і смуга періоду

```
[ шапка: назва вибраного паперу · стан · дії ]
[ смуга періоду: ◀ вересень 2026 ▶ · відкритий · 49 працівників ]
[ ліворуч 232px ][ середина ][ праворуч 288px ]
  види паперів     поля         що входить
                   перегляд     перевірки
                   дії
                   зроблено раніше
```

Смуга періоду одна на екран. Перемкнув місяць - перемкнулися всі папери, а не цей один.

## Контракт

`ua.papers` - AbstractModel, своїх даних не тримає, читає наявні моделі.

### get_screen_data(year=None, month=None, paper=None, params=None)

`params` - словник значень полів вибраного паперу, як їх повернув попередній виклик.
Порожній `paper` означає перший папір першої групи.

```python
{
  "period": {"year": 2026, "month": 9, "label": "вересень 2026", "closed": False,
             "employees": 49,
             "periods": [{"year": .., "month": .., "label": "вер", "current": True}]},  # 6 штук
  "papers": [{"group": "month", "group_label": "За місяць", "key": "timesheet",
              "name": "Табель П-5", "mark": "ok|warn|crit|none", "count": None}],
  "paper": {
      "key": "timesheet",
      "name": "Табель обліку робочого часу",
      "subtitle": "типова форма П-5",
      "state": "confirmed|draft|none",
      "state_text": "затверджено 18 вересня, Гнатюк Л.",
      "record": {"model": "ua.timesheet.sheet", "res_id": 12} або None,
      "fields": [{"key": "department_id", "label": "Підрозділ", "kind": "choice",
                  "value": False, "display": "усі",
                  "options": [{"value": False, "label": "усі"}, ...],
                  "missing": False, "note": None}],
      "preview": {"html": "<html>...", "empty_text": None},
      "actions": [{"key": "print", "label": "Друк", "primary": True,
                   "enabled": True, "reason": None}],
      "sources": [{"label": "Коди днів", "text": "графік роботи і затверджені відсутності",
                   "state": "supplied", "target": {...} або None}],
      "checks": [{"level": "ok|warn|crit", "text": "...", "target": {...} або None}],
      "earlier": [{"label": "серпень", "note": "друковано 2 вересня", "target": {...}}],
  },
}
```

`kind` поля: `text`, `choice` (є `options`), `record` (є `options` із записів періоду),
`date`, `bool`. Поле з `missing: True` малюється червоним - саме його бракує, щоб папір вийшов.

`state` джерела - той самий словник станів, що в `docs/payroll/explain-model.md`:
`supplied`, `imported`, `calculated`, `missing`, `stale`, `manual`, `not_applicable`.

### run_action(paper, action_key, year, month, params)

Повертає дію Odoo (звіт, форма запису) або `{"reload": True}`. Дії:

- `print` - `ir.actions.report` вибраного паперу на його запис.
- `compose` - скласти чернетку документа за полями (клас «чернетка» з `action-model.md`:
  швидко, без плану, звичайне редагування далі). Після цього `reload`.
- `edit` - відкрити форму запису, щоб правити рядки.

Кнопка, якої не можна натиснути, приходить із `enabled: False` і `reason` одним рядком.
Вимкнена кнопка не зникає: бухгалтер має бачити, що папір існує.

### open_target(target)

Один в один як `ua.home.open_target`: `xmlid`, або `model` + `res_id`, або `model` + `domain`.

## Перегляд

`_render_qweb_html` наявного звіту, без жодного нового шаблону. Результат віддається
як повний HTML і показується в `<iframe srcdoc>`: так звіт лишається в своєму CSS і не
б'ється зі стилями Odoo, а виглядає рівно так, як надрукується.

Перегляд нічого не створює. Немає запису - немає HTML, є `empty_text` і кнопка «Скласти
чернетку». Мовчки створювати документ при відкритті екрана не можна.

## Перелік паперів

Група `month` - за місяць:

| key | назва | модель | звіт |
| timesheet | Табель обліку робочого часу | ua.timesheet.sheet | l10n_ua_hr_docs.action_report_ua_timesheet |
| staff_list | Штатний розпис | ua.staff.list | l10n_ua_hr_docs.action_report_ua_staff_list |
| advance | Авансова відомість | ua.advance.sheet | l10n_ua_payroll_reports.action_report_ua_advance_sheet |
| payment_batch | Відомість на перерахування | ua.payment.batch | l10n_ua_payments.action_report_ua_payment_batch |
| payroll_sheet | Розрахунково-платіжна відомість | hr.payslip.run | l10n_ua_payroll_reports.action_report_ua_payroll_sheet |

Група `person` - на людину (поле-вибір запису за період):

| key | назва | модель | звіт |
| order | Наказ | ua.hr.order | l10n_ua_hr_orders.action_report_ua_hr_order |
| payslip | Розрахунковий листок | hr.payslip | l10n_ua_payroll_reports.action_report_ua_payslip |
| p2 | Особова картка П-2 | hr.employee | l10n_ua_hr_card.action_report_ua_p2 |
| contract | Трудовий договір | ua.hire.case | l10n_ua_hire.action_report_hire_contract |

Група `state` - для держави:

| key | назва | модель | звіт |
| pfu | Заява-розрахунок до ПФУ | ua.pfu.claim | l10n_ua_hr_docs.action_report_ua_pfu_claim |
| military_list | Список військового обліку | ua.military.list | l10n_ua_military.action_report_ua_military_list |
| military_reserved | Список заброньованих | ua.military.reserved | l10n_ua_military.action_report_ua_military_reserved |

Група `register` - журнали:

| key | назва | модель | звіт |
| order_register | Журнал реєстрації наказів | ua.hr.order.register.wizard | l10n_ua_hr_orders.action_report_ua_hr_order_register |

Журнал наказів у цьому зрізі йде без перегляду (`empty_text` пояснює, чому): його звіт
будується з майстра, а майстер створювати заради перегляду не можна. Перенесення
чотирьох майстрів-друкарок у документи - крок 3 плану спрощення, не цей зріз.

## Позначка паперу в лівій колонці

- `crit` - папір потрібен цього місяця і його не можна зробити (бракує даних) або строк минув.
- `warn` - папір є чернеткою, або строк близько.
- `ok` - папір складений і затверджений.
- `none` - папір не прив'язаний до місяця (на людину, на вимогу).

Позначка рахується з наявних перевірок документа (`ua.checks.mixin._checks()`), а не
вигадується окремо.

## Чого в цьому зрізі немає

- Друк на багатьох людей одразу. 49 листків одним файлом - окремий режим, потім.
- Пакет документів однієї людини (принесла / зробили ми). Третій режим екрана, наступний зріз.
- Підпис і подання. Екран доводить до друку.

## Перевірка

`scripts/papers_check.py`, база payroll. Обов'язково:

- дія `ua_papers` і корінне меню «Папери» видимі звичайному користувачу (lana);
- `get_screen_data()` дає всі ключі форми, шість періодів, рівно один `current`;
- кожен папір переліку відкривається: `get_screen_data(paper=key)` не падає і дає `paper.key == key`;
- кожна `target` у відповіді (у `sources`, `checks`, `earlier`) відкривається через `open_target`;
- перегляд не пише в базу: кількість записів моделі паперу до і після виклику однакова;
- у паперу зі складеним документом `preview.html` не порожній і містить назву паперу;
- у паперу без документа `preview.html` порожній, є `empty_text` і дія `compose`;
- кнопка з `enabled: False` завжди має `reason`;
- стан кожного джерела - зі списку станів `explain-model.md`;
- зміна місяця міняє `period.label` і не ламає вибраний папір.
