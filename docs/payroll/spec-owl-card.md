# Спека: картка працівника на OWL як основний вигляд

Дата: 9 вересня 2026. Автор: Fable. Виконавець: Sonnet-агент N. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`, база `payroll`. Не комітити, не пушити, не чіпати хмару, не перезапускати контейнер стенду (для нового Python-коду `odoo shell` або тимчасовий `docker run --rm`). Інший агент паралельно робить `addons/l10n_ua_dashboard` на базі `payroll_test`: не редагувати той модуль і ту базу.

## Рішення замовника

OWL-екран є основним. Стандартна форма Odoo лишається доступною за кнопкою і в налаштуваннях. Жодне поле не втрачається.

## Модуль `l10n_ua_card_ui`

- Залежності: `l10n_ua_hr_card`, `l10n_ua_military`, `l10n_ua_payroll_rules`, `l10n_ua_average`, `web`.
- Форма-обгортка: новий вид форми `hr.employee` (`priority` вищий за стандартний), який містить лише віджет:
  ```xml
  <form class="o_ua_employee_card"><sheet><widget name="ua_employee_card"/></sheet></form>
  ```
  Дії, що відкривають працівника (`hr.open_view_employee_list_my`, `hr.hr_employee_action_from_department`, дії наших меню), мають відкривати саме цей вид. Реалізація: у нашому виді вказати `<field name="priority">1</field>` не досить, бо Odoo бере вид з найменшим `priority`. Тому: створити наш вид з `priority` 1, а стандартний `hr.view_employee_form` лишити недоторканим; у діях, які ми контролюємо, вказати `view_ids` явно. Для дій ядра (`hr.open_view_employee_list_my`) переписати `view_mode`/`view_ids` у `post_init_hook` записом у `ir.actions.act_window.view` (list → наша форма). Обов'язково зберегти можливість повернутися до стандартної форми.
- Віджет `ua_employee_card` реєструється у `registry.category("view_widgets")` як `{component: UaEmployeeCard, fieldDependencies: [...]}`. Компонент отримує `props.record`, читає `record.resId`, дані бере одним викликом `orm.call("hr.employee", "get_card_data", [resId])`.
- Метод `get_card_data` на `hr.employee` повертає словник: `header` (ПІБ, посада, підрозділ, місце роботи, керівник, таб. номер, ініціали, значки), `person`, `pay`, `vacation`, `military`, `documents` (список зі станом), `timeline` (об'єднана хроніка: версії контрактів, накази, відпустки, листки з сумами, події військового обліку, документи), `actions` (перелік кнопок з описом дії). Суми округлені, дати у форматі ДД.ММ.РРРР, усе українською.
- Кнопки в картці:
  - «Друк П-2» → звіт `l10n_ua_hr_card.report_ua_p2`;
  - «Наказ» → звіт наказу з поточної версії контракту;
  - «Листки» → список листків працівника;
  - «Змінити оклад» → форма нової версії контракту;
  - «Оформити відпустку» → нова `hr.leave` з підставленим працівником;
  - «Додати документ» → нова `ua.employee.document`;
  - «Записати звірку ТЦК» → нова `ua.military.event` з видом «звірка» і датою сьогодні; після збереження картка перезавантажується;
  - «Звільнити» → форма поточної версії з полями дати і підстави;
  - «Стандартна форма» → `doAction` з `views: [[<id стандартного виду>, "form"]]` і `res_id` працівника. Це і є вихід до рідного Odoo.
- Верстка за макетом, узгодженим із замовником: шапка (аватар або ініціали, ПІБ, посада і підрозділ, значки стану, три кнопки друку праворуч); три колонки (Особа; Оплата і Відпустка; Військовий облік і Документи) щільними таблицями «поле — значення»; нижче таблиця «Хроніка» на всю ширину; внизу рядок кнопок дій. Числа праворуч, моноширинним, `tabular-nums`. Порожні значення показувати сірим словом «немає», не ховати рядок.
- Стилі: файл `static/src/card.scss`, усі правила під `.o_ua_employee_card`. Мінімум: щільні таблиці, тонкі лінії, сітка колонок `repeat(auto-fit, minmax(220px, 1fr))`. Кольори станів класами Bootstrap (`text-danger`, `text-warning`, `text-success`, `text-muted`), без власної палітри.
- Налаштування: булеве поле `ua_card_default` на `res.users` («Відкривати картку OWL за замовчуванням», типово увімкнено) не потрібне; замість нього у формі-обгортці завжди є кнопка «Стандартна форма».

## Odoo 19, точні деталі API

- `registry.category("view_widgets").add("ua_employee_card", {component: UaEmployeeCard});`
- `import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";`
- `import { useService } from "@web/core/utils/hooks";` (`orm`, `action`, `notification`).
- Пропси віджета у формі: `static props = { record: Object, readonly: {type: Boolean, optional: true} };`
- Перезавантаження після дії: `await this.props.record.load(); this.state.data = await this.orm.call(...)`.
- Шаблон у `static/src/card.xml`, `<templates xml:space="preserve">`, `t-name="l10n_ua_card_ui.EmployeeCard"`.
- Ресурси в маніфесті у `web.assets_backend`.

## Перевірка

`scripts/card_ui_check.py` (база з `PAYROLL_DB`, типово `payroll`):
- `get_card_data` для трьох працівників повертає всі ключі; у Ткачука в `timeline` є і прийняття 01.03.2021, і звільнення 31.05.2026, і прийняття 17.08.2026;
- вид-обгортка існує і має пріоритет нижчий за стандартний (тобто відкривається першим);
- дія «Співробітники» відкриває саме нашу форму (перевірити `ir.actions.act_window.view` або `view_ids`);
- бандл `web.assets_backend` збирається без помилок і містить рядок `l10n_ua_card_ui.EmployeeCard`;
- звіт П-2 і далі друкується (регресія).

## Технічні правила

- Оновлення: `docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll -i l10n_ua_card_ui --stop-after-init --log-level=warn 2>&1 | tail -20"`.
- Не редагувати `l10n_ua_dashboard`, `l10n_ua_hub`, модулі OCA і ядро.
- Українська мова, короткі підписи.
- Звіт: файли, вивід перевірки, що не зроблено.
