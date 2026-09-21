# -*- coding: utf-8 -*-
"""Екран «Звітність» виїхав у l10n_ua_reporting_ui: дія і корінь розділу міняють модуль, не запис.

Розділ «Звітність» - корінь верхнього меню, на який посилається і навігація, і смуга
ліворуч. Тому його рядок у ir_model_data перейменовуємо, а не даємо Odoo видалити
старий і створити новий: інакше розділ з'явився б з новим номером, а всі посилання
на старий - і пункти-діти - зникли б.

Робиться ДО оновлення даних l10n_ua_reporting. Повторний запуск безпечний.
"""

MOVED = [
    ("ir.actions.client", "action_ua_reporting"),
    ("ir.ui.menu", "menu_ua_reporting_root"),
]
OLD = "l10n_ua_reporting"
NEW = "l10n_ua_reporting_ui"


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
