# -*- coding: utf-8 -*-
"""Екран анкети виїхав у l10n_ua_setup_ui: клієнтська дія міняє модуль, не запис.

На дію веде пункт меню «Анкета компанії» з l10n_ua_navigation. Перейменуємо рядок
у ir_model_data ДО оновлення даних l10n_ua_setup - інакше модуль прибрав би «зайву»
дію разом із посиланням пункту. Повторний запуск безпечний.
"""

MOVED = [
    ("ir.actions.client", "action_ua_setup_board"),
]
OLD = "l10n_ua_setup"
NEW = "l10n_ua_setup_ui"


def migrate(cr, version):
    if not version:
        return
    for model, name in MOVED:
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = %s AND name = %s AND model = %s",
            (NEW, name, model),
        )
        cr.execute(
            "UPDATE ir_model_data SET module = %s WHERE module = %s AND name = %s AND model = %s",
            (NEW, OLD, name, model),
        )
