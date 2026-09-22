# -*- coding: utf-8 -*-
"""Рахунки бюджету для сплати податків і внеску та способи оплати зарплатного циклу.

Рахунки відкриває Казначейство, вони різні для кожної області і змінюються щороку.
Тому це поле компанії, а не константа в коді. Бухгалтер бере їх з сайта ДПС.

Способи оплати («Зарплата», «Податки») створюємо за потреби, а не даними модуля: на базі
може ще не бути ані банківського журналу, ані плану рахунків, коли модуль ставлять. Пошук
іде за полем компанії, тож повторний виклик нічого не дублює - як у `_ua_partner`.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

# вид виплати -> (поле компанії, назва способу оплати)
MODES = {
    "tax": ("ua_payment_mode_tax_id", "Податки"),
    "salary": ("ua_payment_mode_salary_id", "Зарплата"),
}
# вид виплати -> поле компанії з рахунком бюджету
TAX_IBANS = {"PDFO": "ua_iban_pdfo", "VZ": "ua_iban_vz", "ESV": "ua_iban_esv"}


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_iban_pdfo = fields.Char("Рахунок бюджету: ПДФО")
    ua_iban_vz = fields.Char("Рахунок бюджету: військовий збір")
    ua_iban_esv = fields.Char("Рахунок бюджету: ЄСВ")
    ua_payment_mode_salary_id = fields.Many2one(
        "account.payment.mode", "Спосіб оплати: зарплата", copy=False,
        help="Спосіб оплати, яким ідуть відомості на зарплату, аванс та інші виплати працівникам.")
    ua_payment_mode_tax_id = fields.Many2one(
        "account.payment.mode", "Спосіб оплати: податки", copy=False,
        help="Спосіб оплати, яким ідуть платежі ПДФО, військового збору і ЄСВ до бюджету.")

    # ------------------------------------------------------------------ спосіб оплати
    def _ua_payment_mode(self, kind):
        """Спосіб оплати для виду виплати. Створює за потреби, один раз на компанію."""
        self.ensure_one()
        field, label = MODES["tax" if kind == "tax" else "salary"]
        if self[field]:
            return self[field]
        method = self.env.ref("account.account_payment_method_manual_out", raise_if_not_found=False)
        if not method:
            raise UserError(_("Немає типового способу платежу «Manual Payment» (outbound)."))
        journals = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.id)], order="sequence, id")
        mode = self.env["account.payment.mode"].search(
            [("name", "=", label), ("company_id", "=", self.id)], limit=1)
        if not mode:
            mode = self.env["account.payment.mode"].create({
                "name": label, "company_id": self.id, "payment_method_id": method.id,
                "bank_account_link": "variable", "variable_journal_ids": [(6, 0, journals.ids)],
                "ua_file_format": "csv1251", "group_lines": False,
                "default_date_prefered": "now",
            })
        elif journals and not mode.variable_journal_ids:
            mode.variable_journal_ids = [(6, 0, journals.ids)]
        self[field] = mode
        return mode

    def ua_payment_setup(self):
        """Довідники зарплатних виплат одним викликом: способи оплати і банк.

        Потрібно скриптам і демо, які заводять відомість напряму, без екрана: через RPC
        зручно отримати самі ідентифікатори, а не записи."""
        self.ensure_one()
        return {
            "salary": self.sudo()._ua_payment_mode("salary").id,
            "tax": self.sudo()._ua_payment_mode("tax").id,
            "journal": self.sudo()._ua_payment_journal().id,
        }

    def _ua_payment_journal(self):
        """Банк, з якого платять зарплату: перший банківський журнал компанії."""
        self.ensure_one()
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.id)], order="sequence, id", limit=1)
        if not journal:
            raise UserError(_("У компанії %s немає банківського журналу.", self.name))
        return journal

    # ------------------------------------------------------------------ рахунки бюджету
    def _ua_tax_bank(self, code):
        """Казначейський рахунок ДПС як res.partner.bank: платіж має куди лягти.

        Раніше IBAN бюджету жив рядком у відомості. Платіжне доручення зберігає одержувача
        реквізитом контрагента, тому рахунок з картки компанії заводимо контрагенту ДПС.
        """
        self.ensure_one()
        iban = (self[TAX_IBANS[code]] or "").strip()
        if not iban:
            return self.env["res.partner.bank"]
        partner = self.sudo()._ua_partner("dps")
        Bank = self.env["res.partner.bank"].sudo()
        account = Bank.search([("acc_number", "=", iban), ("partner_id", "=", partner.id)], limit=1)
        if not account:
            account = Bank.create({
                "acc_number": iban, "partner_id": partner.id, "company_id": self.id,
                "allow_out_payment": True,
            })
        elif not account.allow_out_payment:
            account.allow_out_payment = True
        return account
