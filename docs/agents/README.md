# Зв'язок між агентами

Три ролі працюють над одним продуктом у різних місцях:

| Роль | Де | За що відповідає |
| --- | --- | --- |
| core | `odoo-live/addons`, `scripts`, тести | логіка, дані, тести, контракт `docs/api` |
| docs | `odoo-live/docs`, `README`, `CLAUDE.md` | описи модулів, питання бухгалтеру, контракт як текст |
| ui | репозиторій `odoo-ui` | ітерації інтерфейсу поверх контракту; нічого в ядрі не змінює |

Канал - нотатки в `docs/agents/inbox/` (відкриті) і `docs/agents/log/` (закриті й рішення).
Файл = одне повідомлення з шапкою:

```
---
id: 2026-09-22-003
kind: request | decision | question | change
from: ui
to: core
status: open | done | declined
title: Потрібен метод ua_month_summary(company, year, month)
---
Що саме треба, навіщо, приклад відповіді. Одна тема на нотатку.
```

Правила:
1. Нотатка створюється і закривається тільки через `scripts/agent_note.py`, щоб id і статуси були однакові.
2. Хто виконав - закриває з коротким «зроблено: коміт abc123» у тілі. Хто відхилив - пише чому.
3. Зміна контракту (`docs/api/`) без запису в `docs/api/CHANGELOG.md` не проходить `contract_check.py`.
4. UI ніколи не пише в `addons/`. Якщо бракує методу - request до core. Поки core не зробив,
   UI може тимчасово зібрати потрібне з кількох викликів на своєму боці.
5. Обидва репозиторії читають той самий контракт: `odoo-ui/scripts/sync_contract.sh` копіює `docs/api/`
   з ядра в `odoo-ui/contracts/` і записує коміт ядра, з яким синхронізовано.
6. Нотатки короткі, звичайною мовою, з посиланнями на файли і коміти. Жодних секретів.

Команди:
```
python3 scripts/agent_note.py new request --from ui --to core "Заголовок" [--body "…"]
python3 scripts/agent_note.py list [--open] [--to core]
python3 scripts/agent_note.py close 2026-09-22-003 --status done --note "зроблено: коміт abc123"
```
