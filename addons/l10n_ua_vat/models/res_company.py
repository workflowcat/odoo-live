# -*- coding: utf-8 -*-
"""Пошук рахунків і податків ПДВ у компанії.

Один клопіт: коди рахунків у базі виглядають по-різному. Odoo доповнює код
шаблону нулями до шести знаків (6431 стає 643100), а модуль l10n_ua_chart
повертає їх назад до короткого вигляду (6431). Тому шукаємо не за кодом, а
за xmlid шаблону плану - він однаковий в обох випадках; пошук за кодом
лишаємо запасним варіантом для баз, зібраних вручну.
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Рахунки, якими працює ПДВ. Ключ - як ми звемо рахунок у коді,
# значення - (xmlid шаблону ua_psbo, короткий код, повний код).
UA_VAT_ACCOUNTS = {
    # Податкові зобов'язання за авансами (перша подія - оплата).
    "pz_advance": ("ua_psbp_6431", "6431", "643100"),
    # Розрахунки за ПДВ - рахунок, на якому збирається сам податок.
    "vat": ("ua_psbp_6412", "6412", "641200"),
    # Податкові зобов'язання непідтверджені - через нього йдуть компенсуючі ПЗ.
    "pz_unconfirmed": ("ua_psbp_6432", "6432", "643200"),
    # Інші витрати операційної діяльності - списання компенсуючих ПЗ.
    "other_expense": ("ua_psbp_949", "949", "949000"),
    # Розрахунки з іншими дебіторами - заборгованість перед митницею.
    "customs": ("ua_psbp_3771", "3771", "377100"),
}


class ResCompany(models.Model):
    _inherit = "res.company"

    # Код ДПІ, куди подається документ. В Odoo такого реквізиту немає, а шапка
    # XML для ЄРПН без нього не збирається. Дефолт - ГУ ДПС у м. Києві;
    # для іншого регіону бухгалтер виправляє у картці компанії.
    x_ua_dps_reg = fields.Char(
        string="Код області ДПІ", size=2, default="26",
        help="Дві цифри коду області з довідника ДПС (C_REG у XML).")
    x_ua_dps_raj = fields.Char(
        string="Код району ДПІ", size=2, default="59",
        help="Дві цифри коду району з довідника ДПС (C_RAJ у XML).")
    x_ua_dps_sti = fields.Char(
        string="Код ДПІ отримувача", size=4, default="2659",
        help="Чотири цифри коду ДПІ, куди подається документ (C_STI_ORIG).")

    def _ua_vat_account(self, key):
        """Рахунок ПДВ за нашим ключем. Порожній рекордсет, якщо не знайдено."""
        self.ensure_one()
        xmlid, short_code, long_code = UA_VAT_ACCOUNTS[key]
        Account = self.env["account.account"]
        account = self.env["account.chart.template"].with_company(self).ref(
            xmlid, raise_if_not_found=False)
        if account:
            return account
        return Account.search([
            ("code", "in", [short_code, long_code]),
            ("company_ids", "in", self.id),
        ], limit=1)

    def _ua_vat_journal(self):
        """Журнал інших операцій - у ньому живуть службові проводки ПДВ."""
        self.ensure_one()
        return self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.id),
        ], limit=1)

    def _ua_vat_zero_tax(self, type_tax_use, zero_kind):
        """Нульовий податок компанії за видом нуля (export / exempt)."""
        self.ensure_one()
        return self.env["account.tax"].search([
            ("company_id", "=", self.id),
            ("type_tax_use", "=", type_tax_use),
            ("amount", "=", 0.0),
            ("tax_group_id.x_ua_vat_zero_kind", "=", zero_kind),
        ], limit=1)

    def _ua_vat_exempt_tax(self):
        """Податок продажу «звільнено від ПДВ» (пільга)."""
        return self._ua_vat_zero_tax("sale", "exempt")

    def _ua_vat_export_tax(self):
        """Податок продажу «0 % експорт»."""
        return self._ua_vat_zero_tax("sale", "export")
