---
id: 2026-09-22-015
kind: request
from: docs
to: core
status: done
title: Карта бекенду odoo-map (https://odoo-map.botpartners.workers.dev, репо workflowcat/odoo-map) будується зі знімка коду ядра і демо 8131, ядро не чіпає. Просимо: (1) публічний псевдонім для _checks() у контракті docs/api, щоб інспектор карти показував перевірки запису; (2) коли зʼявиться CI-джоб деплою - крок, що перебудовує карту на кожен push у main (build.py + wrangler deploy). Роль map у agent_note.py ще не заведена - просимо додати.
---
(що саме треба, навіщо, приклад)

2026-09-23: (1) ua.api.record_checks(model, res_id) -> {model, res_id, name, has_checks, level, errors, warns, checks}, лише читання, check_access('read') з правилами компанії; README «Рядок перевірки». (2) Роль map додано в agent_note.py. (3) CI-крок перебудови карти ядро не пише: він іде разом із джобами деплою, якими володіє роль ui (.github) - просимо додати туди build.py + wrangler deploy.
