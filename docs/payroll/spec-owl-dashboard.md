# Спека: головна сторінка «Зведення» на OWL

Дата: 9 вересня 2026. Автор: Fable. Виконавець: Sonnet-агент M. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`, база `payroll_test`. Не комітити, не пушити, не чіпати хмару, не перезапускати контейнер стенду.

Правило проєкту змінилося: Kit дозволив OWL для складних екранів (9 вересня 2026). Простими видами Odoo далі робимо все, що можна зробити простими видами; OWL лише там, де стандартний вид не дає потрібного.

## Мета

Замінити поточну стартову сторінку (kanban з категоріями) на щільний екран «Зведення»: факти, суми, строки, попередження і пульт команд на одному екрані. Макет узгоджений з Kit: менше карток, більше фактичної інформації, таблиці з підсумками.

## Модуль `l10n_ua_dashboard`

- Залежності: `l10n_ua_hub`, `l10n_ua_payroll_account`, `l10n_ua_hr_docs`, `l10n_ua_military`, `web`.
- Клієнтська дія `ir.actions.client` з тегом `ua_dashboard`, назва «Зведення».
- Кореневе меню «Зведення» sequence 1 (меню «Головна» модуля `l10n_ua_hub` перенести на sequence 2 і лишити як пульт; не видаляти).
- `post_init_hook`: домашня дія (`res.users.action_id`) для груп `hr.group_hr_user` і `account.group_account_user` = ця клієнтська дія.

## Дані: `models/ua_dashboard.py`

Модель `ua.dashboard` (`_name`, TransientModel не потрібен, звичайний AbstractModel) з методом:

```python
@api.model
def get_data(self, year=None, month=None):
    ...
