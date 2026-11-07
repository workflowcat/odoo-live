"""Вихідні платежі - файлом платіжних доручень 1CClientBankExchange для клієнт-банку.

Платіжка в банку вимагає рахунок і код обох сторін і призначення, де сказано про ПДВ. Тут
усе це збирається з платежу: рахунок компанії - з банківського журналу, рахунок
одержувача - з платежу, код - ЄДРПОУ (або ДРФО у ФОП), ПДВ - пропорційно з рахунків
постачальників, які платіж оплачує.
"""
import base64
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

from . import bank1c_format as fmt


def _code(partner):
    return re.sub(r"\D", "", partner.company_registry or partner.vat or "")


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _ua_bank1c_bills(self):
        """Рахунки постачальників, які оплачує платіж: проведені звірки або рядки доручення."""
        self.ensure_one()
        bills = self.reconciled_bill_ids
        if not bills and "invoice_ids" in self._fields:
            bills = self.invoice_ids
        if not bills and "payment_line_ids" in self._fields:
            bills = self.payment_line_ids.move_line_id.move_id
        return bills.filtered(lambda move: move.is_purchase_document(include_receipts=True))

    def _ua_bank1c_purpose(self):
        self.ensure_one()
        text = (self.payment_reference or self.memo or "").strip()
        if not text:
            refs = [bill.ref or bill.name for bill in self._ua_bank1c_bills()]
            text = _("Оплата за рахунком %s", ", ".join(refs)) if refs else _("Оплата")
        if "ПДВ" not in text.upper():
            text += "; " + self._ua_bank1c_vat_note()
        return text

    def _ua_bank1c_vat_note(self):
        """«у т.ч. ПДВ 20 % - 200,00 грн» або «без ПДВ»: частка ПДВ рахунків у сумі платежу."""
        self.ensure_one()
        bills = self._ua_bank1c_bills()
        total = sum(bills.mapped("amount_total"))
        tax = sum(bills.mapped("amount_tax"))
        if not total or self.currency_id.is_zero(tax):
            return _("без ПДВ")
        vat = self.currency_id.round(self.amount * tax / total)
        rates = {int(round(tax_line.tax_line_id.amount)) for tax_line in bills.line_ids
                 if tax_line.tax_line_id and tax_line.tax_line_id.amount}
        rate = " %s %%" % rates.pop() if len(rates) == 1 else ""
        amount = ("%.2f" % vat).replace(".", ",")
        return _("у т.ч. ПДВ%(rate)s - %(amount)s грн", rate=rate, amount=amount)

    def _ua_bank1c_document(self):
        self.ensure_one()
        company = self.company_id
        journal = self.journal_id
        own = journal.bank_account_id
        if not own:
            raise UserError(_("У банківському журналі %s не вказано рахунок компанії.",
                              journal.display_name))
        other = self.partner_bank_id
        if not other:
            raise UserError(_("Платіж %(payment)s: не вказано рахунок одержувача (%(partner)s).",
                              payment=self.display_name, partner=self.partner_id.display_name))
        digits = re.findall(r"\d+", self.name or "")
        return {
            "number": int(digits[-1]) if digits else self.id,
            "date": self.date or fields.Date.context_today(self),
            "amount": self.amount,
            "purpose": self._ua_bank1c_purpose(),
            "payer": {"account": own.acc_number, "name": company.name, "code": _code(company.partner_id)
                      or re.sub(r"\D", "", company.company_registry or ""),
                      "bank": own.bank_id.name or ""},
            "payee": {"account": other.acc_number,
                      "name": other.acc_holder_name or self.partner_id.commercial_partner_id.name,
                      "code": _code(self.partner_id.commercial_partner_id),
                      "bank": other.bank_id.name or ""},
        }

    def _ua_bank1c_file(self):
        """(байти, ім'я файлу) для платежів одного банківського рахунку."""
        payments = self.filtered(lambda p: p.payment_type == "outbound" and p.state != "canceled")
        if not payments:
            raise UserError(_("Немає вихідних платежів для файлу клієнт-банку."))
        journals = payments.journal_id
        if len(journals) > 1:
            raise UserError(_("Виберіть платежі одного банківського рахунку: у файлі клієнт-банку "
                              "один рахунок платника."))
        if any(p.currency_id != (journals.currency_id or journals.company_id.currency_id)
               for p in payments):
            raise UserError(_("Валютні платежі в банк подають окремою заявою, не файлом 1С."))
        documents = [payment._ua_bank1c_document() for payment in payments.sorted("date")]
        dates = [document["date"] for document in documents]
        content = fmt.render(journals.bank_account_id.acc_number, documents, min(dates), max(dates),
                             sender=journals.company_id.name)
        return content, "1c_to_bank_%s.txt" % max(dates).strftime("%Y-%m-%d")

    def action_ua_bank1c_export(self):
        content, filename = self._ua_bank1c_file()
        attachment = self.env["ir.attachment"].create({
            "name": filename,
            "datas": base64.b64encode(content),
            "mimetype": "text/plain",
            "res_model": self._name,
            "res_id": self[:1].id,
        })
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/web/content/%s?download=true" % attachment.id}
