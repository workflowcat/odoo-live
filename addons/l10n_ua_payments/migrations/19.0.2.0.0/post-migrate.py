# -*- coding: utf-8 -*-
"""Перенесення відомостей `ua.payment.batch` у платіжні доручення `account.payment.order`.

Кожна стара відомість стає дорученням із тими самими рядками: та сама людина, той самий
IBAN, та сама сума, той самий текст призначення, той самий стан (чернетка - затверджено -
оплачено). Вкладення (файли для банку) і стрічка повідомлень переїжджають разом із нею.

Платежі за перенесеними відомостями НЕ проводяться. Дві причини, обидві бухгалтерські:
проведення створило б проводки в місяцях, які вже закриті, і задвоїло б ті самі суми з
виписками, які вже звірені старими правилами за текстом призначення. Тому перенесені
відомості позначені `ua_legacy` і в перевірках чесно кажуть: це історія, платежів немає.
Новий цикл починається з першої відомості, складеної вже на дорученні.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

STATE_MAP = {"draft": "draft", "confirmed": "open", "paid": "uploaded"}
TAX_ACCOUNTS = {"ПДФО": "6411", "Військовий збір": "6415", "Єдиний внесок (ЄСВ)": "651"}


def _table_exists(cr, name):
    cr.execute("SELECT to_regclass(%s)", (name,))
    return cr.fetchone()[0] is not None


def _account(env, company, code):
    Acc = env["account.account"].with_company(company)
    return Acc.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1) or \
        Acc.search([("code", "=like", "%s%%" % code), ("company_ids", "in", company.id)],
                   order="code", limit=1)


def _bank(env, partner, iban, company):
    """Рахунок одержувача за IBAN; створюємо, якщо в довіднику його ще немає."""
    if not iban or not partner:
        return False
    Bank = env["res.partner.bank"].sudo()
    account = Bank.search([("acc_number", "=", iban), ("partner_id", "=", partner.id)], limit=1)
    if not account:
        account = Bank.create({"acc_number": iban, "partner_id": partner.id,
                               "company_id": company.id, "allow_out_payment": True})
    return account


def migrate(cr, version):
    if not _table_exists(cr, "ua_payment_batch"):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""SELECT id, company_id, year, month, kind, pay_date, journal_id, number,
                         number_date, state, note
                    FROM ua_payment_batch ORDER BY id""")
    batches = cr.dictfetchall()
    if not batches:
        return
    Order = env["account.payment.order"].sudo()
    Line = env["account.payment.line"].sudo()
    moved_lines = 0
    for row in batches:
        company = env["res.company"].browse(row["company_id"])
        if not company.exists():
            continue
        kind = row["kind"] or "salary"
        mode = company._ua_payment_mode(kind)
        journal = env["account.journal"].browse(row["journal_id"]) if row["journal_id"] else None
        if not journal or not journal.exists() or journal.company_id != company:
            journal = company._ua_payment_journal()
        order = Order.create({
            "name": row["number"] or "New",
            "payment_mode_id": mode.id,
            "journal_id": journal.id,
            "date_prefered": "now",
            "state": STATE_MAP.get(row["state"], "draft"),
            "ua_kind": kind,
            "ua_year": row["year"],
            "ua_month": row["month"],
            "ua_pay_date": row["pay_date"] or row["number_date"],
            "ua_note": row["note"],
            "ua_legacy": True,
        })
        cr.execute("""SELECT id, employee_id, partner_id, name, account_number, amount, purpose
                        FROM ua_payment_line WHERE batch_id = %s ORDER BY id""", (row["id"],))
        for line in cr.dictfetchall():
            employee = env["hr.employee"].browse(line["employee_id"]) if line["employee_id"] else None
            partner = env["res.partner"].browse(line["partner_id"]) if line["partner_id"] else None
            if employee and employee.exists():
                partner = employee.work_contact_id or partner
                code = "661"
            else:
                employee = None
                code = TAX_ACCOUNTS.get(line["name"] or "", "6851")
            if not partner or not partner.exists():
                partner = company._ua_partner("dps")
            account = _account(env, company, code)
            bank = _bank(env, partner, line["account_number"], company)
            Line.create({
                "order_id": order.id,
                "partner_id": partner.id,
                "partner_bank_id": bank.id if bank else False,
                "amount_currency": line["amount"] or 0.0,
                "currency_id": company.currency_id.id,
                "communication": line["purpose"] or "",
                "ua_employee_id": employee.id if employee else False,
                "ua_label": line["name"] or False,
                "ua_account_id": account.id if account else False,
            })
            moved_lines += 1
        cr.execute("""UPDATE ir_attachment SET res_model = 'account.payment.order', res_id = %s
                       WHERE res_model = 'ua.payment.batch' AND res_id = %s""", (order.id, row["id"]))
        cr.execute("""UPDATE mail_message SET model = 'account.payment.order', res_id = %s
                       WHERE model = 'ua.payment.batch' AND res_id = %s""", (order.id, row["id"]))
        order.message_post(body=(
            "Перенесено з відомості на перерахування «%s». Платежі за нею не проводились: "
            "суми вже звірені з випискою старим способом, а місяць закритий."
            % (row["number"] or "без номера")))
    # Модель Odoo знімає сам (її більше немає в модулі), а таблиці лишає. Перейменовуємо їх
    # у *_legacy: дані видно, якщо бухгалтер захоче звірити перенесення, і повторний запуск
    # міграції вже нічого не задвоїть.
    cr.execute("ALTER TABLE ua_payment_line RENAME TO ua_payment_line_legacy")
    cr.execute("ALTER TABLE ua_payment_batch RENAME TO ua_payment_batch_legacy")
    _logger.info("l10n_ua_payments: перенесено відомостей %d, рядків %d",
                 len(batches), moved_lines)
