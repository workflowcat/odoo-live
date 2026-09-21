# -*- coding: utf-8 -*-
"""Екран «Прийняття» виїхав у l10n_ua_hire_ui: дія і пункт меню міняють модуль, не запис.

Обидва записи лишаються в базі тими самими рядками з тими самими номерами, тому
меню не зникає з навігації, а посилання на дію не рвуться. Міняємо лише колонку
module в ir_model_data, і робимо це ДО того, як Odoo оновить дані l10n_ua_hire:
інакше наприкінці оновлення модуль прибере «зайві» записи разом із самим меню.

Повторний запуск нічого не псує: якщо рядок уже під новим модулем, UPDATE не
знаходить нічого, а можливий дубль під новим модулем спершу видаляється.
"""

MOVED = [
    ("ir.actions.client", "action_ua_hire"),
    ("ir.ui.menu", "menu_ua_hire"),
]
OLD = "l10n_ua_hire"
NEW = "l10n_ua_hire_ui"


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
