# -*- coding: utf-8 -*-
"""Перевірка знімка черги після переходу на OCA auditlog.

Порівнюємо з тим, що записав pre-migrate: та сама кількість відкритих рядків і
ті самі слова. Розбіжність не спиняє оновлення - вона стає WARNING у лозі, бо
дані бухгалтера важливіші за акуратність міграції.
"""
import json
import logging

_logger = logging.getLogger(__name__)

PARAM = "l10n_ua_changes.migration_19_2_queue"


def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (PARAM,))
    row = cr.fetchone()
    if not row:
        _logger.warning("Журнал змін: знімка черги немає, порівняти нема з чим")
        return
    before = json.loads(row[0])
    cr.execute("DELETE FROM ir_config_parameter WHERE key = %s", (PARAM,))

    cr.execute("""
        SELECT company_id, res_name, what, old_value, new_value
          FROM ua_change_log
         WHERE state = 'new' AND year = %s AND month = %s
    """, (before["year"], before["month"]))
    after = sorted("|".join(str(part or "") for part in line) for line in cr.fetchall())
    was = before["rows"]

    if len(was) != len(after):
        _logger.warning("Журнал змін: у черзі %s.%02d було %s відкритих рядків, стало %s",
                        before["year"], before["month"], len(was), len(after))
    lost = [text for text in was if text not in after]
    added = [text for text in after if text not in was]
    for text in lost[:20]:
        _logger.warning("Журнал змін: рядок черги зник після оновлення: %s", text)
    for text in added[:20]:
        _logger.warning("Журнал змін: у черзі з'явився новий рядок: %s", text)
    if not lost and not added and len(was) == len(after):
        _logger.info("Журнал змін: черга %s.%02d після оновлення та сама (%s рядків)",
                     before["year"], before["month"], len(after))
