# -*- coding: utf-8 -*-
"""Модель bp.bridge переїхала з bp_kyc у bp_bridge. XML id мають лишитися ті самі записи.

Переносимо рядки ir_model_data (`model_bp_bridge` і `field_bp_bridge__*`) з модуля
bp_kyc у bp_bridge. На свіжій базі version порожній - переносити нічого, виходимо.
Скрипт ідемпотентний: другий запуск не знаходить рядків. Якщо рядок під bp_bridge
вже створено (модуль встиг віддзеркалити модель), зайвий рядок bp_kyc видаляємо.
"""
import logging

_logger = logging.getLogger(__name__)


def moved(name):
    return name == "model_bp_bridge" or name.startswith("field_bp_bridge__")


def migrate(cr, version):
    if not version:  # свіже встановлення - у базі ще нічого немає
        return
    cr.execute("SELECT id, name FROM ir_model_data WHERE module = 'bp_kyc'")
    rows = [(data_id, name) for data_id, name in cr.fetchall() if moved(name)]
    if not rows:
        return
    renamed = dropped = 0
    for data_id, name in rows:
        cr.execute("SELECT id FROM ir_model_data WHERE module = 'bp_bridge' AND name = %s", (name,))
        if cr.fetchone():
            cr.execute("DELETE FROM ir_model_data WHERE id = %s", (data_id,))
            dropped += 1
        else:
            cr.execute("UPDATE ir_model_data SET module = 'bp_bridge' WHERE id = %s", (data_id,))
            renamed += 1
    _logger.info("bp_bridge: XML id перенесено з bp_kyc - оновлено %s, прибрано дублів %s", renamed, dropped)
