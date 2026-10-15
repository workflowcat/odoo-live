@AGENTS.md

# odoo-live - правила для агентів

Це ЯДРО: логіка українського бек-офісу на Odoo 19 CE. Інтерфейс живе окремо (репозиторій
`odoo-ui`) і читає ядро через контракт у `docs/api/`. Мова коду і коментарів - українська,
без довгих тире (лише «-»), дати YYYY-MM-DD.

## Шари
- Спершу нативний Odoo, потім OCA 19.0 без змін (`addons/OCA_*.commit`), наше - тонко зверху.
- Логічний модуль не має `static/src`, не залежить від UI, меню лише в `l10n_ua_navigation`.
  `python3 scripts/layers_check.py` - закон.
- Кожен модуль ставиться на порожню базу і має Odoo-тести в `addons/l10n_ua_payroll_tests/tests/`
  (тег `ua_<область>`). Гроші - лише з `golden/scenarios.json`; числа підтверджує бухгалтер.

## Перед комітом
```
TEST_TAGS=<теги з README> ./scripts/test.sh      # свіжа база
./scripts/check_all.sh                            # стенд 8130
python3 scripts/contract_check.py                 # контракт docs/api не розійшовся з кодом
```
Стенд: `docker compose` (проєкт `odoo-live-base`, порт 8130, база `payroll`). Демо: `scripts/demo_server.sh`
(8131, база `demo`). Образ без `pypdf` - у разових контейнерах `pip install --break-system-packages pypdf`.
Ролі агентів у спільній теці: різні модулі, свій префікс баз, разові `docker compose run`; сервіс `odoo`
і базу `payroll` перезапускає лише один агент.

## Зв'язок між агентами (ядро, документація, UI)
Канал - файли в git, не чат. Протокол у `docs/agents/README.md`, інструмент `scripts/agent_note.py`.
- Змінив публічний метод, модель або поле, яке бачить UI, - онови `docs/api/` і `docs/api/CHANGELOG.md`
  у тому ж коміті; `contract_check.py` інакше впаде.
- Потрібне щось від іншої ролі - `python3 scripts/agent_note.py new request --to core|docs|ui "…"`.
- Прийняв рішення, яке впливає на інших, - `agent_note.py new decision`.
- На початку сесії: `python3 scripts/agent_note.py list --open --to <твоя роль>`.
