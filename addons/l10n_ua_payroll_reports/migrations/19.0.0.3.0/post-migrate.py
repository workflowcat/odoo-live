# -*- coding: utf-8 -*-
"""Реєстр довідок про доходи став самою довідкою.

`ua.income.certificate.register` тримав лише слід видачі (номер, дата, працівник,
період); тепер довідка - документ `ua.income.certificate`, і його список і є реєстром.
Старі рядки переносимо як видані довідки без рядків розрахунку: листки за той період
може бути вже закрито, і перерахунок заднім числом дав би інші числа, ніж у виданому
папері. Номер, дата і період лишаються - саме їх у реєстрі й шукають.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("SELECT to_regclass('ua_income_certificate_register')")
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        INSERT INTO ua_income_certificate
            (number, date, company_id, employee_id, date_from, date_to, purpose,
             show_net, state, create_uid, create_date, write_uid, write_date)
        SELECT r.name, r.date, r.company_id, r.employee_id, r.date_from, r.date_to,
               r.purpose, TRUE, 'issued', r.create_uid, r.create_date, r.write_uid, r.write_date
          FROM ua_income_certificate_register r
         WHERE NOT EXISTS (
               SELECT 1 FROM ua_income_certificate c WHERE c.number = r.name)
        RETURNING id
    """)
    moved = [row[0] for row in cr.fetchall()]
    cr.execute("DROP TABLE ua_income_certificate_register")
    if not moved:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    docs = env["ua.income.certificate"].browse(moved)
    docs._compute_name()
    docs._compute_totals()
    docs.flush_recordset()
