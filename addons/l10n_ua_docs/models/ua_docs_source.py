"""Спільна логіка первинки: один домішок для всіх носіїв документа.

Рахунок, замовлення і доставка друкуються за тими самими правилами: дві сторони
з реквізитами, таблиця позицій, ПДВ, сума прописом, підписи. Щоб QWeb не знав, з
якого саме запису він друкує, кожен носій підмішує собі `ua.docs.source` і дає
чотири речі: сторони, позиції, податки і суми. Решту - формулювання ставки,
підсумки, пропис - домішок рахує сам.

Шаблони звертаються тільки до методів цього домішка. Тому міст sale чи stock -
це тридцять рядків, а не другий комплект друкованих форм.
"""
from odoo import models

from .tools import amount_in_words, mfo_from_iban


class UaDocsSource(models.AbstractModel):
    _name = "ua.docs.source"
    _description = "Джерело даних української первинки"

    # ------------------------------------------------------------------
    # Що дає носій документа
    # ------------------------------------------------------------------
    def _ua_docs_company(self):
        self.ensure_one()
        return self.company_id

    def _ua_docs_partner(self):
        self.ensure_one()
        return self.partner_id

    def _ua_docs_bank(self):
        """Банківський рахунок постачальника для друку."""
        self.ensure_one()
        return self._ua_docs_company()._ua_docs_bank()

    def _ua_docs_currency(self):
        self.ensure_one()
        return self.currency_id or self._ua_docs_company().currency_id

    def _ua_docs_lines(self):
        """Позиції документа списком словників. Реалізує носій."""
        raise NotImplementedError

    def _ua_docs_taxes(self):
        """Усі податки документа одним рекордсетом. Реалізує носій."""
        raise NotImplementedError

    def _ua_docs_money(self):
        """Суми документа. Типово - нативні amount_* носія."""
        self.ensure_one()
        return {
            "untaxed": self.amount_untaxed,
            "tax": self.amount_tax,
            "total": self.amount_total,
        }

    def _ua_docs_number(self):
        """Номер документа - нативний номер носія, без префікса журналу."""
        self.ensure_one()
        name = self.name or ""
        if not name or name == "/":
            return "б/н"
        return name.split("/")[-1] if "/" in name else name

    def _ua_docs_date(self):
        self.ensure_one()
        return False

    def _ua_docs_basis(self):
        """Підстава: договір, замовлення, інший документ."""
        self.ensure_one()
        return ""

    def _ua_docs_due(self):
        """Дата, до якої документ чинний (для рахунку - строк оплати)."""
        self.ensure_one()
        return False

    def _ua_docs_proxy(self):
        """Довіреність одержувача: номер, дата, на кого виписана."""
        self.ensure_one()
        return {"number": "", "date": False, "person": ""}

    # ------------------------------------------------------------------
    # Що домішок рахує сам
    # ------------------------------------------------------------------
    def _ua_docs_party(self, partner, bank=None, company=None):
        """Реквізити однієї сторони так, як їх чекають на українському папері.

        ЄДРПОУ і ІПН - нативні поля партнера, IBAN і банк - нативний рахунок,
        МФО - шість цифр з того самого IBAN. Підписант: для нашої компанії це
        керівник із картки компанії, для контрагента - його підписант.
        """
        partner = partner.commercial_partner_id or partner
        return {
            "name": partner.name or "",
            "registry": partner.company_registry or "",
            "vat": partner.vat or "",
            "address": partner._ua_docs_address(),
            "actual_address": partner.x_ua_actual_address or "",
            "phone": partner.phone or "",
            "iban": (bank.acc_number or "") if bank else "",
            "bank_name": (bank.bank_name or "") if bank else "",
            "mfo": mfo_from_iban(bank.acc_number) if bank else "",
            "director": (company.ua_director_name if company else partner.x_ua_signatory_name) or "",
            "accountant": (company.ua_accountant_name or "") if company else "",
            "basis": (company.x_ua_acts_on_basis if company else partner.x_ua_signatory_basis) or "",
        }

    def _ua_docs_seller(self):
        self.ensure_one()
        company = self._ua_docs_company()
        return self._ua_docs_party(company.partner_id, bank=self._ua_docs_bank(), company=company)

    def _ua_docs_buyer(self):
        self.ensure_one()
        return self._ua_docs_party(self._ua_docs_partner())

    def _ua_docs_vat_rate(self):
        """Ставка ПДВ документа у відсотках, або None, якщо ставка не одна."""
        self.ensure_one()
        rates = {tax.amount for tax in self._ua_docs_taxes() if tax.amount_type == "percent"}
        return rates.pop() if len(rates) == 1 else None

    def _ua_docs_vat_label(self):
        """Підпис рядка податку: «ПДВ 20 %» або «Без ПДВ»."""
        self.ensure_one()
        if self._ua_docs_currency().is_zero(self._ua_docs_money()["tax"]):
            return "Без ПДВ"
        rate = self._ua_docs_vat_rate()
        return "ПДВ" if rate is None else "ПДВ %g %%" % rate

    def _ua_docs_amount_words(self):
        self.ensure_one()
        return amount_in_words(self._ua_docs_currency(), self._ua_docs_money()["total"])

    def _ua_docs_currency_label(self):
        """Як валюта підписана в шапці колонок: «грн»."""
        self.ensure_one()
        currency = self._ua_docs_currency()
        return "грн" if currency.name == "UAH" else (currency.symbol or currency.name or "")

    def _ua_docs_money_text(self, amount):
        """Сума цифрами по-українськи: пробіл на тисячі, кома перед копійками.

        Нативний віджет monetary друкує за мовою бази, тому на англійському
        стенді в українському бланку з'являлося «5,000.00 ₴». Форма первинки
        від мови інтерфейсу залежати не повинна.
        """
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    def _ua_docs_totals(self):
        """Усе, що друкується під таблицею позицій."""
        self.ensure_one()
        money = self._ua_docs_money()
        return {
            "untaxed": money["untaxed"],
            "tax": money["tax"],
            "total": money["total"],
            "has_vat": not self._ua_docs_currency().is_zero(money["tax"]),
            "vat_label": self._ua_docs_vat_label(),
            "words": self._ua_docs_amount_words(),
            "count": len(self._ua_docs_lines()),
        }
