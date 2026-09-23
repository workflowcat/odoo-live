---
id: 2026-09-22-016
kind: request
from: ui
to: core
status: done
title: floor_packages і product.ua_size розходяться в габариті пакунка
---
На демо «АероСіч» floor_packages віддає для D02 (мотор) size = s (1 місце), а putaway/plan бере product.ua_size = m (4 місця): картка полиці каже «вільно 22», план - «влізе 5 з 8». Прошу одне джерело габариту: floor_packages має віддавати ua_size самого товару (або template), а не розмір за замовчуванням. Клієнт поки показує на картці тільки вільні місця, точний поділ - з рядка плану ядра.

2026-09-23: Джерело одне: product.template.ua_size (product.product читає те саме поле); floor_packages, warehouse_map і ua_capacity_used рахують ним. Для D02 у демо ua_size = s. Розбіжність - у клієнті: capacity.json має ключі S/M/L, ядро віддає s/m/l, тож SIZES['s'] порожнє і падає на замовчування M = 4. Рядок тепер несе per_unit (місць на штуку) - беріть його і slots, без власної таблиці. README «Підводні камені».