```

Повертає словник (усі суми float, округлені до копійок; усі назви українською):

- `company`: назва, ЄДРПОУ, кількість активних працівників, період (рік, місяць, назва місяця українською).
- `periods`: список останніх 6 місяців [{year, month, label, has_run}] для перемикача.
- `payroll_by_department`: рядки [{department, employees, gross, pdfo, vz, esv, net}] за пакетом листків цього місяця (`hr.payslip.run` з `date_start` у місяці; якщо пакета немає, беремо листки за датами), плюс `total`.
- `payments`: рядки [{date, label, amount, state, state_class}] де state_class один із `ok|warn|todo|plan`: виплачена зарплата минулого місяця, ПДФО, ВЗ, ЄСВ (стан «у виписці, не звірено» якщо є рядок виписки з такою сумою і `is_reconciled = False`), аванс цього місяця (стан «не розраховано», якщо немає рядків у авансовій відомості), планові платежі наступного місяця, строк об'єднаної звітності за квартал.
- `attention`: рядки [{title, detail, count, level, action, res_model, domain}] де level `danger|warning|info`: звірка з ТЦК не проводилась (`ua_mil_needs_check`), документи спливають за 30 днів (`ua.employee.document.valid_until`), незвірені рядки виписки (кількість і сума), договори і випробування, що спливають за 30 днів, працівники без РНОКПП, листки в чернетках.
- `documents`: рядки [{name, period, state, action, res_model, res_id}] останні табелі, штатні розписи, заяви ПФУ, авансові відомості, вкладення XML.
- `hub`: розділи і команди з `ua.hub.item` [{section, items: [{name, description, action_xmlid, id}]}], лише доступні (`available`).

Метод `open_item(self, item_id)` на `ua.hub.item` уже є (`action_open`). Для рядків `attention` і `documents` фронт відкриває дію через `action` service: якщо задано `action_xmlid`, викликаємо `orm.call("ua.hub.item", "action_open", [id])`; якщо задано `res_model` і `domain`, відкриваємо act_window з цим доменом (`doAction({type: "ir.actions.act_window", res_model, domain, views: [[false, "list"], [false, "form"]], name})`).

## Фронт: `static/src/`

- `dashboard.js`: компонент OWL `UaDashboard`, `static template = "l10n_ua_dashboard.Dashboard"`, у `setup()` `this.orm = useService("orm")`, `this.action = useService("action")`, `this.state = useState({data: null, year, month})`, `onWillStart(() => this.load())`. Реєстрація: `registry.category("actions").add("ua_dashboard", UaDashboard)`.
- `dashboard.xml`: шаблон з `t-name="l10n_ua_dashboard.Dashboard"`, `owl="1"`. Верстка: заголовок (компанія, період, перемикач місяців кнопками), далі чотири таблиці (нарахування по підрозділах з підсумковим рядком; платежі і строки; потребує уваги; документи періоду), внизу пульт: розділи колонками зі списками команд-посилань.
- `dashboard.scss`: мінімум. Тільки: щільні таблиці (шрифт 12-13px, `tabular-nums`, тонкі лінії), сітка пульта `grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))`, кольори станів через змінні Odoo (`--o-color-*`) або класи Bootstrap `text-danger|text-warning|text-success|text-muted`. Не перевизначати глобальні стилі Odoo, усі правила під коренем `.o_ua_dashboard`.
- Реєстрація ресурсів у маніфесті:
  ```python
  "assets": {"web.assets_backend": [
      "l10n_ua_dashboard/static/src/dashboard.scss",
      "l10n_ua_dashboard/static/src/dashboard.js",
      "l10n_ua_dashboard/static/src/dashboard.xml",
  ]},
  ```
- Порожні стани: якщо пакета листків немає, таблиця нарахувань показує рядок «Листків за цей місяць немає» і кнопку, що відкриває пакети.
- Жодних зовнішніх бібліотек, жодних CDN. Тільки OWL, який уже є в Odoo 19.

## Odoo 19, точні деталі API

- `import { Component, useState, onWillStart } from "@odoo/owl";`
- `import { registry } from "@web/core/registry";`
- `import { useService } from "@web/core/utils/hooks";`
- `import { standardActionServiceProps } from "@web/webclient/actions/action_service";` — компонент клієнтської дії отримує пропси; оголосіть `static props = { ...standardActionServiceProps };` (у 19 це обов'язково, інакше попередження про невідомі пропси).
- Шаблон XML починається з `<?xml version="1.0" encoding="UTF-8"?>` і `<templates xml:space="preserve">`, усередині `<t t-name="l10n_ua_dashboard.Dashboard">`.
- `this.orm.call("ua.dashboard", "get_data", [], {year, month})`.
- Відкриття дії: `this.action.doAction(actionDescriptor)`.
- Числа форматувати через `formatMonetary`/`formatFloat` з `@web/views/fields/formatters` або власною функцією `n.toLocaleString("uk-UA", {minimumFractionDigits: 2})`.

## Перевірка

`scripts/dashboard_check.py` (база з `PAYROLL_DB`):
- `ua.dashboard.get_data` повертає всі ключі, `payroll_by_department` має підсумок, що збігається з сумою рядків;
- клієнтська дія існує (`ir.actions.client` з тегом `ua_dashboard`), меню «Зведення» видиме для `lana`, її домашня дія = ця дія;
- HTTP-перевірка збірки ресурсів: сесією `lana` запросити `/web/assets/debug/web.assets_backend.js` і переконатися, що код 200 і у тілі є рядок `l10n_ua_dashboard.Dashboard` (шаблон і компонент потрапили в бандл). Помилка компіляції SCSS або JS дасть 500 або відсутній рядок.

## Технічні правила

- Оновлення: `docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll_test -i l10n_ua_dashboard --stop-after-init --log-level=warn 2>&1 | tail -20"`.
- Не редагувати чужі модулі, крім `l10n_ua_hub/views/ua_hub_views.xml` (лише зміна sequence меню «Головна» на 2).
- Українська мова інтерфейсу, короткі підписи, без пояснювальних речень.
- Звіт: файли, вивід перевірки, що не зроблено.
