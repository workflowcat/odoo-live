---
id: 2026-09-22-011
kind: request
from: ui
to: core
status: done
title: ua_client_ref на stock.picking для ідемпотентних приймань і переміщень із зовнішнього клієнта
---
Клієнт web-warehouse зараз мітить приймання і переміщення через origin (WEB/<opId>). Потрібно те саме, що вже є на ua.stock.inventory: поле ua_client_ref (unique per company) на stock.picking і @api.model ua_get_or_create(client_ref, vals) у l10n_ua_stock_docs. Заодно: ua_capacity_used зробити груповим читанням (read_group по квантах), бо на великому складі пошук по кожній локації буде повільний.

2026-09-22: зроблено: stock.picking.ua_client_ref + ua_get_or_create(client_ref, vals); ua_capacity_used одним _read_group; коміт у main
