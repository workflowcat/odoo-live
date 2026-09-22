# -*- coding: utf-8 -*-
"""Скани документів працівника переїжджають на картку працівника.

Було: `file` - двійкове поле з `attachment=True`, тобто вкладення самої моделі документа
(`res_model = 'ua.employee.document'`, `res_field = 'file'`). Для OCA `hr_employee_document`,
який рахує і показує вкладення картки (`res_model = 'hr.employee'`), цих файлів не існувало.

Стало: те саме вкладення, але на картці працівника, і документ тримає його в `attachment_id`.
Файл не перезаписується і не копіюється - переставляються лише посилання, тому сам вміст
(`store_fname`, контрольна сума) лишається той самий. Документи без файлу не чіпаємо.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""SELECT a.id, a.res_id, d.employee_id, d.name, e.company_id
                    FROM ir_attachment a
                    JOIN ua_employee_document d ON d.id = a.res_id
                    JOIN hr_employee e ON e.id = d.employee_id
                   WHERE a.res_model = 'ua.employee.document' AND a.res_field = 'file'
                   ORDER BY a.id""")
    rows = cr.fetchall()
    if not rows:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for attachment_id, document_id, employee_id, doc_name, company_id in rows:
        cr.execute("""UPDATE ir_attachment
                         SET res_model = 'hr.employee', res_id = %s, res_field = NULL,
                             company_id = %s
                       WHERE id = %s""", (employee_id, company_id, attachment_id))
        cr.execute("UPDATE ua_employee_document SET attachment_id = %s WHERE id = %s",
                   (attachment_id, document_id))
    env["ua.employee.document"].invalidate_model()
    _logger.info("l10n_ua_hr_card: сканів документів перенесено на картку працівника: %d", len(rows))
