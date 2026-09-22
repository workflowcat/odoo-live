---
id: 2026-09-22-002
kind: request
from: core
to: core
status: done
title: layers_check.py шукає shelved/addons-owl, якої в ядрі вже немає
---
Коміт c0e332c переніс shelved/ у odoo-ui/reference, а правило 5 у scripts/layers_check.py лишилось: воно вимагає теку shelved/addons-owl і без неї дає [FAIL] «тека відкладених екранів на місці». Через це падають і scripts/check_all.sh (1 з 21), і крок contract у .github/workflows/tests.yml. Решта 158 пунктів layers_check проходять.

Що зробити: прибрати або переписати пункт 5 (і супровідний текст у шапці скрипта) разом із рештою правил про відкладені екрани - правило 4 теж мовчить, бо SHELVED_MODULES порожній.

Знайдено під час роботи над docs/api і l10n_ua_api; scripts/layers_check.py не мій файл, тому не чіпав.

2026-09-22: вже зроблено кимось іншим: scripts/layers_check.py у робочому дереві більше не вимагає shelved/addons-owl, layers_check проходить 203 з 203
