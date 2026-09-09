# Спека: стартова сторінка «Головна» з усіма командами (стиль BAS)

Дата: 9 вересня 2026. Автор: Fable. Виконавець: Sonnet-агент J. Репозиторій `/Users/kit/Codius/odoo-live-payroll`, гілка `payroll`, база `payroll_test`. Не комітити, не пушити, не чіпати хмару, не перезапускати контейнер стенду (для нового Python-коду `odoo shell` або тимчасовий `docker run --rm`).

## Мета

Бухгалтер відкриває систему і бачить одну сторінку з усіма командами, згрупованими колонками, як панель розділу в BAS: назва команди це посилання, клік відкриває дію. Без пошуку по випадних меню. Тільки стандартні засоби Odoo: моделі, kanban, дані. Жодного власного JS, CSS, OWL чи тем.

## Модуль `l10n_ua_hub`

- Залежності: `l10n_ua_payroll_ui` (щоб встановлюватися останнім). Дії шукаються за рядковим xmlid, тому інших залежностей не потрібно.
- Модель `ua.hub.section`: `name` Char (translate=True), `sequence` Integer, `code` Char (унікальний), `active`.
- Модель `ua.hub.item`: `name` Char (translate=True, required), `section_id` Many2one `ua.hub.section` (required, ondelete cascade), `sequence` Integer, `action_xmlid` Char (required, наприклад `payroll.hr_payslip_run_menu` не годиться: потрібен xmlid дії, наприклад `payroll.hr_payslip_run_action`), `description` Char (translate=True), `active`, `available` Boolean (compute, non-store: чи існує дія і чи має користувач доступ до її моделі).
- Метод `action_open(self)`: `record = self.env.ref(self.action_xmlid, raise_if_not_found=False)`; якщо немає, `UserError("Команда недоступна: %s")`; інакше `action = record.sudo().read()[0]`, повернути його. Працює для `ir.actions.act_window`, `ir.actions.report`, `ir.actions.server`, `ir.actions.client`.
- Kanban `ua.hub.item`: `default_group_by="section_id"`, `records_draggable="false"`, `group_create="false"`, картка компактна (назва посилання + опис дрібним), клік по картці викликає `action_open` (`<div class="oe_kanban_global_click">` + `<a name="action_open" type="object">`). Порядок: `sequence, id`. Пошуковий вид: пошук за назвою, фільтр за розділом, `group_by` розділ.
- Дія `ir.actions.act_window` «Головна» на `ua.hub.item`, `view_mode="kanban"`, контекст `{"search_default_group_section": 1}` якщо потрібно.
- Меню: кореневий пункт «Головна» (`web_icon` не обов'язковий), sequence 1, щоб стояв першим у верхньому меню.
- Стартова сторінка: у `post_init_hook` встановити `action_id` (домашню дію) цієї дії для користувачів груп `hr.group_hr_user` і `account.group_account_user`, якщо у них не задано власної. Так система відкривається одразу на «Головній».
- Доступ: `base.group_user` читання; `base.group_system` повний CRUD. Розділи і пункти редагуються адміністратором.

## Наповнення (файл `data/hub_data.xml`, `noupdate="0"`)

Розділи і пункти. Перед записом xmlid дії агент має перевірити, що дія існує (пошук у `ir.model.data` по нашій базі), і не вигадувати назви. Пункти, дія яких відсутня, не додавати.

1. «Зарплата»: пакети листків, розрахункові листки, аванс за місяць, авансові відомості.
2. «Звітність ДПС і ПФУ»: об'єднана звітність (XML), повідомлення про прийняття (XML), заяви-розрахунки ПФУ.
3. «Кадрові документи»: штатний розпис (майстер), штатні розписи, табель (майстер), табелі.
4. «Військовий облік»: військовозобов'язані, списки персонального обліку, повідомлення до ТЦК, списки заброньованих, потребують звірки.
5. «Кадри»: співробітники, підрозділи, посади, відпустки (заявки), типи відпусток.
6. «Бухоблік»: журнальні проводки, план рахунків, журнали, банківські виписки, звірка виписок, імпорт виписки.
7. «Звіти»: оборотно-сальдова відомість, головна книга, журнал проводок, незакриті розрахунки, заборгованість за строками.
8. «Контрагенти»: контрагенти, контрагент з ЄДР, справи KYC, перевірки KYC.
9. «Довідники зарплати»: параметри (МЗП, ставки), правила розрахунку, структури зарплати, карта проводок, історія заробітку, шаблони імпорту виписок, правила звірки.

Опис під назвою короткий, 3-6 слів, українською, без крапки.

## Перевірка

`scripts/hub_check.py` (база з `PAYROLL_DB`, типово `payroll`):
- усі `action_xmlid` резолвляться (`env.ref` через JSON-RPC: `ir.model.data.check_object_reference` або пошук у `ir.model.data`), список нерезолвлених має бути порожній;
- кількість пунктів ≥ 30, розділів ≥ 8;
- `action_open` повертає словник з ключем `type` для 5 випадкових пунктів;
- користувач `lana` бачить меню «Головна» (перевірити через `ir.ui.menu.load_menus` під її сесією) і має домашню дію = дія хабу.

## Технічні правила

- Odoo 19: `<list>`, kanban `<t t-name="card">`, `<a type="object" name="...">` всередині картки.
- Оновлення: `docker compose exec -T odoo sh -c "odoo -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d payroll_test -i l10n_ua_hub --stop-after-init --log-level=warn 2>&1 | grep -vE 'deprecated|DeprecationWarning|_sql_constraints|http-interface' | tail -20"`.
- Українська мова, короткі назви. Нічого не ховати з наявних меню: хаб доповнює, а не замінює.
- Звіт: файли, вивід перевірки, список пунктів за розділами, що не зроблено.
