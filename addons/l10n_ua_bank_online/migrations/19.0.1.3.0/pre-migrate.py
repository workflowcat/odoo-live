# -*- coding: utf-8 -*-
"""Екран «Банк» виїхав у l10n_ua_bank_ui: ua.bank.board і все навколо нього міняють модуль.

Переїжджає сама модель екрана (AbstractModel ua.bank.board), її рядок доступу, клієнтська
дія і корінь розділу «Банк» у верхньому меню. Рядки ir_model_data перейменовуємо ДО того,
як Odoo оновить дані l10n_ua_bank_online: інакше модуль, який більше цих записів не
оголошує, прибрав би їх - разом із розділом меню, на який ведуть і навігація, і смуга
ліворуч, і «Домівка».

Записи ir.model / ir.model.fields / ir.model.inherit моделі перейменовуємо теж: інакше
відображення реєстру створить другий рядок на ту саму модель, а старий прибере прибирання
«зайвого» - і абстрактна модель зникла б із ir_model разом із правом доступу на неї.

Повторний запуск безпечний.
"""

MOVED = [
    "access_ua_bank_board_user",
    "action_ua_bank_board",
    "field_ua_bank_board__display_name",
    "field_ua_bank_board__id",
    "menu_ua_bank_board",
    "model_inherit__ua_bank_board__ua_screen",
    "model_ua_bank_board",
]
OLD = "l10n_ua_bank_online"
NEW = "l10n_ua_bank_ui"


def migrate(cr, version):
    if not version:
        return
    for name in MOVED:
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = %s AND name = %s",
            (NEW, name),
        )
        cr.execute(
            "UPDATE ir_model_data SET module = %s WHERE module = %s AND name = %s",
            (NEW, OLD, name),
        )
