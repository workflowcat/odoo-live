# -*- coding: utf-8 -*-
"""Знімок черги бухгалтера перед переходом на OCA auditlog.

Старі рядки `ua.change.log` нікуди не діваються - вони і є історія. Змінюється
лише те, звідки беруться нові. Щоб це було видно, а не на слово: тут ми
записуємо, що саме бухгалтер бачить у черзі поточного місяця, а post-migrate
після оновлення порівнює і пише WARNING на кожну розбіжність.
"""
import json
import logging
from datetime import date

_logger = logging.getLogger(__name__)

PARAM = "l10n_ua_changes.migration_19_2_queue"


def snapshot(cr, year, month):
    cr.execute("""
        SELECT company_id, res_name, what, old_value, new_value
          FROM ua_change_log
         WHERE state = 'new' AND year = %s AND month = %s
    """, (year, month))
    return sorted("|".join(str(part or "") for part in row) for row in cr.fetchall())


def migrate(cr, version):
    today = date.today()
    rows = snapshot(cr, today.year, today.month)
    payload = json.dumps({"year": today.year, "month": today.month, "rows": rows},
                         ensure_ascii=False)
    cr.execute("DELETE FROM ir_config_parameter WHERE key = %s", (PARAM,))
    cr.execute("INSERT INTO ir_config_parameter (key, value) VALUES (%s, %s)", (PARAM, payload))
    _logger.info("Журнал змін: у черзі %s.%02d відкритих рядків до оновлення: %s",
                 today.year, today.month, len(rows))
