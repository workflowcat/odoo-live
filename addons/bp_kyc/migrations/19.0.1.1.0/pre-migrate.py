# -*- coding: utf-8 -*-
"""Модель bp.bridge поїхала в окремий модуль bp_bridge. Тут - той самий перенос XML id.

Потрібен саме тут: на наявному стенді bp_bridge ставиться вперше, а Odoo не запускає
скрипти міграції для модуля зі станом «to install». Реально спрацьовує цей файл -
bp_kyc оновлюється з 19.0.1.0.0 до 19.0.1.1.0. Скрипт ідемпотентний; якщо рядок під
bp_bridge уже створено (модуль встиг віддзеркалити модель), зайвий рядок bp_kyc видаляємо.
"""
import logging

_logger = logging.getLogger(__name__)


def moved(name):
    return name == "model_bp_bridge" or name.startswith("field_bp_bridge__")


def migrate(cr, version):
    if not version:  # свіже встановлення - переносити нічого
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
    _logger.info("bp_kyc: XML id моделі bp.bridge віддано bp_bridge - оновлено %s, прибрано дублів %s",
                 renamed, dropped)
