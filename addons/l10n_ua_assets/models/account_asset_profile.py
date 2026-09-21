# -*- coding: utf-8 -*-
"""Профілі активів під українські податкові групи.

OCA дає модель account.asset.profile з рахунками, журналом і методом
амортизації. Ми додаємо до неї три поля - податкову групу, мінімальний
строк за ПКУ і прапорець «амортизація з наступного місяця» - і будівника,
який створює готовий набір профілів для компанії з планом ua_psbo.

Рахунки шукаємо через account.chart.template.ref(xmlid). Це головне: код
рахунку в базі може бути і 104000 (нативний Odoo доповнює до шести знаків),
і 104 (після l10n_ua_chart), а xmlid шаблону не змінюється ніколи.
"""
import logging

from odoo import api, fields, models

from .ua_tax_groups import (
    EXPENSE_DEFAULT,
    RESIDUAL_ACCOUNT,
    RULE_SELECTION,
    TAX_GROUP_SELECTION,
    UA_ASSET_GROUPS,
)

_logger = logging.getLogger(__name__)


class AccountAssetProfile(models.Model):
    _inherit = "account.asset.profile"

    ua_tax_group = fields.Selection(
        selection=TAX_GROUP_SELECTION,
        string="Податкова група",
        help="Група основних засобів за п. 138.3.3 ПКУ або нематеріальних "
             "активів за п. 138.3.4 ПКУ.",
    )
    ua_rule = fields.Selection(
        selection=RULE_SELECTION,
        string="Українське правило",
        default="linear",
    )
    ua_min_months = fields.Integer(
        string="Мінімальний строк за ПКУ, міс.",
        help="Менший строк податкова не визнає. 0 - мінімуму немає.",
    )
    ua_start_next_month = fields.Boolean(
        string="Амортизація з наступного місяця",
        default=True,
        help="П. 29 П(С)БО 7 і п. 138.3.1 ПКУ: амортизацію нараховують з "
             "місяця, наступного за місяцем введення об'єкта в експлуатацію.",
    )

    # ------------------------------------------------------------------
    # Побудова набору профілів
    # ------------------------------------------------------------------

    @api.model
    def _ua_chart(self, company):
        return self.env["account.chart.template"].with_company(company).sudo()

    @api.model
    def _ua_account(self, company, chart, xmlid, fallback=None, width_from=None):
        """Рахунок за xmlid шаблону. Якщо його в плані немає, а ми знаємо
        код і назву (група 9 - рахунок 109), створюємо його, підбираючи
        довжину коду під сусіда: 104000 -> 109000, 104 -> 109."""
        account = chart.ref(xmlid, raise_if_not_found=False)
        if account:
            return account
        if not fallback:
            return self.env["account.account"]
        code, name, account_type = fallback
        Account = self.env["account.account"].sudo().with_company(company)
        for candidate in Account.search(
            [("code", "=like", code + "%"), ("company_ids", "in", company.ids)]
        ):
            if candidate.code.rstrip("0") == code:
                return candidate
        width = len(width_from.code) if width_from and width_from.code else len(code)
        account = Account.create({
            "code": code.ljust(max(width, len(code)), "0"),
            "name": name,
            "account_type": account_type,
            "company_ids": [(4, company.id)],
        })
        # Даємо рахунку той самий xmlid, що мав би шаблон: тоді l10n_ua_chart
        # скоротить його код разом з рештою, і chart.ref знайде його потім.
        self.env["ir.model.data"].sudo()._update_xmlids([{
            "xml_id": chart.company_xmlid(xmlid, company),
            "record": account,
            "noupdate": True,
        }])
        return account

    @api.model
    def _ua_journal(self, company):
        return self.env["account.journal"].sudo().search(
            [("type", "=", "general"), ("company_id", "=", company.id)], limit=1
        )

    @api.model
    def _ua_profile_values(self, company, chart, group):
        """Значення одного профілю. Повертає False, якщо рахунків немає."""
        depreciation_account = self._ua_account(company, chart, group["depreciation"])
        asset_account = self._ua_account(
            company,
            chart,
            group["asset"],
            group.get("account"),
            width_from=depreciation_account,
        )
        expense_account = self._ua_account(company, chart, EXPENSE_DEFAULT)
        residual_account = self._ua_account(company, chart, RESIDUAL_ACCOUNT)
        journal = self._ua_journal(company)
        if not (asset_account and depreciation_account and expense_account and journal):
            return False
        values = {
            "name": group["name"],
            "company_id": company.id,
            "account_asset_id": asset_account.id,
            "account_depreciation_id": depreciation_account.id,
            "account_expense_depreciation_id": expense_account.id,
            "account_residual_value_id": residual_account.id or False,
            "journal_id": journal.id,
            "ua_tax_group": group["key"],
            "ua_rule": group["rule"],
            "ua_min_months": group["min_months"],
            "ua_start_next_month": True,
            # Строк рахуємо в місяцях: бухгалтерія нараховує щомісяця.
            "method_time": "number",
            "method_period": "month",
            "method_number": group["months"],
            "method": "linear",
            "prorata": True,
        }
        if group["rule"] == "mnma_50_50":
            # 50 % одразу, 50 % лишаються ліквідаційною вартістю і йдуть у
            # витрати при списанні. Рушій OCA робить це сам: метод
            # «прямолінійна до ліквідаційної вартості» + 50 % ліквідаційної.
            values.update({
                "method": "linear-limit",
                "salvage_type": "percent",
                "salvage_value": 50.0,
            })
        if group["rule"] == "none":
            # Земля і природні ресурси не амортизуються: рядків не буде.
            values["method_number"] = 0
            values["note"] = "Об'єкти цієї групи не амортизуються."
        return values

    @api.model
    def _ua_create_profiles(self, company):
        """Створити набір профілів для компанії. Ідемпотентно: профіль,
        який уже є (та сама група і те саме правило), не чіпаємо."""
        if company.chart_template != "ua_psbo":
            return self.browse()
        chart = self._ua_chart(company)
        created = self.browse()
        for group in UA_ASSET_GROUPS:
            if self.sudo().with_context(active_test=False).search_count([
                ("company_id", "=", company.id),
                ("ua_tax_group", "=", group["key"]),
                ("ua_rule", "=", group["rule"]),
            ]):
                continue
            values = self._ua_profile_values(company, chart, group)
            if not values:
                _logger.warning(
                    "l10n_ua_assets: пропущено профіль %s - немає рахунків або журналу",
                    group["name"],
                )
                continue
            created |= self.sudo().with_company(company).create(values)
        return created
