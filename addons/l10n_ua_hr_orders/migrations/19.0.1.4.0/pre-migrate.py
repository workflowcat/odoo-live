# -*- coding: utf-8 -*-
"""Поле ua.employee.document.order_id переїхало з екрана l10n_ua_card_ui сюди, в логіку.

Колонка в базі та сама, міняється лише модуль у ir_model_data. Перейменовуємо запис
ДО того, як Odoo відобразить поля цього модуля: інакше з'явиться другий запис на те
саме поле, а старий Odoo прибере разом із самим полем - і дані зникнуть.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'l10n_ua_hr_orders'
           AND name = 'field_ua_employee_document__order_id'
    """)
    cr.execute("""
        UPDATE ir_model_data
           SET module = 'l10n_ua_hr_orders'
         WHERE module = 'l10n_ua_card_ui'
           AND name = 'field_ua_employee_document__order_id'
    """)
